"""
Thin wrapper around the Vizard.ai API (docs.vizard.ai), confirmed as of
mid-2026. Requires a Vizard Pro plan or higher for API access.

Base URL: https://elb-api.vizard.ai/hvizard-server-front/open-api/v1
Auth: header "VIZARDAI_API_KEY: <your key>" (not a Bearer token — Vizard
uses a custom header name).

  POST /project/create        -> submit a video, returns projectId
  GET  /project/query/{id}    -> poll for clips; code 1000 = still
                                  processing, 2000 = done
"""
import time
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from config import config


class VizardError(Exception):
    pass


# videoType values Vizard expects (see docs.vizard.ai/docs/basic)
VIDEO_TYPE_REMOTE_FILE = 1
VIDEO_TYPE_YOUTUBE = 2
VIDEO_TYPE_GOOGLE_DRIVE = 3
VIDEO_TYPE_VIMEO = 4
VIDEO_TYPE_TWITCH = 9

# preferLength values
LENGTH_AUTO = 0
LENGTH_UNDER_30S = 1
LENGTH_30_60S = 2
LENGTH_60_90S = 3
LENGTH_90S_3MIN = 4


class VizardClient:
    def __init__(self):
        if not config.VIZARD_API_KEY:
            raise RuntimeError(
                "VIZARD_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        self.base_url = config.VIZARD_BASE_URL
        self.headers = {
            "Content-Type": "application/json",
            "VIZARDAI_API_KEY": config.VIZARD_API_KEY,
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2))
    def submit_video(self, video_url: str, video_type: int = VIDEO_TYPE_YOUTUBE,
                      prefer_length=(LENGTH_AUTO,), lang: str = "auto") -> str:
        """Submit a long-form video for clipping. Returns Vizard's project ID."""
        payload = {
            "lang": lang,
            "preferLength": list(prefer_length),
            "videoUrl": video_url,
            "videoType": video_type,
            "ratioOfClip": config.VIZARD_RATIO_OF_CLIP,
            "subtitleSwitch": config.VIZARD_SUBTITLE_SWITCH,
            "headlineSwitch": config.VIZARD_HEADLINE_SWITCH,
            "emojiSwitch": config.VIZARD_EMOJI_SWITCH,
            "highlightSwitch": config.VIZARD_HIGHLIGHT_SWITCH,
            "removeSilenceSwitch": config.VIZARD_REMOVE_SILENCE,
        }
        if config.VIZARD_TEMPLATE_ID:
            try:
                payload["templateId"] = int(config.VIZARD_TEMPLATE_ID)
            except ValueError:
                raise VizardError(
                    f"VIZARD_TEMPLATE_ID in .env is '{config.VIZARD_TEMPLATE_ID}', "
                    f"which isn't a valid number. Vizard template IDs are numeric — "
                    f"double check the ID you copied from the Template tab."
                )
        resp = requests.post(
            f"{self.base_url}/project/create", json=payload, headers=self.headers, timeout=30
        )
        try:
            data = resp.json()
        except ValueError:
            raise VizardError(
                f"submit_video failed: non-JSON response (HTTP {resp.status_code}): {resp.text[:500]}"
            )

        if data.get("code") != 2000:
            raise VizardError(
                f"submit_video failed (HTTP {resp.status_code}, code {data.get('code')}): "
                f"{data.get('errMsg')}. Full response: {data}"
            )

        return str(data["projectId"])

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=3, max=30))
    def get_clips(self, project_id: str) -> list[dict]:
        """
        Poll a project. Returns the list of clip dicts once ready, or an
        empty list if still processing (code 1000). Retries automatically
        on transient network errors (e.g. Wi-Fi not yet reconnected after
        waking from sleep) instead of failing the whole run immediately.
        """
        resp = requests.get(
            f"{self.base_url}/project/query/{project_id}",
            headers=self.headers,
            timeout=30,
        )
        data = resp.json()
        code = data.get("code")

        if code == 1000:
            return []  # still processing
        if code != 2000:
            raise VizardError(f"get_clips failed (code {code}): {data.get('errMsg', '')}")

        return data.get("videos", [])

    def wait_for_clips(self, project_id: str, poll_seconds: int = 30,
                       timeout_seconds: int = 3600) -> list[dict]:
        """Poll until clips are ready. Vizard recommends polling every 30s."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            clips = self.get_clips(project_id)
            if clips:
                return clips
            time.sleep(poll_seconds)
        raise VizardError(f"Timed out waiting for clips on project {project_id}")