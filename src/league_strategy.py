import os

from src import league, ownership_ev
from src import config


VALID_MODES = ("chase", "defend", "differential")


def _player_meta(bootstrap, projections_df=None):
    teams = {t["id"]: t for t in (bootstrap.get("teams") or [])}

    proj_lookup = {}
    if projections_df is not None and not projections_df.empty:
        gw_cols = [c for c in projections_df.columns if c.startswith("xpts_gw")]
        fix_cols = [c for c in projections_df.columns if c.startswith("fixtures_gw")]
        for _, row in projections_df.iterrows():
            pid = row.get("id")
            if pid is None:
                continue
            entry = {
                "xpts_horizon": float(row.get("xpts_horizon") or 0.0),
                "xpts_per_gw": {c.replace("xpts_", ""): round(float(row.get(c) or 0.0), 2) for c in gw_cols},
                "fixtures": {c.replace("fixtures_", ""): row.get(c) for c in fix_cols if row.get(c)},
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
            "fixtures": proj.get("fixtures"),
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


def _ep(p):
    v = p.get("model_xpts_horizon")
    if v is None:
        v = p.get("ep_next")
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def _rank_and_slice(candidates, templates, top_n=10):
    """Rank by differential EV (flag on) or legacy raw xPts (flag off), then slice."""
    if bool(getattr(config, "LEAGUE_EV_RANKING", True)) and templates:
        ranked = ownership_ev.annotate_candidates(candidates, templates)
        ranked.sort(key=lambda c: c.get("differential_ev", 0.0), reverse=True)
    else:
        ranked = sorted(candidates, key=_ep, reverse=True)
    return ranked[:top_n]


def detect_captain_differential(analysis, elements_meta, templates, fixture_ticker):
    """
    Flag when the league's consensus captain (highest league-owned premium MID/FWD)
    faces a hard fixture run AND a low-owned high-EV alternative exists. Returns the
    flag dict, or None when any condition is unmet.
    """
    ownership = analysis.get("league_ownership") or {}
    premium_floor = float(getattr(config, "LEAGUE_EV_CAPTAIN_PREMIUM_FLOOR", 85))
    max_own = float(getattr(config, "LEAGUE_EV_CAPTAIN_DIFF_MAX_OWNERSHIP", 0.10))
    runs = _fixture_run_lookup(fixture_ticker)

    consensus, best_own = None, -1.0
    for pid, meta in elements_meta.items():
        if meta.get("position_id") not in (3, 4):
            continue
        try:
            if float(meta.get("now_cost") or 0) < premium_floor:
                continue
        except (TypeError, ValueError):
            continue
        own = float(ownership.get(int(pid), 0.0) or 0.0)
        if own > best_own:
            consensus, best_own = meta, own
    if consensus is None or best_own <= 0:
        return None

    band = (runs.get(str(consensus.get("team_short") or "")) or {}).get("band")
    if band not in ("hard", "very_hard"):
        return None

    alt, best_ev = None, 0.0
    for pid, meta in elements_meta.items():
        if meta.get("position_id") not in (3, 4):
            continue
        if int(pid) == int(consensus.get("id") or -1):
            continue  # the alternative must differ from the consensus captain
        own = float(ownership.get(int(pid), 0.0) or 0.0)
        if own >= max_own:
            continue
        pos = meta.get("position_id")
        ev = ownership_ev.differential_ev(
            ownership_ev.xpts_of(meta),
            (templates or {}).get(int(pos) if pos is not None else -1, 0.0),
            own,
        )
        if ev > best_ev:
            alt, best_ev = (meta, own, ev), ev
    if alt is None:
        return None
    alt_meta, alt_own, alt_ev = alt

    return {
        "consensus_captain": {
            "id": consensus.get("id"), "web_name": consensus.get("web_name"),
            "team_short": consensus.get("team_short"), "league_ownership": round(best_own, 3),
            "fixture_run_band": band, "model_xpts_horizon": consensus.get("model_xpts_horizon"),
        },
        "alternative": {
            "id": alt_meta.get("id"), "web_name": alt_meta.get("web_name"),
            "team_short": alt_meta.get("team_short"), "league_ownership": round(alt_own, 3),
            "differential_ev": round(alt_ev, 2), "model_xpts_horizon": alt_meta.get("model_xpts_horizon"),
            "fixture_run_band": (runs.get(str(alt_meta.get("team_short") or "")) or {}).get("band"),
        },
        "reason": (
            f"{consensus.get('web_name')} (consensus captain, {round(best_own * 100)}% league-owned) "
            f"faces a {band} run; {alt_meta.get('web_name')} is a "
            f"{round(alt_own * 100)}%-owned differential (+{round(alt_ev, 1)} diff-EV)."
        ),
    }


def _candidate_targets(analysis, elements_meta, mode, templates=None):
    ownership = analysis["league_ownership"]

    if mode == "chase":
        rivals_above_ids = set()
        for rid in [r["entry_id"] for r in analysis["rivals_above"] if r.get("entry_id") in analysis["rival_squads"]]:
            for p in analysis["rival_squads"][rid].get("picks") or []:
                if p.get("element") is not None:
                    rivals_above_ids.add(p["element"])
        my_ids = {p.get("element") for p in analysis["my_squad"].get("picks") or []}
        targets = sorted(rivals_above_ids - my_ids)
        enriched = _enrich_ids(targets, elements_meta, ownership)
        return _rank_and_slice(enriched, templates)

    if mode == "defend":
        rivals_below_ids = set()
        for rid in [r["entry_id"] for r in analysis["rivals_below"] if r.get("entry_id") in analysis["rival_squads"]]:
            for p in analysis["rival_squads"][rid].get("picks") or []:
                if p.get("element") is not None:
                    rivals_below_ids.add(p["element"])
        my_ids = {p.get("element") for p in analysis["my_squad"].get("picks") or []}
        targets = sorted(rivals_below_ids - my_ids)
        enriched = _enrich_ids(targets, elements_meta, ownership)
        return _rank_and_slice(enriched, templates)

    enriched = []
    for pid, meta in elements_meta.items():
        own = ownership.get(int(pid), 0.0)
        if own >= 0.20:
            continue
        if _ep(meta) <= 0:
            continue
        row = dict(meta)
        row["league_ownership"] = round(own, 3)
        enriched.append(row)
    return _rank_and_slice(enriched, templates)


SYSTEM_PROMPT = (
    "You are an FPL mini-league strategist. "
    "Use ONLY numbers from the input — model_xpts_horizon, model_xpts_per_gw, fixtures, point gaps, ranks. "
    "Never invent or estimate numbers. Be direct and short. Respond ONLY with valid JSON."
)


USER_TEMPLATE = """Mode: {mode}
User: {user_name} rank {user_rank} ({user_total} pts) in {league_name}
Rivals above: {rivals_above_short}
Rivals below: {rivals_below_short}
Fixture outlook (xG model): {fixture_outlook_short}

Top candidates (ranked by model xPts over {horizon_gws} GWs — includes fixture difficulty and recent form):
{candidates_short}

Return JSON exactly:
{{
  "headline": "<one punchy sentence: what to do and why, citing the exact point gap>",
  "recommended_targets": [
    {{"player_id": <int>, "name": "<web_name>", "rationale": "<one sentence: cite model_xpts_horizon and at least one fixture from the fixtures field>"}}
  ],
  "watchouts": "<one sentence on the biggest risk>"
}}

Rules:
- Max 3 recommended_targets, picked from the candidates above only.
- Every rationale MUST quote model_xpts_horizon (e.g. '13.7 xPts') and at least one fixture (e.g. 'BOU/h').
- No markdown, no filler phrases like 'it is worth noting'. Plain short sentences.
- If candidates is empty: recommended_targets: [], headline explains why.
"""


def _fixture_run_lookup(fixture_ticker):
    """{team_short: {avg_difficulty, band}} from a build_fixture_ticker payload."""
    out = {}
    for t in (fixture_ticker or {}).get("teams", []):
        short = t.get("team_short")
        if short:
            out[str(short)] = {
                "avg_difficulty": t.get("avg_difficulty"),
                "band": t.get("band"),
            }
    return out


def _attach_fixture_runs(candidates, fixture_ticker):
    """Annotate candidates in-place with their team's xG fixture-run difficulty."""
    runs = _fixture_run_lookup(fixture_ticker)
    for c in candidates:
        run = runs.get(str(c.get("team_short") or ""))
        if run:
            c["fixture_run_difficulty"] = run["avg_difficulty"]
            c["fixture_run_band"] = run["band"]
    return candidates


def _llm_narrative(analysis, mode, candidates, model=None, fixture_ticker=None):
    api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not set"}

    try:
        from anthropic import Anthropic
    except ImportError:
        return {"error": "anthropic package not installed"}

    import json

    def _short_rival(r):
        return f"{r.get('player_name')} #{r.get('rank')} ({r.get('total')} pts, GW {r.get('event_total')})"

    def _short_candidate(c):
        fixes = " | ".join(f"{k}:{v}" for k, v in (c.get("fixtures") or {}).items()) or "—"
        per_gw = " ".join(f"{k}:{v}" for k, v in (c.get("model_xpts_per_gw") or {}).items())
        run = ""
        if c.get("fixture_run_difficulty") is not None:
            run = f" fixture_run={c['fixture_run_difficulty']} ({c.get('fixture_run_band')})"
        return (
            f"id={c['id']} {c.get('web_name')} ({c.get('team_short')}) "
            f"xPts={c.get('model_xpts_horizon', '?')} [{per_gw}] fixtures: {fixes}{run} "
            f"league_own={c.get('league_ownership', '?')}"
        )

    fixture_outlook_short = "n/a"
    if fixture_ticker:
        easiest = ", ".join(fixture_ticker.get("easiest_runs") or []) or "?"
        hardest = ", ".join(fixture_ticker.get("hardest_runs") or []) or "?"
        fixture_outlook_short = (
            f"next {fixture_ticker.get('horizon_gws')} GWs — easiest runs: {easiest}; "
            f"hardest runs: {hardest} (lower fixture_run = easier)"
        )

    user_msg = USER_TEMPLATE.format(
        mode=mode,
        fixture_outlook_short=fixture_outlook_short,
        league_name=analysis["league"].get("name"),
        user_name=(analysis["user"] or {}).get("player_name"),
        user_rank=(analysis["user"] or {}).get("rank"),
        user_total=(analysis["user"] or {}).get("total"),
        rivals_above_short=" / ".join(_short_rival(r) for r in analysis["rivals_above"]) or "none",
        rivals_below_short=" / ".join(_short_rival(r) for r in analysis["rivals_below"]) or "none",
        horizon_gws=len(next(iter(candidates), {}).get("model_xpts_per_gw") or {}) or 3,
        candidates_short="\n".join(_short_candidate(c) for c in candidates) or "(none)",
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


def build_strategy(entry_id, league_id, event_id, mode, bootstrap, projections_df=None, model=None,
                   fixture_ticker=None):
    if mode not in VALID_MODES:
        return {"error": f"mode must be one of {VALID_MODES}"}

    analysis = analyze_league(entry_id, league_id, event_id)
    if analysis.get("error"):
        return analysis

    elements_meta = _player_meta(bootstrap, projections_df=projections_df)
    templates = ownership_ev.compute_position_templates(elements_meta)
    candidates = _candidate_targets(analysis, elements_meta, mode, templates)
    candidates = _attach_fixture_runs(candidates, fixture_ticker)
    captain_differential = detect_captain_differential(analysis, elements_meta, templates, fixture_ticker)
    narrative = _llm_narrative(analysis, mode, candidates, model=model,
                               fixture_ticker=fixture_ticker, captain_differential=captain_differential)

    out = {
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
        "captain_differential": captain_differential,
        "narrative": narrative,
    }
    if fixture_ticker:
        out["fixture_outlook"] = {
            "gw_start": fixture_ticker.get("gw_start"),
            "horizon_gws": fixture_ticker.get("horizon_gws"),
            "easiest_runs": fixture_ticker.get("easiest_runs"),
            "hardest_runs": fixture_ticker.get("hardest_runs"),
            "meta": fixture_ticker.get("meta"),
        }
    return out
