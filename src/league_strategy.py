import os

from src import league


VALID_MODES = ("chase", "defend", "differential")


def _player_meta(bootstrap, projections_df=None):
    teams = {t["id"]: t for t in (bootstrap.get("teams") or [])}

    proj_lookup = {}
    if projections_df is not None and not projections_df.empty:
        gw_cols = [c for c in projections_df.columns if c.startswith("xpts_gw")]
        for _, row in projections_df.iterrows():
            pid = row.get("id")
            if pid is None:
                continue
            entry = {
                "xpts_horizon": float(row.get("xpts_horizon") or 0.0),
                "xpts_per_gw": {c.replace("xpts_", ""): float(row.get(c) or 0.0) for c in gw_cols},
            }
            proj_lookup[int(pid)] = entry

    elements = {}
    for el in bootstrap.get("elements") or []:
        team = teams.get(el.get("team")) or {}
        proj = proj_lookup.get(int(el["id"]), {})
        elements[el["id"]] = {
            "id": el["id"],
            "web_name": el.get("web_name"),
            "team_short": team.get("short_name"),
            "position_id": el.get("element_type"),
            "now_cost": el.get("now_cost"),
            "selected_by_percent": el.get("selected_by_percent"),
            "ep_next": el.get("ep_next"),
            "form": el.get("form"),
            "model_xpts_horizon": proj.get("xpts_horizon"),
            "model_xpts_per_gw": proj.get("xpts_per_gw"),
        }
    return elements


def analyze_league(entry_id, league_id, event_id, max_rivals=20):
    standings = league.fetch_league_standings(league_id, max_entries=max_rivals + 1)
    idx, my_entry = league.find_user_position(standings, entry_id)
    if idx is None:
        return {
            "error": "user not found in this league standings page",
            "league": {"id": standings["league_id"], "name": standings["league_name"]},
        }

    my_squad = league.fetch_rival_squad(entry_id, event_id)
    nbrs = league.neighbours(standings, entry_id, above=3, below=3)

    target_entries = [e for e in (nbrs["above"] + nbrs["below"]) if e.get("entry_id") != entry_id]

    rival_squads = {}
    rival_squad_errors = {}
    for rival in target_entries:
        rid = rival.get("entry_id")
        if rid is None:
            continue
        try:
            rival_squads[int(rid)] = league.fetch_rival_squad(int(rid), event_id)
        except Exception as exc:
            rival_squad_errors[int(rid)] = str(exc)

    rival_picks_by_entry = {rid: sq.get("picks") or [] for rid, sq in rival_squads.items()}
    diffs = league.differentials(my_squad.get("picks") or [], rival_picks_by_entry)
    ownership_in_league = league.league_ownership(list(rival_squads.values()) + [my_squad])

    return {
        "league": {"id": standings["league_id"], "name": standings["league_name"]},
        "user": my_entry,
        "user_position_index": idx,
        "rivals_above": nbrs["above"],
        "rivals_below": nbrs["below"],
        "my_squad": my_squad,
        "rival_squads": rival_squads,
        "rival_squad_errors": rival_squad_errors,
        "differentials": diffs,
        "league_ownership": ownership_in_league,
    }


def _enrich_ids(ids, elements_meta, ownership=None):
    out = []
    for pid in ids:
        meta = elements_meta.get(int(pid))
        if not meta:
            continue
        row = dict(meta)
        if ownership is not None:
            row["league_ownership"] = round(ownership.get(int(pid), 0.0), 3)
        out.append(row)
    return out


def _candidate_targets(analysis, elements_meta, mode):
    diffs = analysis["differentials"]
    ownership = analysis["league_ownership"]

    def ep(p):
        v = p.get("model_xpts_horizon")
        if v is None:
            v = p.get("ep_next")
        try:
            return float(v or 0.0)
        except Exception:
            return 0.0

    if mode == "chase":
        rivals_above_ids = set()
        for rid in [r["entry_id"] for r in analysis["rivals_above"] if r.get("entry_id") in analysis["rival_squads"]]:
            for p in analysis["rival_squads"][rid].get("picks") or []:
                if p.get("element") is not None:
                    rivals_above_ids.add(p["element"])
        my_ids = {p.get("element") for p in analysis["my_squad"].get("picks") or []}
        targets = sorted(rivals_above_ids - my_ids)
        enriched = _enrich_ids(targets, elements_meta, ownership)
        enriched.sort(key=lambda p: ep(p), reverse=True)
        return enriched[:10]

    if mode == "defend":
        rivals_below_ids = set()
        for rid in [r["entry_id"] for r in analysis["rivals_below"] if r.get("entry_id") in analysis["rival_squads"]]:
            for p in analysis["rival_squads"][rid].get("picks") or []:
                if p.get("element") is not None:
                    rivals_below_ids.add(p["element"])
        my_ids = {p.get("element") for p in analysis["my_squad"].get("picks") or []}
        targets = sorted(rivals_below_ids - my_ids)
        enriched = _enrich_ids(targets, elements_meta, ownership)
        enriched.sort(key=lambda p: ep(p), reverse=True)
        return enriched[:10]

    enriched = []
    for pid, meta in elements_meta.items():
        own = ownership.get(int(pid), 0.0)
        if own >= 0.20:
            continue
        if ep(meta) <= 0:
            continue
        row = dict(meta)
        row["league_ownership"] = round(own, 3)
        enriched.append(row)
    enriched.sort(key=lambda p: ep(p), reverse=True)
    return enriched[:10]


SYSTEM_PROMPT = (
    "You are an FPL mini-league strategist. Given an analysis of the user's league position, "
    "their squad, rival squads, differentials, and a list of candidate target players, write a "
    "concise strategy. Be specific: cite ranks, point gaps, ownership percentages, and player "
    "names from the input. Never invent numbers. Respond ONLY with valid JSON."
)


USER_TEMPLATE = """Mode: {mode}

League position summary:
- League: {league_name} (id {league_id})
- User: {user_name} — rank {user_rank}, total {user_total}
- Rivals above (closer = harder to chase): {rivals_above}
- Rivals below (closer = harder to defend): {rivals_below}

Your differentials:
- You own, rivals don't: {diff_owned_by_me}
- Rivals own, you don't: {diff_owned_by_rivals}

Candidate target players (pre-ranked by OUR model's projected points over the horizon — `model_xpts_horizon` — which accounts for fixture difficulty, recent form, and opponent strength). Use `model_xpts_horizon` and `model_xpts_per_gw` in your reasoning, not `ep_next` (FPL's number is shown only as reference):
{candidates}

Return JSON:
{{
  "headline": "<1 sentence framing the strategy for this mode>",
  "key_gap": "<1 sentence on the most important point gap>",
  "recommended_targets": [
    {{"player_id": <int>, "rationale": "<1-2 sentences citing model_xpts_horizon, league ownership, or rival overlap. Prefer our model's projection over ep_next.>"}}
  ],
  "watchouts": "<1 sentence on what could go wrong>"
}}

Rules:
- Up to 3 entries in recommended_targets.
- Plain prose, no markdown.
- If candidates list is empty, return recommended_targets: [] and explain in headline.
"""


def _llm_narrative(analysis, mode, candidates, model=None):
    api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not set"}

    try:
        from anthropic import Anthropic
    except ImportError:
        return {"error": "anthropic package not installed"}

    import json

    user_msg = USER_TEMPLATE.format(
        mode=mode,
        league_name=analysis["league"].get("name"),
        league_id=analysis["league"].get("id"),
        user_name=(analysis["user"] or {}).get("player_name"),
        user_rank=(analysis["user"] or {}).get("rank"),
        user_total=(analysis["user"] or {}).get("total"),
        rivals_above=json.dumps(analysis["rivals_above"], default=str),
        rivals_below=json.dumps(analysis["rivals_below"], default=str),
        diff_owned_by_me=analysis["differentials"]["owned_by_me_not_rivals"],
        diff_owned_by_rivals=analysis["differentials"]["owned_by_rivals_not_me"],
        candidates=json.dumps(candidates, indent=2, default=str),
    )

    client = Anthropic(api_key=api_key)
    chosen_model = model or os.environ.get("FPL_LEAGUE_MODEL") or "claude-haiku-4-5-20251001"
    try:
        resp = client.messages.create(
            model=chosen_model,
            max_tokens=700,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as exc:
        return {"error": f"anthropic api call failed: {exc}", "model": chosen_model}

    text = ""
    for block in resp.content or []:
        if getattr(block, "type", None) == "text":
            text += getattr(block, "text", "") or ""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except Exception:
        s, e = text.find("{"), text.rfind("}")
        parsed = json.loads(text[s : e + 1]) if s >= 0 and e > s else {}
    parsed["model"] = chosen_model
    return parsed


def build_strategy(entry_id, league_id, event_id, mode, bootstrap, projections_df=None, model=None):
    if mode not in VALID_MODES:
        return {"error": f"mode must be one of {VALID_MODES}"}

    analysis = analyze_league(entry_id, league_id, event_id)
    if analysis.get("error"):
        return analysis

    elements_meta = _player_meta(bootstrap, projections_df=projections_df)
    candidates = _candidate_targets(analysis, elements_meta, mode)
    narrative = _llm_narrative(analysis, mode, candidates, model=model)

    return {
        "mode": mode,
        "league": analysis["league"],
        "user": analysis["user"],
        "rivals_above": analysis["rivals_above"],
        "rivals_below": analysis["rivals_below"],
        "differentials_count": {
            "owned_by_me_not_rivals": len(analysis["differentials"]["owned_by_me_not_rivals"]),
            "owned_by_rivals_not_me": len(analysis["differentials"]["owned_by_rivals_not_me"]),
            "shared": len(analysis["differentials"]["shared"]),
        },
        "candidates": candidates,
        "narrative": narrative,
    }
