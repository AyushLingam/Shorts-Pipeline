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

    TOP_N_CLIPS_PER_VIDEO = int(os.getenv("TOP_N_CLIPS_PER_VIDEO", "5"))
    MIN_CLIP_SECONDS = int(os.getenv("MIN_CLIP_SECONDS", "15"))
    MAX_CLIP_SECONDS = int(os.getenv("MAX_CLIP_SECONDS", "90"))

    # Which of YOUR channels to watch for new long-form uploads (find it at
    # youtube.com/account_advanced while logged into your channel — it's
    # the "Channel ID" field, starts with UC...).
    SOURCE_CHANNEL_ID = os.getenv("SOURCE_CHANNEL_ID", "")
    # How many of the channel's most recent uploads to check each run.
    CHANNEL_CHECK_MAX_RESULTS = int(os.getenv("CHANNEL_CHECK_MAX_RESULTS", "5"))

    # "private" = upload and leave private for you to review/publish
    # manually in YouTube Studio. "scheduled" = auto-publish on a spaced
    # schedule (old behavior).
    UPLOAD_MODE = os.getenv("UPLOAD_MODE", "private")
    SCHEDULE_HOURS_BETWEEN_UPLOADS = int(os.getenv("SCHEDULE_HOURS_BETWEEN_UPLOADS", "24"))

    # Optional: AI-written descriptions via OpenAI. Leave OPENAI_API_KEY
    # blank to use the built-in Vizard-metadata description instead.
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # Vizard clip styling — set VIZARD_TEMPLATE_ID after creating a template
    # in the Vizard web editor (Edit a clip -> Template tab -> copy ID).
    VIZARD_TEMPLATE_ID = os.getenv("VIZARD_TEMPLATE_ID", "") or None
    VIZARD_RATIO_OF_CLIP = int(os.getenv("VIZARD_RATIO_OF_CLIP", "1"))  # 1=9:16, 4=16:9
    VIZARD_SUBTITLE_SWITCH = int(os.getenv("VIZARD_SUBTITLE_SWITCH", "1"))
    VIZARD_HEADLINE_SWITCH = int(os.getenv("VIZARD_HEADLINE_SWITCH", "1"))
    VIZARD_EMOJI_SWITCH = int(os.getenv("VIZARD_EMOJI_SWITCH", "0"))
    VIZARD_HIGHLIGHT_SWITCH = int(os.getenv("VIZARD_HIGHLIGHT_SWITCH", "0"))
    VIZARD_REMOVE_SILENCE = int(os.getenv("VIZARD_REMOVE_SILENCE", "0"))

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
