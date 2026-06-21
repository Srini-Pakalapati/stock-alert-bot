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
    return PROMPT_TEMPLATE.format(items_json=json.dumps(items, default=str))


def _parse_response(text: str, expected_len: int) -> list[dict] | None:
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
    from google import genai

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    return response.text


def _call_groq(prompt: str) -> str:
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
    )
    return completion.choices[0].message.content


def analyze_batch(items: list[dict]) -> list[dict] | None:
    """Returns analysis results aligned to `items`, or None if both providers failed
    (caller should re-queue the batch for the next run)."""
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
