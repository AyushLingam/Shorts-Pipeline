"""
Uploads clips to YouTube as scheduled (private-until-publish-time) videos
using the YouTube Data API v3.
"""
import os
import requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import config


def get_authenticated_service():
    """Loads cached OAuth token, refreshes it, or runs the first-time flow."""
    creds = None
    if os.path.exists(config.YT_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(config.YT_TOKEN_FILE, config.YT_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                config.YT_CLIENT_SECRET_FILE, config.YT_SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(config.YT_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def download_clip(download_url: str, dest_path: str) -> str:
    resp = requests.get(download_url, stream=True, timeout=120)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return dest_path


def is_upload_limit_error(exc: Exception) -> bool:
    """
    True if this exception is YouTube's daily upload-cap rejection
    (reason: uploadLimitExceeded). Once this hits, every further upload
    attempt today will fail the same way — no point retrying or trying
    other clips.
    """
    return "uploadLimitExceeded" in str(exc)


def generate_thumbnail(clip_path: str) -> str | None:
    """
    Hook for Phase 9 auto-thumbnail generation. Left as a stub — plugging in
    e.g. "grab the highest-motion frame" or an image-gen call is a taste
    decision, not a technical one. Return None to let YouTube auto-pick.
    """
    return None


def upload_short(youtube, video_path: str, title: str, description: str,
                  scheduled_time_iso: str | None = None, tags: list[str] | None = None) -> str:
    """
    Uploads a video as private. If scheduled_time_iso is given (RFC 3339,
    e.g. '2026-07-28T15:00:00Z'), YouTube will auto-publish it at that time.
    If omitted, the video just stays private indefinitely, for you to
    review and publish manually in YouTube Studio. Returns the video ID.
    """
    status = {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": False,
    }
    if scheduled_time_iso:
        status["publishAt"] = scheduled_time_iso

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags or [],
            "categoryId": "20",  # Gaming; change per your content
        },
        "status": status,
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/*")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        # status is not None while chunks are still uploading; useful for a progress bar

    video_id = response["id"]

    thumb_path = generate_thumbnail(video_path)
    if thumb_path:
        youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumb_path)).execute()

    return video_id