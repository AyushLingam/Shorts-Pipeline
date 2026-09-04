# Shorts Automation Pipeline

Every 3 days, picks the highest-viewed video on your channel that hasn't
been clipped yet, sends it through Vizard.ai (v2 model) for every clip it
can produce, and gets all of them onto YouTube as private uploads spaced
~4 hours apart (never more than 5), with the best-rated clips landing in
the 12pm-8pm window and everything spread across enough days to respect
YouTube's daily upload quota.

## Architecture

```
Task Scheduler (every 3 days)
      │
      ▼
scripts/fetch_and_queue.py
      │  channel_watcher.py   → picks the highest-viewed unclipped video
      │  vizard_client.py     → submits it to Vizard (clipModel=v2), waits for every clip
      │  clip_ranker.py       → scores/sorts ALL clips, best first
      │  scheduler.py         → assigns each a target publish time (peak slots to the best)
      │  downloads every clip locally, writes rows into db.py's upload_queue table
      ▼
   (nothing uploaded yet)

Task Scheduler (daily) ─┐
                         ▼
         scripts/drain_upload_queue.py
               → uploads up to YOUTUBE_DAILY_UPLOAD_QUOTA (default 6) queued
                 clips as private, each with its assigned publishAt time,
                 title as both the title AND description, no tags
               → auto-publishes at its scheduled slot unless you review/
                 edit/publish it earlier in YouTube Studio
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

Two separate schedules are required because YouTube's upload quota is
charged when a video is **created**, not when it goes public -- so even
though `publishAt` spreads visibility across days, the actual upload
calls themselves still have to be throttled to ~6/day. See
"Task Scheduler setup" below.

`dags/shorts_pipeline_dag.py` (Airflow) reflects the OLD top-N/single-shot
upload flow and hasn't been updated for the queue-based design -- the
actual runbook here is the two Task Scheduler jobs above. Ignore the DAG
unless you specifically want to move off Task Scheduler onto Airflow, in
which case it'll need the same fetch/queue split applied to it.

## What you need to supply (I can't create these for you)

1. **Vizard.ai API key** — requires a Pro plan or higher (API access isn't
   on the free tier). Get it from your Vizard account → Workspace Settings →
   API tab → Generate API Key.
2. **YouTube Data API v3 + YouTube Analytics API OAuth credentials** — create
   a project in Google Cloud Console, enable both APIs, create an OAuth
   client (Desktop app type is easiest for a first run), download
   `client_secret.json`. First run opens a browser to authorize; after that
   a `token.json` is cached.

Nothing in this repo will run without those two things — the credentials
are account-specific and there's no way to get them for you.

## Setup

```bash
cd shorts-pipeline
python -m venv venv && source venv/bin/activate   # (Windows: py -m venv venv && venv\Scripts\activate)
pip install -r requirements.txt
cp .env.example .env        # fill in your keys, especially SOURCE_CHANNEL_ID
python scripts/first_time_youtube_auth.py   # one-time OAuth flow, creates token.json
```

## Running a single pass manually (for testing)

```bash
python scripts/fetch_and_queue.py      # picks a video, clips it, fills the queue
python scripts/drain_upload_queue.py   # uploads whatever's queued (up to the daily quota)
```

## Task Scheduler setup (Windows)

You need **two** scheduled tasks:

1. **Existing one** (`run_pipeline.bat`, every 3 days) — now calls
   `scripts/fetch_and_queue.py`. No change needed to the trigger itself,
   just make sure it's still pointed at `run_pipeline.bat`.
2. **New one** (`run_upload_queue.bat`, daily) — you'll need to add this:
   - Task Scheduler → Create Task → give it a name like "Shorts Upload Queue"
   - Trigger: Daily, at whatever time you like (mornings are a safe bet,
     so uploads land well ahead of their scheduled publish times)
   - Action: Start a program → point it at
     `C:\Users\ayush\Downloads\shorts-pipeline (1)\shorts-pipeline\run_upload_queue.bat`
   - Same "run whether user is logged on or not" / wake-the-computer
     settings as your existing task, if you used those

Logs go to `pipeline_log.txt` (every-3-days job) and
`upload_queue_log.txt` (daily job) in the project folder.

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
  **temporary and expire after 7 days** — `fetch_and_queue.py` downloads
  every clip to `QUEUE_DIR` immediately after Vizard finishes, specifically
  so the queue can safely hold clips for longer than 7 days without their
  download link expiring.
- Vizard doesn't expose a "hook score" or per-clip word-density metric the
  way some competitors do — `clip_ranker.py`'s heuristic uses `viralScore`
  (0–10, normalized) plus duration fit, and derives word count from the
  clip's transcript for the ML feature set.
- `VIZARD_CLIP_MODEL=v2` matches the "Select model" picker in the Vizard
  web app but isn't documented in Vizard's crawled public API docs as of
  this writing — after your first real run, spot-check Vizard's credit
  deduction for that project (v2 should cost noticeably more than v1 for
  the same video, ~1.25x in our testing) to confirm it actually took.
- Thumbnail auto-generation (Phase 9) is stubbed in `youtube_uploader.py`
  as a hook — plugging in an actual model (e.g. picking a high-motion
  frame, or an image-gen call) is left for you to choose since it's a
  taste decision.
- Third-party APIs move — the endpoint paths in `vizard_client.py` match
  Vizard's published docs as of mid-2026, but sanity-check against
  `docs.vizard.ai` before relying on it long-term.
