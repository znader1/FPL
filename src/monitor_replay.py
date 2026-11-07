"""Rebuild the app's advice as of a past gameweek, for the monitoring dashboard.

The app never stored the transfer plan or the wildcard squads it showed, so for
past gameweeks they are rebuilt: today's engine, run on what was knowable before
that gameweek's deadline (src/season_replay.py), fed with the owner's real squad
at the time. The dashboard labels these "rebuilt with today's engine".

Rules this module exists to keep:

* The engine is called directly. The HTTP routes and their builders read live
  data and today's manual files, so they are never used here.
* The manual team and player files are off: they hold present-day information.
* The wildcard's injury prior comes from an as-of status file built from the
  stored snapshots, not from the live status history.
* A replay that fails says so and returns; it never raises to the caller, so
  one bad gameweek cannot stop the others.
"""
from __future__ import annotations

import pandas as pd

from . import config, ft_tracker, injury_prior, projections, recommender, season_replay, transfer_planner

FREE_HIT = "freehit"
NO_SQUAD_REASON = "no squad known before this gameweek"
# Bootstrap fields that say who takes penalties, free kicks and corners *today*.
SET_PIECE_FIELDS = ("penalties_order", "direct_freekicks_order", "corners_and_indirect_freekicks_order")
# What in a rebuild is still present-day, said on every rebuilt report.
PRESENT_DAY_NOTES = (
    "set-piece takers are switched off in the rebuild: only today's are known, and today's taker "
    "would be credited in weeks he was not on penalties",
    "the fixture list is today's: a match rescheduled since then appears in its new gameweek",
    "club and position are today's",
)
WILDCARD_NOTES = (
    "injury prior rebuilt from stored snapshot statuses before this gameweek",
    "European haircut uses the calendar file as shipped",
)


def _unavailable(exc):
    return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}


def _free_hit_gws(chips):
    return {int(c["event"]) for c in chips or []
            if str(c.get("name") or "").lower() == FREE_HIT and c.get("event") is not None}


def _gw_before(gw, chips):
    """The last gameweek whose squad was permanent: a Free Hit squad is handed back."""
    prev = int(gw) - 1
    fh = _free_hit_gws(chips)
    while prev in fh:
        prev -= 1
    return prev


def permanent_squad_before(gw, picks_by_gw, chips):
    """The fifteen held going into `gw`: the picks of the gameweek before, or of
    the one before that when the last one was a Free Hit. None when unknown."""
    if int(gw) <= 1:
        return None
    picks = (picks_by_gw or {}).get(_gw_before(gw, chips))
    return [int(p) for p in picks] if picks else None


def entry_state_before(gw, picks_by_gw, history):
    """→ {squad_ids, bank_m, value_m, free_transfers} going into `gw`, or None.

    `history` is FPL's /entry/{id}/history/ payload. Bank and squad value come
    from the same gameweek as the squad (value is selling prices plus bank)."""
    history = history or {}
    chips = history.get("chips") or []
    squad = permanent_squad_before(gw, picks_by_gw, chips)
    if squad is None:
        return None
    prev = _gw_before(gw, chips)
    row = next((r for r in history.get("current") or [] if int(r.get("event", 0) or 0) == prev), None)
    if row is None:
        return None
    return {
        "squad_ids": squad,
        "bank_m": round(float(row.get("bank") or 0) / 10.0, 1),
        "value_m": round(float(row.get("value") or 0) / 10.0, 1),
        "free_transfers": int(ft_tracker.derive_free_transfers(history.get("current"), chips, int(gw))),
    }


def write_status_history_as_of(snapshots_df, season, gw, path):
    """Write a status-history CSV (injury_prior.COLUMNS) from the stored
    snapshots of gameweeks strictly before `gw`. Returns rows written."""
    snaps = snapshots_df[pd.to_numeric(snapshots_df["gw"], errors="coerce") < int(gw)]
    out = pd.DataFrame({
        "season": str(season),
        "event": pd.to_numeric(snaps["gw"], errors="coerce").astype(int).values,
        "element": pd.to_numeric(snaps["player_id"], errors="coerce").astype(int).values,
        "status": snaps["status"].fillna("a").astype(str).str.lower().values,
        "chance": pd.to_numeric(snaps["chance"], errors="coerce").values,
    }, columns=injury_prior.COLUMNS).sort_values(["event", "element"])
    out.to_csv(path, index=False)
    return int(len(out))


def opponents_by_gw(fixtures, teams_short_map, gws):
    """{gw: {team short: {opponent shorts}}}, as production builds it for the
    planner's head-to-head nudge."""
    fx = pd.DataFrame(fixtures)
    out = {}
    for g in gws:
        m = {}
        if not fx.empty:
            for _, f in fx[pd.to_numeric(fx["event"], errors="coerce") == int(g)].iterrows():
                home, away = teams_short_map.get(int(f["team_h"])), teams_short_map.get(int(f["team_a"]))
                if home and away:
                    m.setdefault(home, set()).add(away)
                    m.setdefault(away, set()).add(home)
        out[int(g)] = m
    return out


def project(gw, horizon, inputs):
    """The as-of projection every rebuild uses: season_replay.project_as_of with
    today's set-piece orders blanked, so today's penalty taker gets no uplift in
    a gameweek where he may not have been the taker. The caller's `inputs` are
    not modified."""
    bootstrap = dict(inputs["bootstrap"])
    bootstrap["elements"] = [{**e, **{f: None for f in SET_PIECE_FIELDS}}
                             for e in bootstrap.get("elements") or []]
    return season_replay.project_as_of(int(gw), int(horizon), {**inputs, "bootstrap": bootstrap})


def _teams_short_map(bootstrap):
    return {int(t["id"]): t.get("short_name") for t in (bootstrap or {}).get("teams") or []}


def replay_transfer_plan(gw, state, inputs):
    """The headline transfer plan the engine gives for `gw` from the owner's real
    squad, bank and free transfers. Arguments mirror production's call in
    api/main.py (server defaults: 3-gameweek horizon, injured-first on)."""
    if not state:
        return {"available": False, "reason": NO_SQUAD_REASON}
    try:
        horizon = int(config.MONITOR_ADVICE_HORIZON_GWS)
        gws = [int(gw) + i for i in range(horizon)]
        proj = project(gw, horizon, inputs)
        known = set(pd.to_numeric(proj["id"], errors="coerce").dropna().astype(int))
        squad = [int(p) for p in state["squad_ids"]]
        plan = transfer_planner.plan_transfers(
            proj, squad, gws,
            itb_m=float(state["bank_m"]),
            start_ft=int(state["free_transfers"]), ft_cap=int(config.FT_MAX),
            allow_hits=bool(config.TRANSFER_PLAN_ALLOW_HITS),
            max_moves_per_gw=int(config.TRANSFER_PLAN_MAX_MOVES_PER_GW),
            min_gain=transfer_planner.scaled_min_gain(len(gws)),
            opponents_by_gw=opponents_by_gw(inputs["fixtures"], _teams_short_map(inputs["bootstrap"]), gws),
            prioritize_injured=True,
        )
        first = next((row for row in plan.get("plan") or [] if int(row.get("gw", -1)) == int(gw)), {})
        moves = [{"sell_id": int(m["sell"]["id"]), "buy_id": int(m["buy"]["id"])}
                 for m in first.get("moves") or []]
        return {"available": True, "moves": moves, "action": "move" if moves else "roll",
                "plan": plan, "dropped_squad_ids": [p for p in squad if p not in known]}
    except Exception as exc:  # noqa: BLE001 - one gameweek's replay must not stop the others
        return _unavailable(exc)


def replay_wildcard_squads(gw, budget_m, inputs, status_path):
    """The fifteen each wildcard preset drafts for `gw` on `budget_m`.

    Built from the same pieces as the drafts page (European haircut, wildcard
    signals, preset builder) but fed as-of inputs explicitly; the page's own
    entry points read the live match history and status files."""
    try:
        from api import wildcard as wc   # the preset builder lives beside the route
        horizon = int(config.CHIP_WILDCARD_DEFAULT_HORIZON_GWS)
        gws = [int(gw) + i for i in range(horizon)]
        proj = project(gw, horizon, inputs)
        scoring = projections.attach_wildcard_signals(
            wc.european_haircut(proj, gws, inputs["bootstrap"]), gw_start=int(gw),
            match_df=season_replay.cap_match_history(inputs["match_df"], int(gw)),
            status_path=status_path,
        )
        presets = {}
        for name in config.CHIP_WILDCARD_PRESET_ORDER:
            try:
                _, build = wc._build_preset(scoring, int(gw), horizon, float(budget_m), name)
                ok = build.get("ok") and build.get("squad_df") is not None
                presets[name] = sorted(int(i) for i in build["squad_df"]["id"]) if ok else None
            except Exception:  # noqa: BLE001 - a preset that cannot build is recorded as missing
                presets[name] = None
        return {"available": True, "presets": presets, "notes": list(WILDCARD_NOTES)}
    except Exception as exc:  # noqa: BLE001
        return _unavailable(exc)


def replay_buy_targets(gw, inputs):
    """The app's squad-independent buy list for `gw`: the top of the hot list in
    each outfield position, with no players owned."""
    try:
        horizon = int(config.MONITOR_ADVICE_HORIZON_GWS)
        proj = project(gw, horizon, inputs)
        market = recommender.prepare_market(proj, score_col="xpts_horizon", horizon_gws=horizon)
        hot = recommender.hot_by_position(market, owned_ids=[],
                                          n=int(config.MONITOR_BUY_LIST_PER_POSITION),
                                          xpts_col="xpts_horizon")
        ids = [int(row["id"]) for pos in config.MONITOR_BUY_LIST_POSITIONS for row in hot.get(pos) or []]
        return {"available": True, "player_ids": ids}
    except Exception as exc:  # noqa: BLE001
        return _unavailable(exc)


def parity(proj, snapshots_df, gw, code_version):
    """Does the replay reproduce what production stored for this gameweek?

    Only comparable where the stored rows were made by the same model version
    as the code replaying them. Anything older: "no_same_version_baseline",
    neither passed nor failed."""
    none = {"status": "no_same_version_baseline", "mae": None, "corr": None, "n": 0}
    if snapshots_df is None or "model_version" not in getattr(snapshots_df, "columns", []):
        return none
    snaps = snapshots_df[(pd.to_numeric(snapshots_df["gw"], errors="coerce") == int(gw))
                         & (snapshots_df["model_version"].astype(str) == str(code_version))]
    col = f"xpts_gw{int(gw)}"
    if snaps.empty or col not in proj.columns:
        return none
    stored = pd.DataFrame({"id": pd.to_numeric(snaps["player_id"], errors="coerce"),
                           "stored": pd.to_numeric(snaps["model_xpts"], errors="coerce")})
    replay = pd.DataFrame({"id": pd.to_numeric(proj["id"], errors="coerce"),
                           "replay": pd.to_numeric(proj[col], errors="coerce")})
    both = replay.merge(stored, on="id").dropna()
    if both.empty:
        return none
    mae = float((both["replay"] - both["stored"]).abs().mean())
    corr = float(both["replay"].corr(both["stored"])) if len(both) > 1 else 1.0
    ok = mae <= float(config.MONITOR_PARITY_MAX_MEAN_ABS_DIFF) and corr >= float(config.MONITOR_PARITY_MIN_CORR)
    return {"status": "pass" if ok else "fail", "mae": round(mae, 4), "corr": round(corr, 4), "n": int(len(both))}
