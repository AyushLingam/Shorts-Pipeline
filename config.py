"""Central config, loaded from environment / .env."""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    VIZARD_API_KEY = os.getenv("VIZARD_API_KEY", "")
    VIZARD_BASE_URL = "https://elb-api.vizard.ai/hvizard-server-front/open-api/v1"

    YT_CLIENT_SECRET_FILE = os.getenv("YT_CLIENT_SECRET_FILE", "./client_secret.json")
    YT_TOKEN_FILE = os.getenv("YT_TOKEN_FILE", "./token.json")
    YT_SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ]

    # Upload EVERY clip Vizard returns for a video -- no top-N cutoff anymore.
    # (Kept as a safety valve only; leave at 0 to mean "no cap".)
    TOP_N_CLIPS_PER_VIDEO = int(os.getenv("TOP_N_CLIPS_PER_VIDEO", "0"))
    MIN_CLIP_SECONDS = int(os.getenv("MIN_CLIP_SECONDS", "15"))
    MAX_CLIP_SECONDS = int(os.getenv("MAX_CLIP_SECONDS", "90"))

    # Which of YOUR channels to watch (find it at youtube.com/account_advanced
    # while logged into your channel -- the "Channel ID" field, starts with UC...).
    SOURCE_CHANNEL_ID = os.getenv("SOURCE_CHANNEL_ID", "")
    # How many of the channel's most recent uploads to scan when picking the
    # highest-viewed unprocessed video (not just the newest).
    CHANNEL_SCAN_LIMIT = int(os.getenv("CHANNEL_SCAN_LIMIT", "50"))

    # "private" = upload and leave private for you to review/publish manually.
    # "scheduled" = upload private but with YouTube's publishAt set, so it
    # auto-publishes at its assigned slot unless you intervene first in
    # YouTube Studio. The queue-drain flow (scripts/drain_upload_queue.py)
    # always uses "scheduled".
    UPLOAD_MODE = os.getenv("UPLOAD_MODE", "scheduled")

    # ---- Spacing / scheduling (Phase: spaced private uploads) ----
    # Target gap between uploads, and the fallback tight gap used only when
    # there isn't enough of an upload budget to keep the target gap while
    # covering everything within the 3-day cycle.
    SCHEDULE_TARGET_GAP_HOURS = int(os.getenv("SCHEDULE_TARGET_GAP_HOURS", "4"))
    SCHEDULE_MAX_GAP_HOURS = int(os.getenv("SCHEDULE_MAX_GAP_HOURS", "5"))
    SCHEDULE_TIGHT_GAP_HOURS = int(os.getenv("SCHEDULE_TIGHT_GAP_HOURS", "3"))
    # Local day window clips can be slotted into (24h clock).
    SCHEDULE_DAY_START_HOUR = int(os.getenv("SCHEDULE_DAY_START_HOUR", "8"))
    SCHEDULE_DAY_END_HOUR = int(os.getenv("SCHEDULE_DAY_END_HOUR", "23"))
    # The "prime time" window the highest-rated clips of each day should land in.
    SCHEDULE_PEAK_START_HOUR = int(os.getenv("SCHEDULE_PEAK_START_HOUR", "12"))
    SCHEDULE_PEAK_END_HOUR = int(os.getenv("SCHEDULE_PEAK_END_HOUR", "20"))
    # How many days a single video's clips should normally be spread across
    # before falling back to the tight gap.
    SCHEDULE_TARGET_DAYS = int(os.getenv("SCHEDULE_TARGET_DAYS", "3"))
    # IANA timezone the hours above are interpreted in.
    SCHEDULE_TIMEZONE = os.getenv("SCHEDULE_TIMEZONE", "America/New_York")

    # YouTube Data API default quota is 10,000 units/day and an upload costs
    # 1,600 units -- so ~6 uploads/day unless you've requested a quota bump.
    # This caps how many queued clips scripts/drain_upload_queue.py will
    # actually upload in one run.
    YOUTUBE_DAILY_UPLOAD_QUOTA = int(os.getenv("YOUTUBE_DAILY_UPLOAD_QUOTA", "6"))

    # Local folder where clips wait after being downloaded but before their
    # turn to be uploaded (queue-drain reads from here).
    QUEUE_DIR = os.getenv("QUEUE_DIR", "./queued_clips")

    # Vizard clip styling -- set VIZARD_TEMPLATE_ID after creating a template
    # in the Vizard web editor (Edit a clip -> Template tab -> copy ID).
    VIZARD_TEMPLATE_ID = os.getenv("VIZARD_TEMPLATE_ID", "") or None
    VIZARD_RATIO_OF_CLIP = int(os.getenv("VIZARD_RATIO_OF_CLIP", "1"))  # 1=9:16, 4=16:9
    VIZARD_SUBTITLE_SWITCH = int(os.getenv("VIZARD_SUBTITLE_SWITCH", "1"))
    VIZARD_HEADLINE_SWITCH = int(os.getenv("VIZARD_HEADLINE_SWITCH", "1"))
    VIZARD_EMOJI_SWITCH = int(os.getenv("VIZARD_EMOJI_SWITCH", "0"))
    VIZARD_HIGHLIGHT_SWITCH = int(os.getenv("VIZARD_HIGHLIGHT_SWITCH", "0"))
    VIZARD_REMOVE_SILENCE = int(os.getenv("VIZARD_REMOVE_SILENCE", "0"))
    # "v1" = faster, more clips. "v2" = AI thinks longer/goes deeper, fewer
    # but more complete clips, charged at a higher credit rate (seen ~1.25x
    # in the Vizard dashboard, e.g. 23 credits on v1 vs 29 on v2 for the same
    # video). Confirmed against the Vizard web app's model picker, not just
    # the public API docs -- if Vizard ever renames this field, submit_video()
    # will raise a clear VizardError rather than failing silently.
    VIZARD_CLIP_MODEL = os.getenv("VIZARD_CLIP_MODEL", "v2")
    # Ask Vizard for as many clips as it's willing to return (1-100).
    VIZARD_MAX_CLIP_NUMBER = int(os.getenv("VIZARD_MAX_CLIP_NUMBER", "100"))

    DB_PATH = os.getenv("DB_PATH", "./shorts.db")
    MODEL_PATH = os.getenv("MODEL_PATH", "./models/ranker.txt")

    def validate(self):
        missing = [k for k in ("VIZARD_API_KEY",) if not getattr(self, k)]
        if missing:
            raise RuntimeError(
                f"Missing required config values: {missing}. "
                f"Copy .env.example to .env and fill them in."
            )


config = Config()
