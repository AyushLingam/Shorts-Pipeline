"""Run once to create token.json via browser OAuth consent."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from youtube_uploader import get_authenticated_service  # noqa: E402

if __name__ == "__main__":
    get_authenticated_service()
    print("Auth complete — token.json created. You're set for future runs.")
