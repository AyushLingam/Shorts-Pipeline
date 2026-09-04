"""
Phase 8: train a model that predicts "which clip is likely to perform
better" rather than a binary viral/not-viral classifier.

Target: views-per-hour in the first 48h after publish, log-transformed and
normalized so the loss isn't dominated by your one breakout hit.

Run manually or via the weekly Airflow DAG task.
"""
import os
import sys
import math
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split

import db
from config import config

# Must match clip_ranker.py's FEATURE_ORDER exactly.
FEATURE_COLUMNS = ["duration_sec", "viral_score", "word_count"]
MIN_ROWS_TO_TRAIN = 30  # below this, you don't have enough signal yet


def _build_dataframe() -> pd.DataFrame:
    rows = db.get_training_dataset()
    if not rows:
        return pd.DataFrame()

    records = []
    for r in rows:
        meta = json.loads(r["raw_metadata"]) if r["raw_metadata"] else {}
        views = r["views"] or 0
        # hours since publish, at least 1 to avoid div by zero
        # (you'd compute this from published_time -> now in a real run;
        #  simplified here since this repo has no live data yet)
        hours_live = max(meta.get("hours_since_publish", 48), 1)

        transcript = meta.get("transcript", "") or ""

        records.append({
            "duration_sec": r["duration_sec"] or 30,
            "viral_score": (float(r["viral_score"]) / 10.0) if r["viral_score"] else 0.5,
            "word_count": len(transcript.split()),
            "target": math.log1p(views / hours_live),
        })

    return pd.DataFrame(records)


def train_and_save() -> dict:
    df = _build_dataframe()
    if len(df) < MIN_ROWS_TO_TRAIN:
        return {
            "status": "skipped",
            "reason": f"only {len(df)} labeled examples, need {MIN_ROWS_TO_TRAIN}+",
        }

    X = df[FEATURE_COLUMNS]
    y = df["target"]
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)

    train_set = lgb.Dataset(X_train, label=y_train)
    val_set = lgb.Dataset(X_val, label=y_val, reference=train_set)

    params = {
        "objective": "regression",
        "metric": "rmse",
        "learning_rate": 0.05,
        "num_leaves": 15,
        "verbose": -1,
    }

    model = lgb.train(
        params, train_set, num_boost_round=200,
        valid_sets=[val_set],
        callbacks=[lgb.early_stopping(20, verbose=False)],
    )

    os.makedirs(os.path.dirname(config.MODEL_PATH), exist_ok=True)
    model.save_model(config.MODEL_PATH)

    return {
        "status": "trained",
        "rows": len(df),
        "best_iteration": model.best_iteration,
        "best_score": model.best_score["valid_0"]["rmse"],
    }


if __name__ == "__main__":
    print(train_and_save())
