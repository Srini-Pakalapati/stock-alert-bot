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
    global _finnhub_client
    if _finnhub_client is None:
        import finnhub

        key = os.environ.get("FINNHUB_API_KEY")
        if key:
            _finnhub_client = finnhub.Client(api_key=key)
    return _finnhub_client


def get_fundamentals(ticker: str) -> dict:
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
            }
        )
    except Exception:
        log.warning("yfinance fundamentals failed for %s", ticker, exc_info=True)

    client = _finnhub()
    if client:
        try:
            metrics = client.company_basic_financials(ticker, "all").get("metric", {})
            out.setdefault("pe_ratio", metrics.get("peTTM"))
            out["52w_high"] = metrics.get("52WeekHigh")
            out["52w_low"] = metrics.get("52WeekLow")
            out["beta"] = metrics.get("beta")
        except Exception:
            log.warning("Finnhub fundamentals failed for %s", ticker, exc_info=True)

    return out
