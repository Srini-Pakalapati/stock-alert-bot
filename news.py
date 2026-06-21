"""Headline ingestion from multiple free sources, so we're not relying on
Yahoo alone and can catch stories that aren't tagged to any specific ticker
(e.g. a Trump statement that never mentions "INTC")."""
import logging
import os
from urllib.parse import quote_plus

import feedparser
import yfinance as yf

log = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
YAHOO_GENERAL_RSS = "https://finance.yahoo.com/news/rssindex"
GENERAL_QUERY = "stock market OR earnings OR Fed OR tariffs OR merger when:1h"

_finnhub_client = None


def _finnhub():
    global _finnhub_client
    if _finnhub_client is None:
        import finnhub

        key = os.environ.get("FINNHUB_API_KEY")
        if key:
            _finnhub_client = finnhub.Client(api_key=key)
    return _finnhub_client


def _normalize(title, link, source):
    return {"title": title.strip(), "link": link, "source": source}


def get_general_headlines() -> list[dict]:
    """Broad market headlines, not tied to a specific ticker."""
    items = []

    try:
        feed = feedparser.parse(YAHOO_GENERAL_RSS)
        for entry in feed.entries:
            items.append(_normalize(entry.title, entry.link, "yahoo"))
    except Exception:
        log.warning("Yahoo general RSS failed", exc_info=True)

    try:
        feed = feedparser.parse(GOOGLE_NEWS_RSS.format(query=quote_plus(GENERAL_QUERY)))
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
    """Recent news for a specific ticker, used to attach 'why' context to a price-move alert."""
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
