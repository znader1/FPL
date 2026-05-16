"""
Reflection Agent — runs periodically (e.g. every 4 GWs) over the decision
memory and proposes new strategy rules.

Usage:
    from agents.reflection_agent import run_reflection
    new_rule = run_reflection(store, entry_id, gw_window=(5, 8))
"""
from __future__ import annotations
import json
import os
from pathlib import Path

from anthropic import Anthropic

from src.agent_memory import MemoryStore, Decision


MODEL = "claude-haiku-4-5-20251001"
SYSTEM_PROMPT_PATH = Path(__file__).parent / "reflection_agent.md"
SYSTEM_PROMPT = SYSTEM_PROMPT_PATH.read_text() if SYSTEM_PROMPT_PATH.exists() else ""

# File alongside the DB that mirrors active rules as plain markdown (easy to inspect)
STRATEGY_RULES_MD = Path("agents/strategy_rules.md")


def _format_decisions_for_reflection(decisions: list[Decision]) -> str:
    rows = []
    for d in decisions:
        outcome = f"{d.outcome_delta:+.1f}" if d.outcome_delta is not None else "n/a"
        rows.append({
            "gw": d.gw,
            "agent_type": d.agent_type,
            "decision": d.decision,
            "context": d.context,
            "outcome_delta": outcome,
            "notes": d.notes,
        })
    return json.dumps(rows, indent=2)


def _refresh_rules_md(store: MemoryStore):
    rules = store.get_active_rules()
    if not rules:
        STRATEGY_RULES_MD.write_text(
            "# Strategy Rules (auto-generated)\n\nNo rules yet — the reflection agent hasn't run or found patterns.\n"
        )
        return
    lines = [
        "# Strategy Rules (auto-generated)",
        "",
        "Rules learned by the reflection agent from past gameweek outcomes. The main agents read this file at startup.",
        "",
    ]
    for r in rules:
        lines.append(f"## Rule {r['id']}")
        lines.append(r["rule_text"])
        ev = json.loads(r["evidence_gws"]) if r.get("evidence_gws") else []
        if ev:
            lines.append(f"  - Evidence GWs: {ev}")
        lines.append(f"  - Created: {r['created_at']}")
        lines.append("")
    STRATEGY_RULES_MD.parent.mkdir(parents=True, exist_ok=True)
    STRATEGY_RULES_MD.write_text("\n".join(lines))


def run_reflection(
    store: MemoryStore,
    entry_id: int,
    gw_window: tuple[int, int],
    verbose: bool = False,
) -> dict | None:
    """
    Look at decisions in gw_window=[lo, hi] (inclusive) and propose ONE new rule.
    Returns the rule dict if added, else None.
    """
    lo, hi = gw_window
    all_decisions = store.get_decisions_for(entry_id, agent_type=None, gw_max=hi, limit=500)
    window_decisions = [d for d in all_decisions if lo <= d.gw <= hi]
    decisions_with_outcome = [d for d in window_decisions if d.outcome_delta is not None]

    if len(decisions_with_outcome) < 3:
        if verbose:
            print(f"Reflection: too few decisions with outcomes ({len(decisions_with_outcome)}); skipping")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        if verbose:
            print("Reflection: ANTHROPIC_API_KEY not set; skipping")
        return None

    client = Anthropic(api_key=api_key)
    user_msg = (
        f"Window: GW{lo}-{hi}. {len(decisions_with_outcome)} decisions with outcomes.\n\n"
        f"Decisions:\n{_format_decisions_for_reflection(decisions_with_outcome)}\n\n"
        f"Propose ONE rule the main agent should follow going forward, "
        f"or null if no clear pattern. Return JSON only."
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        if verbose:
            print(f"Reflection: API call failed: {e}")
        return None

    text = next((b.text for b in response.content if b.type == "text"), "").strip()
    # Strip code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        if verbose:
            print(f"Reflection: could not parse JSON. Raw: {text[:200]}")
        return None

    rule = parsed.get("rule")
    if not rule:
        if verbose:
            print(f"Reflection: no rule proposed ({parsed.get('rationale', '')})")
        return None

    evidence = parsed.get("evidence_gws", [])
    store.add_strategy_rule(rule_text=rule, evidence_gws=evidence)
    _refresh_rules_md(store)

    if verbose:
        print(f"Reflection: new rule → {rule}")
        print(f"  Evidence: GWs {evidence}")
        print(f"  Confidence: {parsed.get('confidence')}")

    return parsed


def load_active_rules_text(store: MemoryStore) -> str:
    """Render active rules as a text block for injection into specialist agent prompts."""
    rules = store.get_active_rules()
    if not rules:
        return ""
    lines = ["Learned rules from past gameweeks (apply these):"]
    for r in rules:
        lines.append(f"  - {r['rule_text']}")
    return "\n".join(lines)
