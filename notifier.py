"""Telegram delivery. One free HTTPS POST per alert, no templates/approval needed."""
from __future__ import annotations

import logging
import os

import requests

import movers

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

NEWS_TYPE_EMOJI = {"positive": "🟢", "negative": "🔴", "neutral": "🟡"}

DISCLAIMER = "(Heads-up only, not investment advice — see README)"


def _format_market_cap(value: float | None) -> str | None:
    """Format a raw market cap (e.g. 4376979046400) as a short string like '$4.38T'."""
    if value is None:
        return None
    for divisor, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if value >= divisor:
            return f"${value / divisor:.2f}{suffix}"
    return f"${value:,.0f}"


def _format_52w_position(price: float | None, low: float | None, high: float | None) -> str | None:
    """Describe where `price` sits within the [low, high] 52-week range.

    Returns a string like "62% of 52-week range (low $4.10, high $12.50)", or
    None if any input is missing -- this is a "nice to have" context line, not
    something that should block an alert if the data isn't available.
    """
    if price is None or low is None or high is None or high <= low:
        return None
    position_pct = (price - low) / (high - low) * 100
    return f"{position_pct:.0f}% of 52-week range (low ${low:.2f}, high ${high:.2f})"


def format_price_alert(
    mover: dict,
    news_context: dict | None,
    fundamentals: dict | None,
    source_link: str | None = None,
) -> str:
    """Build the Telegram message text for a price-move alert.

    Args:
        mover: one entry from movers.get_movers(), e.g.
            {"ticker": "RGTI", "pct_change": -7.2, "session": "regular", ...}.
        news_context: the matching analyzer.py result for this mover's most
            recent headline, or None if no headline was found/analyzed.
        fundamentals: the fundamentals.get_fundamentals() result for this
            ticker, or None if the lookup failed.
        source_link: URL of the headline used for news_context, if any.

    Returns:
        The full multi-line message text, including the standing disclaimer.
    """
    ticker = mover["ticker"]
    pct = mover["pct_change"]
    session = mover["session"]
    emoji = "🟢" if pct > 0 else "🔴"
    rebound_note = "\n⚠️ Potential rebound watch" if movers.is_rebound_watch(pct) else ""

    lines = [f"{emoji} {ticker}  {pct:+.1f}% ({session}){rebound_note}"]

    fundamentals = fundamentals or {}
    price = fundamentals.get("current_price") or mover.get("price")
    market_cap = _format_market_cap(fundamentals.get("market_cap"))
    range_position = _format_52w_position(price, fundamentals.get("week52_low"), fundamentals.get("week52_high"))

    if price is not None:
        lines.append(f"Price: ${price:,.2f}" + (f"  |  Market cap: {market_cap}" if market_cap else ""))
    if range_position:
        lines.append(range_position)

    if news_context:
        nt = news_context.get("news_type", "n/a")
        score = news_context.get("signal_score", "n/a")
        reasoning = news_context.get("reasoning", "")
        lines.append(f"News type: {nt.capitalize() if nt != 'n/a' else 'n/a'}")
        lines.append(f"Signal score: {score}/10")
        if reasoning:
            lines.append(f"Why: {reasoning}")
        if source_link:
            lines.append(f"Source: {source_link}")
    else:
        lines.append("News type: n/a (price move only, no matching headline)")

    lines.append(DISCLAIMER)
    return "\n".join(lines)


def format_news_alert(headline: dict, analysis: dict) -> str:
    """Build the Telegram message text for a news-only "potential mover" alert.

    Args:
        headline: one entry from news.get_general_headlines() /
            news.get_ticker_news(), e.g. {"title": ..., "link": ..., "source": ...}.
        analysis: the matching analyzer.py result for this headline.

    Returns:
        The full multi-line message text, including the standing disclaimer.
    """
    ticker = analysis.get("ticker") or "Unknown"
    nt = analysis.get("news_type", "neutral")
    emoji = NEWS_TYPE_EMOJI.get(nt, "🟡")
    lines = [
        f"{emoji} Potential mover: {ticker}",
        f'Headline: "{headline["title"]}"',
        f"News type: {nt.capitalize()}",
        f"Signal score: {analysis.get('signal_score', 'n/a')}/10  "
        f"(confidence {analysis.get('confidence', 'n/a')})",
        f"Why: {analysis.get('reasoning', '')}",
    ]
    if headline.get("link"):
        lines.append(f"Source: {headline['link']}")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def send(message: str, dry_run: bool = False) -> None:
    """Send (or print) one alert message.

    Args:
        message: the full message text, e.g. from format_price_alert().
        dry_run: if True, print to stdout instead of calling the Telegram API
            -- used for local testing without needing real credentials.
    """
    if dry_run:
        print("--- DRY RUN: would send ---")
        print(message)
        print("----------------------------")
        return

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    resp = requests.post(
        TELEGRAM_API.format(token=token),
        json={"chat_id": chat_id, "text": message},
        timeout=15,
    )
    if not resp.ok:
        log.error("Telegram send failed: %s %s", resp.status_code, resp.text)
