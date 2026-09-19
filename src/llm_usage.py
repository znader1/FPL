"""Per-call LLM token accounting.

Every Anthropic ``messages.create`` in the API discarded ``response.usage``,
so the largest variable cost in the business (narratives per user per
gameweek) was unmeasured. ``record_usage`` reads the usage block, prices it,
and emits one structured log line — and optionally a JSONL row — keyed by the
authenticated user so spend can be summed per user and per gameweek.

It never raises: a missing ``usage`` attribute or an unknown model must not
break a user-facing call.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import time

logger = logging.getLogger("fpl.llm_usage")

# The authenticated Supabase ``sub`` for the request in flight. Bound by the
# rate-limiter key function (it already verifies the JWT on every LLM route),
# so agents deep in the call stack need no extra parameter.
_current_user: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fpl_llm_user", default=None
)

# USD per million tokens (input, output). Longest-prefix match on the model id
# so dated snapshots (``claude-haiku-4-5-20251001``) price correctly.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
}
CACHE_READ_MULT = 0.1     # cache reads bill at ~10% of input
CACHE_WRITE_MULT = 1.25   # cache writes bill at ~125% of input


def bind_user(sub: str | None) -> None:
    """Attach the authenticated user id to the current request context."""
    _current_user.set(sub)


def current_user() -> str | None:
    return _current_user.get()


def _price_for(model: str | None) -> tuple[float, float] | None:
    if not model:
        return None
    best = None
    for prefix, rates in PRICES_USD_PER_MTOK.items():
        if model.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, rates)
    return best[1] if best else None


def estimate_usd(model, input_tokens, output_tokens, cache_read=0, cache_write=0):
    rates = _price_for(model)
    if rates is None:
        return None
    in_rate, out_rate = rates
    usd = (
        input_tokens * in_rate
        + cache_read * in_rate * CACHE_READ_MULT
        + cache_write * in_rate * CACHE_WRITE_MULT
        + output_tokens * out_rate
    ) / 1_000_000
    return round(usd, 6)


def record_usage(resp, feature: str, model: str | None = None, gw=None, user=None):
    """Log the token usage of one ``messages.create`` response.

    Returns the record dict (also written to ``FPL_LLM_USAGE_LOG`` as JSONL
    when that env var names a file), or None if the response carries no usage.
    """
    try:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return None
        rec = {
            "ts": round(time.time(), 3),
            "feature": feature,
            "model": model or getattr(resp, "model", None),
            "user": user or current_user(),
            "gw": gw,
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "cache_read_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            "cache_write_tokens": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        }
        rec["usd"] = estimate_usd(
            rec["model"], rec["input_tokens"], rec["output_tokens"],
            rec["cache_read_tokens"], rec["cache_write_tokens"],
        )
        logger.info(
            "llm_usage feature=%s model=%s user=%s gw=%s in=%d out=%d cache_read=%d usd=%s",
            rec["feature"], rec["model"], rec["user"], rec["gw"],
            rec["input_tokens"], rec["output_tokens"], rec["cache_read_tokens"], rec["usd"],
        )
        path = (os.environ.get("FPL_LLM_USAGE_LOG") or "").strip()
        if path:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
        return rec
    except Exception as exc:  # accounting must never break the call it measures
        logger.warning("llm_usage: failed to record (%s)", exc)
        return None
