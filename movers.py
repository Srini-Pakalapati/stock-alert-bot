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
    """Returns a deduped list of {ticker, pct_change, session, price, prev_close}."""
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
    """Best-effort: scan the same screener tickers' info dicts for pre/post-market
    change fields. yfinance/Yahoo field names here are not guaranteed stable."""
    candidates = list(movers.keys())
    for ticker in candidates:
        try:
            info = yf.Ticker(ticker).info
        except Exception:
            continue

        post_pct = info.get("postMarketChangePercent")
        pre_pct = info.get("preMarketChangePercent")

        if post_pct is not None and abs(post_pct * 100 if abs(post_pct) < 1 else post_pct) >= config.EXTENDED_HOURS_MOVE_PCT:
            pct = post_pct * 100 if abs(post_pct) < 1 else post_pct
            movers[f"{ticker}:post"] = {
                "ticker": ticker,
                "pct_change": round(pct, 2),
                "session": "after-hours",
                "price": info.get("postMarketPrice"),
                "prev_close": info.get("regularMarketPrice"),
            }

        if pre_pct is not None and abs(pre_pct * 100 if abs(pre_pct) < 1 else pre_pct) >= config.EXTENDED_HOURS_MOVE_PCT:
            pct = pre_pct * 100 if abs(pre_pct) < 1 else pre_pct
            movers[f"{ticker}:pre"] = {
                "ticker": ticker,
                "pct_change": round(pct, 2),
                "session": "pre-market",
                "price": info.get("preMarketPrice"),
                "prev_close": info.get("regularMarketPreviousClose"),
            }


def is_rebound_watch(pct_change: float) -> bool:
    return pct_change <= config.REBOUND_WATCH_PCT
