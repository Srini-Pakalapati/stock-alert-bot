"""Telegram delivery. One free HTTPS POST per alert, no templates/approval needed."""
from __future__ import annotations

import html
import logging
import os

import requests

import movers

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

NEWS_TYPE_EMOJI = {"positive": "🟢", "negative": "🔴", "neutral": "🟡"}

DISCLAIMER = "Disclaimer: For information only, not investment advice."


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


def _source_line(link: str | None) -> str | None:
    """Render a source link as a short clickable "Read more" instead of the
    raw URL -- Google News RSS links in particular are long opaque redirect
    URLs that would otherwise dominate the message."""
    if not link:
        return None
    return f'Source: <a href="{html.escape(link)}">Read more</a>'


def format_price_alert(
    mover: dict,
    news_context: dict | None,
    fundamentals: dict | None,
    source_link: str | None = None,
) -> str:
    """Build the Telegram message text (HTML-formatted) for a price-move alert.

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
        All dynamic text is HTML-escaped; send() uses Telegram's HTML parse mode.
    """
    ticker = html.escape(mover["ticker"])
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
        reasoning = html.escape(news_context.get("reasoning", ""))
        lines.append(f"News type: {nt.capitalize() if nt != 'n/a' else 'n/a'}")
        lines.append(f"Signal score: {score}/10")
        if reasoning:
            lines.append(f"Why: {reasoning}")
        source = _source_line(source_link)
        if source:
            lines.append(source)
    else:
        lines.append("News type: n/a (price move only, no matching headline)")

    lines.append(DISCLAIMER)
    return "\n".join(lines)


def format_news_alert(headline: dict, analysis: dict) -> str:
    """Build the Telegram message text (HTML-formatted) for a news-only alert.

    Broad market-wide headlines (e.g. "Wall Street rallies") often don't name
    a specific company -- analyzer.py returns `ticker: null` for those, and
    this is labeled "Market-wide news" rather than "Potential mover: Unknown"
    so it reads correctly instead of looking like a parsing failure.

    Args:
        headline: one entry from news.get_general_headlines() /
            news.get_ticker_news(), e.g. {"title": ..., "link": ..., "source": ...}.
        analysis: the matching analyzer.py result for this headline.

    Returns:
        The full multi-line message text, including the standing disclaimer.
        All dynamic text is HTML-escaped; send() uses Telegram's HTML parse mode.
    """
    ticker = analysis.get("ticker")
    nt = analysis.get("news_type", "neutral")
    emoji = NEWS_TYPE_EMOJI.get(nt, "🟡")
    header = f"{emoji} Potential mover: {html.escape(ticker)}" if ticker else f"{emoji} Market-wide news"

    lines = [
        header,
        f'Headline: "{html.escape(headline["title"])}"',
        f"News type: {nt.capitalize()}",
        f"Signal score: {analysis.get('signal_score', 'n/a')}/10  "
        f"(confidence {analysis.get('confidence', 'n/a')})",
        f"Why: {html.escape(analysis.get('reasoning', ''))}",
    ]
    source = _source_line(headline.get("link"))
    if source:
        lines.append(source)
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def send(message: str, dry_run: bool = False) -> None:
    """Send (or print) one alert message.

    Args:
        message: the full HTML-formatted message text, e.g. from format_price_alert().
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
        json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
        timeout=15,
    )
    if not resp.ok:
        log.error("Telegram send failed: %s %s", resp.status_code, resp.text)
