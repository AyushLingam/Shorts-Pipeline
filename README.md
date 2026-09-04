# Shorts Automation Pipeline

Turns a long-form video (e.g. a livestream VOD) into ranked, scheduled YouTube
Shorts, then tracks performance so a ranking model can improve future clip
selection.

## Architecture

```
long video URL
      │
      ▼
vizard_client.py       → submits video to Vizard.ai, polls for clips
      │
      ▼
clip_ranker.py          → scores/sorts clips, picks top N to publish
      │
      ▼
youtube_uploader.py     → uploads winners to YouTube, schedules publish time
      │
      ▼
db.py (SQLite)          → stores clip + upload metadata
      │
      ▼
performance_tracker.py  → pulls YouTube Analytics daily, updates db
      │
      ▼
ml/train_ranker.py      → retrains LightGBM ranker on accumulated data
      │
      ▼
clip_ranker.py uses the trained model next run (closes the loop)
```

`dags/shorts_pipeline_dag.py` is the Airflow DAG that runs this end to end on
a schedule.

## What you need to supply (I can't create these for you)

1. **Vizard.ai API key** — requires a Pro plan or higher (API access isn't
   on the free tier). Get it from your Vizard account → Workspace Settings →
   API tab → Generate API Key.
2. **YouTube Data API v3 + YouTube Analytics API OAuth credentials** — create
   a project in Google Cloud Console, enable both APIs, create an OAuth
   client (Desktop app type is easiest for a first run), download
   `client_secret.json`. First run opens a browser to authorize; after that
   a `token.json` is cached.
3. **A place to run Airflow** — locally (`pip install apache-airflow`) or a
   managed service (MWAA, Cloud Composer, Astronomer).

Nothing in this repo will run without those three things — I've built the
real logic against Vizard's actual documented API and the real YouTube APIs,
but the credentials are account-specific and I have no way to get them for
you.

## Setup

```bash
cd shorts-pipeline
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in your keys
python scripts/first_time_youtube_auth.py   # one-time OAuth flow, creates token.json
```

## Running a single pass manually (no Airflow, for testing)

```bash
python scripts/run_once.py --video-url "https://youtube.com/watch?v=XXXX" --top-n 5
```

## Running the full pipeline on a schedule

Copy `dags/shorts_pipeline_dag.py` into your Airflow `dags/` folder. It:
1. Watches a "source videos" folder/table for new long-form videos
2. Submits each to Vizard and waits for clips
3. Ranks and picks the top N
4. Uploads + schedules them on YouTube, spaced out over the week
5. Runs a daily task pulling performance stats for everything uploaded in
   the last 30 days
6. Runs a weekly task retraining the ranking model

## Phase 8 model — how it actually works here

`clip_ranker.py` starts with a heuristic score (Vizard's own 0–10 viral
score, blended with duration-fit) because you'll have zero historical data
on day one. Once `performance_tracker.py` has logged real outcomes for,
say, 50+ published Shorts, run `ml/train_ranker.py` — it trains a LightGBM
regressor on (clip features) → (views per hour in first 48h, normalized),
and `clip_ranker.py` will automatically prefer the trained model over the
heuristic if `models/ranker.txt` exists.

## Known gaps / things you'll need to adjust

- Vizard's clip download URLs (the `videoUrl` field in query responses) are
  **temporary and expire after 7 days** — the pipeline downloads them
  immediately after fetching, but don't try to re-download an old clip from
  a stale DB entry without re-querying the project first.
- Vizard doesn't expose a "hook score" or per-clip word-density metric the
  way some competitors do — `clip_ranker.py`'s heuristic uses `viralScore`
  (0–10, normalized) plus duration fit, and derives word count from the
  clip's transcript for the ML feature set. If you want richer features
  (speaking pace, cuts, audio intensity), that's a separate video-analysis
  step on the downloaded clip file — not something Vizard's API returns.
- Thumbnail auto-generation (Phase 9) is stubbed in `youtube_uploader.py`
  as a hook — plugging in an actual model (e.g. picking a high-motion
  frame, or an image-gen call) is left for you to choose since it's a
  taste decision.
- Third-party APIs move — the endpoint paths in `vizard_client.py` match
  Vizard's published docs as of mid-2026, but sanity-check against
  `docs.vizard.ai` before relying on it long-term.
