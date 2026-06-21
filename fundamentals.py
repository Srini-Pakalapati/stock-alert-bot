"""Company fundamentals lookup so news/price alerts can be judged against
whether the underlying business is actually strong or weak, not just headline
sentiment. Best-effort: unofficial/free sources have inconsistent schemas, so
every field lookup is defensive."""
import logging
import os

import yfinance as yf

log = logging.getLogger(__name__)

_finnhub_client = None


def _finnhub():
    """Lazily build (and cache) a Finnhub client from FINNHUB_API_KEY.

    Returns None if the env var isn't set, so callers can treat Finnhub as an
    optional enrichment source rather than a hard dependency.
    """
    global _finnhub_client
    if _finnhub_client is None:
        import finnhub

        key = os.environ.get("FINNHUB_API_KEY")
        if key:
            _finnhub_client = finnhub.Client(api_key=key)
    return _finnhub_client


def get_fundamentals(ticker: str) -> dict:
    """Look up a company's key fundamentals for a given ticker.

    Combines yfinance (primary) and Finnhub (fills in/overrides anything
    yfinance is missing) so callers get a best-effort snapshot of valuation,
    growth, profitability, leverage, analyst sentiment, and 52-week range.
    Every lookup is wrapped in try/except: unofficial/free data sources have
    inconsistent schemas and occasionally miss fields or fail outright, and a
    missing fundamentals field shouldn't block an alert from being sent.

    Args:
        ticker: stock ticker symbol, e.g. "AAPL".

    Returns:
        A dict with `ticker` plus whichever of the following fields could be
        resolved: pe_ratio, forward_pe, revenue_growth, profit_margins,
        debt_to_equity, total_cash, analyst_recommendation, target_mean_price,
        market_cap, current_price, week52_high, week52_low, beta. Missing
        fields are simply absent rather than set to None, so use `.get()`.
    """
    out = {"ticker": ticker}

    try:
        info = yf.Ticker(ticker).info
        out.update(
            {
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "revenue_growth": info.get("revenueGrowth"),
                "profit_margins": info.get("profitMargins"),
                "debt_to_equity": info.get("debtToEquity"),
                "total_cash": info.get("totalCash"),
                "analyst_recommendation": info.get("recommendationKey"),
                "target_mean_price": info.get("targetMeanPrice"),
                "market_cap": info.get("marketCap"),
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "week52_high": info.get("fiftyTwoWeekHigh"),
                "week52_low": info.get("fiftyTwoWeekLow"),
            }
        )
    except Exception:
        log.warning("yfinance fundamentals failed for %s", ticker, exc_info=True)

    client = _finnhub()
    if client:
        try:
            metrics = client.company_basic_financials(ticker, "all").get("metric", {})
            out.setdefault("pe_ratio", metrics.get("peTTM"))
            if not out.get("week52_high"):
                out["week52_high"] = metrics.get("52WeekHigh")
            if not out.get("week52_low"):
                out["week52_low"] = metrics.get("52WeekLow")
            out["beta"] = metrics.get("beta")
        except Exception:
            log.warning("Finnhub fundamentals failed for %s", ticker, exc_info=True)

    return out
