"""
Three structured wildcard squads on an honest budget (spec 4.8 / 4.11,
docs/superpowers/specs/2026-10-22-wildcard-v2-design.md).

`build_wildcard_drafts(payload)` runs the same projection stack as
/recommendations, then scores and drafts one squad per preset in
config.CHIP_WILDCARD_PRESET_ORDER on the entry's real budget. The
response carries every squad as lineup records (with the component
`score_breakdown` and engine-blind `facts`), the shared core, and the
budget breakdown. /recommendations is untouched by this module.
"""
from __future__ import annotations

import logging

import pandas as pd
from fastapi import HTTPException

from src import (
    config,
    european,
    fixture_difficulty,
    narrative_facts,
    optimizer,
    player_knowledge,
    projections,
    transforms,
)
from src.lineup_builder import pack_lineup_records
from src.squad_builder import squad_budget_breakdown
from src.utils import clean_value, safe_float, safe_int

logger = logging.getLogger(__name__)

HORIZON_MIN, HORIZON_MAX = 3, 8
PREMIUM_FLOOR = float(config.CHIP_WILDCARD_PREMIUM_CAPTAIN_PRICE_FLOOR)
PREMIUM_POS = list(config.CHIP_WILDCARD_PREMIUM_CAPTAIN_POSITIONS)


def _load_context(entry_id, squad_event_id=None, with_fixtures=True):
    from api import main as _main  # late import: api.main mounts this module's router
    return _main.load_fpl_context(entry_id, squad_event_id, with_fixtures=with_fixtures)


def _event_id(bootstrap, flag):
    for ev in bootstrap.get("events", []):
        if ev.get(flag):
            return safe_int(ev.get("id"))
    return None


def sanitize(obj):
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    return clean_value(obj)


def european_haircut(proj, gws, bootstrap, calendar_path=None):
    """Return a COPY of `proj` with xpts_gw{gw} scaled by CHIP_PLAN_EURO_XPTS_MULT
    for teams in a European week that GW. Scoring input only — the caller's
    display frame keeps the raw xPts. Fail-soft: no calendar → unchanged copy."""
    out = proj.copy()
    mult = float(config.CHIP_PLAN_EURO_XPTS_MULT)
    if mult >= 1.0 or mult <= 0.0 or "team_name" not in out.columns:
        return out
    try:
        aliases = {}
        for t in bootstrap.get("teams", []):
            name = t.get("name")
            if not name:
                continue
            aliases[str(name)] = name
            if t.get("short_name"):
                aliases[str(t["short_name"])] = name
            aliases[str(t.get("id"))] = name
        calendar = european.normalize_calendar_teams(
            european.load_european_calendar(calendar_path), aliases)
        euro_by_gw = european.european_weeks_by_gw(bootstrap.get("events", []), calendar)
    except Exception as exc:  # noqa: BLE001
        logger.warning("European haircut unavailable: %s", exc)
        return out
    for gw in gws:
        teams = euro_by_gw.get(int(gw)) or {}
        col = f"xpts_gw{int(gw)}"
        if not teams or col not in out.columns:
            continue
        mask = out["team_name"].isin(list(teams))
        out.loc[mask, col] = pd.to_numeric(out.loc[mask, col], errors="coerce").fillna(0.0) * mult
    return out


def _next_opponents(fixtures, gw, elements):
    by_team = transforms.fixtures_by_team_for_gw(fixtures, int(gw)) if fixtures is not None and not fixtures.empty else {}
    team_of = dict(zip(pd.to_numeric(elements["id"], errors="coerce"), pd.to_numeric(elements["team"], errors="coerce")))
    out = {}
    for pid, team in team_of.items():
        if pd.isna(pid) or pd.isna(team):
            continue
        lst = by_team.get(int(team)) or []
        if lst:
            out[int(pid)] = int(lst[0]["opp"])
    return out


def _captain_pair(xi_ids, proj, play_gw):
    """Top two XI players by the play-GW xPts (the draft market carries no per-GW columns)."""
    col = f"xpts_gw{int(play_gw)}"
    if col not in proj.columns or not xi_ids:
        return None, None
    x = pd.to_numeric(proj.set_index("id")[col], errors="coerce").reindex(xi_ids).fillna(0.0)
    ids = [int(i) for i in x.sort_values(ascending=False).index]
    return (ids[0] if ids else None), (ids[1] if len(ids) > 1 else None)


def _scoring_frame(proj_all, gws, bootstrap, play_event_id):
    """European haircut + trend / injury signals: the market every preset scores."""
    scoring = european_haircut(proj_all, gws, bootstrap)
    return projections.attach_wildcard_signals(scoring, gw_start=play_event_id)


def _build_preset(scoring, play_event_id, horizon, budget_m, preset_name, pinned_ids=None, excluded_ids=None):
    """Score the market under one preset and draft its squad → (scored, build)."""
    preset = config.CHIP_WILDCARD_PRESETS[preset_name]
    scored = projections.add_wildcard_scores(scoring, gw_start=play_event_id, horizon_gws=horizon, preset=preset)
    build = optimizer.build_chip_squad(
        elements_all=scored, score_col="wildcard_score", budget_m=float(budget_m),
        max_per_team=int(preset.get("max_per_team") or config.CHIP_MAX_PER_TEAM or 3),
        preset=preset, pinned_ids=list(pinned_ids or []), excluded_ids=list(excluded_ids or []),
    )
    return scored, build


def preset_squad_ids(proj_all, bootstrap, play_event_id, horizon, budget_m, preset_name):
    """The 15 ids one preset drafts (no pins, no bans), or None when the build fails.

    Shares _scoring_frame/_build_preset with build_wildcard_drafts so the chip
    planner's wildcard verdict scores the same squad the drafts page shows.
    """
    gws = list(range(int(play_event_id), int(play_event_id) + int(horizon)))
    scoring = _scoring_frame(proj_all, gws, bootstrap, int(play_event_id))
    _, build = _build_preset(scoring, int(play_event_id), int(horizon), budget_m, preset_name)
    if not build.get("ok") or build.get("squad_df") is None:
        return None
    return {int(i) for i in build["squad_df"]["id"]}


def build_wildcard_drafts(payload):
    payload = payload or {}
    entry_id = safe_int(payload.get("entry_id"))
    if entry_id is None:
        raise HTTPException(status_code=422, detail="entry_id is required")

    ctx = _load_context(entry_id, payload.get("squad_event_id"), with_fixtures=True)
    bootstrap = ctx["bootstrap"]
    fixtures = ctx["fixtures"]
    elements = ctx["elements"]
    notes = list(ctx.get("notes") or [])

    next_event_id = _event_id(bootstrap, "is_next") or _event_id(bootstrap, "is_current") or 1
    play_event_id = safe_int(payload.get("play_event_id")) or int(next_event_id)
    play_event_id = max(int(next_event_id), min(int(ctx["max_event_id"]), int(play_event_id)))
    horizon = safe_int(payload.get("horizon_gws")) or int(config.CHIP_WILDCARD_DEFAULT_HORIZON_GWS or 5)
    horizon = max(HORIZON_MIN, min(HORIZON_MAX, int(horizon)))
    gws = list(range(play_event_id, play_event_id + horizon))
    pinned_ids = [int(x) for x in (payload.get("pinned_ids") or []) if safe_int(x) is not None]
    excluded_ids = [int(x) for x in (payload.get("excluded_ids") or []) if safe_int(x) is not None]

    finished = [safe_int(e.get("id")) for e in bootstrap.get("events", []) if e.get("finished")]
    finished_gw_max = max([e for e in finished if e], default=None)
    proj_all = projections.project_elements_next_gws(
        elements=elements, fixtures=fixtures, teams_short_map=ctx["teams_short"],
        gw_start=play_event_id, horizon_gws=horizon, finished_gw_max=finished_gw_max,
    )
    proj_all, pk_notes = player_knowledge.apply(proj_all, gws, request_pk=payload.get("player_knowledge"))
    notes.extend(pk_notes)

    itb_explicit = payload.get("itb_m") is not None
    budget = squad_budget_breakdown(
        ctx.get("entry_history"), ctx.get("squad_df"), elements,
        itb_m=safe_float(payload.get("itb_m"), default=None) if itb_explicit else None,
    )

    scoring = _scoring_frame(proj_all, gws, bootstrap, play_event_id)

    match_df = fixture_difficulty.load_match_history()
    raw_elements = pd.DataFrame(bootstrap.get("elements") or [])
    next_opp = _next_opponents(fixtures, play_event_id, elements)
    current_ids = set()
    if ctx.get("squad_df") is not None and not ctx["squad_df"].empty and "player_id" in ctx["squad_df"].columns:
        current_ids = set(pd.to_numeric(ctx["squad_df"]["player_id"], errors="coerce").dropna().astype(int))

    presets_out = []
    xi_sets = []
    for name in config.CHIP_WILDCARD_PRESET_ORDER:
        preset = config.CHIP_WILDCARD_PRESETS[name]
        scored, build = _build_preset(scoring, play_event_id, horizon, float(budget["budget_m"]), name,
                                      pinned_ids=pinned_ids, excluded_ids=excluded_ids)
        if not build.get("ok") or build.get("squad_df") is None:
            presets_out.append({"name": name, "label": preset.get("label", name), "ok": False,
                                "reason": build.get("reason"), "squad": [], "xi_ids": [], "notes": []})
            continue
        squad_df = build["squad_df"].copy()
        xi_df = squad_df[squad_df["is_xi"].astype(bool)].copy()
        bench_df = squad_df[~squad_df["is_xi"].astype(bool)].copy()
        ids = [int(i) for i in squad_df["id"]]
        facts = narrative_facts.for_players(ids, next_opp, match_df, fixtures, raw_elements)
        xi_df["facts"] = xi_df["id"].astype(int).map(facts)
        bench_df["facts"] = bench_df["id"].astype(int).map(facts)
        captain_id, vice_id = _captain_pair([int(i) for i in xi_df["id"]], proj_all, play_event_id)

        # Display frame = raw xPts; wildcard components come from the scored copy.
        wc_cols = ["id"] + [c for c in scored.columns if c.startswith("wildcard_")]
        display = proj_all.drop(columns=[c for c in proj_all.columns if c.startswith("wildcard_")], errors="ignore")
        display = display.merge(scored[wc_cols], on="id", how="left")
        starting, bench = pack_lineup_records(
            starting_df=xi_df, bench_df=bench_df, elements=elements, proj_all=display, gws=gws,
            teams_code=ctx["teams_code"], chip_strategy="wildcard", objective_score_col="wildcard_score",
            optimize_event_id=play_event_id,
        )
        for rec in starting:
            rec["is_xi"] = True
            rec["is_captain"] = rec.get("player_id") == captain_id
            rec["is_vice_captain"] = rec.get("player_id") == vice_id
        for rec in bench:
            rec["is_xi"] = False
        xi_ids = [int(i) for i in xi_df["id"]]
        xi_sets.append(set(xi_ids))
        xpts_h = pd.to_numeric(display.set_index("id").get("xpts_horizon"), errors="coerce") if "xpts_horizon" in display.columns else None
        own = pd.to_numeric(squad_df.get("selected_by_percent"), errors="coerce") if "selected_by_percent" in squad_df.columns else None
        presets_out.append({
            "name": name,
            "label": preset.get("label", name),
            "ok": True,
            "squad": starting + bench,
            "xi_ids": xi_ids,
            "bench_roles": build.get("bench_roles") or {},
            "captain_id": captain_id,
            "vice_id": vice_id,
            "objective_score_total": build.get("objective_score_total"),
            "xi_xpts_horizon": round(float(xpts_h.reindex(xi_ids).fillna(0.0).sum()), 2) if xpts_h is not None else None,
            "bench_xpts_horizon": round(float(xpts_h.reindex([int(i) for i in bench_df["id"]]).fillna(0.0).sum()), 2) if xpts_h is not None else None,
            "squad_cost_m": build.get("squad_cost_m"),
            "remaining_budget_m": build.get("remaining_budget_m"),
            "premiums": int(((xi_df["price_m"] >= float(build.get("premium_floor_m") or PREMIUM_FLOOR)) & xi_df["pos"].isin(PREMIUM_POS)).sum()),
            "premium_floor_m": build.get("premium_floor_m"),
            "avg_ownership": round(float(own.mean()), 1) if own is not None and own.notna().any() else None,
            "transfers_from_current": int(15 - len(current_ids & set(ids))) if current_ids else None,
            "flags": int(sum(1 for r in starting + bench if r.get("alerts"))),
            "notes": list(build.get("notes") or []),
            "pins_conflict": list(build.get("pins_conflict") or []),
        })

    core_ids = sorted(set.intersection(*xi_sets)) if xi_sets else []
    return sanitize({
        "entry_id": int(entry_id),
        "event_id": int(play_event_id),
        "horizon_gws": int(horizon),
        "gws": gws,
        "budget_breakdown": budget,
        "presets": presets_out,
        "core_ids": core_ids,
        "notes": notes,
    })
