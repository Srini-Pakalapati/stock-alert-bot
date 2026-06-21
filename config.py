"""Thresholds, schedule windows, and other tunables for the alert bot."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

# --- Price-move thresholds (percent) ---
INTRADAY_MOVE_PCT = 5.0
EXTENDED_HOURS_MOVE_PCT = 8.0
REBOUND_WATCH_PCT = -5.0  # a drop at/beyond this also gets flagged as "potential rebound watch"

# --- LLM gating ---
MIN_CONFIDENCE = 60          # 0-100, below this a news item is not alert-worthy
MIN_SIGNAL_SCORE_NEWS_ONLY = 6  # 1-10, bar for "potential mover" alerts with no price move yet

# --- Screener scope ---
SCREENER_QUERIES = ["day_gainers", "day_losers", "most_actives"]
SCREENER_COUNT = 50  # results per screener query

# --- Active windows (US/Eastern) ---
# Pre-market 4:00-9:30, regular 9:30-16:00, after-hours 16:00-20:00. No weekends.
PRE_MARKET_START = (4, 0)
AFTER_HOURS_END = (20, 0)


def is_active_window(now: datetime | None = None) -> bool:
    """True if `now` (Eastern) falls inside pre-market/regular/after-hours and is a weekday."""
    now = (now or datetime.now(EASTERN)).astimezone(EASTERN)
    if now.weekday() >= 5:  # Sat/Sun
        return False
    start = now.replace(hour=PRE_MARKET_START[0], minute=PRE_MARKET_START[1], second=0, microsecond=0)
    end = now.replace(hour=AFTER_HOURS_END[0], minute=AFTER_HOURS_END[1], second=0, microsecond=0)
    return start <= now <= end
