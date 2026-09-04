"""
The "daily" job (needs its OWN Task Scheduler entry -- see
run_upload_queue.bat). Uploads up to config.YOUTUBE_DAILY_UPLOAD_QUOTA
(default 6) clips from the local queue built by fetch_and_queue.py.

Every upload:
  - privacyStatus = private
  - publishAt = the clip's pre-assigned schedule.py slot, so it auto-
    publishes at the right time unless you review/edit/publish it earlier
    in YouTube Studio.
  - description = the clip's title (nothing else), no tags.

This is what actually respects YouTube's daily upload quota -- the quota
is charged when a video is CREATED, not when it goes public, so this has
to run daily even though publish times are spread across days.

    python scripts/drain_upload_queue.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402
from config import config  # noqa: E402
from youtube_uploader import get_authenticated_service, upload_short, is_upload_limit_error  # noqa: E402

OVERDUE_BUFFER_MINUTES = 5


def main():
    db.init_db()
    rows = db.get_next_to_upload(config.YOUTUBE_DAILY_UPLOAD_QUOTA)
    if not rows:
        print("Upload queue is empty -- nothing to do today.")
        return

    print(f"{db.count_queued()} clip(s) queued total; uploading up to "
          f"{len(rows)} today (quota={config.YOUTUBE_DAILY_UPLOAD_QUOTA}/day).")

    youtube = get_authenticated_service()
    now = datetime.now(timezone.utc)

    for row in rows:
        if not os.path.exists(row["local_file_path"]):
            db.mark_queue_failed(row["queue_id"], "local clip file is missing")
            print(f"  SKIPPED '{row['title']}': local file missing "
                  f"({row['local_file_path']}).")
            continue

        publish_at = datetime.fromisoformat(row["target_publish_time"].replace("Z", "+00:00"))
        if publish_at <= now:
            publish_at = now + timedelta(minutes=OVERDUE_BUFFER_MINUTES)
            print(f"  Note: '{row['title']}' was scheduled for "
                  f"{row['target_publish_time']} (already past) -- "
                  f"publishing shortly instead ({publish_at.isoformat()}).")
        publish_iso = publish_at.isoformat().replace("+00:00", "Z")

        try:
            video_id = upload_short(
                youtube, row["local_file_path"],
                title=row["title"],
                description=row["title"],
                scheduled_time_iso=publish_iso,
                tags=[],
            )
        except Exception as e:
            if is_upload_limit_error(e):
                print("YouTube's daily upload limit was reached. Stopping here -- "
                      "the rest of the queue will go out on a future run.")
                return
            db.mark_queue_failed(row["queue_id"], str(e))
            print(f"  FAILED to upload '{row['title']}': {e}. Marked failed, continuing.")
            continue

        db.mark_queue_uploaded(row["queue_id"], video_id)
        db.save_upload(video_id, row["clip_id"], row["title"], publish_iso, status="scheduled")
        os.remove(row["local_file_path"])
        print(f"  Uploaded '{row['title']}' -> https://youtube.com/watch?v={video_id} "
              f"(publishes {publish_iso})")


if __name__ == "__main__":
    main()
