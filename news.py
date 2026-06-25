"""Headline ingestion from multiple free sources, so we're not relying on
Yahoo alone and can catch stories that aren't tagged to any specific ticker
(e.g. a Trump statement that never mentions "INTC")."""
import logging
import os

import feedparser
import yfinance as yf

log = logging.getLogger(__name__)

# Topic feed, not a keyword search: this is deliberate. An earlier keyword-based
# Google News query (e.g. "stock market OR earnings OR Fed OR tariffs OR merger")
# missed single-company stories whose headline doesn't happen to contain one of
# those exact words (a Wendy's-specific story, for instance). The Business topic
# feed surfaces broad market news AND individual-company stories without being
# filtered by keyword match.
GOOGLE_NEWS_BUSINESS_RSS = "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en"
YAHOO_GENERAL_RSS = "https://finance.yahoo.com/news/rssindex"

_finnhub_client = None


def _finnhub():
    """Lazily build (and cache) a Finnhub client from FINNHUB_API_KEY.

    Returns None if the env var isn't set, so callers can treat Finnhub as an
    optional source rather than a hard dependency.
    """
    global _finnhub_client
    if _finnhub_client is None:
        import finnhub

        key = os.environ.get("FINNHUB_API_KEY")
        if key:
            _finnhub_client = finnhub.Client(api_key=key)
    return _finnhub_client


def _normalize(title, link, source):
    """Coerce a headline from any source into the common {title, link, source} shape."""
    return {"title": title.strip(), "link": link, "source": source}


def get_general_headlines() -> list[dict]:
    """Fetch broad market headlines, not tied to a specific ticker.

    Combines Yahoo Finance's general news RSS, a Google News RSS search, and
    Finnhub's general news endpoint (if FINNHUB_API_KEY is set). This breadth
    matters for catching stories that never mention a ticker symbol at all --
    e.g. a politician's statement about a company -- which a ticker-scoped
    feed would miss entirely. Any one source failing is logged and skipped
    rather than failing the whole call.

    Returns:
        A list of {"title": str, "link": str, "source": str} dicts. May
        contain duplicates/near-duplicates across sources; dedup is handled
        by the caller via state.headline_key().
    """
    items = []

    try:
        feed = feedparser.parse(YAHOO_GENERAL_RSS)
        for entry in feed.entries:
            items.append(_normalize(entry.title, entry.link, "yahoo"))
    except Exception:
        log.warning("Yahoo general RSS failed", exc_info=True)

    try:
        feed = feedparser.parse(GOOGLE_NEWS_BUSINESS_RSS)
        for entry in feed.entries:
            items.append(_normalize(entry.title, entry.link, "google_news"))
    except Exception:
        log.warning("Google News RSS failed", exc_info=True)

    client = _finnhub()
    if client:
        try:
            for n in client.general_news("general", min_id=0)[:50]:
                items.append(_normalize(n.get("headline", ""), n.get("url", ""), "finnhub"))
        except Exception:
            log.warning("Finnhub general news failed", exc_info=True)

    return [i for i in items if i["title"]]


def get_ticker_news(ticker: str) -> list[dict]:
    """Fetch recent news for a specific ticker.

    Combines yfinance's per-ticker news with Finnhub's company-news endpoint
    (last 2 days, if FINNHUB_API_KEY is set). Used by main.py to attach a
    "why" headline + link to a price-move alert. Any one source failing is
    logged and skipped rather than failing the whole call.

    Args:
        ticker: stock ticker symbol, e.g. "RGTI".

    Returns:
        A list of {"title": str, "link": str, "source": str} dicts, most
        recent first, capped at 10 per source.
    """
    items = []

    try:
        for n in yf.Ticker(ticker).news[:10]:
            content = n.get("content", n)
            title = content.get("title") or n.get("title", "")
            link = (content.get("canonicalUrl") or {}).get("url", n.get("link", ""))
            items.append(_normalize(title, link, "yahoo"))
    except Exception:
        log.warning("yfinance ticker news failed for %s", ticker, exc_info=True)

    client = _finnhub()
    if client:
        try:
            from datetime import date, timedelta

            today = date.today()
            for n in client.company_news(
                ticker, _from=(today - timedelta(days=2)).isoformat(), to=today.isoformat()
            )[:10]:
                items.append(_normalize(n.get("headline", ""), n.get("url", ""), "finnhub"))
        except Exception:
            log.warning("Finnhub company news failed for %s", ticker, exc_info=True)

    return [i for i in items if i["title"]]
