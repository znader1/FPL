import re

import pandas as pd

from . import config


VALID_FORMATIONS = [
    (3, 4, 3),
    (3, 5, 2),
    (4, 3, 3),
    (4, 4, 2),
    (4, 5, 1),
    (5, 3, 2),
    (5, 4, 1),
]


CAPTAIN_POSITION_MULTIPLIER = dict(config.CAPTAIN_POSITION_MULTIPLIER)
CHIP_POS_ORDER = ["GKP", "DEF", "MID", "FWD"]


def to_number(value, default=0.0):
    """Safely parse value to float, returning default on invalid input."""
    try:
        parsed = float(pd.to_numeric(value, errors="coerce"))
        if pd.isna(parsed):
            return float(default)
        return float(parsed)
    except Exception:
        return float(default)


def _chip_shape(shape=None):
    """Return normalized 15-player shape map used for wildcard/free-hit drafts."""
    raw = shape or getattr(config, "CHIP_SQUAD_SHAPE", None) or {}
    out = {
        "GKP": int(raw.get("GKP", 2)),
        "DEF": int(raw.get("DEF", 5)),
        "MID": int(raw.get("MID", 5)),
        "FWD": int(raw.get("FWD", 3)),
    }
    return out


def _team_counts(df):
    """Count selected players per team id."""
    if df is None or df.empty or "team" not in df.columns:
        return {}
    return df["team"].astype(int).value_counts().to_dict()


def _swap_team_ok(team_counts, team_out, team_in, max_per_team):
    """Check if a same-position swap keeps the per-team cap valid."""
    team_out = int(team_out)
    team_in = int(team_in)
    if team_out == team_in:
        return True
    out_count = int(team_counts.get(team_out, 0))
    in_count = int(team_counts.get(team_in, 0))
    if out_count <= 0:
        return False
    return (in_count + 1) <= int(max_per_team)


def _is_premium_attack_row(row, premium_floor, premium_positions):
    """Return True when a row is a premium attacker/captaincy slot."""
    pos = str(row.get("pos") or "")
    price = float(to_number(row.get("price_m"), 0.0))
    return pos in set(premium_positions or []) and price >= float(to_number(premium_floor, 0.0))


def _count_premium_attackers(df, premium_floor, premium_positions):
    """Count premium attackers in a squad DataFrame."""
    if df is None or df.empty:
        return 0
    positions = set(premium_positions or [])
    price = pd.to_numeric(df.get("price_m"), errors="coerce").fillna(0.0)
    pos = df.get("pos", pd.Series("", index=df.index)).astype(str)
    return int(((pos.isin(list(positions))) & (price >= float(to_number(premium_floor, 0.0)))).sum())


def _premium_count_after_swap(selected, idx, cand, premium_floor, premium_positions):
    """Return premium-attacker count after replacing one row."""
    row = selected.loc[idx]
    count_now = _count_premium_attackers(selected, premium_floor, premium_positions)
    count_now -= int(_is_premium_attack_row(row, premium_floor, premium_positions))
    count_now += int(_is_premium_attack_row(cand, premium_floor, premium_positions))
    return int(count_now)


def _prepare_chip_market(elements_all, score_col, shape, extra_cols=None):
    """Build clean player market table with chip objective score.

    `extra_cols` (e.g. per-GW `xpts_gw{n}` columns, recent start rates) ride
    along untouched when present — the wildcard builder needs them for the
    rotation bench and the start-rate gate; column-guarded so any market works.
    """
    if elements_all is None or elements_all.empty:
        return pd.DataFrame()
    if score_col not in elements_all.columns:
        return pd.DataFrame()

    cols = ["id", "web_name", "pos", "team", "team_short", "team_name", "price_m", "now_cost",
            "status", "minutes", "selected_by_percent", score_col]
    for c in (extra_cols or []):
        if c not in cols:
            cols.append(c)
    keep = [c for c in cols if c in elements_all.columns]
    market = elements_all[keep].copy()

    # Injured / suspended / unavailable players never belong in a chip draft —
    # not in the XI and not as bench fodder. Column-guarded: engine callers
    # whose markets carry no status column are unaffected.
    if "status" in market.columns:
        excluded = tuple(getattr(config, "CHIP_MARKET_EXCLUDE_STATUS", ("i", "s", "u")))
        market = market[~market["status"].astype(str).str.lower().isin(excluded)].copy()

    market["id"] = pd.to_numeric(market.get("id"), errors="coerce")
    market["team"] = pd.to_numeric(market.get("team"), errors="coerce")
    market["price_m"] = pd.to_numeric(market.get("price_m"), errors="coerce")
    if market["price_m"].isna().any() and "now_cost" in market.columns:
        fallback = pd.to_numeric(market.get("now_cost"), errors="coerce") / 10.0
        market.loc[market["price_m"].isna(), "price_m"] = fallback.loc[market["price_m"].isna()]
    market["chip_score"] = pd.to_numeric(market.get(score_col), errors="coerce")

    market = market[
        market["id"].notna()
        & market["team"].notna()
        & market["price_m"].notna()
        & market["chip_score"].notna()
        & market["pos"].isin(list(shape.keys()))
    ].copy()
    if market.empty:
        return market

    market["id"] = market["id"].astype(int)
    market["team"] = market["team"].astype(int)
    market["price_m"] = market["price_m"].astype(float)
    market["chip_score"] = market["chip_score"].astype(float)
    market = market[market["price_m"] > 0].copy()
    market = market.sort_values(["chip_score", "price_m"], ascending=[False, True]).reset_index(drop=True)
    return market


def _apply_differential(market):
    """Differential draft mode: dock each candidate's score by
    CHIP_DIFF_OWNERSHIP_WEIGHT × ownership, so near-equal low-owned players
    displace the template. No-op when ownership data is missing."""
    if market is None or market.empty or "selected_by_percent" not in market.columns:
        return market
    w = float(getattr(config, "CHIP_DIFF_OWNERSHIP_WEIGHT", 0.35))
    own = (
        pd.to_numeric(market["selected_by_percent"], errors="coerce").fillna(0.0) / 100.0
    ).clip(0.0, 1.0)
    out = market.copy()
    out["chip_score"] = out["chip_score"] * (1.0 - w * own)
    return out.sort_values(
        ["chip_score", "price_m"], ascending=[False, True]
    ).reset_index(drop=True)


def _replace_row(selected, idx, cand):
    """Replace a selected row with a candidate row by index."""
    for col in selected.columns:
        if col in cand.index:
            selected.at[idx, col] = cand[col]
    return selected


def _repair_team_cap(selected, market, max_per_team):
    """Swap out overflow-team picks until team cap is respected."""
    if selected is None or selected.empty:
        return selected
    out = selected.copy().reset_index(drop=True)

    for _ in range(300):
        counts = _team_counts(out)
        overflow = [(int(t), int(c)) for t, c in counts.items() if int(c) > int(max_per_team)]
        if not overflow:
            return out

        overflow_team = sorted(overflow, key=lambda x: x[1], reverse=True)[0][0]
        over_rows = out[out["team"].astype(int) == int(overflow_team)].sort_values(
            ["chip_score", "price_m"], ascending=[True, False]
        )
        swapped = False
        selected_ids = set(out["id"].astype(int).tolist())

        for idx, row in over_rows.iterrows():
            pool = market[
                (market["pos"] == row["pos"])
                & (~market["id"].astype(int).isin(selected_ids))
                & (market["team"].astype(int) != int(overflow_team))
            ].sort_values(["price_m", "chip_score"], ascending=[True, False])
            if pool.empty:
                continue
            for _, cand in pool.iterrows():
                cand_team = int(cand["team"])
                if int(counts.get(cand_team, 0)) >= int(max_per_team):
                    continue
                out = _replace_row(out, idx, cand)
                swapped = True
                break
            if swapped:
                break

        if not swapped:
            return None
    return None


def _reduce_cost_to_budget(
    selected,
    market,
    budget_m,
    max_per_team,
    min_premium_attackers=0,
    premium_floor=0.0,
    premium_positions=None,
):
    """Downgrade picks until total squad cost fits the budget."""
    if selected is None or selected.empty:
        return None
    out = selected.copy().reset_index(drop=True)
    budget_m = float(to_number(budget_m, 100.0))

    for _ in range(500):
        cost = float(pd.to_numeric(out["price_m"], errors="coerce").fillna(0.0).sum())
        if cost <= budget_m + 1e-9:
            return out

        selected_ids = set(out["id"].astype(int).tolist())
        counts = _team_counts(out)
        best = None

        for idx, row in out.iterrows():
            pool = market[
                (market["pos"] == row["pos"])
                & (~market["id"].astype(int).isin(selected_ids))
                & (market["price_m"] < float(to_number(row.get("price_m"), 0.0)) - 1e-9)
            ].sort_values(["price_m", "chip_score"], ascending=[True, False])
            if pool.empty:
                continue

            row_price = float(to_number(row.get("price_m"), 0.0))
            row_score = float(to_number(row.get("chip_score"), 0.0))
            row_team = int(to_number(row.get("team"), 0))

            for _, cand in pool.head(80).iterrows():
                cand_price = float(to_number(cand.get("price_m"), 0.0))
                cand_score = float(to_number(cand.get("chip_score"), 0.0))
                cand_team = int(to_number(cand.get("team"), 0))
                if not _swap_team_ok(counts, row_team, cand_team, max_per_team):
                    continue
                if int(min_premium_attackers or 0) > 0:
                    next_premium_count = _premium_count_after_swap(
                        out,
                        idx,
                        cand,
                        premium_floor=premium_floor,
                        premium_positions=premium_positions,
                    )
                    if next_premium_count < int(min_premium_attackers):
                        continue

                cost_save = row_price - cand_price
                if cost_save <= 0:
                    continue
                score_loss = max(0.0, row_score - cand_score)
                key = (
                    score_loss / cost_save,
                    score_loss,
                    -cost_save,
                )
                if best is None or key < best["key"]:
                    best = {"idx": idx, "cand": cand, "key": key}
                break

        if not best:
            return None
        out = _replace_row(out, best["idx"], best["cand"])

    return None


def _pick_best_upgrade(
    selected,
    market,
    budget_left,
    max_per_team,
    min_premium_attackers=0,
    premium_floor=0.0,
    premium_positions=None,
    extra_team_counts=None,
    extra_ids=None,
):
    """Find highest-value affordable upgrade for one selected slot.

    `extra_team_counts` / `extra_ids` describe squad members outside
    `selected` (a fixed bench while only the XI is searched) so the team cap
    and the no-duplicate rule still see the whole 15.
    """
    if selected is None or selected.empty:
        return None
    out = selected
    budget_left = float(to_number(budget_left, 0.0))
    if budget_left <= 1e-9:
        return None

    selected_ids = set(out["id"].astype(int).tolist()) | set(int(x) for x in (extra_ids or []))
    counts = _team_counts(out)
    for t, c in (extra_team_counts or {}).items():
        counts[int(t)] = counts.get(int(t), 0) + int(c)
    best = None

    for idx, row in out.iterrows():
        row_price = float(to_number(row.get("price_m"), 0.0))
        row_score = float(to_number(row.get("chip_score"), 0.0))
        row_team = int(to_number(row.get("team"), 0))
        max_price = row_price + budget_left + 1e-9

        pool = market[
            (market["pos"] == row["pos"])
            & (~market["id"].astype(int).isin(selected_ids))
            & (market["price_m"] <= max_price)
            & (market["chip_score"] > row_score + 1e-9)
        ].sort_values(["chip_score", "price_m"], ascending=[False, True])
        if pool.empty:
            continue

        for _, cand in pool.head(100).iterrows():
            cand_price = float(to_number(cand.get("price_m"), 0.0))
            cand_score = float(to_number(cand.get("chip_score"), 0.0))
            cand_team = int(to_number(cand.get("team"), 0))
            delta_cost = cand_price - row_price
            if delta_cost > budget_left + 1e-9:
                continue
            if not _swap_team_ok(counts, row_team, cand_team, max_per_team):
                continue
            if int(min_premium_attackers or 0) > 0:
                next_premium_count = _premium_count_after_swap(
                    out,
                    idx,
                    cand,
                    premium_floor=premium_floor,
                    premium_positions=premium_positions,
                )
                if next_premium_count < int(min_premium_attackers):
                    continue

            delta_score = cand_score - row_score
            efficiency = delta_score / (delta_cost + 0.05)
            key = (delta_score, efficiency, -delta_cost, cand_score)
            if best is None or key > best["key"]:
                best = {"idx": idx, "cand": cand, "delta_cost": delta_cost, "key": key}
            break

    return best


def _ensure_min_premium_attackers(
    selected,
    market,
    budget_m,
    max_per_team,
    min_premium_attackers=0,
    premium_floor=0.0,
    premium_positions=None,
):
    """Best-effort swap-in of premium attackers for wildcard structure."""
    out = selected.copy().reset_index(drop=True)
    min_premium_attackers = int(min_premium_attackers or 0)
    if min_premium_attackers <= 0 or out.empty:
        return out, True

    premium_positions = list(premium_positions or ["MID", "FWD"])
    for _ in range(max(1, min_premium_attackers * 3)):
        current_count = _count_premium_attackers(out, premium_floor, premium_positions)
        if current_count >= min_premium_attackers:
            return out, True

        selected_ids = set(out["id"].astype(int).tolist())
        best_trial = None
        premium_pool = market[
            market["pos"].isin(premium_positions)
            & (market["price_m"] >= float(to_number(premium_floor, 0.0)))
            & (~market["id"].astype(int).isin(selected_ids))
        ].sort_values(["chip_score", "price_m"], ascending=[False, True])

        if premium_pool.empty:
            break

        for _, cand in premium_pool.head(60).iterrows():
            pos = str(cand.get("pos") or "")
            candidates_out = out[out["pos"].astype(str) == pos].copy()
            if candidates_out.empty:
                continue
            candidates_out = candidates_out.sort_values(["chip_score", "price_m"], ascending=[True, True])

            for idx, _row in candidates_out.iterrows():
                trial = _replace_row(out.copy(), idx, cand)
                trial = _reduce_cost_to_budget(
                    trial,
                    market,
                    budget_m=budget_m,
                    max_per_team=max_per_team,
                    min_premium_attackers=0,
                    premium_floor=premium_floor,
                    premium_positions=premium_positions,
                )
                if trial is None or trial.empty:
                    continue
                premium_count = _count_premium_attackers(trial, premium_floor, premium_positions)
                if premium_count < current_count + 1:
                    continue
                trial_score = float(pd.to_numeric(trial["chip_score"], errors="coerce").fillna(0.0).sum())
                trial_cost = float(pd.to_numeric(trial["price_m"], errors="coerce").fillna(0.0).sum())
                key = (premium_count, trial_score, -trial_cost)
                if best_trial is None or key > best_trial["key"]:
                    best_trial = {"selected": trial, "key": key}

        if not best_trial:
            break
        out = best_trial["selected"].copy().reset_index(drop=True)

    final_ok = _count_premium_attackers(out, premium_floor, premium_positions) >= min_premium_attackers
    return out, final_ok


_H2H_DEFENSIVE_POS = {"GKP", "DEF"}


def _bench_sort(pool):
    """Bench-fodder ordering: players with at least CHIP_BENCH_MIN_MINUTES
    season minutes come first (cheap is fine, ghosts are not), then price
    ascending, then WORST scorer so a price tie never eats an XI candidate.
    Preference, not a filter — a thin market falls through to the ghosts."""
    pool = pool.copy()
    floor = float(getattr(config, "CHIP_BENCH_MIN_MINUTES", 90.0))
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


def _h2h_conflict_count(row, picked_rows, opponents):
    """Count GK/DEF↔attacker pairs between `row` and already-picked XI rows
    whose teams face each other this GW — own players cancelling each other."""
    if not opponents:
        return 0
    row_defensive = row["pos"] in _H2H_DEFENSIVE_POS
    row_opps = opponents.get(int(row["team"])) or ()
    n = 0
    for r in picked_rows:
        if (r["pos"] in _H2H_DEFENSIVE_POS) == row_defensive:
            continue
        if int(r["team"]) in row_opps:
            n += 1
    return n


def build_free_hit_squad(elements_all, score_col, budget_m, max_per_team=None, opponents=None,
                         differential=False):
    """
    Build a legal free-hit 15-man squad optimised for a single gameweek.

    Strategy:
    - Starting XI: pick the best 11 players by xPts across all valid formations,
      concentrating budget on high-scoring starters (premiums welcome).
    - Bench (4 slots): fill with the cheapest legal players in the required
      positions (1 GKP + remaining outfield to complete the shape), keeping
      budget available for the XI.
    - Head-to-head hedge: with an `opponents` map ({team_id: opponent ids this
      GW}), a candidate is docked CHIP_H2H_CONFLICT_PENALTY per own XI player
      it directly opposes (GK/DEF vs attacker), so the draft avoids picks that
      cancel each other unless one is clearly better. Surviving pairs are
      returned as `h2h_conflicts`.

    This reflects real free-hit usage: the bench only exists to satisfy the
    squad rules, not to score points.
    """
    max_per_team = int(max_per_team or getattr(config, "CHIP_MAX_PER_TEAM", 3) or 3)
    budget_m = float(to_number(budget_m, 100.0))

    market = _prepare_chip_market(
        elements_all,
        score_col=score_col,
        shape={"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3},
    )
    if market.empty:
        return {"ok": False, "reason": f"Market missing columns or score `{score_col}`.", "squad_df": None}
    if differential:
        market = _apply_differential(market)

    # --- Step 1: pick bench fillers first (cheapest per position) ---
    # Bench shape: 1 GKP + enough outfield to complete the 15.
    # We defer deciding the exact outfield bench split until after picking the XI.
    # Cheapest available GKP for bench slot. The XI keeper is NOT price-picked —
    # it competes on chip_score inside the XI loop below like every other XI
    # slot (a price-ranked XI keeper meant a random 4.0m backup started every
    # free hit). Bench ordering prefers fodder that actually plays (minutes
    # floor), then cheapest, then the worst scorer of a price tie — leaving
    # better keepers for the XI.
    gkp_pool = market[market["pos"] == "GKP"]
    if len(gkp_pool) < 2:
        return {"ok": False, "reason": "Not enough GKPs in market.", "squad_df": None}

    bench_gkp = _bench_sort(gkp_pool).iloc[[0]]

    # --- Step 2: pick best XI across all valid formations ---
    best_xi = None
    best_xi_score = -1.0
    best_formation = None

    used_ids = set(bench_gkp["id"].astype(int).tolist())

    for d, m, f in VALID_FORMATIONS:
        # Need d DEF + m MID + f FWD in XI, then bench = (5-d) DEF + (5-m) MID + (3-f) FWD
        bench_d, bench_m, bench_f = 5 - d, 5 - m, 3 - f

        # Pick bench outfielders (cheapest) first to know budget left for XI.
        # Two passes per position: the first prefers teams not already on the
        # bench (so one postponement can't wipe several subs), but only at
        # the cheapest available price (+ configurable margin) — diversity is
        # never allowed to inflate the bench cost. The second pass fills
        # whatever the diversity preference couldn't.
        bench_outfield = []
        team_counts_bench = _team_counts(bench_gkp)
        bench_teams = set(team_counts_bench.keys())
        diversity_extra = float(getattr(config, "CHIP_BENCH_DIVERSITY_MAX_EXTRA_M", 0.0))
        ok = True
        for pos, need in [("DEF", bench_d), ("MID", bench_m), ("FWD", bench_f)]:
            pool = _bench_sort(market[
                (market["pos"] == pos)
                & (~market["id"].astype(int).isin(used_ids | {r["id"] for r in bench_outfield}))
            ])
            min_price = float(pool["price_m"].min()) if len(pool) else 0.0
            picked = []
            picked_ids = set()
            for prefer_distinct in (True, False):
                for _, row in pool.iterrows():
                    if len(picked) == need:
                        break
                    t = int(row["team"])
                    rid = int(row["id"])
                    if rid in picked_ids:
                        continue
                    if prefer_distinct and (
                        t in bench_teams
                        or float(row["price_m"]) > min_price + diversity_extra
                    ):
                        continue
                    if team_counts_bench.get(t, 0) < max_per_team:
                        picked.append(row)
                        picked_ids.add(rid)
                        team_counts_bench[t] = team_counts_bench.get(t, 0) + 1
                        bench_teams.add(t)
                if len(picked) == need:
                    break
            if len(picked) < need:
                ok = False
                break
            bench_outfield.extend(picked)

        if not ok:
            continue

        bench_cost = (
            float(bench_gkp["price_m"].sum())
            + sum(float(r["price_m"]) for r in bench_outfield)
        )
        xi_budget = budget_m - bench_cost
        if xi_budget < 0:
            continue

        bench_ids = used_ids | {int(r["id"]) for r in bench_outfield}

        # Pick the XI (best by score within xi_budget). The keeper slot is
        # score-picked here exactly like the outfield slots. Order matters for
        # the H2H hedge: outfield first, keeper last, so the GK choice can see
        # which attackers it would directly oppose. Conflicts only pair
        # defensive picks (GK/DEF) with attackers, so within one position
        # group the penalty is constant and can be computed per pool.
        h2h_penalty = float(getattr(config, "CHIP_H2H_CONFLICT_PENALTY", 0.75))
        xi_rows = []
        team_counts_xi = {}
        # Merge bench team counts since they share the same 15-man squad
        for t, c in team_counts_bench.items():
            team_counts_xi[t] = team_counts_xi.get(t, 0) + c

        xi_ok = True
        total_xi_slots = 1 + d + m + f
        for pos, need in [("DEF", d), ("MID", m), ("FWD", f), ("GKP", 1)]:
            pool = market[
                (market["pos"] == pos)
                & (~market["id"].astype(int).isin(bench_ids | {int(r["id"]) for r in xi_rows}))
            ].copy()
            pool["_adj"] = pool["chip_score"]
            if len(pool):
                if opponents:
                    pool["_adj"] = pool["_adj"] - h2h_penalty * pool.apply(
                        lambda r: _h2h_conflict_count(r, xi_rows, opponents), axis=1
                    )
                # Soft attacker-stack limit: from the Nth same-team attacker
                # already in the XI, the next one pays a penalty — stacking
                # survives only when clearly better than the spread option.
                stack_pen = float(getattr(config, "CHIP_ATTACKER_STACK_PENALTY", 0.6))
                stack_lim = int(getattr(config, "CHIP_ATTACKER_STACK_SOFT_LIMIT", 2))
                if pos in ("MID", "FWD") and stack_pen > 0:
                    atk_counts: dict[int, int] = {}
                    for r in xi_rows:
                        if r["pos"] in ("MID", "FWD"):
                            rt = int(r["team"])
                            atk_counts[rt] = atk_counts.get(rt, 0) + 1
                    pool["_adj"] = pool["_adj"] - pool["team"].astype(int).map(
                        lambda t: stack_pen if atk_counts.get(t, 0) >= stack_lim else 0.0
                    )
            pool = pool.sort_values("_adj", ascending=False, kind="mergesort")
            picked = []
            for _, row in pool.iterrows():
                t = int(row["team"])
                cost_so_far = (
                    sum(float(r["price_m"]) for r in xi_rows)
                    + sum(float(r["price_m"]) for r in picked)
                    + float(row["price_m"])
                )
                remaining_slots = total_xi_slots - len(xi_rows) - len(picked) - 1
                # rough budget check: leave min budget for remaining slots
                if cost_so_far + remaining_slots * 4.0 > xi_budget:
                    continue
                if team_counts_xi.get(t, 0) < max_per_team:
                    picked.append(row)
                    team_counts_xi[t] = team_counts_xi.get(t, 0) + 1
                if len(picked) == need:
                    break
            if len(picked) < need:
                xi_ok = False
                break
            xi_rows.extend(picked)

        if not xi_ok:
            continue

        # Compare formations on the hedge-adjusted score so a formation that
        # avoids self-cancelling picks can beat a raw-score-equal one.
        xi_score = sum(float(r["_adj"]) for r in xi_rows)
        if xi_score > best_xi_score:
            best_xi_score = xi_score
            best_formation = (d, m, f)
            best_xi = pd.concat(
                [pd.DataFrame([r]) for r in xi_rows],
                ignore_index=True,
            ).drop(columns=["_adj"])
            best_bench = pd.concat(
                [bench_gkp] + [pd.DataFrame([r]) for r in bench_outfield],
                ignore_index=True,
            )

    if best_xi is None:
        return {"ok": False, "reason": "Could not build a valid free-hit XI under budget.", "squad_df": None}

    selected = pd.concat([best_xi, best_bench], ignore_index=True)
    selected = selected.drop(
        columns=[c for c in ("_bench_pref", "_adj") if c in selected.columns]
    )
    selected = selected.copy().reset_index(drop=True)
    selected["player_id"] = selected["id"].astype(int)
    selected["multiplier"] = 0
    selected["is_captain"] = False
    selected["is_vice_captain"] = False

    cost = float(pd.to_numeric(selected["price_m"], errors="coerce").fillna(0.0).sum())
    xi_score_total = float(pd.to_numeric(best_xi["chip_score"], errors="coerce").fillna(0.0).sum())

    # Surviving head-to-head pairs in the chosen XI (penalty applied but the
    # conflicted pick still won) — surfaced so the UI can badge them.
    h2h_conflicts = []
    if opponents:
        defensive = best_xi[best_xi["pos"].isin(_H2H_DEFENSIVE_POS)]
        attackers = best_xi[~best_xi["pos"].isin(_H2H_DEFENSIVE_POS)]
        for _, drow in defensive.iterrows():
            opps = opponents.get(int(drow["team"])) or ()
            for _, arow in attackers.iterrows():
                if int(arow["team"]) in opps:
                    h2h_conflicts.append({
                        "defender": str(drow.get("web_name", drow.get("id"))),
                        "attacker": str(arow.get("web_name", arow.get("id"))),
                        "defender_team": int(drow["team"]),
                        "attacker_team": int(arow["team"]),
                    })

    reason = (
        f"Free-hit draft built: {best_formation[0]}-{best_formation[1]}-{best_formation[2]} "
        f"formation, XI xPts={round(xi_score_total, 1)}."
    )
    if h2h_conflicts:
        pair_txt = "; ".join(f"{p['defender']} vs {p['attacker']}" for p in h2h_conflicts[:3])
        reason += (
            f" H2H note: {len(h2h_conflicts)} own-player pair(s) face each other this GW"
            f" ({pair_txt}) — kept despite the hedge penalty."
        )

    return {
        "ok": True,
        "reason": reason,
        "h2h_conflicts": h2h_conflicts,
        "objective_score_col": score_col,
        "budget_m": float(round(budget_m, 2)),
        "squad_cost_m": float(round(cost, 2)),
        "remaining_budget_m": float(round(max(0.0, budget_m - cost), 2)),
        "objective_score_total": float(round(xi_score_total, 2)),
        "squad_df": selected,
    }


def build_chip_squad(
    elements_all,
    score_col,
    budget_m,
    max_per_team=None,
    shape=None,
    min_premium_attackers=0,
    premium_floor=0.0,
    premium_positions=None,
    differential=False,
):
    """
    Build a legal 15-man draft for wildcard/free-hit under budget and team caps.

    The draft squad objective is `score_col` (for example `xpts_horizon` for wildcard,
    or `xpts_gwXX` for free hit), while the final XI can still be optimized separately.
    `differential=True` docks scores by ownership (see _apply_differential).
    """
    shape_map = _chip_shape(shape)
    max_per_team = int(max_per_team or getattr(config, "CHIP_MAX_PER_TEAM", 3) or 3)
    budget_m = float(to_number(budget_m, 100.0))
    market = _prepare_chip_market(elements_all, score_col=score_col, shape=shape_map)
    if market.empty:
        return {"ok": False, "reason": f"Market missing columns or score `{score_col}`.", "squad_df": None}
    if differential:
        market = _apply_differential(market)

    for pos, need in shape_map.items():
        have = int((market["pos"] == pos).sum())
        if int(have) < int(need):
            return {"ok": False, "reason": f"Not enough {pos} players in market ({have} < {need}).", "squad_df": None}

    selected_rows = []
    for pos in CHIP_POS_ORDER:
        need = int(shape_map.get(pos, 0))
        if need <= 0:
            continue
        pool = market[market["pos"] == pos].sort_values(["price_m", "chip_score"], ascending=[True, False])
        selected_rows.append(pool.head(need))
    selected = pd.concat(selected_rows, ignore_index=True) if selected_rows else pd.DataFrame()
    if selected.empty or int(len(selected)) != int(sum(shape_map.values())):
        return {"ok": False, "reason": "Could not build initial shape.", "squad_df": None}

    selected = _repair_team_cap(selected, market, max_per_team=max_per_team)
    if selected is None or selected.empty:
        return {"ok": False, "reason": "Could not satisfy max-per-team cap.", "squad_df": None}

    selected = _reduce_cost_to_budget(selected, market, budget_m=budget_m, max_per_team=max_per_team)
    if selected is None or selected.empty:
        return {"ok": False, "reason": "Could not fit squad to budget.", "squad_df": None}

    selected, premium_ok = _ensure_min_premium_attackers(
        selected,
        market,
        budget_m=budget_m,
        max_per_team=max_per_team,
        min_premium_attackers=min_premium_attackers,
        premium_floor=premium_floor,
        premium_positions=premium_positions,
    )

    max_iters = int(getattr(config, "CHIP_UPGRADE_MAX_ITERS", 320) or 320)
    for _ in range(max_iters):
        cost_now = float(pd.to_numeric(selected["price_m"], errors="coerce").fillna(0.0).sum())
        budget_left = max(0.0, float(budget_m - cost_now))
        best = _pick_best_upgrade(
            selected,
            market,
            budget_left=budget_left,
            max_per_team=max_per_team,
            min_premium_attackers=min_premium_attackers,
            premium_floor=premium_floor,
            premium_positions=premium_positions,
        )
        if not best:
            break
        selected = _replace_row(selected, best["idx"], best["cand"])

    selected, premium_ok_after_upgrades = _ensure_min_premium_attackers(
        selected,
        market,
        budget_m=budget_m,
        max_per_team=max_per_team,
        min_premium_attackers=min_premium_attackers,
        premium_floor=premium_floor,
        premium_positions=premium_positions,
    )
    premium_ok = bool(premium_ok and premium_ok_after_upgrades)

    selected = selected.copy().reset_index(drop=True)
    selected["player_id"] = selected["id"].astype(int)
    selected["multiplier"] = 0
    selected["is_captain"] = False
    selected["is_vice_captain"] = False

    cost = float(pd.to_numeric(selected["price_m"], errors="coerce").fillna(0.0).sum())
    score = float(pd.to_numeric(selected["chip_score"], errors="coerce").fillna(0.0).sum())
    return {
        "ok": True,
        "reason": (
            "Chip draft built successfully."
            if premium_ok or int(min_premium_attackers or 0) <= 0
            else "Chip draft built, but premium captaincy structure could not be fully satisfied under the budget."
        ),
        "objective_score_col": score_col,
        "budget_m": float(round(budget_m, 2)),
        "squad_cost_m": float(round(cost, 2)),
        "remaining_budget_m": float(round(max(0.0, budget_m - cost), 2)),
        "objective_score_total": float(round(score, 2)),
        "squad_df": selected,
    }


# ---------------------------------------------------------------------------
# Wildcard builder (2026-09-21): XI-first.
#
# The legacy `build_chip_squad` maximised the summed objective of all FIFTEEN
# players, so the greedy upgrade loop happily spent budget on bench slots and
# on whichever position the projections inflated that week (a 4-5 DEF XI
# with a bench that never plays). A wildcard is worth what its STARTING XI
# scores across the horizon plus what a bench can add through rotation, so
# this builder:
#
#   1. searches every legal formation, optimising the XI (not the 15) under
#      the budget left after a bench reserve — the same knapsack helpers as
#      before, applied to 11 slots;
#   2. applies `CHIP_WILDCARD_XI_POS_MULT` while comparing/choosing the XI, a
#      mild attacker preference (DEF xPts are clean-sheet driven, correlated
#      within a team and low-ceiling; MID/FWD carry the captaincy + haul
#      upside) so a 4-5 DEF shape has to be clearly better to win;
#   3. gates XI candidates on a recent start rate (`CHIP_WILDCARD_XI_MIN_START_RATE`)
#      so rotation risks never anchor the XI — they can still be bench bodies;
#   4. picks a ROTATION bench: the bench GK is the cheap keeper that best
#      complements the XI keeper week by week (sum over the horizon of how
#      much better he projects that GW — home/away alternation falls out of
#      the per-GW xPts), likewise one cheap DEF against the weakest XI DEF;
#      the remaining bench slots are the cheapest bodies that actually play.
#
# `score_col` stays the horizon objective (`wildcard_score` / `xpts_horizon`)
# and `gw_cols` the per-GW xPts columns the rotation bench reads; without
# `gw_cols` the bench falls back to cheapest-fodder (legacy behaviour).
# ---------------------------------------------------------------------------

_XI_SHAPE_ORDER = ("GKP", "DEF", "MID", "FWD")


def _xi_shape(formation):
    d, m, f = formation
    return {"GKP": 1, "DEF": int(d), "MID": int(m), "FWD": int(f)}


def _bench_shape(formation):
    d, m, f = formation
    return {"GKP": 1, "DEF": 5 - int(d), "MID": 5 - int(m), "FWD": 3 - int(f)}


def _start_rate_series(market):
    """Recent start share per row (0..1) or NaN when unknown. Reads
    `recent_gw_avg_starts` (history CSV, needs >= 2 samples); NaN rows are
    never gated — no data is not evidence of rotation."""
    if market is None or market.empty or "recent_gw_avg_starts" not in market.columns:
        return pd.Series(float("nan"), index=market.index if market is not None else None)
    rate = pd.to_numeric(market["recent_gw_avg_starts"], errors="coerce")
    if "recent_gw_samples" in market.columns:
        samples = pd.to_numeric(market["recent_gw_samples"], errors="coerce").fillna(0.0)
        rate = rate.where(samples >= 2.0)
    return rate.clip(lower=0.0, upper=1.0)


def _cheapest_of_shape(pool, shape):
    """Cheapest legal starting set for a shape (price asc, then best score)."""
    rows = []
    for pos in _XI_SHAPE_ORDER:
        need = int(shape.get(pos, 0))
        if need <= 0:
            continue
        sub = pool[pool["pos"] == pos].sort_values(["price_m", "chip_score"], ascending=[True, False])
        if len(sub) < need:
            return None
        rows.append(sub.head(need))
    if not rows:
        return None
    return pd.concat(rows, ignore_index=True)


def _optimise_xi(xi_pool, shape, xi_budget, max_per_team, min_premium_attackers,
                 premium_floor, premium_positions, max_iters):
    """Knapsack one starting XI of `shape` inside `xi_budget`: cheapest legal
    set → team-cap repair → budget fit → premium structure → greedy upgrades."""
    selected = _cheapest_of_shape(xi_pool, shape)
    if selected is None or selected.empty:
        return None
    selected = _repair_team_cap(selected, xi_pool, max_per_team=max_per_team)
    if selected is None or selected.empty:
        return None
    selected = _reduce_cost_to_budget(selected, xi_pool, budget_m=xi_budget, max_per_team=max_per_team)
    if selected is None or selected.empty:
        return None
    selected, _ok = _ensure_min_premium_attackers(
        selected, xi_pool, budget_m=xi_budget, max_per_team=max_per_team,
        min_premium_attackers=min_premium_attackers, premium_floor=premium_floor,
        premium_positions=premium_positions,
    )
    for _ in range(int(max_iters)):
        cost_now = float(pd.to_numeric(selected["price_m"], errors="coerce").fillna(0.0).sum())
        best = _pick_best_upgrade(
            selected, xi_pool, budget_left=max(0.0, xi_budget - cost_now),
            max_per_team=max_per_team, min_premium_attackers=min_premium_attackers,
            premium_floor=premium_floor, premium_positions=premium_positions,
        )
        if not best:
            break
        selected = _replace_row(selected, best["idx"], best["cand"])
    selected, premium_ok = _ensure_min_premium_attackers(
        selected, xi_pool, budget_m=xi_budget, max_per_team=max_per_team,
        min_premium_attackers=min_premium_attackers, premium_floor=premium_floor,
        premium_positions=premium_positions,
    )
    return selected.reset_index(drop=True), bool(premium_ok)


def _greedy_xi_estimate(xi_pool, shape, xi_budget, max_per_team):
    """Fast upper-ish estimate of a formation's XI score: best-score-first
    fill with a per-slot minimum-price guard (the free-hit heuristic). Used
    only to shortlist formations before the knapsack runs."""
    rows = []
    counts = {}
    spent = 0.0
    total_slots = int(sum(shape.values()))
    for pos in ("MID", "FWD", "DEF", "GKP"):
        need = int(shape.get(pos, 0))
        picked = 0
        for _, row in xi_pool[xi_pool["pos"] == pos].iterrows():
            if picked == need:
                break
            t = int(row["team"])
            remaining = total_slots - len(rows) - 1
            if spent + float(row["price_m"]) + remaining * 4.0 > xi_budget:
                continue
            if counts.get(t, 0) >= max_per_team:
                continue
            rows.append(row)
            counts[t] = counts.get(t, 0) + 1
            spent += float(row["price_m"])
            picked += 1
        if picked < need:
            return None
    return float(sum(float(r["chip_score"]) for r in rows))


def _complement_value(cand_row, baseline_by_gw, gw_cols):
    """How many xPts a bench body adds over the horizon by starting in the
    weeks he out-projects the XI player he would replace."""
    total = 0.0
    for col in gw_cols:
        base = float(baseline_by_gw.get(col, 0.0))
        val = float(to_number(cand_row.get(col), 0.0))
        total += max(0.0, val - base)
    return total


def _pick_rotation_body(pool, baseline_by_gw, gw_cols, max_price, team_counts, max_per_team):
    """Best rotation partner under `max_price`: highest complement value, then
    cheapest, then most minutes. Falls back to the cheapest playing body when
    nobody complements (or the market has no per-GW columns)."""
    if pool is None or pool.empty:
        return None, 0.0
    cands = pool[pd.to_numeric(pool["price_m"], errors="coerce") <= float(max_price) + 1e-9]
    if cands.empty:
        # Nobody under the cap: the slot is plain fodder — cheapest playing
        # body, no complement ranking (which would happily bench a premium).
        cands = _bench_sort(pool)
        gw_cols = []
    else:
        cands = _bench_sort(cands)
    if gw_cols and baseline_by_gw:
        scored = []
        for _, row in cands.iterrows():
            if team_counts.get(int(row["team"]), 0) >= max_per_team:
                continue
            comp = _complement_value(row, baseline_by_gw, gw_cols)
            scored.append((comp, -float(row["price_m"]), bool(row.get("_bench_pref", True)), row))
        if scored:
            scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
            comp, _p, _pref, row = scored[0]
            if comp > 1e-9:
                return row, float(comp)
    for _, row in cands.iterrows():
        if team_counts.get(int(row["team"]), 0) < max_per_team:
            return row, 0.0
    return None, 0.0


def _fill_fodder(pool, need, team_counts, max_per_team, bench_teams, diversity_extra):
    """Cheapest playing bodies for `need` slots; prefers a team not already on
    the bench when it costs nothing extra (one postponement should not wipe
    several subs). Mirrors the free-hit bench fill."""
    picked = []
    if need <= 0:
        return picked
    pool = _bench_sort(pool)
    if pool.empty:
        return picked
    min_price = float(pool["price_m"].min())
    picked_ids = set()
    for prefer_distinct in (True, False):
        for _, row in pool.iterrows():
            if len(picked) == need:
                break
            t = int(row["team"])
            rid = int(row["id"])
            if rid in picked_ids:
                continue
            if prefer_distinct and (t in bench_teams or float(row["price_m"]) > min_price + diversity_extra):
                continue
            if team_counts.get(t, 0) < max_per_team:
                picked.append(row)
                picked_ids.add(rid)
                team_counts[t] = team_counts.get(t, 0) + 1
                bench_teams.add(t)
        if len(picked) == need:
            break
    return picked


def build_wildcard_squad(
    elements_all,
    score_col,
    budget_m,
    max_per_team=None,
    gw_cols=None,
    min_premium_attackers=0,
    premium_floor=0.0,
    premium_positions=None,
    differential=False,
    formations=None,
):
    """
    Build a legal wildcard 15 whose objective is the STARTING XI's horizon
    score plus a rotation-aware bench (see the module note above).

    Returns the same dict shape as `build_chip_squad` plus `formation`,
    `xi_player_ids`, `bench_rotation` (the GK / DEF rotation partners and the
    xPts they add over the horizon), `xi_gated_out` (rotation-risk players
    kept off the XI) and `objective_xi_total`. `squad_df` lists the XI rows
    first, then the bench (GK first).
    """
    max_per_team = int(max_per_team or getattr(config, "CHIP_MAX_PER_TEAM", 3) or 3)
    budget_m = float(to_number(budget_m, 100.0))
    gw_cols = [c for c in (gw_cols or []) if c in (elements_all.columns if elements_all is not None else [])]
    extra_cols = list(gw_cols) + ["recent_gw_avg_starts", "recent_gw_samples"]
    market = _prepare_chip_market(
        elements_all, score_col=score_col,
        shape={"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}, extra_cols=extra_cols,
    )
    if market.empty:
        return {"ok": False, "reason": f"Market missing columns or score `{score_col}`.", "squad_df": None}
    if differential:
        market = _apply_differential(market)
    market["raw_score"] = market["chip_score"].astype(float)

    # --- XI candidate pool: start-rate gate + positional preference ---
    min_start = getattr(config, "CHIP_WILDCARD_XI_MIN_START_RATE", 0.0)
    min_start = float(min_start or 0.0)
    start_rate = _start_rate_series(market)
    gated = pd.Series(False, index=market.index)
    if min_start > 0:
        gated = start_rate.notna() & (start_rate < min_start)
    xi_pool = market[~gated].copy()
    pos_mult = dict(getattr(config, "CHIP_WILDCARD_XI_POS_MULT", {}) or {})
    if pos_mult:
        xi_pool["chip_score"] = xi_pool["raw_score"] * xi_pool["pos"].map(pos_mult).fillna(1.0).astype(float)
    xi_pool = xi_pool.sort_values(["chip_score", "price_m"], ascending=[False, True]).reset_index(drop=True)

    gk_cap = float(getattr(config, "CHIP_WILDCARD_BENCH_GK_MAX_PRICE", 4.5))
    def_cap = float(getattr(config, "CHIP_WILDCARD_BENCH_ROTATION_DEF_MAX_PRICE", 4.5))
    minutes_floor = float(getattr(config, "CHIP_BENCH_MIN_MINUTES", 90.0))
    diversity_extra = float(getattr(config, "CHIP_BENCH_DIVERSITY_MAX_EXTRA_M", 0.0))
    max_iters = int(getattr(config, "CHIP_UPGRADE_MAX_ITERS", 320) or 320)
    premium_positions = list(premium_positions or ["MID", "FWD"])

    def _cheapest_price(pos, n):
        sub = market[market["pos"] == pos].sort_values("price_m")
        if len(sub) < n:
            return None
        return float(sub["price_m"].head(n).sum()) if n > 0 else 0.0

    # Formation candidates: every legal shape gets a fast greedy estimate;
    # only the top CHIP_WILDCARD_FORMATION_SHORTLIST run the full knapsack.
    candidates = []
    for formation in (formations or VALID_FORMATIONS):
        shape = _xi_shape(formation)
        bench = _bench_shape(formation)
        # Bench reserve: the rotation GK and (when the formation benches a DEF)
        # the rotation DEF at their caps, cheapest bodies for the rest.
        # A rotation slot costs at most its cap, but never less than the
        # cheapest body in that position (a market whose cheapest keeper is
        # 5.0m must reserve 5.0m, or the XI overspends).
        cheapest_gk = _cheapest_price("GKP", 2)
        if cheapest_gk is None:
            continue
        reserve = max(gk_cap, _cheapest_price("GKP", 1) or 0.0)
        rest = dict(bench)
        rest["GKP"] = 0
        if bench["DEF"] >= 1:
            reserve += max(def_cap, _cheapest_price("DEF", 1) or 0.0)
            rest["DEF"] -= 1
        ok = True
        for pos, n in rest.items():
            price = _cheapest_price(pos, n)
            if price is None:
                ok = False
                break
            reserve += price
        if not ok:
            continue
        xi_budget = budget_m - reserve
        if xi_budget <= 0:
            continue
        est = _greedy_xi_estimate(xi_pool, shape, xi_budget, max_per_team)
        candidates.append((est if est is not None else -1.0, formation, shape, bench, reserve, xi_budget))
    shortlist = int(getattr(config, "CHIP_WILDCARD_FORMATION_SHORTLIST", 3) or 0)
    candidates.sort(key=lambda t: t[0], reverse=True)
    if shortlist > 0:
        candidates = candidates[:shortlist]

    best = None
    for _est, formation, shape, bench, reserve, xi_budget in candidates:
        out = _optimise_xi(
            xi_pool, shape, xi_budget, max_per_team, min_premium_attackers,
            premium_floor, premium_positions, max_iters,
        )
        if out is None:
            continue
        xi_df, premium_ok = out
        adj = float(pd.to_numeric(xi_df["chip_score"], errors="coerce").fillna(0.0).sum())
        cost = float(pd.to_numeric(xi_df["price_m"], errors="coerce").fillna(0.0).sum())
        key = (adj, -cost)
        if best is None or key > best["key"]:
            best = {"key": key, "formation": formation, "xi": xi_df, "premium_ok": premium_ok,
                    "bench_shape": bench, "reserve": reserve}

    if best is None:
        return {"ok": False, "reason": "Could not build a valid wildcard XI under budget.", "squad_df": None}

    xi = best["xi"].copy()
    formation = best["formation"]
    bench_shape = best["bench_shape"]
    xi_ids = set(xi["id"].astype(int).tolist())
    team_counts = _team_counts(xi)
    bench_rows = []
    bench_rotation = {}

    def _baseline(pos_rows):
        """Per-GW xPts of the XI player a bench body would replace: the (only)
        XI keeper, or the weakest XI defender that week."""
        base = {}
        for col in gw_cols:
            vals = pd.to_numeric(pos_rows[col], errors="coerce").fillna(0.0)
            base[col] = float(vals.min()) if len(vals) else 0.0
        return base

    # Rotation GK.
    gk_pool = market[(market["pos"] == "GKP") & (~market["id"].astype(int).isin(xi_ids))]
    gk_row, gk_comp = _pick_rotation_body(
        gk_pool, _baseline(xi[xi["pos"] == "GKP"]), gw_cols, gk_cap, team_counts, max_per_team)
    if gk_row is None:
        return {"ok": False, "reason": "Not enough GKPs in market.", "squad_df": None}
    bench_rows.append(gk_row)
    team_counts[int(gk_row["team"])] = team_counts.get(int(gk_row["team"]), 0) + 1
    bench_rotation["GKP"] = {
        "player_id": int(gk_row["id"]), "web_name": str(gk_row.get("web_name", gk_row["id"])),
        "team": int(gk_row["team"]), "price_m": float(gk_row["price_m"]),
        "rotation_xpts": round(float(gk_comp), 2),
    }

    # Rotation DEF (when the formation benches at least one defender).
    used = xi_ids | {int(gk_row["id"])}
    remaining = dict(bench_shape)
    remaining["GKP"] = 0
    if remaining["DEF"] >= 1:
        def_pool = market[(market["pos"] == "DEF") & (~market["id"].astype(int).isin(used))]
        def_row, def_comp = _pick_rotation_body(
            def_pool, _baseline(xi[xi["pos"] == "DEF"]), gw_cols, def_cap, team_counts, max_per_team)
        if def_row is not None:
            bench_rows.append(def_row)
            used.add(int(def_row["id"]))
            team_counts[int(def_row["team"])] = team_counts.get(int(def_row["team"]), 0) + 1
            remaining["DEF"] -= 1
            bench_rotation["DEF"] = {
                "player_id": int(def_row["id"]), "web_name": str(def_row.get("web_name", def_row["id"])),
                "team": int(def_row["team"]), "price_m": float(def_row["price_m"]),
                "rotation_xpts": round(float(def_comp), 2),
            }

    # Fodder for the rest.
    bench_teams = {int(r["team"]) for r in bench_rows}
    for pos in ("DEF", "MID", "FWD"):
        need = int(remaining.get(pos, 0))
        if need <= 0:
            continue
        pool = market[(market["pos"] == pos) & (~market["id"].astype(int).isin(used))]
        picked = _fill_fodder(pool, need, team_counts, max_per_team, bench_teams, diversity_extra)
        if len(picked) < need:
            return {"ok": False, "reason": f"Not enough {pos} players in market for the bench.", "squad_df": None}
        for r in picked:
            bench_rows.append(r)
            used.add(int(r["id"]))

    bench_df = pd.DataFrame([r for r in bench_rows]).reset_index(drop=True)
    bench_cost = float(pd.to_numeric(bench_df["price_m"], errors="coerce").fillna(0.0).sum())

    # The bench came in under its reserve → let the XI spend the difference.
    bench_counts = _team_counts(bench_df)
    xi_budget = budget_m - bench_cost
    for _ in range(max_iters):
        cost_now = float(pd.to_numeric(xi["price_m"], errors="coerce").fillna(0.0).sum())
        up = _pick_best_upgrade(
            xi, xi_pool, budget_left=max(0.0, xi_budget - cost_now), max_per_team=max_per_team,
            min_premium_attackers=min_premium_attackers, premium_floor=premium_floor,
            premium_positions=premium_positions, extra_team_counts=bench_counts,
            extra_ids=bench_df["id"].astype(int).tolist(),
        )
        if not up:
            break
        xi = _replace_row(xi, up["idx"], up["cand"])

    selected = pd.concat([xi, bench_df], ignore_index=True)
    # Report the raw objective (the positional preference only steered the search).
    selected["chip_score"] = pd.to_numeric(selected["raw_score"], errors="coerce").fillna(0.0)
    selected = selected.drop(columns=[c for c in ("_bench_pref", "raw_score") if c in selected.columns])
    selected = selected.copy().reset_index(drop=True)
    selected["player_id"] = selected["id"].astype(int)
    selected["multiplier"] = 0
    selected["is_captain"] = False
    selected["is_vice_captain"] = False

    cost = float(pd.to_numeric(selected["price_m"], errors="coerce").fillna(0.0).sum())
    xi_total = float(pd.to_numeric(selected["chip_score"].head(11), errors="coerce").fillna(0.0).sum())
    score = float(pd.to_numeric(selected["chip_score"], errors="coerce").fillna(0.0).sum())
    gated_names = market.loc[gated, "web_name"].astype(str).tolist() if "web_name" in market.columns else []

    reason = (
        f"Wildcard draft built: {formation[0]}-{formation[1]}-{formation[2]}, "
        f"XI objective {round(xi_total, 1)}"
    )
    rot_bits = []
    for pos, info in bench_rotation.items():
        if info["rotation_xpts"] > 0:
            rot_bits.append(f"{info['web_name']} ({pos}) +{info['rotation_xpts']:.1f} by rotation")
    if rot_bits:
        reason += "; bench: " + ", ".join(rot_bits)
    if not best["premium_ok"] and int(min_premium_attackers or 0) > 0:
        reason += "; premium captaincy structure could not be fully satisfied under the budget"
    reason += "."

    return {
        "ok": True,
        "reason": reason,
        "objective_score_col": score_col,
        "budget_m": float(round(budget_m, 2)),
        "squad_cost_m": float(round(cost, 2)),
        "remaining_budget_m": float(round(max(0.0, budget_m - cost), 2)),
        "objective_score_total": float(round(score, 2)),
        "objective_xi_total": float(round(xi_total, 2)),
        "formation": [int(x) for x in formation],
        "xi_player_ids": [int(x) for x in selected["player_id"].head(11).tolist()],
        "bench_rotation": bench_rotation,
        "xi_gated_out": gated_names[:20],
        "xi_gated_out_count": int(gated.sum()),
        "squad_df": selected,
    }


def merge_scores(squad_df, projections_df, score_col):
    """
    Attach `xpts` to a squad DataFrame using a projections table.
    - squad_df: expects `player_id`
    - projections_df: expects `id` and `score_col`
    """
    df = squad_df.copy()
    optional_cols = []
    for c in ["price_m", "form", "penalties_order"]:
        if c in projections_df.columns:
            optional_cols.append(c)
    # Matching per-GW fixture difficulty (diff_avg_gw{N} for xpts_gw{N}) rides
    # along as `fixture_difficulty` so the captain pick can see the fixture.
    rename = {"id": "player_id", score_col: "xpts"}
    m = re.match(r"xpts_gw(\d+)$", str(score_col))
    if m and f"diff_avg_gw{m.group(1)}" in projections_df.columns:
        diff_col = f"diff_avg_gw{m.group(1)}"
        optional_cols.append(diff_col)
        rename[diff_col] = "fixture_difficulty"
    proj = projections_df[["id", score_col] + optional_cols].copy()
    proj = proj.rename(columns=rename)
    df = df.merge(proj, on="player_id", how="left")
    df["xpts"] = pd.to_numeric(df["xpts"], errors="coerce").fillna(0.0)
    if "price_m" in df.columns:
        df["price_m"] = pd.to_numeric(df["price_m"], errors="coerce").fillna(0.0)
    if "form" in df.columns:
        df["form"] = pd.to_numeric(df["form"], errors="coerce").fillna(0.0)
    if "penalties_order" in df.columns:
        df["penalties_order"] = pd.to_numeric(df["penalties_order"], errors="coerce")
    return df


def optimize_lineup(squad_df, projections_df, score_col, formations=None):
    """
    Pick best XI + bench order + captain/vice from an existing 15-man squad.

    Returns a dict:
      - formation: (DEF, MID, FWD)
      - starting_xi: DataFrame (includes xpts + suggested captain/vice flags)
      - bench: DataFrame (includes bench_order + xpts)
      - captain_player_id / vice_player_id
      - projected_points_with_captain
    """
    if squad_df is None or squad_df.empty:
        return None

    df = merge_scores(squad_df, projections_df, score_col)
    formations = formations or VALID_FORMATIONS

    gk = df[df["pos"] == "GKP"].sort_values("xpts", ascending=False)
    de = df[df["pos"] == "DEF"].sort_values("xpts", ascending=False)
    mi = df[df["pos"] == "MID"].sort_values("xpts", ascending=False)
    fw = df[df["pos"] == "FWD"].sort_values("xpts", ascending=False)

    if gk.empty:
        return None

    best = None

    for d, m, f in formations:
        if len(de) < d or len(mi) < m or len(fw) < f:
            continue

        starting = pd.concat(
            [
                gk.head(1),
                de.head(int(d)),
                mi.head(int(m)),
                fw.head(int(f)),
            ],
            ignore_index=True,
        )
        remaining = df[~df["player_id"].isin(starting["player_id"])].copy()

        start_sorted = starting.sort_values("xpts", ascending=False).reset_index(drop=True)
        captain_eligible = start_sorted[start_sorted["pos"].isin(["MID", "FWD"])].copy()
        if captain_eligible.empty:
            captain_eligible = start_sorted[start_sorted["pos"] != "GKP"].copy()
        if captain_eligible.empty:
            captain_eligible = start_sorted.copy()
        captain_eligible["captain_score"] = captain_eligible.apply(
            lambda r: (
                float(r["xpts"]) * float(CAPTAIN_POSITION_MULTIPLIER.get(r["pos"], 1.0))
                + (
                    max(
                        0.0,
                        to_number(r.get("price_m"), 0.0)
                        - float(config.CAPTAIN_PREMIUM_PRICE_FLOOR),
                    )
                    * float(config.CAPTAIN_PREMIUM_PRICE_BONUS_PER_M)
                    * (1.0 if str(r.get("pos")) in ["MID", "FWD"] else 0.0)
                )
                + (
                    max(0.0, to_number(r.get("form"), 0.0))
                    * float(config.CAPTAIN_FORM_CEILING_WEIGHT)
                    * (1.0 if str(r.get("pos")) in ["MID", "FWD"] else 0.0)
                )
                + (
                    float(config.CAPTAIN_SET_PIECE_PENALTY_WEIGHT)
                    if to_number(r.get("penalties_order"), 99.0) == 1.0
                    and str(r.get("pos")) in ["MID", "FWD"]
                    else 0.0
                )
                + (
                    # Ceiling term: captaincy pays on hauls, and hauls die in
                    # D4/D5 fixtures faster than the mean does. ± per FDR
                    # step from neutral 3 — flips near-ties, never a monster.
                    (3.0 - to_number(r.get("fixture_difficulty"), 3.0))
                    * float(getattr(config, "CAPTAIN_FIXTURE_DIFFICULTY_WEIGHT", 0.35))
                    if str(r.get("pos")) in ["MID", "FWD"]
                    else 0.0
                )
            ),
            axis=1,
        )
        captain_rank = captain_eligible.sort_values(["captain_score", "xpts"], ascending=[False, False]).reset_index(drop=True)
        captain_id = int(captain_rank.loc[0, "player_id"])
        vice_pool = captain_rank[captain_rank["player_id"] != captain_id].copy()
        vice_id = int(vice_pool.iloc[0]["player_id"]) if not vice_pool.empty else captain_id

        # Score includes captain doubling (add captain again)
        captain_xpts = float(starting[starting["player_id"] == captain_id]["xpts"].iloc[0])
        score = float(starting["xpts"].sum() + captain_xpts)

        starting_out = starting.copy()
        starting_out["is_captain_suggested"] = starting_out["player_id"] == captain_id
        starting_out["is_vice_suggested"] = starting_out["player_id"] == vice_id
        starting_out = starting_out.sort_values(["pos", "xpts"], ascending=[True, False])

        # Bench: outfield by xpts, GK last
        bench_gk = remaining[remaining["pos"] == "GKP"].sort_values("xpts", ascending=False).head(1).copy()
        bench_outfield = remaining[remaining["pos"] != "GKP"].sort_values("xpts", ascending=False).reset_index(drop=True)
        bench_outfield["bench_order"] = bench_outfield.index + 1

        if not bench_gk.empty:
            last = int(bench_outfield["bench_order"].max()) if not bench_outfield.empty else 0
            bench_gk["bench_order"] = last + 1
            bench = pd.concat([bench_outfield, bench_gk], ignore_index=True)
        else:
            bench = bench_outfield

        bench = bench.sort_values("bench_order")

        res = {
            "formation": (int(d), int(m), int(f)),
            "captain_player_id": captain_id,
            "vice_player_id": vice_id,
            "starting_xi": starting_out,
            "bench": bench,
            "projected_points_with_captain": score,
        }

        if best is None or res["projected_points_with_captain"] > best["projected_points_with_captain"]:
            best = res

    return best
