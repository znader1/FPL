import hashlib
import json
import os
import time

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_OUTPUT_TOKENS = 500
CACHE_TTL_S = 3600

_cache = {}


def _cache_key(payload):
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _cache_get(key):
    entry = _cache.get(key)
    if not entry:
        return None
    if time.time() - entry["ts"] > CACHE_TTL_S:
        _cache.pop(key, None)
        return None
    return entry["data"]


def _cache_set(key, data):
    _cache[key] = {"ts": time.time(), "data": data}


def _player_lookup(recommendations):
    lookup = {}
    for source in (
        recommendations.get("squad_with_transfers", {}).get("starting_xi") or [],
        recommendations.get("squad_with_transfers", {}).get("bench") or [],
        recommendations.get("squad", {}).get("starting_xi") or [],
        recommendations.get("squad", {}).get("bench") or [],
    ):
        for p in source:
            pid = p.get("player_id") or p.get("id")
            if pid is not None and pid not in lookup:
                lookup[int(pid)] = {
                    "name": p.get("web_name") or p.get("name"),
                    "team": p.get("team_short") or p.get("team_name"),
                    "position": p.get("position_short") or p.get("position"),
                    "projected": p.get("projected_points") or p.get("ep_next"),
                }
    return lookup


def _compact_context(recommendations):
    lookup = _player_lookup(recommendations)
    transfer_steps = recommendations.get("squad_with_transfers_steps") or []
    transfers = []
    for step in transfer_steps:
        out_id = step.get("out_player_id") or step.get("player_out_id")
        in_id = step.get("in_player_id") or step.get("player_in_id")
        transfers.append({
            "out": lookup.get(int(out_id)) if out_id else None,
            "out_id": out_id,
            "in": lookup.get(int(in_id)) if in_id else None,
            "in_id": in_id,
            "delta_points": step.get("delta_points") or step.get("ep_delta"),
            "cost_change_m": step.get("cost_change_m"),
        })

    swt = recommendations.get("squad_with_transfers") or recommendations.get("squad") or {}
    captain_id = swt.get("captain_player_id")
    vice_id = swt.get("vice_player_id")

    strategy = recommendations.get("strategy_recommendation") or {}
    chip = {
        "strategy": strategy.get("chip_strategy") or strategy.get("active_chip"),
        "summary": strategy.get("summary"),
    }

    return {
        "transfers": transfers,
        "captain": {"player": lookup.get(int(captain_id)) if captain_id else None, "id": captain_id},
        "vice": {"player": lookup.get(int(vice_id)) if vice_id else None, "id": vice_id},
        "chip": chip,
        "horizon_gws": recommendations.get("horizon_gws"),
        "free_transfers": recommendations.get("free_transfers"),
    }


SYSTEM_PROMPT = (
    "You are an FPL optimizer assistant. "
    "Explain each decision in one short sentence using ONLY numbers from the input — "
    "projected points, cost, form, fixtures. Never invent numbers. No filler. "
    "Respond ONLY with valid JSON."
)


USER_TEMPLATE = """Optimizer output:
{context}

Return JSON:
{{
  "transfers": [
    {{"out_id": <int|null>, "in_id": <int|null>, "rationale": "<one sentence citing projected points or fixtures>"}}
  ],
  "captain": {{"player_id": <int|null>, "rationale": "<one sentence citing projected points>"}},
  "chip": {{"name": "<string|null>", "rationale": "<one sentence|null>"}}
}}

Rules:
- One transfer entry per transfer (return [] if no transfers).
- One sentence per rationale — direct, no padding.
- Chip null if strategy is none.
"""


def _build_messages(context):
    return [{"role": "user", "content": USER_TEMPLATE.format(context=json.dumps(context, indent=2, default=str))}]


def _parse_response(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def explain(recommendations, model=None):
    if not recommendations:
        return {"error": "no recommendations payload provided"}

    api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not set"}

    context = _compact_context(recommendations)
    cache_key = _cache_key(context)
    cached = _cache_get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    try:
        from anthropic import Anthropic
    except ImportError:
        return {"error": "anthropic package not installed"}

    client = Anthropic(api_key=api_key)
    chosen_model = model or os.environ.get("FPL_EXPLAIN_MODEL") or DEFAULT_MODEL

    resp = client.messages.create(
        model=chosen_model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        messages=_build_messages(context),
    )

    text = ""
    for block in resp.content or []:
        if getattr(block, "type", None) == "text":
            text += getattr(block, "text", "") or ""

    parsed = _parse_response(text)
    out = {
        "transfers": parsed.get("transfers") or [],
        "captain": parsed.get("captain") or {"player_id": None, "rationale": None},
        "chip": parsed.get("chip") or {"name": None, "rationale": None},
        "model": chosen_model,
        "cached": False,
    }
    _cache_set(cache_key, out)
    return out
