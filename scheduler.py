"""
Assigns a target publish time to every ranked clip from one source video.

Rules this implements (from how Ayush described the workflow):
  - Uploads should land ~4 hours apart, never more than 5.
  - The highest-rated clips should land in the 12pm-8pm (local) window.
  - Spread across config.SCHEDULE_TARGET_DAYS days (default 3) when
    everything fits at the target gap.
  - If there are too many clips to fit in that many days at the target
    gap, compress to config.SCHEDULE_TIGHT_GAP_HOURS (default 3h) instead.
  - If it STILL doesn't fit (because of the YouTube daily upload quota),
    keep spilling into day 4, 5, 6... rather than dropping any clips.

Hierarchy (our own design, since Ayush left this to us): within each day,
slots inside the peak window are filled before slots outside it, and
clips are dealt to days round-robin in rank order first -- so clip #1
overall gets day 0's best peak slot, clip #2 gets day 1's best peak slot,
clip #3 gets day 2's, clip #4 comes back to day 0's second-best peak slot,
and so on. That keeps every day's lineup similarly strong instead of
front-loading day 1 with everything good, while still guaranteeing the
best clips land in the peak window first.
"""
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import config


def _day_hour_slots(gap_hours: int) -> list[int]:
    """Hours-of-day (local) spaced gap_hours apart within the day window."""
    hours = []
    h = config.SCHEDULE_DAY_START_HOUR
    while h <= config.SCHEDULE_DAY_END_HOUR:
        hours.append(h)
        h += gap_hours
    return hours or [config.SCHEDULE_DAY_START_HOUR]


def _priority_order(day_hours: list[int]) -> list[int]:
    """Peak-window hours first (closest to the window's center first), then
    non-peak hours in chronological order -- so the best-ranked clip of
    each day always lands on the best available peak slot."""
    peak = [h for h in day_hours
            if config.SCHEDULE_PEAK_START_HOUR <= h <= config.SCHEDULE_PEAK_END_HOUR]
    non_peak = [h for h in day_hours if h not in peak]
    center = (config.SCHEDULE_PEAK_START_HOUR + config.SCHEDULE_PEAK_END_HOUR) / 2
    peak_sorted = sorted(peak, key=lambda h: abs(h - center))
    return peak_sorted + sorted(non_peak)


def _pick_tier(num_clips: int):
    """Returns (day_hours, num_days) for the pace this batch needs."""
    target_hours = _day_hour_slots(config.SCHEDULE_TARGET_GAP_HOURS)
    quota = config.YOUTUBE_DAILY_UPLOAD_QUOTA or len(target_hours)
    target_hours = target_hours[:quota]

    target_capacity = len(target_hours) * config.SCHEDULE_TARGET_DAYS
    if num_clips <= target_capacity:
        return target_hours, config.SCHEDULE_TARGET_DAYS

    tight_hours = _day_hour_slots(config.SCHEDULE_TIGHT_GAP_HOURS)[:quota]
    num_days = max(config.SCHEDULE_TARGET_DAYS, math.ceil(num_clips / len(tight_hours)))
    return tight_hours, num_days


def _start_date(earliest_start_utc: datetime, tz: ZoneInfo, last_hour: int):
    local = earliest_start_utc.astimezone(tz)
    start_date = local.date()
    if local.hour >= last_hour:
        start_date += timedelta(days=1)
    return start_date


def assign_slots(ranked_clips: list[dict], earliest_start_utc: datetime | None = None) -> list[dict]:
    """
    Returns a NEW list of clips (best-first input, any order in), each with
    'target_publish_time_utc' (RFC3339 'Z' string) and
    'target_publish_time_local' (ISO string, config.SCHEDULE_TIMEZONE)
    added -- sorted chronologically by that assigned time, ready to enqueue.
    """
    if not ranked_clips:
        return []

    tz = ZoneInfo(config.SCHEDULE_TIMEZONE)
    if earliest_start_utc is None:
        earliest_start_utc = datetime.now(timezone.utc) + timedelta(hours=1)
    elif earliest_start_utc.tzinfo is None:
        earliest_start_utc = earliest_start_utc.replace(tzinfo=timezone.utc)

    num_clips = len(ranked_clips)
    day_hours, num_days = _pick_tier(num_clips)
    slots_per_day = len(day_hours)
    priority_hours = _priority_order(day_hours)
    start_date = _start_date(earliest_start_utc, tz, day_hours[-1])

    block_size = num_days * slots_per_day
    scheduled = []

    for i, clip in enumerate(ranked_clips):
        day_block = i // block_size
        within_block = i % block_size
        day_in_block = within_block % num_days
        pos_in_day = within_block // num_days
        day_offset = day_block * num_days + day_in_block
        hour = priority_hours[pos_in_day]

        local_dt = datetime(
            start_date.year, start_date.month, start_date.day, hour, 0, tzinfo=tz
        ) + timedelta(days=day_offset)
        if local_dt < earliest_start_utc.astimezone(tz):
            local_dt += timedelta(days=1)

        utc_dt = local_dt.astimezone(timezone.utc)
        scheduled.append({
            **clip,
            "target_publish_time_utc": utc_dt.isoformat().replace("+00:00", "Z"),
            "target_publish_time_local": local_dt.isoformat(),
        })

    scheduled.sort(key=lambda c: c["target_publish_time_utc"])
    return scheduled
