"""
Every N days (default 3), looks at each batch of clips generated from the
same source video, compares their current view counts, and records which
one performed best. Requires performance_tracker to have already pulled
view counts for those videos (the daily tracking DAG handles that).

This doesn't take any action on YouTube by itself — it's a report, and the
recorded results double as extra signal for ml/train_ranker.py later.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "."))

import db


def evaluate_ready_batches(min_age_days: int = 3) -> list[dict]:
    results = []
    for project_id in db.get_unevaluated_project_batches(min_age_days=min_age_days):
        video_ids = db.get_video_ids_by_project(project_id)
        if not video_ids:
            continue

        views_by_video = {vid: db.get_latest_views(vid) for vid in video_ids}
        winner_id = max(views_by_video, key=views_by_video.get)
        winner_views = views_by_video[winner_id]

        db.save_batch_winner(project_id, winner_id, winner_views, views_by_video)
        results.append({
            "project_id": project_id,
            "winner_video_id": winner_id,
            "winner_views": winner_views,
            "all_views": views_by_video,
        })
    return results


if __name__ == "__main__":
    db.init_db()
    batches = evaluate_ready_batches()
    if not batches:
        print("No batches ready to evaluate yet (need clips uploaded 3+ days ago "
              "with performance data tracked).")
    for r in batches:
        print(
            f"Batch {r['project_id']}: winner is "
            f"https://youtube.com/watch?v={r['winner_video_id']} "
            f"with {r['winner_views']} views  |  all: {r['all_views']}"
        )
