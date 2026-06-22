# Stock Alert Bot

Scans the market for big price moves and notable news, weighs it against company
fundamentals, and sends a Telegram alert to your phone. Runs entirely on GitHub
Actions' free tier — no server, no machine of yours needs to stay on.

> **Disclaimer — not investment advice.** This is a heads-up tool, not a
> prediction or trading system. It will produce false positives and false
> negatives; LLM-based "will this news move the stock" calls are inherently
> probabilistic, and free news feeds typically lag the market by minutes, so
> some alerts will arrive after a move has already happened, not before. The
> `signal_score` in each alert is a heuristic strength indicator for that
> specific alert — it is **not** a buy/sell recommendation or a guarantee of
> profit. No system can tell you how to invest "without losing money." If
> you choose to size real positions around these alerts, a commonly cited
> (not personalized) retail risk-management practice is capping any single
> speculative position around 1–5% of investable capital, and total
> speculative/alert-driven exposure around 10–20% of the portfolio — any
> actual number for your own money should come from you or a licensed
> financial advisor, not from this bot.

## What it does

- **Price-move alerts**: scans Yahoo Finance's day-gainers/losers/most-actives
  screeners (no fixed watchlist) plus pre/post-market change %, threshold-gated
  and deduped so the same move doesn't refire every cycle.
- **News alerts**: scans broad market headlines (Yahoo, Google News, Finnhub),
  classifies each with an LLM for plausible price impact, direction, and a
  `news_type` (positive/negative/neutral) + `signal_score` (1-10) weighed
  against the company's fundamentals.
- **Fundamentals context**: P/E, margins, debt, cash, analyst ratings pulled
  for any ticker that's moving or in flagged news, so alerts say whether the
  news is *supported* or *contradicted* by the underlying business.

## One-time setup

1. **Telegram bot**: message **@BotFather** → `/newbot` → copy the token.
   Send the new bot any message, then visit
   `https://api.telegram.org/bot<token>/getUpdates` to find your `chat_id`.
2. **Gemini API key** (free, no card): https://aistudio.google.com/app/apikey
3. **Groq API key** (free, no card, used as fallback if Gemini's free quota
   is hit): https://console.groq.com/keys
4. **Finnhub API key** (free, no card, secondary news/fundamentals source):
   https://finnhub.io/register
5. Create a **public** GitHub repo and push this code to it.
6. In the repo's Settings → Secrets and variables → Actions, add:
   `GEMINI_API_KEY`, `GROQ_API_KEY`, `FINNHUB_API_KEY`, `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`.
7. The workflow in `.github/workflows/scan.yml` runs automatically from then
   on. Trigger it manually once from the Actions tab (`Run workflow`) to
   verify everything end-to-end.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your keys for local testing
set -a; source .env; set +a
python main.py --dry-run
```

`--dry-run` prints alerts instead of sending them, and bypasses the
market-hours gate so you can test at any time.

## Why a public repo

Public repos get unlimited free GitHub Actions minutes; private repos only
get a shared free pool (~2,000 min/month) that a 10-15 min cron job would
burn through. The code has nothing sensitive in it — all credentials live in
encrypted GitHub Secrets, which are never exposed in logs or to anyone
viewing the repo.

## Modifying later

Each concern is isolated to one file, so changes are usually small,
contained edits:

- Thresholds, confidence bar, schedule windows → `config.py`
- Data sources → `news.py` / `fundamentals.py` / `movers.py`
- Notification channel → `notifier.py`
- LLM provider/prompt → `analyzer.py`
