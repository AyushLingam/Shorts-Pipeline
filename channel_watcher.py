"""
Watches your own YouTube channel for new long-form uploads (e.g. livestream
VODs) and returns only the ones not already processed through Vizard.

This is what makes source-video discovery automatic — no more manually
typing a video URL. Airflow calls get_unprocessed_source_videos() on its
schedule; anything new gets clipped and uploaded without you doing anything.
"""
from youtube_uploader import get_authenticated_service
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


def get_recent_uploads(youtube, channel_id: str, max_results: int = 5) -> list[dict]:
    """Most recent uploads on the channel, newest first."""
    playlist_id = get_uploads_playlist_id(youtube, channel_id)
    resp = youtube.playlistItems().list(
        part="snippet,contentDetails",
        playlistId=playlist_id,
        maxResults=max_results,
    ).execute()

    videos = []
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
    return videos


def get_unprocessed_source_videos(channel_id: str, max_results: int = 5) -> list[dict]:
    """
    Returns recent uploads from `channel_id` that haven't already been sent
    to Vizard. Marks them as seen immediately (before Vizard submission) so
    a retry or overlapping run won't double-submit the same source video.
    """
    youtube = get_authenticated_service()
    recent = get_recent_uploads(youtube, channel_id, max_results=max_results)

    already_seen = db.get_seen_source_video_ids()
    new_videos = [v for v in recent if v["video_id"] not in already_seen]

    for v in new_videos:
        db.mark_source_video_seen(v["video_id"], v["url"], v["title"])

    return new_videos
