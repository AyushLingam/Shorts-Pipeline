"""
The "every 3 days" job (run via Task Scheduler / run_pipeline.bat).

1. Looks at your channel, picks the highest-viewed video that hasn't been
   sent to Vizard before.
2. Submits it to Vizard using the v2 model, waits for every clip.
3. Ranks all of them (best-first) and assigns each a target publish time
   via scheduler.py (peak slots for the best clips, spread over enough
   days to respect the YouTube upload quota).
4. Downloads every clip locally and drops it in the upload queue
   (upload_queue table) -- does NOT touch YouTube. That happens in
   scripts/drain_upload_queue.py, run daily, which is what actually keeps
   uploads under the ~6/day quota while still hitting every clip's
   assigned schedule.

    python scripts/fetch_and_queue.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402
from config import config  # noqa: E402
from vizard_client import VizardClient, VIDEO_TYPE_YOUTUBE  # noqa: E402
from clip_ranker import rank_clips  # noqa: E402
from scheduler import assign_slots  # noqa: E402
from channel_watcher import get_highest_viewed_unprocessed_video  # noqa: E402
from youtube_uploader import download_clip  # noqa: E402


def main():
    if not config.SOURCE_CHANNEL_ID:
        print("SOURCE_CHANNEL_ID is not set in .env. Find yours at "
              "youtube.com/account_advanced (starts with 'UC') and add it, then rerun.")
        return

    db.init_db()
    os.makedirs(config.QUEUE_DIR, exist_ok=True)

    print(f"Scanning channel {config.SOURCE_CHANNEL_ID} for the highest-viewed "
          f"video not already clipped (checking up to {config.CHANNEL_SCAN_LIMIT} "
          f"recent uploads)...")
    video = get_highest_viewed_unprocessed_video(config.SOURCE_CHANNEL_ID)
    if not video:
        print("No unprocessed source videos found (either the channel has nothing "
              "new, or everything recent has already been clipped).")
        return

    print(f"Picked '{video['title']}' ({video['view_count']:,} views) -> {video['url']}")

    vizard = VizardClient()
    pending_project_id = db.get_pending_submission(video["video_id"])
    try:
        if pending_project_id:
            print(f"Resuming previous submission (project {pending_project_id}, "
                  f"no new credits spent)...")
            project_id = pending_project_id
        else:
            print(f"Submitting to Vizard (clipModel={config.VIZARD_CLIP_MODEL})...")
            project_id = vizard.submit_video(video["url"], video_type=VIDEO_TYPE_YOUTUBE)
            db.save_pending_submission(video["video_id"], project_id, video["url"], video["title"])

        print("Waiting for clips (v2 model can take a while)...")
        clips = vizard.wait_for_clips(project_id)
    except Exception as e:
        print(f"FAILED to process '{video['title']}': {e}")
        print("Will resume from the same Vizard project next run (no duplicate credits spent).")
        return

    db.clear_pending_submission(video["video_id"])
    print(f"Got {len(clips)} clip(s). Ranking...")

    ranked = rank_clips(clips)

    existing_max = db.get_max_queued_publish_time()
    earliest_start = None
    if existing_max:
        last_dt = datetime.fromisoformat(existing_max.replace("Z", "+00:00"))
        earliest_start = last_dt + timedelta(hours=config.SCHEDULE_TARGET_GAP_HOURS)

    scheduled = assign_slots(ranked, earliest_start_utc=earliest_start)

    queued_count = 0
    for clip in scheduled:
        clip_id = str(clip["videoId"])
        title = (clip.get("title") or "New Short")[:100]
        local_path = os.path.join(config.QUEUE_DIR, f"{clip_id}.mp4")

        try:
            download_clip(clip["videoUrl"], local_path)
        except Exception as e:
            print(f"  FAILED to download clip {clip_id}: {e}. Skipping it.")
            continue

        db.save_clip(clip, project_id, video["url"])
        db.enqueue_clip(
            clip_id=clip_id,
            source_project_id=project_id,
            title=title,
            local_file_path=local_path,
            target_publish_time_utc=clip["target_publish_time_utc"],
        )
        queued_count += 1
        print(f"  Queued '{title}' -> publishes {clip['target_publish_time_local']} "
              f"({clip['target_publish_time_utc']})")

    print(f"\nQueued {queued_count}/{len(scheduled)} clip(s) from '{video['title']}'. "
          f"scripts/drain_upload_queue.py will upload up to "
          f"{config.YOUTUBE_DAILY_UPLOAD_QUOTA}/day from here.")


if __name__ == "__main__":
    main()
