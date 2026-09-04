"""
Airflow DAGs for the full pipeline:

1. shorts_pipeline           — every 6h: checks YOUR channel for new
                                long-form uploads, clips them via Vizard,
                                ranks, uploads the top N to YouTube as
                                PRIVATE (you review/publish manually, or
                                switch UPLOAD_MODE=scheduled in .env for
                                hands-off auto-publish).
2. shorts_performance_tracking — daily: pulls view/like/retention stats
                                for everything published in the last 30 days.
3. shorts_pick_winner         — every 3 days: for each batch of clips that
                                came from the same source video, compares
                                view counts and records the winner.
4. shorts_ranker_retrain      — weekly: retrains the LightGBM ranking model
                                on whatever performance data has accumulated.

Copy this file into your Airflow dags/ folder. It imports from the project
root, so also make sure the project root is on PYTHONPATH (or copy the
whole repo next to your dags folder).
"""
from __future__ import annotations

import sys
import os
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from airflow import DAG
from airflow.operators.python import PythonOperator

import db
from config import config
from vizard_client import VizardClient, VIDEO_TYPE_YOUTUBE
from clip_ranker import select_top_n
from youtube_uploader import get_authenticated_service, download_clip, upload_short, is_upload_limit_error
from performance_tracker import track_all_recent
from channel_watcher import get_unprocessed_source_videos
from pick_winner import evaluate_ready_batches

default_args = {
    "owner": "shorts-pipeline",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": True,  # configure Airflow's SMTP connection for this
}


def get_new_source_videos(**context) -> list[dict]:
    """
    Checks config.SOURCE_CHANNEL_ID for new uploads not already sent to
    Vizard. Fully automatic — no manual URL entry needed once
    SOURCE_CHANNEL_ID is set in .env.
    """
    if not config.SOURCE_CHANNEL_ID:
        raise RuntimeError(
            "SOURCE_CHANNEL_ID is not set in .env. Find your channel ID at "
            "youtube.com/account_advanced (starts with 'UC')."
        )
    db.init_db()
    videos = get_unprocessed_source_videos(
        config.SOURCE_CHANNEL_ID, max_results=config.CHANNEL_CHECK_MAX_RESULTS
    )
    print(f"Found {len(videos)} new source video(s).")
    return videos


def clip_and_rank(**context):
    videos = context["ti"].xcom_pull(task_ids="get_new_source_videos")
    if not videos:
        return []

    vizard = VizardClient()
    all_selected = []

    for v in videos:
        pending_project_id = db.get_pending_submission(v["video_id"])
        try:
            if pending_project_id:
                project_id = pending_project_id
            else:
                project_id = vizard.submit_video(v["url"], video_type=VIDEO_TYPE_YOUTUBE)
                db.save_pending_submission(v["video_id"], project_id, v["url"], v["title"])

            clips = vizard.wait_for_clips(project_id, poll_seconds=60, timeout_seconds=7200)
        except Exception as e:
            print(f"FAILED to process '{v['title']}' ({v['url']}): {e}. "
                  f"Will resume from the same Vizard project next run.")
            continue

        db.mark_source_video_seen(v["video_id"], v["url"], v["title"])
        db.clear_pending_submission(v["video_id"])
        top = select_top_n(clips)
        for c in top:
            db.save_clip(c, project_id, v["url"])
        all_selected.extend(top)

    return all_selected


def upload_selected(**context):
    clips = context["ti"].xcom_pull(task_ids="clip_and_rank")
    if not clips:
        return

    youtube = get_authenticated_service()
    use_schedule = config.UPLOAD_MODE == "scheduled"
    next_slot = datetime.now(timezone.utc) + timedelta(hours=2)

    for clip in clips:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            # clip["videoUrl"] is a temporary download link, valid 7 days
            local_path = download_clip(clip["videoUrl"], tmp.name)

        title = clip.get("title", "New Short")[:100]
        scheduled_iso = None

        if use_schedule:
            scheduled_iso = next_slot.isoformat().replace("+00:00", "Z")
            next_slot += timedelta(hours=config.SCHEDULE_HOURS_BETWEEN_UPLOADS)

        try:
            video_id = upload_short(
                youtube, local_path, title,
                description="Auto-generated Short.",
                scheduled_time_iso=scheduled_iso,
            )
        except Exception as e:
            os.remove(local_path)
            if is_upload_limit_error(e):
                print("YouTube's daily upload limit was reached. Stopping uploads "
                      "for this run — remaining clips will need tomorrow's run.")
                return
            print(f"FAILED to upload a clip: {e}. Skipping it, continuing with the rest.")
            continue

        status = "scheduled" if scheduled_iso else "private"
        db.save_upload(video_id, str(clip["videoId"]), title, scheduled_iso, status=status)
        print(f"Uploaded {video_id} ({status}) — https://youtube.com/watch?v={video_id}")
        os.remove(local_path)


def track_performance(**context):
    n = track_all_recent(days=30)
    print(f"Refreshed performance for {n} videos.")


def pick_winners(**context):
    results = evaluate_ready_batches(min_age_days=3)
    if not results:
        print("No batches ready yet.")
    for r in results:
        print(
            f"Batch {r['project_id']}: winner "
            f"https://youtube.com/watch?v={r['winner_video_id']} "
            f"with {r['winner_views']} views"
        )


def retrain_ranker(**context):
    # Imported lazily — only needed weekly, keeps daily DAG runs light
    from ml.train_ranker import train_and_save
    metrics = train_and_save()
    print(f"Retrained ranker: {metrics}")


with DAG(
    dag_id="shorts_pipeline",
    default_args=default_args,
    description=(
        "Watches your channel for new uploads -> Vizard.ai -> ranked "
        "Shorts -> uploaded to YouTube (private by default)"
    ),
    schedule="0 */6 * * *",  # check for new source videos every 6 hours
    start_date=datetime(2026, 7, 1),
    catchup=False,
    tags=["shorts", "vizard", "youtube"],
) as dag:

    t_get_videos = PythonOperator(
        task_id="get_new_source_videos",
        python_callable=get_new_source_videos,
    )

    t_clip_and_rank = PythonOperator(
        task_id="clip_and_rank",
        python_callable=clip_and_rank,
    )

    t_upload = PythonOperator(
        task_id="upload_selected",
        python_callable=upload_selected,
    )

    t_get_videos >> t_clip_and_rank >> t_upload


with DAG(
    dag_id="shorts_performance_tracking",
    default_args=default_args,
    description="Daily performance pull for all recently published Shorts",
    schedule="0 9 * * *",  # daily at 9am
    start_date=datetime(2026, 7, 1),
    catchup=False,
    tags=["shorts", "analytics"],
) as tracking_dag:

    PythonOperator(task_id="track_performance", python_callable=track_performance)


with DAG(
    dag_id="shorts_pick_winner",
    default_args=default_args,
    description=(
        "Every 3 days: compares view counts within each clip batch "
        "(clips from the same source video) and records the winner"
    ),
    schedule=timedelta(days=3),
    start_date=datetime(2026, 7, 1),
    catchup=False,
    tags=["shorts", "analytics"],
) as winner_dag:

    PythonOperator(task_id="pick_winners", python_callable=pick_winners)


with DAG(
    dag_id="shorts_ranker_retrain",
    default_args=default_args,
    description="Weekly retrain of the LightGBM clip-ranking model",
    schedule="0 3 * * 0",  # Sundays at 3am
    start_date=datetime(2026, 7, 1),
    catchup=False,
    tags=["shorts", "ml"],
) as retrain_dag:

    PythonOperator(task_id="retrain_ranker", python_callable=retrain_ranker)