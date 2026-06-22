"""LLM classification: batches headlines (+ fundamentals context) into one call
per provider. Gemini free tier is primary; on a 429/quota error we fail over to
Groq's free tier. If both fail, the caller should re-queue the batch for next run.

signal_score is an explicit heuristic *signal-strength* indicator (1-10), not a
buy/sell recommendation -- see README disclaimer.
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

PROMPT_TEMPLATE = """You are a financial news triage assistant. For each news item below, \
assess whether it plausibly causes a significant stock price move (up or down) for the \
company involved, even via indirect causality (e.g. a politician's statement about a \
company, a supplier/competitor event). Use the attached fundamentals (if present) to judge \
whether the news is supported or contradicted by the company's actual financial health.

Return ONLY a JSON array, one object per input item in the same order, with exactly these \
fields:
- "ticker": best-guess ticker symbol, or null if none identifiable
- "news_type": "positive", "negative", or "neutral"
- "direction": "up", "down", or "unclear"
- "magnitude_guess": rough expected % move as a number, or null
- "confidence": integer 0-100, how sure you are this headline is actually significant
- "signal_score": integer 1-10, composite of confidence and whether fundamentals support \
  or contradict the news (contradicted news scores lower)
- "reasoning": one sentence, referencing fundamentals if provided

Items:
{items_json}
"""


def _build_prompt(items: list[dict]) -> str:
    """Render the batch prompt: each item is `{"headline": str, "fundamentals": dict?}`."""
    return PROMPT_TEMPLATE.format(items_json=json.dumps(items, default=str))


def _parse_response(text: str, expected_len: int) -> list[dict] | None:
    """Parse an LLM's raw text response into the expected list of result dicts.

    Strips a markdown code-fence if the model wrapped its JSON in one (common
    even when explicitly asked not to). Returns None -- rather than raising --
    if the text isn't valid JSON or isn't a list of exactly `expected_len`
    items, so the caller can try the next provider instead of crashing.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1 :] if "\n" in text else text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning("LLM response was not valid JSON: %s", text[:300])
        return None
    if not isinstance(data, list) or len(data) != expected_len:
        log.warning("LLM response shape mismatch (got %s items, expected %d)", len(data) if isinstance(data, list) else "?", expected_len)
        return None
    return data


def _call_gemini(prompt: str) -> str:
    """Call Gemini's free tier (gemini-2.5-flash). Raises on any error/quota
    exhaustion (e.g. 429) -- analyze_batch() catches this and falls back to Groq."""
    from google import genai

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    return response.text


def _call_groq(prompt: str) -> str:
    """Call Groq's free tier (llama-3.3-70b-versatile), used as the fallback
    provider when Gemini fails or its free quota is exhausted.

    max_tokens is set high and temperature low: a large batch of headlines
    produces a long JSON array response, and the default max_tokens was
    observed truncating it mid-response (cutting the JSON off before it
    could close), which then fails to parse.
    """
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=8192,
        temperature=0.2,
    )
    return completion.choices[0].message.content


def analyze_batch(items: list[dict]) -> list[dict] | None:
    """Classify a batch of news items in a single LLM call (Gemini, falling
    back to Groq on failure).

    Batching everything into one request -- rather than one request per item
    -- is what keeps this well within both providers' free-tier daily quotas
    even under continuous polling, and is also what keeps a single scan cycle
    fast (see main.py's MAX_MOVERS_PER_CYCLE cap for the other half of that).

    Args:
        items: list of dicts shaped `{"headline": str, "fundamentals": dict?}`.

    Returns:
        A list of result dicts aligned 1:1 with `items` (see PROMPT_TEMPLATE
        for the exact fields: ticker, news_type, direction, magnitude_guess,
        confidence, signal_score, reasoning), or None if both providers
        failed -- in which case the caller should re-queue the batch for the
        next run rather than treating it as "no significant news".
        Returns [] immediately if `items` is empty (no call is made).
    """
    if not items:
        return []

    prompt = _build_prompt(items)

    for provider, call in (("gemini", _call_gemini), ("groq", _call_groq)):
        try:
            text = call(prompt)
        except Exception as exc:
            log.warning("%s call failed: %s", provider, exc)
            continue

        parsed = _parse_response(text, len(items))
        if parsed is not None:
            return parsed
        log.warning("%s returned unparseable/mismatched response, trying next provider", provider)

    return None
