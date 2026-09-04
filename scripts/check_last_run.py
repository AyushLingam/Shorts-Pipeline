"""
Prints the last run time for each scheduled task, read from the log files
Task Scheduler writes to. Quick way to confirm the overnight automation
actually fired without scrolling through full logs.

    python scripts/check_last_run.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.join(os.path.dirname(__file__), "..")

LOG_FILES = {
    "Pipeline (clip + upload)": "pipeline_log.txt",
    "Performance Tracking": "tracking_log.txt",
    "Pick Winner": "winner_log.txt",
}


def last_run_line(log_path: str) -> str | None:
    if not os.path.exists(log_path):
        return None
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        lines = [l.strip() for l in f if l.strip()]
    for line in reversed(lines):
        if line.startswith("---- Run finished"):
            return line.replace("---- Run finished", "").replace("----", "").strip()
    return None


def main():
    for label, filename in LOG_FILES.items():
        path = os.path.join(ROOT, filename)
        last = last_run_line(path)
        if last:
            print(f"{label}: last ran {last}")
        else:
            print(f"{label}: no runs recorded yet ({filename} missing or empty)")


if __name__ == "__main__":
    main()
