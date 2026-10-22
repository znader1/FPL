"""
Bench construction for chip drafts (spec 4.4, docs/superpowers/specs/2026-10-22-wildcard-v2-design.md).

Two modes:
- ``enablers``: cheapest bodies that actually play, per needed position
  (the free-hit behaviour, with an availability gate in front).
- ``roles``: GK2 / DEF cover / DC midfielder / free slot, each the cheapest
  qualifying player, so the bench earns minutes and the budget flows to the XI.
``enablers_gem`` is ``enablers`` with the last slot filled like the roles
``free`` slot through a gem filter.

Pure pandas; the optimizer supplies the market and the chosen XI.
"""
from __future__ import annotations

import pandas as pd

from . import config

FULL_SHAPE = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
POS_ORDER = ["GKP", "DEF", "MID", "FWD"]


def bench_sort(pool):
    """Bench-fodder ordering: players with at least CHIP_BENCH_MIN_MINUTES
    season minutes come first (cheap is fine, ghosts are not), then price
    ascending, then WORST scorer so a price tie never eats an XI candidate.
    Preference, not a filter — a thin market falls through to the ghosts."""
    pool = pool.copy()
    floor = float(config.CHIP_BENCH_MIN_MINUTES)
    if "minutes" in pool.columns:
        pool["_bench_pref"] = (
            pd.to_numeric(pool["minutes"], errors="coerce").fillna(0.0) >= floor
        )
    else:
        pool["_bench_pref"] = True
    return pool.sort_values(
        ["_bench_pref", "price_m", "chip_score"],
        ascending=[False, True, True],
        kind="mergesort",
    )


def availability_mask(market, start_share_min):
    """True where a player is a usable body: started at least `start_share_min`
    of team games, status 'a' (when the column exists) and no injury flag
    (when the column exists). A market without `start_share` is a caller
    error: a preset that gates on availability must not silently pass ghosts."""
    if "start_share" not in market.columns:
        raise KeyError("start_share")
    share = pd.to_numeric(market["start_share"], errors="coerce").fillna(0.0)
    mask = share >= float(start_share_min)
    if "status" in market.columns:
        mask &= market["status"].astype(str).str.lower().eq("a")
    if "injury_flag" in market.columns:
        mask &= ~market["injury_flag"].fillna(False).astype(bool)
    return mask


def _needed_positions(xi_df):
    xi_pos = xi_df["pos"].astype(str).value_counts().to_dict()
    return {pos: int(FULL_SHAPE[pos] - xi_pos.get(pos, 0)) for pos in POS_ORDER}


def _pick(pool, team_counts, max_per_team, budget_left):
    """First row of `pool` that respects the team cap and the budget, or None."""
    for _, row in pool.iterrows():
        team = int(row["team"])
        if team_counts.get(team, 0) >= int(max_per_team):
            continue
        if float(row["price_m"]) > budget_left + 1e-9:
            continue
        return row
    return None


def fill_bench(market, xi_df, mode, budget_left_m, max_per_team, team_counts, gem_filter=None):
    """
    Return (bench_df, notes). `bench_df` holds the market rows plus a `role`
    column; positions complete the XI to 2/5/5/3.

    - market: optimizer market (id, pos, team, price_m, chip_score, start_share,
      optional p_dc / p_clean_sheet / status / injury_flag).
    - xi_df: the 11 chosen rows (id, pos, team).
    - mode: "enablers" | "roles" | "enablers_gem".
    - gem_filter: boolean Series aligned to `market`; the free slot prefers
      rows where it is True.
    """
    notes: list[str] = []
    need = _needed_positions(xi_df)
    xi_ids = set(pd.to_numeric(xi_df["id"], errors="coerce").dropna().astype(int))
    counts = dict(team_counts or {})
    for t in pd.to_numeric(xi_df["team"], errors="coerce").dropna().astype(int):
        counts[int(t)] = counts.get(int(t), 0) + 1

    pool_all = market[~market["id"].astype(int).isin(xi_ids)].copy()
    avail = availability_mask(pool_all, config.CHIP_BENCH_START_SHARE)
    pool = pool_all[avail].copy()
    if pool.empty:
        pool = pool_all.copy()
        notes.append("bench: no player passes the availability gate; using the full market")

    budget = float(budget_left_m)
    picked: list[pd.Series] = []

    def take(row, role):
        nonlocal budget
        r = row.copy()
        r["role"] = role
        picked.append(r)
        budget -= float(row["price_m"])
        counts[int(row["team"])] = counts.get(int(row["team"]), 0) + 1
        need[str(row["pos"])] -= 1

    def remaining(pos=None):
        ids = {int(r["id"]) for r in picked}
        out = pool[~pool["id"].astype(int).isin(ids)]
        if pos is not None:
            out = out[out["pos"] == pos]
        return out

    def cheapest(pos):
        return _pick(remaining(pos).sort_values(["price_m", "chip_score"], ascending=[True, False], kind="mergesort"),
                     counts, max_per_team, budget)

    def best(pos_list, prefer=None):
        out = remaining()
        out = out[out["pos"].isin(pos_list)]
        if prefer is not None:
            pref = out[prefer.reindex(out.index).fillna(False).astype(bool)]
            cand = _pick(pref.sort_values(["chip_score", "price_m"], ascending=[False, True], kind="mergesort"),
                         counts, max_per_team, budget)
            if cand is not None:
                return cand
        return _pick(out.sort_values(["chip_score", "price_m"], ascending=[False, True], kind="mergesort"),
                     counts, max_per_team, budget)

    if mode == "roles":
        # GK2: cheapest playing keeper.
        if need["GKP"] > 0:
            row = cheapest("GKP")
            if row is not None:
                take(row, "gk2")
        # DEF cover: cheapest DEF with CS or DC at/above the DEF median.
        if need["DEF"] > 0:
            defs = remaining("DEF")
            dc = pd.to_numeric(defs.get("p_dc"), errors="coerce") if "p_dc" in defs.columns else None
            cs = pd.to_numeric(defs.get("p_clean_sheet"), errors="coerce") if "p_clean_sheet" in defs.columns else None
            qual = pd.Series(True, index=defs.index)
            if dc is not None or cs is not None:
                q = pd.Series(False, index=defs.index)
                if dc is not None and dc.notna().any():
                    q |= dc >= float(dc.median())
                if cs is not None and cs.notna().any():
                    q |= cs >= float(cs.median())
                qual = q
            row = _pick(defs[qual].sort_values(["price_m", "chip_score"], ascending=[True, False], kind="mergesort"),
                        counts, max_per_team, budget)
            if row is None:
                row = cheapest("DEF")
            if row is not None:
                take(row, "def_cover")
        # DC midfielder: cheapest MID reaching the DC threshold often enough;
        # fallback a DEF with the same floor.
        dc_floor = float(config.CHIP_BENCH_MID_DC_PROB)
        if need["MID"] > 0 or need["DEF"] > 0:
            row = None
            if need["MID"] > 0 and "p_dc" in pool.columns:
                mids = remaining("MID")
                mids = mids[pd.to_numeric(mids["p_dc"], errors="coerce").fillna(0.0) >= dc_floor]
                row = _pick(mids.sort_values(["price_m", "chip_score"], ascending=[True, False], kind="mergesort"),
                            counts, max_per_team, budget)
            if row is None and need["DEF"] > 0 and "p_dc" in pool.columns:
                defs = remaining("DEF")
                defs = defs[pd.to_numeric(defs["p_dc"], errors="coerce").fillna(0.0) >= dc_floor]
                row = _pick(defs.sort_values(["price_m", "chip_score"], ascending=[True, False], kind="mergesort"),
                            counts, max_per_team, budget)
                if row is not None:
                    notes.append("dc_mid fallback: DEF (no midfielder reaches the DC floor under budget)")
            if row is None:
                pos = "MID" if need["MID"] > 0 else "DEF"
                row = cheapest(pos)
                if row is not None:
                    notes.append(f"dc_mid fallback: cheapest {pos} (no DC body under budget)")
            if row is not None:
                take(row, "dc_mid")
        # Free slot(s): best score among still-needed positions, gem-preferred.
        while sum(need.values()) > 0 and len(picked) < 4:
            needed = [p for p, n in need.items() if n > 0]
            row = best(needed, prefer=gem_filter)
            if row is None:
                row = next((r for r in (cheapest(p) for p in needed) if r is not None), None)
            if row is None:
                break
            take(row, "free")
    else:
        slots_enabler = 4 if mode == "enablers" else 3
        for pos in POS_ORDER:
            while need[pos] > 0 and len(picked) < slots_enabler:
                row = cheapest(pos)
                if row is None:
                    break
                take(row, "enabler")
        while sum(need.values()) > 0 and len(picked) < 4:
            needed = [p for p, n in need.items() if n > 0]
            row = best(needed, prefer=gem_filter) if mode == "enablers_gem" else None
            if row is None:
                row = next((r for r in (cheapest(p) for p in needed) if r is not None), None)
            if row is None:
                break
            take(row, "free" if mode == "enablers_gem" else "enabler")

    if sum(need.values()) > 0:
        notes.append("bench incomplete: " + ", ".join(f"{p} x{n}" for p, n in need.items() if n > 0))
    bench = pd.DataFrame(picked).reset_index(drop=True) if picked else pd.DataFrame(columns=list(market.columns) + ["role"])
    return bench, notes
