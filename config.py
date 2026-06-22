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

# Max headlines per analyzer.analyze_batch() call. A single batch covering 60+
# headlines risks the LLM response exceeding even a generous max_tokens,
# truncating the JSON array mid-response. main.py processes new headlines in
# sequential chunks of this size rather than dropping the excess, so nothing
# is starved -- this only bounds each individual request's size.
MAX_HEADLINES_PER_CYCLE = 30

# --- Screener scope ---
SCREENER_QUERIES = ["day_gainers", "day_losers", "most_actives"]
SCREENER_COUNT = 50  # results per screener query

# On a volatile day, 100+ tickers can clear INTRADAY_MOVE_PCT. Processing all of
# them (news + fundamentals + LLM call each) is what made a single run take
# ~10 minutes against a 15-minute schedule. main.py sorts movers by the size of
# their move (biggest absolute % change first) and only fully processes the top
# MAX_MOVERS_PER_CYCLE; anything bumped this cycle is still picked up next cycle.
MAX_MOVERS_PER_CYCLE = 20

# --- Active windows (US/Eastern) ---
# 6am-8pm ET, Mon-Fri. Trimmed from the full 4am pre-market open since 4-6am
# trading is thin/noisy; 6am still catches most pre-market earnings releases
# (many companies report 6-8am ET), and 8pm covers after-hours since volume
# drops off sharply after that.
PRE_MARKET_START = (6, 0)
AFTER_HOURS_END = (20, 0)


def is_active_window(now: datetime | None = None) -> bool:
    """Check whether a scan should run right now.

    Returns True if `now` (converted to US/Eastern) falls on a weekday and
    within the pre-market/regular/after-hours trading window
    (PRE_MARKET_START to AFTER_HOURS_END). Used by main.py to skip scans
    outside trading hours, saving free-tier API quota and avoiding noise
    overnight/on weekends.

    Args:
        now: the datetime to check; defaults to the current time. Passing
            this explicitly is mainly useful for tests.

    Returns:
        True if a scan should run, False if it should be skipped.
    """
    now = (now or datetime.now(EASTERN)).astimezone(EASTERN)
    if now.weekday() >= 5:  # Sat/Sun
        return False
    start = now.replace(hour=PRE_MARKET_START[0], minute=PRE_MARKET_START[1], second=0, microsecond=0)
    end = now.replace(hour=AFTER_HOURS_END[0], minute=AFTER_HOURS_END[1], second=0, microsecond=0)
    return start <= now <= end
