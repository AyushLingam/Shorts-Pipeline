"""
Manual test of the AUTOMATIC path: checks your channel for new uploads,
clips them via Vizard, uploads the winners to YouTube as PRIVATE (or
scheduled, if UPLOAD_MODE=scheduled in .env) — the same logic the Airflow
DAG runs on its own schedule. Useful to test before trusting Airflow with it.

    python scripts/run_watch_and_process.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402
from config import config  # noqa: E402
from vizard_client import VizardClient, VIDEO_TYPE_YOUTUBE  # noqa: E402
from clip_ranker import select_top_n  # noqa: E402
from youtube_uploader import get_authenticated_service, download_clip, upload_short, is_upload_limit_error  # noqa: E402
from channel_watcher import get_unprocessed_source_videos  # noqa: E402


def main():
    if not config.SOURCE_CHANNEL_ID:
        print("SOURCE_CHANNEL_ID is not set in .env. Find yours at "
              "youtube.com/account_advanced (starts with 'UC') and add it, then rerun.")
        return

    db.init_db()

    print(f"Checking channel {config.SOURCE_CHANNEL_ID} for new uploads...")
    videos = get_unprocessed_source_videos(
        config.SOURCE_CHANNEL_ID, max_results=config.CHANNEL_CHECK_MAX_RESULTS
    )
    if not videos:
        print("No new source videos found.")
        return

    print(f"Found {len(videos)} new video(s): " + ", ".join(v["title"] for v in videos))

    vizard = VizardClient()
    youtube = get_authenticated_service()
    use_schedule = config.UPLOAD_MODE == "scheduled"
    next_slot = datetime.now(timezone.utc) + timedelta(hours=2)

    for v in videos:
        pending_project_id = db.get_pending_submission(v["video_id"])
        try:
            if pending_project_id:
                print(f"\nResuming previous submission of '{v['title']}' "
                      f"(project {pending_project_id}, no new credits spent)...")
                project_id = pending_project_id
            else:
                print(f"\nSubmitting '{v['title']}' to Vizard...")
                project_id = vizard.submit_video(v["url"], video_type=VIDEO_TYPE_YOUTUBE)
                db.save_pending_submission(v["video_id"], project_id, v["url"], v["title"])

            clips = vizard.wait_for_clips(project_id)
        except Exception as e:
            print(f"  FAILED to process '{v['title']}': {e}")
            print("  Skipping — it will resume from the same Vizard project next run "
                  "(no duplicate credits spent).")
            continue

        print(f"Got {len(clips)} clips.")
        db.mark_source_video_seen(v["video_id"], v["url"], v["title"])
        db.clear_pending_submission(v["video_id"])

        top_clips = select_top_n(clips)
        for clip in top_clips:
            db.save_clip(clip, project_id, v["url"])

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
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
                    print(f"  YouTube's daily upload limit was reached. Stopping uploads "
                          f"for this run — {len(top_clips) - top_clips.index(clip) - 1} "
                          f"remaining clip(s) from this video won't be uploaded (Vizard "
                          f"already processed them, so no extra credits needed to skip them).")
                    return
                print(f"  FAILED to upload this clip: {e}")
                print("  Skipping it, continuing with the rest.")
                continue

            status = "scheduled" if scheduled_iso else "private"
            db.save_upload(video_id, str(clip["videoId"]), title, scheduled_iso, status=status)
            print(f"  Uploaded ({status}): https://youtube.com/watch?v={video_id}")
            os.remove(local_path)


if __name__ == "__main__":
    main()