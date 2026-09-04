"""
Manual end-to-end test run: one long-form video -> clips -> rank -> upload.

    python scripts/run_once.py --video-url "https://youtube.com/watch?v=XXXX" --top-n 5
"""
import argparse
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402
from vizard_client import VizardClient, VIDEO_TYPE_YOUTUBE  # noqa: E402
from clip_ranker import select_top_n  # noqa: E402
from youtube_uploader import get_authenticated_service, download_clip, upload_short, generate_description  # noqa: E402
from description_writer import generate_description_via_ai  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-url", required=True)
    parser.add_argument("--top-n", type=int, default=None)
    parser.add_argument("--hours-between-uploads", type=int, default=24)
    args = parser.parse_args()

    db.init_db()

    print("Submitting to Vizard...")
    vizard = VizardClient()
    project_id = vizard.submit_video(args.video_url, video_type=VIDEO_TYPE_YOUTUBE)

    print(f"Project {project_id} submitted. Polling for clips (this can take a while)...")
    clips = vizard.wait_for_clips(project_id)
    print(f"Got {len(clips)} clips.")

    top_clips = select_top_n(clips, n=args.top_n)
    print(f"Selected top {len(top_clips)} by rank_score:")
    for c in top_clips:
        duration_s = c.get("videoMsDuration", 0) / 1000.0
        print(f"  {c['videoId']}: score={c['rank_score']:.3f} "
              f"viral_score={c.get('viralScore')}/10 duration={duration_s:.0f}s")
        db.save_clip(c, project_id, args.video_url)

    youtube = get_authenticated_service()
    next_slot = datetime.now(timezone.utc) + timedelta(hours=1)

    for clip in top_clips:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            # clip["videoUrl"] is a temporary download link, valid 7 days
            local_path = download_clip(clip["videoUrl"], tmp.name)

        title = clip.get("title", "New Short")[:100]
        description = generate_description_via_ai(title, args.video_url) or generate_description(clip, args.video_url)
        scheduled_iso = next_slot.isoformat().replace("+00:00", "Z")

        video_id = upload_short(
            youtube, local_path, title,
            description=description,
            scheduled_time_iso=scheduled_iso,
        )
        db.save_upload(video_id, str(clip["videoId"]), title, scheduled_iso)
        print(f"Uploaded clip {clip['videoId']} -> https://youtube.com/watch?v={video_id} "
              f"(publishes {scheduled_iso})")

        next_slot += timedelta(hours=args.hours_between_uploads)
        os.remove(local_path)


if __name__ == "__main__":
    main()
