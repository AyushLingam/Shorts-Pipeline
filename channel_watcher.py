"""
Looks at your YouTube channel and picks which long-form video (e.g. a
livestream VOD) to send through Vizard next.

Every 3 days: scan the channel's recent uploads, skip anything already
sent to Vizard before, and pick whichever of the rest currently has the
most views. That's the "video to clip" for this cycle.
"""
from youtube_uploader import get_authenticated_service
from config import config
import db


def get_uploads_playlist_id(youtube, channel_id: str) -> str:
    resp = youtube.channels().list(part="contentDetails", id=channel_id).execute()
    items = resp.get("items", [])
    if not items:
        raise ValueError(
            f"No channel found for id '{channel_id}'. Check SOURCE_CHANNEL_ID in .env — "
            f"it should start with 'UC' (find it at youtube.com/account_advanced)."
        )
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_recent_uploads(youtube, channel_id: str, max_results: int = 50) -> list[dict]:
    """
    Most recent uploads on the channel, newest first, up to max_results
    (paginates in batches of 50, the YouTube API's per-page cap).
    """
    playlist_id = get_uploads_playlist_id(youtube, channel_id)
    videos = []
    page_token = None

    while len(videos) < max_results:
        resp = youtube.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=playlist_id,
            maxResults=min(50, max_results - len(videos)),
            pageToken=page_token,
        ).execute()

        for item in resp.get("items", []):
            vid = item["contentDetails"]["videoId"]
            videos.append({
                "video_id": vid,
                "url": f"https://youtube.com/watch?v={vid}",
                "title": item["snippet"]["title"],
                "published_at": item["contentDetails"].get(
                    "videoPublishedAt", item["snippet"]["publishedAt"]
                ),
            })

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return videos


def _fetch_view_counts(youtube, video_ids: list[str]) -> dict[str, int]:
    """Batches videos().list(part=statistics) in chunks of 50 (the API's cap)."""
    views_by_id = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        resp = youtube.videos().list(part="statistics", id=",".join(chunk)).execute()
        for item in resp.get("items", []):
            views_by_id[item["id"]] = int(item.get("statistics", {}).get("viewCount", 0))
    return views_by_id


def get_unprocessed_source_videos(channel_id: str, max_results: int = 5) -> list[dict]:
    """
    Kept for scripts/run_once.py-style manual/testing use: recent uploads
    from `channel_id` that haven't already been sent to Vizard, newest
    first. The automatic flow (scripts/fetch_and_queue.py) uses
    get_highest_viewed_unprocessed_video() instead.
    """
    youtube = get_authenticated_service()
    recent = get_recent_uploads(youtube, channel_id, max_results=max_results)

    already_seen = db.get_seen_source_video_ids()
    new_videos = [v for v in recent if v["video_id"] not in already_seen]

    for v in new_videos:
        db.mark_source_video_seen(v["video_id"], v["url"], v["title"])

    return new_videos


def get_highest_viewed_unprocessed_video(channel_id: str, scan_limit: int | None = None) -> dict | None:
    """
    Scans the channel's `scan_limit` most recent uploads (default
    config.CHANNEL_SCAN_LIMIT), excludes anything already sent to Vizard,
    and returns the single remaining video with the most views right now
    (None if nothing qualifies). Marks it seen immediately so a retry or
    overlapping run won't pick it twice.
    """
    scan_limit = scan_limit or config.CHANNEL_SCAN_LIMIT
    youtube = get_authenticated_service()
    recent = get_recent_uploads(youtube, channel_id, max_results=scan_limit)
    if not recent:
        return None

    already_seen = db.get_seen_source_video_ids()
    candidates = [v for v in recent if v["video_id"] not in already_seen]
    if not candidates:
        return None

    views_by_id = _fetch_view_counts(youtube, [v["video_id"] for v in candidates])
    for v in candidates:
        v["view_count"] = views_by_id.get(v["video_id"], 0)

    winner = max(candidates, key=lambda v: v["view_count"])
    db.mark_source_video_seen(winner["video_id"], winner["url"], winner["title"])
    return winner
