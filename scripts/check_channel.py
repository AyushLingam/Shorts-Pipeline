"""
Read-only check: confirms which YouTube channel the current token.json is
actually authorized for. Uploads nothing — safe to run anytime you want to
verify you're pointed at the right channel before trusting an automated run.

    python scripts/check_channel.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from youtube_uploader import get_authenticated_service  # noqa: E402


def main():
    youtube = get_authenticated_service()
    resp = youtube.channels().list(part="snippet,statistics", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        print("No channel found for this token — something's wrong with the auth.")
        return

    channel = items[0]
    snippet = channel["snippet"]
    stats = channel.get("statistics", {})

    print(f"Authorized channel: {snippet['title']}")
    print(f"Channel ID: {channel['id']}")
    print(f"Subscriber count: {stats.get('subscriberCount', 'hidden')}")
    print(f"Video count: {stats.get('videoCount', 'unknown')}")


if __name__ == "__main__":
    main()
