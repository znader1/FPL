#!/usr/bin/env python3
"""
Backtest with agent memory + reflection enabled.

Same simulator as scripts/backtest_season.py but with three additions:
  1. Every decision (captain, transfer) is written to the memory store
  2. After actual points are scored, outcome_delta is filled in
  3. Every 4 GWs, the reflection agent runs and may add a new strategy rule

Usage:
  python scripts/backtest_with_memory.py --season 2025-26 --start 2 --end 29 \
    --use-engine --initial-squad data/backtest/my_gw1_squad.csv

Use --no-memory to disable memory (for A/B comparison against the same logic).
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env early so reflection_agent can hit Anthropic
def _load_env():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            v = v.strip().strip('"').strip("'")
            if k.strip() and k.strip() not in os.environ:
                os.environ[k.strip()] = v
_load_env()

from src.agent_memory import MemoryStore, Decision, find_similar_decisions, format_memory_context
from src.backtest_data import load_teams, load_fixtures, player_actuals_at, player_actuals_through
from scripts.backtest_season import (
    project_gw, project_gw_engine, pick_starting_xi, pick_captain,
    suggest_transfer, auto_pick_initial_squad,
    INITIAL_BUDGET_M, CAN_BONUS_GW, CAN_BONUS_FT,
)
from src.captain_advisor import pick_captain_id as advisor_pick_captain
from src.transfer_advisor import top_transfer as advisor_top_transfer


REFLECTION_EVERY_N_GWS = 4
ENTRY_ID_PLACEHOLDER = 1  # synthetic entry_id for backtest


def run_memory_backtest(
    season: str,
    start_gw: int,
    end_gw: int,
    initial_squad_csv: str | None,
    use_engine: bool,
    use_memory: bool,
    db_path: str,
    enable_can_bonus: bool = True,
    min_gain: float = 0.6,
) -> pd.DataFrame:

    teams = load_teams(season)
    fixtures_all = load_fixtures(season)
    full_history = player_actuals_through(end_gw, season)

    store = MemoryStore(db_path=db_path) if use_memory else None
    if store:
        # Fresh start: wipe existing decisions for this entry so backtests are reproducible
        with store._conn() as c:
            c.execute("DELETE FROM decisions WHERE entry_id = ?", (ENTRY_ID_PLACEHOLDER,))
            c.execute("DELETE FROM strategy_rules")

    # Build initial squad
    if initial_squad_csv:
        squad_ids = pd.read_csv(initial_squad_csv)["player_id"].astype(int).tolist()
        meta = (full_history[full_history["player_id"].isin(squad_ids)]
                .sort_values("gw").groupby("player_id").tail(1))
        squad = meta[["player_id", "name", "pos", "team", "price_m"]].reset_index(drop=True)
        bank_m = INITIAL_BUDGET_M - float(squad["price_m"].sum())
        if bank_m < 0:
            print(f"⚠️  Initial squad over budget by £{-bank_m:.1f}m")
            bank_m = 0.0
    else:
        gw1_hist = full_history[full_history["gw"] == 1]
        gw1_proj = gw1_hist[["player_id", "name", "pos", "team", "price_m"]].copy()
        gw1_proj["xpts"] = pd.to_numeric(gw1_hist["xP"], errors="coerce").fillna(0).values
        squad = auto_pick_initial_squad(gw1_proj, INITIAL_BUDGET_M)
        squad = squad[["player_id", "name", "pos", "team", "price_m"]].reset_index(drop=True)
        bank_m = max(0.0, INITIAL_BUDGET_M - float(squad["price_m"].sum()))

    free_transfers = 1
    total_points = 0.0
    log = []
    decision_id_map = {}  # gw → list of decision_ids to update with outcomes

    print(f"Memory: {'ON' if use_memory else 'OFF'}")
    print(f"Squad starting value: £{squad['price_m'].sum():.1f}m, bank £{bank_m:.1f}m")

    for gw in range(start_gw, end_gw + 1):
        if enable_can_bonus and gw == CAN_BONUS_GW:
            free_transfers = CAN_BONUS_FT

        # Project market
        if use_engine:
            market = project_gw_engine(gw, season=season, horizon=1)
        else:
            history_before = full_history[full_history["gw"] < gw]
            market = project_gw(gw, history_before, fixtures_all, teams)

        if market.empty or "xpts" not in market.columns:
            print(f"  ! GW{gw}: empty market, skipping")
            continue

        # Squad with projections
        squad_clean = squad.drop(columns=[c for c in ("xpts", "fixture_count") if c in squad.columns])
        squad_proj = squad_clean.merge(market[["player_id", "xpts", "fixture_count"]],
                                        on="player_id", how="left")
        squad_proj["xpts"] = squad_proj["xpts"].fillna(0)
        squad_proj["fixture_count"] = squad_proj["fixture_count"].fillna(0).astype(int)

        # --- Transfer decision (advisor-based, multi-GW horizon) ---
        # Build a tiny 3-GW horizon for the advisor
        horizon_proj = {gw: market}
        for fgw in range(gw + 1, min(gw + 3, end_gw + 1)):
            try:
                if use_engine:
                    horizon_proj[fgw] = project_gw_engine(fgw, season=season, horizon=1)
                else:
                    horizon_proj[fgw] = project_gw(fgw,
                        full_history[full_history["gw"] < fgw], fixtures_all, teams)
            except Exception:
                pass

        advisor_rec = advisor_top_transfer(
            squad=squad_proj, market=market, gw_projections=horizon_proj,
            current_gw=gw, bank_m=bank_m, horizon=3, min_gain=min_gain,
        )

        transfer = None
        hit_cost = 0
        if advisor_rec:
            transfer = {
                "sell_id": advisor_rec.sell_id, "sell_name": advisor_rec.sell_name,
                "buy_id": advisor_rec.buy_id, "buy_name": advisor_rec.buy_name,
                "gain": advisor_rec.expected_gain,
                "sell_price": advisor_rec.sell_price, "buy_price": advisor_rec.buy_price,
                "pos": advisor_rec.sell_pos,
            }
            sold = squad[squad["player_id"] == transfer["sell_id"]]
            buy_row = market[market["player_id"] == transfer["buy_id"]].iloc[0]
            squad = squad[squad["player_id"] != transfer["sell_id"]].copy()
            squad = pd.concat([squad, pd.DataFrame([{
                "player_id": int(buy_row["player_id"]), "name": buy_row["name"],
                "pos": buy_row["pos"], "team": buy_row["team"],
                "price_m": float(buy_row["price_m"]),
            }])], ignore_index=True)
            bank_m += transfer["sell_price"] - transfer["buy_price"]
            if free_transfers > 0:
                free_transfers -= 1
            else:
                hit_cost = 4

            # Record transfer decision in memory
            if store:
                t_id = store.add_decision(Decision(
                    entry_id=ENTRY_ID_PLACEHOLDER, gw=gw, agent_type="transfer",
                    decision={"sell": transfer["sell_name"], "buy": transfer["buy_name"],
                              "expected_gain": float(advisor_rec.expected_gain)},
                    context={"position": transfer["pos"],
                             "squad_value_m": float(squad["price_m"].sum()),
                             "bank_m": float(bank_m)},
                ))
                decision_id_map.setdefault(gw, []).append({
                    "id": t_id, "type": "transfer",
                    "expected": float(advisor_rec.expected_gain),
                    "sell_id": transfer["sell_id"], "buy_id": transfer["buy_id"],
                })

        # --- Captain decision (advisor) ---
        squad_clean = squad.drop(columns=[c for c in ("xpts",) if c in squad.columns])
        squad_proj = squad_clean.merge(market[["player_id", "xpts"]], on="player_id", how="left")
        squad_proj["xpts"] = squad_proj["xpts"].fillna(0)
        starting = pick_starting_xi(squad_proj)
        captain_id = advisor_pick_captain(starting)
        captain_row = starting[starting["player_id"] == captain_id].iloc[0]

        if store:
            cap_decision_id = store.add_decision(Decision(
                entry_id=ENTRY_ID_PLACEHOLDER, gw=gw, agent_type="captain",
                decision={"captain_id": int(captain_id), "captain_name": captain_row["name"],
                          "expected_xpts": float(captain_row["xpts"])},
                context={"position": captain_row["pos"],
                         "fixture_difficulty": int(captain_row.get("fixture_count", 1)),
                         "squad_value_m": float(squad["price_m"].sum())},
            ))
            decision_id_map.setdefault(gw, []).append({
                "id": cap_decision_id, "type": "captain",
                "expected": float(captain_row["xpts"]),
                "captain_id": int(captain_id),
            })

        # --- Actual scoring ---
        actuals = player_actuals_at(gw, season)[["player_id", "total_points", "minutes"]]
        starting_actuals = starting.merge(actuals, on="player_id", how="left")
        starting_actuals["total_points"] = starting_actuals["total_points"].fillna(0)
        captain_pts = float(starting_actuals.loc[
            starting_actuals["player_id"] == captain_id, "total_points"].iloc[0])
        gw_points = float(starting_actuals["total_points"].sum()) + captain_pts - hit_cost

        # --- Fill in outcomes in memory ---
        if store and gw in decision_id_map:
            for entry in decision_id_map[gw]:
                if entry["type"] == "captain":
                    # Delta = (actual captain pts - expected pts)
                    delta = captain_pts - entry["expected"]
                    notes = f"{captain_row['name']} got {captain_pts:.0f} (expected {entry['expected']:.1f})"
                    store.update_outcome(entry["id"], {"actual_points": captain_pts},
                                         delta=delta, notes=notes)
                elif entry["type"] == "transfer":
                    # Delta = (buy actual - sell actual). Look up actual points for both.
                    sell_actual = float(actuals[actuals["player_id"] == entry["sell_id"]]["total_points"].sum() or 0)
                    buy_actual = float(actuals[actuals["player_id"] == entry["buy_id"]]["total_points"].sum() or 0)
                    delta = buy_actual - sell_actual
                    notes = f"Bought {buy_actual:.0f} pts, sold {sell_actual:.0f} pts"
                    store.update_outcome(entry["id"], {
                        "sell_actual": sell_actual, "buy_actual": buy_actual,
                    }, delta=delta, notes=notes)

        # --- FT rollover ---
        free_transfers = min(2, free_transfers + 1) if not transfer else min(2, free_transfers + 1)
        total_points += gw_points

        log.append({
            "gw": gw, "points": gw_points, "captain": captain_row["name"],
            "captain_pts": captain_pts,
            "transfer_in": transfer["buy_name"] if transfer else "",
            "transfer_out": transfer["sell_name"] if transfer else "",
            "hit": hit_cost, "bank": round(bank_m, 1),
            "ft": free_transfers, "total": total_points,
        })

        # --- Reflection (every N GWs) ---
        if store and gw > start_gw and (gw - start_gw + 1) % REFLECTION_EVERY_N_GWS == 0:
            try:
                from agents.reflection_agent import run_reflection
                window_lo = max(start_gw, gw - REFLECTION_EVERY_N_GWS + 1)
                result = run_reflection(
                    store=store, entry_id=ENTRY_ID_PLACEHOLDER,
                    gw_window=(window_lo, gw), verbose=True,
                )
                if result and result.get("rule"):
                    print(f"  [reflection GW{window_lo}-{gw}] new rule: {result['rule']}")
            except Exception as e:
                print(f"  [reflection failed] {e}")

    return pd.DataFrame(log), store


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2025-26")
    ap.add_argument("--start", type=int, default=2)
    ap.add_argument("--end", type=int, default=29)
    ap.add_argument("--initial-squad", default=None)
    ap.add_argument("--use-engine", action="store_true")
    ap.add_argument("--no-memory", action="store_true",
                    help="Disable memory + reflection (for A/B comparison)")
    ap.add_argument("--db", default="data/agent_memory/decisions.db")
    ap.add_argument("--out", default="data/backtest/results_with_memory.csv")
    args = ap.parse_args()

    log_df, store = run_memory_backtest(
        season=args.season, start_gw=args.start, end_gw=args.end,
        initial_squad_csv=args.initial_squad, use_engine=args.use_engine,
        use_memory=not args.no_memory, db_path=args.db,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    log_df.to_csv(out, index=False)

    print(f"\n=== Backtest {args.season} GW{args.start}-{args.end} (memory={'ON' if not args.no_memory else 'OFF'}) ===")
    print(f"Total points: {log_df['total'].iloc[-1]:.0f}")
    print(f"Avg points/GW: {log_df['points'].mean():.1f}")
    print(f"Captain hit (≥10 pts): "
          f"{(log_df['captain_pts'] >= 10).sum()}/{len(log_df)} "
          f"({(log_df['captain_pts'] >= 10).mean()*100:.0f}%)")
    print(f"Results written to {out}")

    if store:
        summary = store.summary()
        print(f"\nMemory summary: {summary}")
        rules = store.get_active_rules()
        if rules:
            print(f"\nLearned rules:")
            for r in rules:
                print(f"  - {r['rule_text']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
