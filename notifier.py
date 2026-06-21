"""Telegram delivery. One free HTTPS POST per alert, no templates/approval needed."""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

NEWS_TYPE_EMOJI = {"positive": "🟢", "negative": "🔴", "neutral": "🟡"}

DISCLAIMER = "(Heads-up only, not investment advice — see README)"


def format_price_alert(mover: dict, news_context: dict | None, fundamentals: dict | None) -> str:
    ticker = mover["ticker"]
    pct = mover["pct_change"]
    session = mover["session"]
    emoji = "🟢" if pct > 0 else "🔴"
    rebound_note = ""
    if pct <= 0 and -pct >= 5:
        rebound_note = "\n⚠️ Potential rebound watch"

    lines = [f"{emoji} {ticker}  {pct:+.1f}% ({session}){rebound_note}"]

    if news_context:
        nt = news_context.get("news_type", "n/a")
        score = news_context.get("signal_score", "n/a")
        reasoning = news_context.get("reasoning", "")
        lines.append(f"News type: {nt.capitalize() if nt != 'n/a' else 'n/a'}")
        lines.append(f"Signal score: {score}/10")
        if reasoning:
            lines.append(f"Why: {reasoning}")
    else:
        lines.append("News type: n/a (price move only, no matching headline)")

    lines.append(DISCLAIMER)
    return "\n".join(lines)


def format_news_alert(headline: str, analysis: dict) -> str:
    ticker = analysis.get("ticker") or "Unknown"
    nt = analysis.get("news_type", "neutral")
    emoji = NEWS_TYPE_EMOJI.get(nt, "🟡")
    lines = [
        f"{emoji} Potential mover: {ticker}",
        f'Headline: "{headline}"',
        f"News type: {nt.capitalize()}",
        f"Signal score: {analysis.get('signal_score', 'n/a')}/10  "
        f"(confidence {analysis.get('confidence', 'n/a')})",
        f"Why: {analysis.get('reasoning', '')}",
        DISCLAIMER,
    ]
    return "\n".join(lines)


def send(message: str, dry_run: bool = False) -> None:
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
