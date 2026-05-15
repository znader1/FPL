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


DIFFICULTY_MULTIPLIER = {1: 1.25, 2: 1.12, 3: 1.0, 4: 0.88, 5: 0.75}
SQUAD_SHAPE = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
FORMATION_BOUNDS = {"GKP": (1, 1), "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3)}
INITIAL_BUDGET_M = 100.0

# Captaincy preference: heavily favor attackers since they have higher ceilings
CAPTAIN_POSITION_MULT = {"FWD": 1.16, "MID": 1.12, "DEF": 0.92, "GKP": 0.70}


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


# ---------- main loop ----------

def run_backtest(
    season: str,
    start_gw: int,
    end_gw: int,
    initial_squad_csv: str | None,
    min_transfer_gain: float,
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

    for gw in range(start_gw, end_gw + 1):
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

        # Transfer decision (1 transfer per GW max in Phase 1)
        transfer = suggest_transfer(squad_proj, market, bank_m, min_gain=min_transfer_gain)
        hit_cost = 0
        if transfer:
            sell = squad[squad["player_id"] == transfer["sell_id"]].iloc[0]
            # Get buy metadata
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

        # Re-project for final pick (drop stale xpts first)
        squad_clean = squad.drop(columns=[c for c in ("xpts",) if c in squad.columns])
        squad_proj = squad_clean.merge(market[["player_id", "xpts"]], on="player_id", how="left")
        squad_proj["xpts"] = squad_proj["xpts"].fillna(0)

        # Captain + starting XI
        starting = pick_starting_xi(squad_proj)
        captain_id = pick_captain(starting)

        # Actual points
        actuals = player_actuals_at(gw, season)[["player_id", "total_points", "minutes"]]
        starting_actuals = starting.merge(actuals, on="player_id", how="left")
        starting_actuals["total_points"] = starting_actuals["total_points"].fillna(0)
        captain_pts = float(starting_actuals.loc[starting_actuals["player_id"] == captain_id, "total_points"].iloc[0])
        gw_points = float(starting_actuals["total_points"].sum()) + captain_pts - hit_cost

        # Free transfer rollover
        free_transfers = min(2, free_transfers + 1) if not transfer else free_transfers + 1
        free_transfers = min(2, free_transfers)

        total_points += gw_points
        log.append({
            "gw": gw,
            "points": gw_points,
            "captain": starting_actuals.loc[starting_actuals["player_id"] == captain_id, "name"].iloc[0],
            "captain_pts": captain_pts,
            "transfer_in": transfer["buy_name"] if transfer else "",
            "transfer_out": transfer["sell_name"] if transfer else "",
            "hit": hit_cost,
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
    args = ap.parse_args()

    log = run_backtest(args.season, args.start, args.end, args.initial_squad, args.min_gain)

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
