"""
Preset-driven wildcard draft (spec 4.4 / 4.5 / 4.8,
docs/superpowers/specs/2026-10-22-wildcard-v2-design.md).

Two stages on the horizon scalar objective:
1. XI: pins first, then the cheapest available body per slot of the preset's
   formation, then greedy upgrades under the team cap, the defensive cap,
   the same-team defender penalty, the premium count and (Gems) the
   ownership floor.
2. Bench: chip_bench.fill_bench by the preset's bench mode under the bench
   budget cap. Leftover money then goes back into one more XI upgrade pass.

The legacy single-stage build stays in optimizer.build_chip_squad for every
caller that passes no preset.
"""
from __future__ import annotations

import pandas as pd

from . import chip_bench, config


def to_number(value, default=0.0):
    try:
        if value is None or (isinstance(value, float) and value != value):
            return float(default)
        return float(value)
    except Exception:
        return float(default)

POS_ORDER = ["GKP", "DEF", "MID", "FWD"]
DEFENSIVE = {"GKP", "DEF"}


def shrink_small_sample_scores(market):
    """Teams with fewer than CHIP_WILDCARD_MIN_TEAM_MATCHES rated matches have
    their chip_score pulled toward the price prior (median chip_score of
    same-position players within ±0.5m) by the missing share. Unknown match
    counts (NaN) are left alone: no evidence either way."""
    out = market.copy()
    if "team_rated_matches" not in out.columns:
        return out
    min_m = float(config.CHIP_WILDCARD_MIN_TEAM_MATCHES)
    rated = pd.to_numeric(out["team_rated_matches"], errors="coerce")
    thin = rated.notna() & (rated < min_m)
    if not thin.any():
        return out
    for idx in out.index[thin]:
        row = out.loc[idx]
        peers = out[
            (out["pos"] == row["pos"])
            & ((out["price_m"] - float(row["price_m"])).abs() <= 0.5 + 1e-9)
            & ~thin
        ]
        prior = float(peers["chip_score"].median()) if len(peers) else float(row["chip_score"])
        share = max(0.0, min(1.0, float(rated.loc[idx]) / min_m))
        out.loc[idx, "chip_score"] = prior + (float(row["chip_score"]) - prior) * share
    return out


def _is_premium(row, floor, positions):
    return float(row["price_m"]) >= float(floor) and str(row["pos"]) in positions


def _defensive_count(rows, team, skip_id=None):
    return sum(
        1 for r in rows
        if str(r["pos"]) in DEFENSIVE and int(r["team"]) == int(team) and int(r["id"]) != skip_id
    )


def _team_count(rows, team, skip_id=None):
    return sum(1 for r in rows if int(r["team"]) == int(team) and int(r["id"]) != skip_id)


def _low_owned_count(rows, max_pct, skip_id=None):
    return sum(
        1 for r in rows
        if float(to_number(r.get("selected_by_percent"), 100.0)) < max_pct and int(r["id"]) != skip_id
    )


def build_preset_squad(market, preset, budget_m, pinned_ids=None, excluded_ids=None):
    """market: optimizer._prepare_chip_market output (differential already
    applied). Returns the optimizer result dict (see build_chip_squad)."""
    notes: list[str] = []
    pins_conflict: list[int] = []
    pins_conflict_reasons: dict[int, str] = {}
    pinned = list(dict.fromkeys(int(x) for x in (pinned_ids or [])))  # dedupe, keep order
    excluded = {int(x) for x in (excluded_ids or [])}

    def conflict(pid, reason):
        if pid not in pins_conflict:
            pins_conflict.append(pid)
        pins_conflict_reasons.setdefault(pid, reason)
    budget_m = float(to_number(budget_m, 100.0))

    if "start_share" not in market.columns:
        raise KeyError("start_share")

    market = shrink_small_sample_scores(market)
    market = market[~market["id"].astype(int).isin(excluded)].copy()
    market = market.sort_values(["chip_score", "price_m"], ascending=[False, True]).reset_index(drop=True)

    premium_floor = float(config.CHIP_WILDCARD_PREMIUM_CAPTAIN_PRICE_FLOOR)
    premium_pos = list(config.CHIP_WILDCARD_PREMIUM_CAPTAIN_POSITIONS)
    prem_exact = preset.get("premiums_exact")
    prem_max = preset.get("premiums_max")
    prem_min = int(prem_exact) if prem_exact is not None else 0
    prem_cap = int(prem_exact) if prem_exact is not None else (int(prem_max) if prem_max is not None else 99)
    max_per_team = int(preset.get("max_per_team") or config.CHIP_MAX_PER_TEAM or 3)
    max_def = preset.get("max_def_per_team")
    max_def = int(max_def) if max_def is not None else 99
    elite_rank = int(config.CHIP_WILDCARD_ELITE_DEF_RANK)
    pen_table = list(config.CHIP_WILDCARD_SAME_TEAM_DEF_PENALTY or [0.0])
    gem_max_pct = float(config.CHIP_WILDCARD_GEM_OWNERSHIP_MAX)
    gem_min_xi = int(preset.get("gem_min_xi") or 0)
    xi_share = float(preset.get("xi_start_share") or config.CHIP_XI_START_SHARE)

    d, m, f = (int(x) for x in preset["formation"])
    xi_need = {"GKP": 1, "DEF": d, "MID": m, "FWD": f}
    bench_need = {"GKP": 1, "DEF": 5 - d, "MID": 5 - m, "FWD": 3 - f}

    avail = chip_bench.availability_mask(market, xi_share)
    xi_pool = market[avail].copy()

    def elite(team):
        r = market.loc[market["team"] == int(team), "team_def_rank"] if "team_def_rank" in market.columns else pd.Series(dtype=float)
        r = pd.to_numeric(r, errors="coerce").dropna()
        return bool(len(r)) and int(r.iloc[0]) <= elite_rank

    def def_cap_ok(rows, cand, skip_id=None):
        if str(cand["pos"]) not in DEFENSIVE or elite(cand["team"]):
            return True
        return _defensive_count(rows, cand["team"], skip_id) < max_def

    def same_team_penalty(rows, cand, skip_id=None):
        if str(cand["pos"]) not in DEFENSIVE:
            return 0.0
        n = _defensive_count(rows, cand["team"], skip_id)
        return float(pen_table[min(n, len(pen_table) - 1)])

    # ---- stage 1a: pins ----
    # A pin is honoured when the squad can stay legal with it: at most 15,
    # at most 2/5/5/3 per position (XI slots first, then bench slots), under
    # the team cap and the defensive cap. Anything else is dropped and named
    # in pins_conflict with a reason: "shape", "team_cap", "def_cap", "unknown".
    xi_rows: list[pd.Series] = []
    pinned_bench: list[pd.Series] = []
    full_shape = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    for pid in pinned:
        hit = market[market["id"].astype(int) == pid]
        if hit.empty:
            notes.append(f"pin {pid} not in market (excluded, unavailable or unknown)")
            conflict(pid, "unknown")
            continue
        row = hit.iloc[0].copy()
        pos = str(row["pos"])
        if len(xi_rows) + len(pinned_bench) >= 15:
            conflict(pid, "shape")
            continue
        in_pos = sum(1 for r in xi_rows + pinned_bench if str(r["pos"]) == pos)
        if in_pos >= full_shape[pos]:
            conflict(pid, "shape")
            continue
        all_rows = xi_rows + pinned_bench
        if _team_count(all_rows, row["team"]) >= max_per_team:
            conflict(pid, "team_cap")
            continue
        if not def_cap_ok(all_rows, row):
            conflict(pid, "def_cap")
            continue
        placed_xi = sum(1 for r in xi_rows if str(r["pos"]) == pos)
        if placed_xi < xi_need[pos]:
            xi_rows.append(row)
        else:
            # XI slots for this position are full: the pin sits on the bench.
            bench_need[pos] -= 1
            pinned_bench.append(row)
    pinned = [int(r["id"]) for r in xi_rows + pinned_bench]

    # ---- stage 1b: cheapest available body per remaining XI slot ----
    pinned_xi = [r.copy() for r in xi_rows]

    def remaining_pool(pos):
        ids = {int(r["id"]) for r in xi_rows} | {int(r["id"]) for r in pinned_bench}
        return xi_pool[(xi_pool["pos"] == pos) & ~xi_pool["id"].astype(int).isin(ids)]

    def cheapest_fill():
        """Reset the XI to the pins and fill every open slot with the cheapest
        available body under the caps. Returns an error reason or None."""
        xi_rows[:] = [r.copy() for r in pinned_xi]
        for pos in POS_ORDER:
            while sum(1 for r in xi_rows if str(r["pos"]) == pos) < xi_need[pos]:
                pool = remaining_pool(pos).sort_values(["price_m", "chip_score"], ascending=[True, False], kind="mergesort")
                pick = None
                for _, cand in pool.iterrows():
                    if _team_count(xi_rows, cand["team"]) >= max_per_team:
                        continue
                    if not def_cap_ok(xi_rows, cand):
                        continue
                    if _is_premium(cand, premium_floor, premium_pos) and sum(
                        1 for r in xi_rows if _is_premium(r, premium_floor, premium_pos)
                    ) >= prem_cap:
                        continue
                    pick = cand
                    break
                if pick is None:
                    return f"Not enough available {pos} players for the XI."
                xi_rows.append(pick.copy())
        return None

    fill_error = cheapest_fill()
    if fill_error:
        return {"ok": False, "reason": fill_error, "squad_df": None}

    # ---- bench reserve: cheapest available body per bench slot ----
    bench_avail = market[chip_bench.availability_mask(market, config.CHIP_BENCH_START_SHARE)]
    reserve = 0.0
    for pos, n in bench_need.items():
        if n <= 0:
            continue
        prices = bench_avail[bench_avail["pos"] == pos]["price_m"].nsmallest(n)
        reserve += float(prices.sum()) if len(prices) == n else float(market[market["pos"] == pos]["price_m"].nsmallest(n).sum())
    pinned_bench_cost = sum(float(r["price_m"]) for r in pinned_bench)

    def xi_cost():
        return sum(float(r["price_m"]) for r in xi_rows)

    pinned_set = set(pinned)

    def upgrade_pass(xi_budget, gem_floor):
        """Greedy: best score delta per swap under every constraint."""
        for _ in range(int(config.CHIP_UPGRADE_MAX_ITERS or 320)):
            left = xi_budget - xi_cost()
            if left <= 1e-9:
                return
            best = None
            for i, row in enumerate(xi_rows):
                if int(row["id"]) in pinned_set:
                    continue
                row_score = float(row["chip_score"])
                others = [r for j, r in enumerate(xi_rows) if j != i]
                pool = remaining_pool(str(row["pos"]))
                pool = pool[(pool["price_m"] <= float(row["price_m"]) + left + 1e-9) & (pool["chip_score"] > row_score)]
                for _, cand in pool.head(60).iterrows():
                    if _team_count(others, cand["team"]) >= max_per_team:
                        continue
                    if not def_cap_ok(others, cand):
                        continue
                    n_prem = sum(1 for r in others if _is_premium(r, premium_floor, premium_pos))
                    cand_prem = _is_premium(cand, premium_floor, premium_pos)
                    if cand_prem and n_prem >= prem_cap:
                        continue
                    if not cand_prem and _is_premium(row, premium_floor, premium_pos) and n_prem < prem_min:
                        continue  # would drop below the preset's premium floor
                    if gem_floor and not (float(to_number(cand.get("selected_by_percent"), 100.0)) < gem_max_pct):
                        if _low_owned_count(others, gem_max_pct) < gem_floor:
                            continue
                    adj = float(cand["chip_score"]) * (1.0 - same_team_penalty(others, cand))
                    delta = adj - row_score
                    if delta <= 1e-9:
                        continue
                    dcost = float(cand["price_m"]) - float(row["price_m"])
                    key = (delta, delta / (dcost + 0.05), -dcost)
                    if best is None or key > best[0]:
                        best = (key, i, cand)
                    break
            if best is None:
                return
            xi_rows[best[1]] = best[2].copy()

    def ensure_premiums(xi_budget):
        """Swap in premiums until prem_min is met, cheapest-upgrade first."""
        for _ in range(prem_min * 3 + 1):
            n = sum(1 for r in xi_rows if _is_premium(r, premium_floor, premium_pos))
            if n >= prem_min:
                return True
            left = xi_budget - xi_cost()
            best = None
            for i, row in enumerate(xi_rows):
                if int(row["id"]) in pinned_set or str(row["pos"]) not in premium_pos:
                    continue
                if _is_premium(row, premium_floor, premium_pos):
                    continue
                others = [r for j, r in enumerate(xi_rows) if j != i]
                pool = remaining_pool(str(row["pos"]))
                pool = pool[(pool["price_m"] >= premium_floor) & (pool["price_m"] <= float(row["price_m"]) + left + 1e-9)]
                for _, cand in pool.iterrows():
                    if _team_count(others, cand["team"]) >= max_per_team:
                        continue
                    gain = float(cand["chip_score"]) - float(row["chip_score"])
                    if best is None or gain > best[0]:
                        best = (gain, i, cand)
                    break
            if best is None:
                return False
            xi_rows[best[1]] = best[2].copy()
        return sum(1 for r in xi_rows if _is_premium(r, premium_floor, premium_pos)) >= prem_min

    gem_floor = gem_min_xi
    if gem_floor:
        n_low_market = int((xi_pool["selected_by_percent"] < gem_max_pct).sum()) if "selected_by_percent" in xi_pool.columns else 0
        if n_low_market < gem_floor:
            notes.append(f"gems: only {n_low_market} available players under {gem_max_pct:.0f}% ownership; floor relaxed")
            gem_floor = 0
    bench_cap = float(preset.get("bench_budget_max_m") or config.CHIP_WILDCARD_BENCH_BUDGET_MAX_M)
    gem_filter = None
    if gem_min_xi and "selected_by_percent" in market.columns:
        gem_filter = pd.to_numeric(market["selected_by_percent"], errors="coerce").fillna(100.0) < gem_max_pct

    # The reserve is the cheapest legal bench ignoring team caps; when the XI
    # has used a cap the real bench costs a little more, so widen the reserve
    # and rebuild until the bench completes.
    bench_df = None
    premium_ok = True
    for extra in (0.0, 1.0, 2.0, 3.5, 5.0):
        xi_budget = budget_m - reserve - extra - pinned_bench_cost
        if extra > 0.0:
            fill_error = cheapest_fill()
            if fill_error:
                return {"ok": False, "reason": fill_error, "squad_df": None}
        premium_ok = ensure_premiums(xi_budget)
        upgrade_pass(xi_budget, gem_floor)
        premium_ok = ensure_premiums(xi_budget) and premium_ok

        xi_df = pd.DataFrame(xi_rows).reset_index(drop=True)
        # The cap never undercuts the cheapest legal bench: fodder prices are what they are.
        bench_budget = max(min(bench_cap, budget_m - xi_cost()), reserve + extra) - pinned_bench_cost
        xi_plus_pinned = pd.concat([xi_df, pd.DataFrame(pinned_bench)], ignore_index=True) if pinned_bench else xi_df
        cand_bench, bench_notes = chip_bench.fill_bench(
            market, xi_plus_pinned, mode=str(preset.get("bench_mode") or "enablers"),
            budget_left_m=bench_budget, max_per_team=max_per_team, team_counts={}, gem_filter=gem_filter,
        )
        if len(cand_bench) == 4 - len(pinned_bench) and xi_cost() + float(cand_bench["price_m"].sum()) + pinned_bench_cost <= budget_m + 1e-9:
            bench_df = cand_bench
            notes.extend(bench_notes)
            break
    if bench_df is None:
        return {"ok": False, "reason": "Could not complete the bench under the budget.", "squad_df": None}
    if gem_floor and _low_owned_count(xi_rows, gem_max_pct) < gem_floor:
        notes.append("gems: ownership floor not reachable under budget and caps; relaxed")
    if not premium_ok:
        notes.append(f"premium structure ({prem_min}) could not be met under the budget")
    if pinned_bench:
        pb = pd.DataFrame(pinned_bench)
        pb["role"] = "pinned"
        bench_df = pd.concat([pb, bench_df], ignore_index=True)
    xi_df = pd.DataFrame(xi_rows).reset_index(drop=True)

    # ---- leftover money back into the XI ----
    bench_cost = float(bench_df["price_m"].sum())
    upgrade_pass(budget_m - bench_cost, gem_floor)
    n_prem_final = sum(1 for r in xi_rows if _is_premium(r, premium_floor, premium_pos))
    if n_prem_final < prem_min and not any("premium structure" in n for n in notes):
        notes.append(f"premium structure ({prem_min}) could not be met under the budget")
    xi_df = pd.DataFrame(xi_rows).reset_index(drop=True)
    xi_df["role"] = ["pinned" if int(i) in pinned_set else "xi" for i in xi_df["id"]]
    xi_df["is_xi"] = True
    bench_df["is_xi"] = False
    selected = pd.concat([xi_df, bench_df], ignore_index=True)
    selected["player_id"] = selected["id"].astype(int)
    selected["multiplier"] = 0
    selected["is_captain"] = False
    selected["is_vice_captain"] = False

    cost = float(selected["price_m"].sum())
    xi_score = float(xi_df["chip_score"].sum())
    bench_score = float(bench_df["chip_score"].sum())
    total = xi_score + float(config.CHIP_WILDCARD_BENCH_WEIGHT) * bench_score
    return {
        "ok": True,
        "reason": "Chip draft built successfully." if not notes else "Chip draft built with notes.",
        "preset": preset.get("name") or preset.get("label", "").lower() or None,
        "objective_score_col": None,
        "budget_m": round(budget_m, 2),
        "squad_cost_m": round(cost, 2),
        "remaining_budget_m": round(max(0.0, budget_m - cost), 2),
        "objective_score_total": round(total, 2),
        "xi_score_total": round(xi_score, 2),
        "bench_score_total": round(bench_score, 2),
        "xi_ids": [int(i) for i in xi_df["id"]],
        "bench_roles": {int(r["id"]): str(r["role"]) for _, r in bench_df.iterrows()},
        "pins_conflict": sorted(set(pins_conflict)),
        "pins_conflict_reasons": dict(pins_conflict_reasons),
        "notes": notes,
        "squad_df": selected,
    }
