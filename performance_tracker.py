"""
Phase 7: pull performance data for uploaded Shorts.

Uses the YouTube Analytics API (channel-scoped reports) for view/retention
metrics, and the Data API's videos.list for basic public counts (views,
likes, comments) as a lightweight fallback/cross-check.
"""
from datetime import datetime, timezone
from googleapiclient.discovery import build

from youtube_uploader import get_authenticated_service
import db


def _basic_stats(youtube, video_id: str) -> dict:
    resp = youtube.videos().list(part="statistics", id=video_id).execute()
    items = resp.get("items", [])
    if not items:
        return {}
    stats = items[0]["statistics"]
    return {
        "views": int(stats.get("viewCount", 0)),
        "likes": int(stats.get("likeCount", 0)),
        "comments": int(stats.get("commentCount", 0)),
    }


def _analytics_stats(analytics, video_id: str, channel_id: str = "mine") -> dict:
    """Average view duration & audience retention from the Analytics API."""
    today = datetime.now(timezone.utc).date().isoformat()
    resp = analytics.reports().query(
        ids=f"channel==MINE",
        startDate="2020-01-01",
        endDate=today,
        metrics="averageViewDuration,averageViewPercentage,shares",
        filters=f"video=={video_id}",
    ).execute()
    rows = resp.get("rows", [])
    if not rows:
        return {}
    avg_dur, avg_pct, shares = rows[0]
    return {
        "avg_view_duration_sec": avg_dur,
        "audience_retention_pct": avg_pct,
        "shares": int(shares),
    }


def track_all_recent(days: int = 30):
    creds_service = get_authenticated_service()
    # Analytics API uses the same OAuth creds but a different API name/version
    analytics = build("youtubeAnalytics", "v2", credentials=creds_service._http.credentials)

    video_ids = db.get_published_video_ids(days=days)
    pulled_at = datetime.now(timezone.utc).isoformat()

    for vid in video_ids:
        stats = _basic_stats(creds_service, vid)
        stats.update(_analytics_stats(analytics, vid))
        db.save_performance_snapshot(vid, pulled_at, stats)

    return len(video_ids)


if __name__ == "__main__":
    db.init_db()
    n = track_all_recent()
    print(f"Updated performance for {n} videos.")
