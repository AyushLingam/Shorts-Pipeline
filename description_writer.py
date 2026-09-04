"""
Optional: asks OpenAI (the actual API behind ChatGPT) to write a YouTube
Shorts description from just the clip's title and a link to the full
source video. Set OPENAI_API_KEY in .env to enable it. If the key is
unset, or the request fails for any reason, callers fall back to
youtube_uploader.generate_description() (the Vizard-metadata version)
instead — this never blocks an upload.
"""
import requests
from config import config

OPENAI_URL = "https://api.openai.com/v1/chat/completions"

SYSTEM_PROMPT = (
    "You write short, natural-sounding YouTube Shorts descriptions. Rules: "
    "no clickbait phrases like 'You won't believe' or 'Wait for it', no "
    "more than one emoji (zero is often better), no all-caps, no more than "
    "5 hashtags, sound like a real person wrote it in 30 seconds, not a "
    "marketing bot. 2-3 sentences max. Don't invent facts the title doesn't "
    "support. End with a short line crediting/linking the full video."
)


def generate_description_via_ai(title: str, source_video_url: str) -> str | None:
    """Returns an AI-written description, or None if unavailable/failed."""
    if not config.OPENAI_API_KEY:
        return None

    user_prompt = (
        f'Video clip title: "{title}"\n'
        f"Full source video: {source_video_url}\n\n"
        f"Write a YouTube Shorts description for this clip."
    )

    try:
        resp = requests.post(
            OPENAI_URL,
            headers={
                "Authorization": f"Bearer {config.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 200,
                "temperature": 0.7,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        return text[:5000] or None
    except Exception as e:
        print(f"AI description generation failed, falling back to default: {e}")
        return None
