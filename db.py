"""SQLite storage for clips, uploads, the upload queue, and performance data."""
import sqlite3
import json
from contextlib import contextmanager
from config import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    clip_id           TEXT PRIMARY KEY,
    source_project_id TEXT,
    source_video_url  TEXT,
    duration_sec      REAL,
    viral_score       REAL,
    rank_score        REAL,
    download_url      TEXT,
    raw_metadata      TEXT,           -- full JSON blob from Vizard
    created_at        TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS uploads (
    youtube_video_id  TEXT PRIMARY KEY,
    clip_id           TEXT REFERENCES clips(clip_id),
    title             TEXT,
    scheduled_time    TEXT,
    published_time    TEXT,
    status            TEXT,           -- scheduled | published | failed
    created_at        TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS performance (
    youtube_video_id  TEXT REFERENCES uploads(youtube_video_id),
    pulled_at         TEXT,
    views             INTEGER,
    likes             INTEGER,
    comments          INTEGER,
    shares            INTEGER,
    avg_view_duration_sec REAL,
    audience_retention_pct REAL,
    PRIMARY KEY (youtube_video_id, pulled_at)
);

CREATE TABLE IF NOT EXISTS source_videos (
    -- Tracks which of YOUR long-form uploads have already been sent to
    -- Vizard, so the channel watcher never picks the same VOD twice.
    video_id   TEXT PRIMARY KEY,
    video_url  TEXT,
    title      TEXT,
    seen_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS batch_winners (
    -- Every N days, compares view counts across the clips generated from
    -- the same source video and records which one performed best.
    source_project_id      TEXT PRIMARY KEY,
    winner_youtube_video_id TEXT,
    winner_views            INTEGER,
    all_views_json          TEXT,
    evaluated_at            TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pending_submissions (
    -- A video already submitted to Vizard (project created, credits
    -- spent) but not yet fully processed into queued clips. If a run
    -- crashes after submission (e.g. network drop while polling), the
    -- next run resumes checking THIS project instead of resubmitting the
    -- video and wasting credits twice.
    video_id    TEXT PRIMARY KEY,
    project_id  TEXT,
    video_url   TEXT,
    title       TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS upload_queue (
    -- Every clip Vizard returns for a picked source video, downloaded and
    -- waiting for its turn to actually be uploaded to YouTube. This is
    -- what lets scripts/fetch_and_queue.py (every 3 days) run instantly
    -- while scripts/drain_upload_queue.py (daily) trickles uploads out
    -- at YouTube's ~6/day quota, each with the schedule.py-assigned
    -- publishAt time.
    queue_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id             TEXT,
    source_project_id   TEXT,
    title               TEXT,
    local_file_path     TEXT,
    target_publish_time TEXT,          -- RFC3339 UTC, e.g. 2026-09-05T16:00:00Z
    status              TEXT DEFAULT 'queued',  -- queued | uploaded | failed
    youtube_video_id    TEXT,
    error_message       TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def save_clip(clip: dict, source_project_id: str, source_video_url: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO clips
               (clip_id, source_project_id, source_video_url, duration_sec,
                viral_score, rank_score, download_url, raw_metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(clip["videoId"]),
                source_project_id,
                source_video_url,
                clip.get("videoMsDuration", 0) / 1000.0,
                clip.get("viralScore"),
                clip.get("rank_score"),
                clip.get("videoUrl"),
                json.dumps(clip),
            ),
        )


def save_upload(youtube_video_id: str, clip_id: str, title: str,
                 scheduled_time: str, status: str = "scheduled"):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO uploads
               (youtube_video_id, clip_id, title, scheduled_time, status)
               VALUES (?, ?, ?, ?, ?)""",
            (youtube_video_id, clip_id, title, scheduled_time, status),
        )


def mark_published(youtube_video_id: str, published_time: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE uploads SET status = 'published', published_time = ? WHERE youtube_video_id = ?",
            (published_time, youtube_video_id),
        )


def save_performance_snapshot(youtube_video_id: str, pulled_at: str, stats: dict):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO performance
               (youtube_video_id, pulled_at, views, likes, comments, shares,
                avg_view_duration_sec, audience_retention_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                youtube_video_id, pulled_at,
                stats.get("views", 0), stats.get("likes", 0),
                stats.get("comments", 0), stats.get("shares", 0),
                stats.get("avg_view_duration_sec"), stats.get("audience_retention_pct"),
            ),
        )


def get_published_video_ids(days: int = 30) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT youtube_video_id FROM uploads
               WHERE status = 'published'
               AND published_time >= datetime('now', ?)""",
            (f"-{days} days",),
        ).fetchall()
        return [r["youtube_video_id"] for r in rows]


def get_training_dataset() -> list[dict]:
    """Join clip features with latest performance for ML training (Phase 8)."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.clip_id, c.duration_sec, c.viral_score, c.raw_metadata,
                   u.youtube_video_id, u.published_time,
                   p.views, p.likes, p.comments, p.avg_view_duration_sec,
                   p.audience_retention_pct
            FROM clips c
            JOIN uploads u ON u.clip_id = c.clip_id
            JOIN performance p ON p.youtube_video_id = u.youtube_video_id
            WHERE p.pulled_at = (
                SELECT MAX(pulled_at) FROM performance p2
                WHERE p2.youtube_video_id = u.youtube_video_id
            )
            """
        ).fetchall()
        return [dict(r) for r in rows]


# ---- Channel watcher / dedup ----

def get_seen_source_video_ids() -> set[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT video_id FROM source_videos").fetchall()
        return {r["video_id"] for r in rows}


def mark_source_video_seen(video_id: str, video_url: str, title: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO source_videos (video_id, video_url, title) VALUES (?, ?, ?)",
            (video_id, video_url, title),
        )


# ---- Batch winner picking (every N days) ----

def get_video_ids_by_project(source_project_id: str) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT u.youtube_video_id FROM uploads u
               JOIN clips c ON c.clip_id = u.clip_id
               WHERE c.source_project_id = ?""",
            (source_project_id,),
        ).fetchall()
        return [r["youtube_video_id"] for r in rows]


def get_unevaluated_project_batches(min_age_days: int = 3) -> list[str]:
    """
    Returns source_project_ids where every clip in the batch was uploaded
    at least min_age_days ago, and the batch hasn't been scored yet.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.source_project_id
            FROM clips c
            JOIN uploads u ON u.clip_id = c.clip_id
            WHERE c.source_project_id NOT IN (SELECT source_project_id FROM batch_winners)
            GROUP BY c.source_project_id
            HAVING MAX(u.created_at) <= datetime('now', ?)
            """,
            (f"-{min_age_days} days",),
        ).fetchall()
        return [r["source_project_id"] for r in rows]


def get_latest_views(youtube_video_id: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT views FROM performance
               WHERE youtube_video_id = ?
               ORDER BY pulled_at DESC LIMIT 1""",
            (youtube_video_id,),
        ).fetchone()
        return row["views"] if row else 0


def save_batch_winner(source_project_id: str, winner_video_id: str,
                       winner_views: int, all_views: dict):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO batch_winners
               (source_project_id, winner_youtube_video_id, winner_views, all_views_json)
               VALUES (?, ?, ?, ?)""",
            (source_project_id, winner_video_id, winner_views, json.dumps(all_views)),
        )


# ---- Pending Vizard submissions (crash-safe resume) ----

def save_pending_submission(video_id: str, project_id: str, video_url: str, title: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO pending_submissions
               (video_id, project_id, video_url, title)
               VALUES (?, ?, ?, ?)""",
            (video_id, project_id, video_url, title),
        )


def get_pending_submission(video_id: str) -> str | None:
    """Returns the existing Vizard project_id for this video, if one is pending."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT project_id FROM pending_submissions WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        return row["project_id"] if row else None


def clear_pending_submission(video_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM pending_submissions WHERE video_id = ?", (video_id,))


# ---- Upload queue (spaced private uploads, drained daily) ----

def enqueue_clip(clip_id: str, source_project_id: str, title: str,
                  local_file_path: str, target_publish_time_utc: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO upload_queue
               (clip_id, source_project_id, title, local_file_path, target_publish_time)
               VALUES (?, ?, ?, ?, ?)""",
            (clip_id, source_project_id, title, local_file_path, target_publish_time_utc),
        )
        return cur.lastrowid


def get_max_queued_publish_time() -> str | None:
    """
    The latest target_publish_time already queued (any status). Used so a
    new fetch_and_queue.py run continues the schedule after whatever the
    previous batch already claimed, instead of colliding with it.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(target_publish_time) AS max_time FROM upload_queue"
        ).fetchone()
        return row["max_time"] if row and row["max_time"] else None


def get_next_to_upload(limit: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM upload_queue
               WHERE status = 'queued'
               ORDER BY target_publish_time ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def count_queued() -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM upload_queue WHERE status = 'queued'"
        ).fetchone()
        return row["n"]


def mark_queue_uploaded(queue_id: int, youtube_video_id: str):
    with get_conn() as conn:
        conn.execute(
            """UPDATE upload_queue
               SET status = 'uploaded', youtube_video_id = ?, updated_at = datetime('now')
               WHERE queue_id = ?""",
            (youtube_video_id, queue_id),
        )


def mark_queue_failed(queue_id: int, error_message: str):
    with get_conn() as conn:
        conn.execute(
            """UPDATE upload_queue
               SET status = 'failed', error_message = ?, updated_at = datetime('now')
               WHERE queue_id = ?""",
            (error_message[:2000], queue_id),
        )
