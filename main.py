"""Orchestrates one scan cycle: price movers + general news, both checked
against fundamentals and an LLM, deduped against state, and sent to Telegram.

Run manually with --dry-run to print instead of sending (and to bypass the
active-hours gate, for local testing at any time). Run with --force (or set
FORCE_RUN=true) to bypass the active-hours gate but still send real alerts --
used by the GitHub Actions "Run workflow" manual trigger for end-to-end tests.
"""
import argparse
import logging
import os

import analyzer
import config
import fundamentals
import movers
import news
import notifier
import state

log = logging.getLogger(__name__)


def handle_movers(dry_run: bool) -> None:
    """Scan for price movers and alert on the ones that pass the dedup/threshold checks.

    Movers are sorted by the size of their move (biggest absolute % change
    first) and capped to config.MAX_MOVERS_PER_CYCLE -- on a volatile day the
    screener can return 100+ qualifying tickers, and processing all of them
    (news + fundamentals + an LLM call each) is what previously made a single
    run take ~10 minutes against a 15-minute schedule. Anything not processed
    this cycle is simply picked up on the next one.

    All of this cycle's LLM analysis is sent as a single batched call (one
    request covering every mover with a headline), rather than one request
    per mover, to keep both runtime and free-tier API usage in check.
    """
    all_movers = movers.get_movers()
    all_movers.sort(key=lambda m: abs(m["pct_change"]), reverse=True)

    pending = []  # [(state_key, mover), ...] -- movers not yet notified this cycle
    for mover in all_movers[: config.MAX_MOVERS_PER_CYCLE]:
        key = state.price_move_key(mover["ticker"], mover["pct_change"], mover["session"])
        if not state.was_notified(key):
            pending.append((key, mover))

    # For each pending mover, fetch its news + fundamentals context, and collect
    # the ones with a headline into a single batch for one LLM call.
    context = {}  # index in `pending` -> (ticker_news, fundamentals_dict)
    batch_items = []
    batch_index_for_item = []  # parallel to batch_items: which `pending` index it belongs to
    for idx, (_, mover) in enumerate(pending):
        ticker_news = news.get_ticker_news(mover["ticker"])
        fnd = fundamentals.get_fundamentals(mover["ticker"])
        context[idx] = (ticker_news, fnd)
        if ticker_news:
            batch_items.append({"headline": ticker_news[0]["title"], "fundamentals": fnd})
            batch_index_for_item.append(idx)

    results = analyzer.analyze_batch(batch_items) if batch_items else []
    news_context_for = {}
    if results:
        for item_pos, pending_idx in enumerate(batch_index_for_item):
            news_context_for[pending_idx] = results[item_pos]

    for idx, (key, mover) in enumerate(pending):
        ticker_news, fnd = context[idx]
        news_context = news_context_for.get(idx)
        source_link = ticker_news[0]["link"] if ticker_news else None
        message = notifier.format_price_alert(mover, news_context, fnd, source_link)
        notifier.send(message, dry_run=dry_run)
        if not dry_run:
            state.mark_notified(key)


def handle_general_news(dry_run: bool) -> None:
    """Scan broad market headlines and alert on high-confidence "potential mover" news.

    Unlike handle_movers, this covers stories not yet reflected in any price
    move -- e.g. an indirect headline (a politician's statement about a
    company) that hasn't moved the stock yet. All new headlines are batched
    into a single LLM call; if both providers fail, items are left unmarked
    in state so they're retried on the next cycle instead of being lost.
    """
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
            message = notifier.format_news_alert(h, analysis)
            notifier.send(message, dry_run=dry_run)


def main() -> None:
    """Entry point: parse CLI args, apply the active-hours gate, then run both scans."""
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
