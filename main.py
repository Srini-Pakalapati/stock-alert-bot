"""Orchestrates one scan cycle: price movers + general news, both checked
against fundamentals and an LLM, deduped against state, and sent to Telegram.

Run manually with --dry-run to print instead of sending (and to bypass the
active-hours gate, for local testing at any time).
"""
import argparse
import logging

import analyzer
import config
import fundamentals
import movers
import news
import notifier
import state

log = logging.getLogger(__name__)


def handle_movers(dry_run: bool) -> None:
    for mover in movers.get_movers():
        key = state.price_move_key(mover["ticker"], mover["pct_change"], mover["session"])
        if state.was_notified(key):
            continue

        ticker_news = news.get_ticker_news(mover["ticker"])
        fnd = fundamentals.get_fundamentals(mover["ticker"])

        news_context = None
        if ticker_news:
            results = analyzer.analyze_batch(
                [{"headline": ticker_news[0]["title"], "fundamentals": fnd}]
            )
            if results:
                news_context = results[0]

        message = notifier.format_price_alert(mover, news_context, fnd)
        notifier.send(message, dry_run=dry_run)
        if not dry_run:
            state.mark_notified(key)


def handle_general_news(dry_run: bool) -> None:
    headlines = news.get_general_headlines()
    new_items = []
    for h in headlines:
        key = state.headline_key(h["title"], h["source"])
        if not state.was_notified(key):
            new_items.append((key, h))

    if not new_items:
        return

    batch_input = [{"headline": h["title"]} for _, h in new_items]
    results = analyzer.analyze_batch(batch_input)
    if results is None:
        log.warning("Both LLM providers failed for this batch; leaving items unmarked to retry next run")
        return

    for (key, h), analysis in zip(new_items, results):
        if not dry_run:
            state.mark_notified(key)
        if (
            analysis.get("confidence", 0) >= config.MIN_CONFIDENCE
            and analysis.get("signal_score", 0) >= config.MIN_SIGNAL_SCORE_NEWS_ONLY
        ):
            message = notifier.format_news_alert(h["title"], analysis)
            notifier.send(message, dry_run=dry_run)


def main() -> None:
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print alerts instead of sending; also bypasses the active-hours gate")
    parser.add_argument("--force", action="store_true", help="bypass the active-hours gate but still send real alerts (for manual test runs)")
    args = parser.parse_args()
    force = args.force or os.environ.get("FORCE_RUN") == "true"

    logging.basicConfig(level=logging.INFO)

    if not args.dry_run and not force and not config.is_active_window():
        log.info("Outside active trading window; skipping run.")
        return

    handle_movers(args.dry_run)
    handle_general_news(args.dry_run)


if __name__ == "__main__":
    main()
