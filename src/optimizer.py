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


def _prepare_chip_market(elements_all, score_col, shape):
    """Build clean player market table with chip objective score."""
    if elements_all is None or elements_all.empty:
        return pd.DataFrame()
    if score_col not in elements_all.columns:
        return pd.DataFrame()

    cols = ["id", "web_name", "pos", "team", "team_short", "team_name", "price_m", "now_cost", score_col]
    keep = [c for c in cols if c in elements_all.columns]
    market = elements_all[keep].copy()

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
):
    """Find highest-value affordable upgrade for one selected slot."""
    if selected is None or selected.empty:
        return None
    out = selected
    budget_left = float(to_number(budget_left, 0.0))
    if budget_left <= 1e-9:
        return None

    selected_ids = set(out["id"].astype(int).tolist())
    counts = _team_counts(out)
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


def build_chip_squad(
    elements_all,
    score_col,
    budget_m,
    max_per_team=None,
    shape=None,
    min_premium_attackers=0,
    premium_floor=0.0,
    premium_positions=None,
):
    """
    Build a legal 15-man draft for wildcard/free-hit under budget and team caps.

    The draft squad objective is `score_col` (for example `xpts_horizon` for wildcard,
    or `xpts_gwXX` for free hit), while the final XI can still be optimized separately.
    """
    shape_map = _chip_shape(shape)
    max_per_team = int(max_per_team or getattr(config, "CHIP_MAX_PER_TEAM", 3) or 3)
    budget_m = float(to_number(budget_m, 100.0))
    market = _prepare_chip_market(elements_all, score_col=score_col, shape=shape_map)
    if market.empty:
        return {"ok": False, "reason": f"Market missing columns or score `{score_col}`.", "squad_df": None}

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
    proj = projections_df[["id", score_col] + optional_cols].copy()
    proj = proj.rename(columns={"id": "player_id", score_col: "xpts"})
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
        start_sorted["captain_score"] = start_sorted.apply(
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
            ),
            axis=1,
        )
        captain_rank = start_sorted.sort_values(["captain_score", "xpts"], ascending=[False, False]).reset_index(drop=True)
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
