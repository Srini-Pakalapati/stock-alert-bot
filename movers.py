"""Dynamic price-move discovery — no fixed watchlist.

Uses yfinance's screener for the day's biggest movers, plus pre/post-market
change percentages where available, to catch moves like the after-hours
INTC example. Yahoo's endpoints here are unofficial and can change/throttle;
failures are logged and skipped rather than crashing the run.
"""
import logging

import yfinance as yf

import config

log = logging.getLogger(__name__)


def get_movers() -> list[dict]:
    """Find tickers currently moving beyond config's thresholds.

    Queries Yahoo Finance's day_gainers/day_losers/most_actives screeners
    (config.SCREENER_QUERIES) for the regular session, then layers on
    pre-market/after-hours movers via _add_extended_hours_movers(). There is
    no fixed watchlist -- whatever the screeners surface and clears the
    relevant threshold is included.

    Returns:
        A deduped list of dicts, each shaped like:
        {"ticker": "RGTI", "pct_change": -7.2, "session": "regular",
         "price": 12.34, "prev_close": 13.30}
        `session` is one of "regular", "pre-market", "after-hours".
    """
    movers: dict[str, dict] = {}

    for query in config.SCREENER_QUERIES:
        try:
            result = yf.screen(query, count=config.SCREENER_COUNT)
            quotes = result.get("quotes", [])
        except Exception:
            log.warning("screener query %r failed", query, exc_info=True)
            continue

        for q in quotes:
            ticker = q.get("symbol")
            pct = q.get("regularMarketChangePercent")
            if not ticker or pct is None:
                continue
            if abs(pct) >= config.INTRADAY_MOVE_PCT:
                movers[ticker] = {
                    "ticker": ticker,
                    "pct_change": round(pct, 2),
                    "session": "regular",
                    "price": q.get("regularMarketPrice"),
                    "prev_close": q.get("regularMarketPreviousClose"),
                }

    _add_extended_hours_movers(movers)
    return list(movers.values())


def _add_extended_hours_movers(movers: dict[str, dict]) -> None:
    """Add pre-market/after-hours movers to `movers`, mutating it in place.

    For each ticker already found by the regular-session screeners, checks
    its Yahoo `info` dict for pre/post-market change percentages and adds an
    entry (keyed "TICKER:pre" / "TICKER:post" to avoid clobbering the regular
    session's entry) if the move clears config.EXTENDED_HOURS_MOVE_PCT. This
    is how a case like "INTC up 10% after-hours" gets caught even though the
    regular-session screener wouldn't reflect it.

    Best-effort: any ticker that fails to fetch is silently skipped. Note:
    Yahoo's postMarketChangePercent/preMarketChangePercent are already plain
    percent values (e.g. 0.6 means +0.6%), consistent with
    regularMarketChangePercent -- do not multiply by 100.
    """
    candidates = list(movers.keys())
    for ticker in candidates:
        try:
            info = yf.Ticker(ticker).info
        except Exception:
            continue

        post_pct = info.get("postMarketChangePercent")
        pre_pct = info.get("preMarketChangePercent")

        if post_pct is not None and abs(post_pct) >= config.EXTENDED_HOURS_MOVE_PCT:
            movers[f"{ticker}:post"] = {
                "ticker": ticker,
                "pct_change": round(post_pct, 2),
                "session": "after-hours",
                "price": info.get("postMarketPrice"),
                "prev_close": info.get("regularMarketPrice"),
            }

        if pre_pct is not None and abs(pre_pct) >= config.EXTENDED_HOURS_MOVE_PCT:
            movers[f"{ticker}:pre"] = {
                "ticker": ticker,
                "pct_change": round(pre_pct, 2),
                "session": "pre-market",
                "price": info.get("preMarketPrice"),
                "prev_close": info.get("regularMarketPreviousClose"),
            }


def is_rebound_watch(pct_change: float) -> bool:
    """True if a drop is at/beyond config.REBOUND_WATCH_PCT, worth flagging as a
    "potential rebound watch" rather than just a plain decline."""
    return pct_change <= config.REBOUND_WATCH_PCT
