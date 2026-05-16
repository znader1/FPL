#!/usr/bin/env python3
"""
Walk-forward season simulator using Vaastav historical data.

For each GW N from start to end:
  1. Project xPts for every player using only data from GWs < N
  2. Pick captain + bench order from current squad
  3. Suggest transfers (subject to FT/hits) — apply the top one if it beats threshold
  4. Score the resulting starting XI against actual GW N points
  5. Record running total, captain pick, transfer log

Phase 1: no chips (no wildcard, free hit, BB, TC).

Usage:
  python3 scripts/backtest_season.py --season 2025-26 --start 2 --end 29
  python3 scripts/backtest_season.py --season 2025-26 --start 2 --end 29 --initial-squad my_gw1.csv
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest_data import (
    available_gws,
    load_teams,
    load_fixtures,
    player_actuals_at,
    player_actuals_through,
)
from src.backtest_adapter import build_engine_inputs
from src import projections as engine_projections


DIFFICULTY_MULTIPLIER = {1: 1.25, 2: 1.12, 3: 1.0, 4: 0.88, 5: 0.75}
SQUAD_SHAPE = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
FORMATION_BOUNDS = {"GKP": (1, 1), "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3)}
INITIAL_BUDGET_M = 100.0

# Captaincy preference: heavily favor attackers since they have higher ceilings
CAPTAIN_POSITION_MULT = {"FWD": 1.16, "MID": 1.12, "DEF": 0.92, "GKP": 0.70}

# CAN/AFCON 2025/26: FPL gave 5 free transfers at GW16 to compensate for African players
# being unavailable at the Africa Cup of Nations
CAN_BONUS_GW = 16
CAN_BONUS_FT = 5


# ---------- projection ----------

def project_gw(
    target_gw: int,
    history: pd.DataFrame,
    fixtures_all: pd.DataFrame,
    teams: pd.DataFrame,
    window: int = 5,
    recent_weight: float = 2.0,
) -> pd.DataFrame:
    """
    Returns DataFrame keyed by player_id with columns:
      player_id, name, pos, team, price_m, xpts
    `history` must only contain GWs < target_gw.
    """
    if history.empty:
        return pd.DataFrame(columns=["player_id", "name", "pos", "team", "price_m", "xpts"])

    # Recency-weighted average over last `window` GWs where player had a fixture (minutes > 0 or fixture played)
    h = history.copy()
    h["played"] = pd.to_numeric(h.get("minutes"), errors="coerce").fillna(0) > 0
    # Limit to last `window` GWs
    max_gw_in_hist = int(h["gw"].max())
    window_lo = max(1, max_gw_in_hist - window + 1)
    h_window = h[h["gw"] >= window_lo].copy()
    # Recency weight: last 2 GWs get higher weight
    h_window["_w"] = np.where(h_window["gw"] >= max_gw_in_hist - 1, recent_weight, 1.0)

    # Exclude blank GWs (player's team didn't play that GW) — proxy: if player had no fixture row
    # In Vaastav format, every player appears every GW (even if 0 points), so use minutes>0 as proxy for "available + played"
    # For a cleaner blank-GW signal we'd need fixtures; for now use minutes-based filter
    agg = (
        h_window.groupby("player_id")
        .apply(lambda g: pd.Series({
            "ppg": (g["total_points"] * g["_w"]).sum() / max(g["_w"].sum(), 1e-9),
            "samples": int((g["minutes"] > 0).sum()),
            "minutes_avg": g["minutes"].mean(),
        }))
        .reset_index()
    )

    # Latest player metadata (use last appearance per player in history)
    meta = h.sort_values("gw").groupby("player_id").tail(1)[
        ["player_id", "name", "pos", "team", "price_m"]
    ].reset_index(drop=True)

    df = meta.merge(agg, on="player_id", how="left")
    df["ppg"] = df["ppg"].fillna(0.0)
    df["samples"] = df["samples"].fillna(0).astype(int)

    # Apply fixture difficulty for target GW
    fx_gw = fixtures_all[pd.to_numeric(fixtures_all["event"], errors="coerce") == target_gw].copy()
    diff_by_team = _team_difficulty_map(fx_gw, teams)
    df["diff_avg"] = df["team"].map(diff_by_team).fillna(3)
    df["diff_mult"] = df["diff_avg"].round().clip(1, 5).astype(int).map(DIFFICULTY_MULTIPLIER).fillna(1.0)

    # Fixture count for target GW (DGW = 2), keyed by team NAME
    fixture_count_by_team = _fixture_count_by_team_name(fx_gw, teams)
    df["fixture_count"] = df["team"].map(fixture_count_by_team).fillna(0).astype(int)

    df["xpts"] = df["ppg"] * df["diff_mult"] * df["fixture_count"].clip(upper=2).replace(0, 0.0)
    # Penalize players with very few samples (no minutes recently)
    df.loc[df["samples"] < 2, "xpts"] = df.loc[df["samples"] < 2, "xpts"] * 0.5

    return df[["player_id", "name", "pos", "team", "price_m", "xpts", "fixture_count", "ppg", "samples"]]


def _team_difficulty_map(fx_gw: pd.DataFrame, teams: pd.DataFrame) -> dict:
    """Map of team_name -> average opponent difficulty for that GW (1=easy, 5=hard)."""
    if fx_gw.empty:
        return {}
    team_name_by_id = dict(zip(teams["id"], teams["name"]))
    rows = []
    for _, fx in fx_gw.iterrows():
        rows.append({"team": team_name_by_id.get(fx["team_h"]), "diff": fx["team_h_difficulty"]})
        rows.append({"team": team_name_by_id.get(fx["team_a"]), "diff": fx["team_a_difficulty"]})
    df = pd.DataFrame(rows)
    return df.groupby("team")["diff"].mean().to_dict()


def _fixture_count_by_team(fx_gw: pd.DataFrame) -> dict:
    if fx_gw.empty:
        return {}
    counts = {}
    for _, fx in fx_gw.iterrows():
        counts[fx["team_h"]] = counts.get(fx["team_h"], 0) + 1
        counts[fx["team_a"]] = counts.get(fx["team_a"], 0) + 1
    # But we want by team NAME, not id, since projection uses team name
    return counts


def _fixture_count_by_team_name(fx_gw: pd.DataFrame, teams: pd.DataFrame) -> dict:
    if fx_gw.empty:
        return {}
    team_name_by_id = dict(zip(teams["id"], teams["name"]))
    counts = {}
    for _, fx in fx_gw.iterrows():
        for tid in (fx["team_h"], fx["team_a"]):
            name = team_name_by_id.get(tid)
            if name:
                counts[name] = counts.get(name, 0) + 1
    return counts


def project_gw_engine(target_gw: int, season: str = "2025-26", horizon: int = 3) -> pd.DataFrame:
    """
    Run the real src/projections.py engine on Vaastav data via the adapter.
    Returns a DataFrame with the same columns as project_gw (simple proxy) so
    the simulator can drop it in interchangeably.
    """
    elements, fixtures, teams_short, history_df = build_engine_inputs(target_gw, season, horizon)

    # Patch the engine to use our in-memory history (it normally loads from disk)
    orig_load = engine_projections.load_latest_player_gw_history
    engine_projections.load_latest_player_gw_history = lambda **kw: history_df
    try:
        proj = engine_projections.project_elements_next_gws(
            elements=elements,
            fixtures=fixtures,
            teams_short_map=teams_short,
            gw_start=target_gw,
            horizon_gws=horizon,
        )
    finally:
        engine_projections.load_latest_player_gw_history = orig_load

    # Reshape engine output -> simulator schema (player_id, name, pos, team, price_m, xpts, fixture_count)
    teams_full = load_teams(season)
    team_name_by_id = dict(zip(teams_full["id"], teams_full["name"]))

    if "pos" in proj.columns:
        pos_col = proj["pos"]
    else:
        pos_col = proj["element_type"].map({1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"})

    out = pd.DataFrame({
        "player_id": proj["id"].astype(int),
        "name": proj["web_name"],
        "pos": pos_col.values,
        "team": proj["team"].map(team_name_by_id).values,
        "price_m": (pd.to_numeric(proj["now_cost"], errors="coerce") / 10.0).values,
        "xpts": pd.to_numeric(proj.get(f"xpts_gw{target_gw}"), errors="coerce").fillna(0).values,
        "fixture_count": 1,
        "ppg": pd.to_numeric(proj.get("points_per_game"), errors="coerce").fillna(0).values,
        "samples": 5,
    })
    return out


# ---------- squad ops ----------

def pick_starting_xi(squad_proj: pd.DataFrame) -> pd.DataFrame:
    """Pick best 11 respecting formation bounds. squad_proj has player_id, pos, xpts."""
    s = squad_proj.sort_values("xpts", ascending=False).copy()
    s["start"] = False

    by_pos = {p: s[s["pos"] == p].copy() for p in SQUAD_SHAPE}

    # Take minimum required per position first
    starters = []
    for pos, (lo, hi) in FORMATION_BOUNDS.items():
        pool = by_pos[pos].sort_values("xpts", ascending=False)
        picks = pool.head(lo)
        starters.append(picks)
    starting = pd.concat(starters, ignore_index=False)

    # Fill remaining 11 - currently_selected slots greedily across MID/DEF/FWD
    remaining_slots = 11 - len(starting)
    candidates = s[~s.index.isin(starting.index) & (s["pos"] != "GKP")].copy()
    # Respect max bounds
    bench_caps = {pos: hi - lo for pos, (lo, hi) in FORMATION_BOUNDS.items()}
    bench_used = {pos: 0 for pos in bench_caps}
    extra_idx = []
    for idx, row in candidates.sort_values("xpts", ascending=False).iterrows():
        if remaining_slots <= 0:
            break
        pos = row["pos"]
        if bench_used[pos] < bench_caps.get(pos, 0):
            extra_idx.append(idx)
            bench_used[pos] += 1
            remaining_slots -= 1

    final_starting = pd.concat([starting, s.loc[extra_idx]], ignore_index=False)
    return final_starting


def pick_captain(starting: pd.DataFrame) -> int:
    """Highest xPts starter, weighted by position (favor attackers)."""
    s = starting.copy()
    s["_cap_score"] = s["xpts"] * s["pos"].map(CAPTAIN_POSITION_MULT).fillna(1.0)
    return int(s.sort_values("_cap_score", ascending=False).iloc[0]["player_id"])


def suggest_transfer(
    squad: pd.DataFrame,
    market: pd.DataFrame,
    bank_m: float,
    min_gain: float = 0.6,
) -> dict | None:
    """
    Simple 1-for-1 transfer: find the worst-xPts player in squad and swap for the
    best available not-in-squad player in same position within budget.
    Returns dict {sell_id, buy_id, gain} or None.
    """
    if squad.empty:
        return None
    owned = set(squad["player_id"].astype(int).tolist())
    candidates = []
    for _, sell in squad.iterrows():
        pos = sell["pos"]
        sell_value = float(sell["price_m"])
        budget_for_buy = bank_m + sell_value
        pool = market[
            (market["pos"] == pos)
            & (~market["player_id"].isin(owned))
            & (market["price_m"] <= budget_for_buy)
        ]
        if pool.empty:
            continue
        best = pool.sort_values("xpts", ascending=False).iloc[0]
        gain = float(best["xpts"]) - float(sell["xpts"])
        if gain > min_gain:
            candidates.append({
                "sell_id": int(sell["player_id"]),
                "sell_name": sell["name"],
                "buy_id": int(best["player_id"]),
                "buy_name": best["name"],
                "pos": pos,
                "gain": gain,
                "buy_price": float(best["price_m"]),
                "sell_price": sell_value,
            })
    if not candidates:
        return None
    return max(candidates, key=lambda x: x["gain"])


# ---------- initial squad ----------

def auto_pick_initial_squad(gw1_projection: pd.DataFrame, budget: float = INITIAL_BUDGET_M) -> pd.DataFrame:
    """
    Greedy initial squad picker. Strategy: fill cheapest positions first (DEF/GKP)
    with affordable players to leave room for premiums in MID/FWD.
    """
    chosen = []
    remaining = float(budget)

    # Order: GKP -> DEF -> FWD -> MID (MID last to spend leftover on premiums)
    order = [("GKP", 2), ("DEF", 5), ("FWD", 3), ("MID", 5)]
    total_slots = sum(c for _, c in order)

    for idx_pos, (pos, count) in enumerate(order):
        remaining_pos_slots = sum(c for p, c in order[idx_pos + 1:])
        # Reserve at least 4.0m per future slot
        reserve = 4.0 * remaining_pos_slots
        budget_for_this_pos = remaining - reserve
        # Per-slot budget for this position
        per_slot_budget = budget_for_this_pos / max(count, 1)

        pool = gw1_projection[gw1_projection["pos"] == pos].sort_values("xpts", ascending=False)
        picks = []
        # First pass: stay within per-slot budget on average
        spent_in_pos = 0.0
        for _, row in pool.iterrows():
            if len(picks) >= count:
                break
            slots_left = count - len(picks)
            avg_budget_left = (budget_for_this_pos - spent_in_pos) / max(slots_left, 1)
            if row["price_m"] <= avg_budget_left * 1.5:  # allow 50% over per-slot budget for stars
                picks.append(row)
                spent_in_pos += float(row["price_m"])

        # Fallback: fill with cheapest available
        if len(picks) < count:
            picked_ids = {int(p["player_id"]) for p in picks}
            cheap = pool[~pool["player_id"].isin(picked_ids)].sort_values("price_m", ascending=True)
            for _, row in cheap.iterrows():
                if len(picks) >= count:
                    break
                picks.append(row)
                spent_in_pos += float(row["price_m"])

        remaining -= spent_in_pos
        chosen.extend(picks)

    return pd.DataFrame(chosen)


# ---------- chip planning ----------

def plan_chips(
    season: str,
    start_gw: int,
    end_gw: int,
    teams: pd.DataFrame,
    fixtures_all: pd.DataFrame,
    use_engine: bool,
    full_history: pd.DataFrame,
) -> dict:
    """
    Pre-scan GWs to identify best chip moments. Returns:
        {"wildcard": gw, "triple_captain": gw, "bench_boost": gw, "free_hit": gw}
    Looks at fixture structure (single/double/blank GWs) for each GW in the range.
    """
    # Per-GW fixture stats
    gw_stats = []
    for gw in range(start_gw, end_gw + 1):
        fx_gw = fixtures_all[pd.to_numeric(fixtures_all["event"], errors="coerce") == gw]
        teams_playing = set()
        for _, fx in fx_gw.iterrows():
            teams_playing.add(int(fx["team_h"]))
            teams_playing.add(int(fx["team_a"]))
        fixture_count_by_team = {}
        for _, fx in fx_gw.iterrows():
            for t in (int(fx["team_h"]), int(fx["team_a"])):
                fixture_count_by_team[t] = fixture_count_by_team.get(t, 0) + 1
        n_doubles = sum(1 for c in fixture_count_by_team.values() if c >= 2)
        n_blanks = 20 - len(teams_playing)  # 20 PL teams
        gw_stats.append({
            "gw": gw,
            "n_fixtures": len(fx_gw),
            "n_doubles": n_doubles,
            "n_blanks": n_blanks,
            "teams_doubling": [t for t, c in fixture_count_by_team.items() if c >= 2],
        })
    gw_df = pd.DataFrame(gw_stats)

    chips = {"wildcard": None, "triple_captain": None, "bench_boost": None, "free_hit": None}

    # Free Hit: biggest blank GW (most teams without fixtures)
    blanks = gw_df[gw_df["n_blanks"] > 0].sort_values("n_blanks", ascending=False)
    if not blanks.empty:
        chips["free_hit"] = int(blanks.iloc[0]["gw"])

    # Bench Boost: biggest double GW (most teams with 2 fixtures)
    doubles = gw_df[gw_df["n_doubles"] > 0].sort_values("n_doubles", ascending=False)
    if not doubles.empty:
        chips["bench_boost"] = int(doubles.iloc[0]["gw"])

    # Triple Captain: pick a DIFFERENT DGW from BB if possible
    if not doubles.empty:
        for _, row in doubles.iterrows():
            gw_cand = int(row["gw"])
            if gw_cand != chips["bench_boost"]:
                chips["triple_captain"] = gw_cand
                break
        if chips["triple_captain"] is None and not doubles.empty:
            chips["triple_captain"] = int(doubles.iloc[0]["gw"])

    # If still no DGW found, fall back to "biggest projected captain GW" — use a GW where Haaland-tier
    # players have good fixtures. Heuristic: GW with most fixtures (proxy for opportunity).
    if chips["triple_captain"] is None:
        big_gw = gw_df.sort_values("n_fixtures", ascending=False).iloc[0]
        chips["triple_captain"] = int(big_gw["gw"])
    if chips["bench_boost"] is None:
        # Use a different big GW than TC
        big = gw_df.sort_values("n_fixtures", ascending=False)
        for _, row in big.iterrows():
            if int(row["gw"]) != chips["triple_captain"]:
                chips["bench_boost"] = int(row["gw"])
                break

    # Wildcard: roughly mid-season. Pick GW 8-10 for first-half reset.
    wc_candidates = [g for g in range(max(start_gw, 7), min(end_gw, 11) + 1)]
    if wc_candidates:
        chips["wildcard"] = wc_candidates[0] + 1  # GW8 if start>=7

    return chips


# ---------- main loop ----------

def run_backtest(
    season: str,
    start_gw: int,
    end_gw: int,
    initial_squad_csv: str | None,
    min_transfer_gain: float,
    use_engine: bool = False,
    enable_chips: bool = False,
    enable_can_bonus: bool = False,
) -> pd.DataFrame:
    teams = load_teams(season)
    fixtures_all = load_fixtures(season)

    # Build full history once for projection step (we'll slice it per GW)
    full_history = player_actuals_through(end_gw, season)

    # Initial squad: from CSV or auto-picked using GW1 projection (no priors)
    if initial_squad_csv:
        squad_ids = pd.read_csv(initial_squad_csv)["player_id"].astype(int).tolist()
        # Get latest metadata for those players
        meta = full_history[full_history["player_id"].isin(squad_ids)].sort_values("gw").groupby("player_id").tail(1)
        squad = meta[["player_id", "name", "pos", "team", "price_m"]].reset_index(drop=True)
        bank_m = INITIAL_BUDGET_M - float(squad["price_m"].sum())
        if bank_m < 0:
            print(f"⚠️  Initial squad over budget by £{-bank_m:.1f}m — continuing anyway")
            bank_m = 0.0
    else:
        gw1_hist = full_history[full_history["gw"] == 1]
        # Build a "pre-season" projection using only price + position (no past data)
        # Use Vaastav's xP for GW1 as a reasonable pre-season proxy
        gw1_proj = gw1_hist[["player_id", "name", "pos", "team", "price_m"]].copy()
        gw1_proj["xpts"] = pd.to_numeric(gw1_hist["xP"], errors="coerce").fillna(0).values
        squad = auto_pick_initial_squad(gw1_proj, INITIAL_BUDGET_M)
        squad = squad[["player_id", "name", "pos", "team", "price_m"]].reset_index(drop=True)
        bank_m = INITIAL_BUDGET_M - float(squad["price_m"].sum())
        print(f"Auto-picked initial squad ({len(squad)} players, £{squad['price_m'].sum():.1f}m, bank £{bank_m:.1f}m)")
        if bank_m < 0:
            print(f"  ⚠️  Over budget by £{-bank_m:.1f}m — continuing for now (fix the picker)")
            bank_m = 0.0

    free_transfers = 1
    total_points = 0
    total_hits = 0
    log = []

    chip_plan = {}
    if enable_chips:
        chip_plan = plan_chips(season, start_gw, end_gw, teams, fixtures_all, use_engine, full_history)
        print(f"Chip plan: {chip_plan}")

    for gw in range(start_gw, end_gw + 1):
        # CAN bonus: 5 FT at GW16 (real FPL gave this in 2025/26 for AFCON)
        if enable_can_bonus and gw == CAN_BONUS_GW:
            free_transfers = CAN_BONUS_FT
            print(f"  GW{gw}: CAN bonus applied → {free_transfers} free transfers")

        chip_this_gw = None
        for chip, planned_gw in chip_plan.items():
            if planned_gw == gw:
                chip_this_gw = chip
                break
        if use_engine:
            market = project_gw_engine(gw, season=season, horizon=3)
        else:
            history_before = full_history[full_history["gw"] < gw]
            market = project_gw(gw, history_before, fixtures_all, teams)

        if market.empty or "xpts" not in market.columns:
            print(f"  ! GW{gw}: empty market, skipping")
            continue

        # Drop stale xpts/fixture_count if present, then merge fresh market values
        squad_clean = squad.drop(columns=[c for c in ("xpts", "fixture_count") if c in squad.columns])
        squad_proj = squad_clean.merge(market[["player_id", "xpts", "fixture_count"]], on="player_id", how="left")
        squad_proj["xpts"] = squad_proj["xpts"].fillna(0)
        squad_proj["fixture_count"] = squad_proj["fixture_count"].fillna(0).astype(int)

        hit_cost = 0
        transfer = None
        free_hit_temp_squad = None

        # --- Chip handling ---
        if chip_this_gw == "wildcard":
            # Rebuild squad from scratch using full current budget (squad value + bank)
            squad_value = float(squad["price_m"].sum()) + bank_m
            new_squad = auto_pick_initial_squad(market.rename(columns={"name": "name"}), squad_value)
            new_squad = new_squad[["player_id", "name", "pos", "team", "price_m"]].reset_index(drop=True)
            squad = new_squad
            bank_m = squad_value - float(squad["price_m"].sum())
            # No transfer cost, no FT consumed
        elif chip_this_gw == "free_hit":
            # Temporary squad for this GW only — pick best 15 within (current value + bank)
            squad_value = float(squad["price_m"].sum()) + bank_m
            fh_squad = auto_pick_initial_squad(market, squad_value)
            free_hit_temp_squad = fh_squad[["player_id", "name", "pos", "team", "price_m"]].reset_index(drop=True)
        elif chip_this_gw is None or chip_this_gw in ("triple_captain", "bench_boost"):
            # Normal transfer flow (TC and BB don't affect transfers)
            transfer = suggest_transfer(squad_proj, market, bank_m, min_gain=min_transfer_gain)
            if transfer:
                sell = squad[squad["player_id"] == transfer["sell_id"]].iloc[0]
                buy_row = market[market["player_id"] == transfer["buy_id"]].iloc[0]
                squad = squad[squad["player_id"] != transfer["sell_id"]].copy()
                squad = pd.concat([squad, pd.DataFrame([{
                    "player_id": int(buy_row["player_id"]),
                    "name": buy_row["name"],
                    "pos": buy_row["pos"],
                    "team": buy_row["team"],
                    "price_m": float(buy_row["price_m"]),
                }])], ignore_index=True)
                bank_m += transfer["sell_price"] - transfer["buy_price"]
                if free_transfers > 0:
                    free_transfers -= 1
                else:
                    hit_cost = 4
                    total_hits += 4

        # Use free-hit temp squad for this GW if active, otherwise actual squad
        active_squad = free_hit_temp_squad if free_hit_temp_squad is not None else squad

        # Re-project for final pick (drop stale xpts first)
        active_clean = active_squad.drop(columns=[c for c in ("xpts",) if c in active_squad.columns])
        squad_proj = active_clean.merge(market[["player_id", "xpts"]], on="player_id", how="left")
        squad_proj["xpts"] = squad_proj["xpts"].fillna(0)

        # Captain + starting XI
        starting = pick_starting_xi(squad_proj)
        captain_id = pick_captain(starting)

        # Actual points
        actuals = player_actuals_at(gw, season)[["player_id", "total_points", "minutes"]]
        # For BB: score all 15 instead of just XI
        score_squad = squad_proj if chip_this_gw == "bench_boost" else starting
        squad_actuals = score_squad.merge(actuals, on="player_id", how="left")
        squad_actuals["total_points"] = squad_actuals["total_points"].fillna(0)

        captain_pts = float(squad_actuals.loc[squad_actuals["player_id"] == captain_id, "total_points"].iloc[0]) if captain_id in squad_actuals["player_id"].values else 0.0
        # Captain multiplier: TC = 3x (so add 2x on top), regular = 2x (so add 1x on top)
        cap_multiplier_extra = 2 if chip_this_gw == "triple_captain" else 1
        gw_points = float(squad_actuals["total_points"].sum()) + cap_multiplier_extra * captain_pts - hit_cost

        # Free transfer rollover
        free_transfers = min(2, free_transfers + 1) if not transfer else free_transfers + 1
        free_transfers = min(2, free_transfers)

        total_points += gw_points
        log.append({
            "gw": gw,
            "points": gw_points,
            "captain": squad_actuals.loc[squad_actuals["player_id"] == captain_id, "name"].iloc[0] if captain_id in squad_actuals["player_id"].values else "",
            "captain_pts": captain_pts,
            "transfer_in": transfer["buy_name"] if transfer else "",
            "transfer_out": transfer["sell_name"] if transfer else "",
            "hit": hit_cost,
            "chip": chip_this_gw or "",
            "bank": round(bank_m, 1),
            "ft": free_transfers,
            "total": total_points,
        })

    return pd.DataFrame(log)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2025-26")
    ap.add_argument("--start", type=int, default=2, help="Start GW (inclusive)")
    ap.add_argument("--end", type=int, default=29, help="End GW (inclusive)")
    ap.add_argument("--initial-squad", default=None, help="CSV path with one column player_id")
    ap.add_argument("--min-gain", type=float, default=0.6, help="Minimum xPts gain to make a transfer")
    ap.add_argument("--out", default="data/backtest/results.csv")
    ap.add_argument("--use-engine", action="store_true",
                    help="Use the real src/projections.py engine (slower) instead of the simple proxy")
    ap.add_argument("--chips", action="store_true",
                    help="Enable chip strategy (WC, FH, BB, TC)")
    ap.add_argument("--can-bonus", action="store_true",
                    help="Apply CAN/AFCON 5-FT bonus at GW16 (2025/26 season)")
    args = ap.parse_args()

    log = run_backtest(
        args.season, args.start, args.end, args.initial_squad, args.min_gain,
        args.use_engine, args.chips, args.can_bonus,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    log.to_csv(out, index=False)

    print(f"\n=== Backtest {args.season} GW{args.start}–{args.end} ===")
    print(log.to_string(index=False))
    print(f"\nTotal points: {log['total'].iloc[-1]:.0f}")
    print(f"Total hits: -{log['hit'].sum()}")
    print(f"Avg points/GW: {log['points'].mean():.1f}")
    print(f"Captain hit (>=10 pts): {(log['captain_pts'] >= 10).sum()}/{len(log)} ({(log['captain_pts'] >= 10).mean()*100:.0f}%)")
    print(f"\nResults written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
