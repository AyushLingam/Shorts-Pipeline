"""
Ranks Vizard clips so we only publish the best N.

Vizard's /project/query response gives each clip a `viralScore` (string,
0-10) plus `videoMsDuration` and `transcript`. There's no hook score or
word count field, so word count is derived from the transcript.

Day 1 (no historical data): heuristic score using Vizard's own viral score
plus duration fit. Later (Phase 8): if models/ranker.txt exists, use the
trained LightGBM model instead.
"""
import os
from config import config

try:
    import lightgbm as lgb
except ImportError:
    lgb = None


# Must match ml/train_ranker.py's FEATURE_COLUMNS order exactly, or the
# trained model will score garbage features.
FEATURE_ORDER = ["duration_sec", "viral_score", "word_count"]


def _duration_sec(clip: dict) -> float:
    return clip.get("videoMsDuration", 30000) / 1000.0


def _viral_score_normalized(clip: dict) -> float:
    """Vizard gives 0-10 as a string; normalize to 0-1."""
    try:
        return float(clip.get("viralScore", 5)) / 10.0
    except (TypeError, ValueError):
        return 0.5


def _word_count(clip: dict) -> int:
    transcript = clip.get("transcript", "") or ""
    return len(transcript.split())


def _heuristic_score(clip: dict) -> float:
    viral = _viral_score_normalized(clip)
    duration = _duration_sec(clip)

    lo, hi = config.MIN_CLIP_SECONDS, config.MAX_CLIP_SECONDS
    if duration < lo or duration > hi:
        duration_fit = 0.5
    else:
        mid = (lo + hi) / 2
        duration_fit = 1.0 - abs(duration - mid) / (hi - mid)

    return 0.75 * viral + 0.25 * duration_fit


def _extract_features(clip: dict) -> list[float]:
    # Order must match FEATURE_ORDER / ml/train_ranker.py's FEATURE_COLUMNS
    return [_duration_sec(clip), _viral_score_normalized(clip), _word_count(clip)]


def _model_score(clip: dict, model) -> float:
    x = [_extract_features(clip)]
    return float(model.predict(x)[0])


def rank_clips(clips: list[dict]) -> list[dict]:
    """Returns clips sorted best-first, each with a 'rank_score' field added."""
    model = None
    if lgb is not None and os.path.exists(config.MODEL_PATH):
        try:
            model = lgb.Booster(model_file=config.MODEL_PATH)
        except Exception:
            model = None  # fall back to heuristic silently

    scored = []
    for clip in clips:
        score = _model_score(clip, model) if model else _heuristic_score(clip)
        scored.append({**clip, "rank_score": score})

    return sorted(scored, key=lambda c: c["rank_score"], reverse=True)


def select_top_n(clips: list[dict], n: int | None = None) -> list[dict]:
    n = n or config.TOP_N_CLIPS_PER_VIDEO
    return rank_clips(clips)[:n]
