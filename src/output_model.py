"""
Output model: expected FPL points conditional on minutes and fixture difficulty.

This is the structural, xG-based scoring layer. For each player with a fixture
it estimates the expected contribution from every FPL scoring source and sums
them:

    E[pts] = appearance + goals + assists + clean_sheet
             + goals_conceded_penalty + saves + bonus

Inputs are dependency-injected so the same code runs live or in the backtest:

* ``player_rates``   per-90 xG / xA per player (``compute_player_rates``), built
                     from the processed ``player_match_history`` (time-decayed).
* ``minutes_df``     output of ``minutes_model.minutes_projection`` (indexed by id).
* ``ratings``        team attack/defense ratings from ``fixture_difficulty``.
* ``elements_df``    needs ``id``, ``team``, ``pos`` (or ``element_type``).
* ``fixtures``       fixtures DataFrame for the GW.

Attacking output is scaled by the **opponent's defense rating** and venue only
(the player's own team attack is already baked into their per-90 rates, so we
don't double count it). Clean-sheet and conceded terms use the team's expected
xG-against for the fixture via a Poisson model.

All tunables live in ``config`` (``OUTPUT_*``).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

try:
    from . import config, fixture_difficulty
except Exception:  # pragma: no cover - flat script usage
    import config  # type: ignore
    import fixture_difficulty  # type: ignore


_ELEMENT_TYPE_TO_POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


# ---------------------------------------------------------------------------
# Player per-90 attacking rates
# ---------------------------------------------------------------------------

def compute_player_rates(match_df, gw, halflife_days=None, min_minutes_trust=None):
    """
    Time-decayed per-90 xG and xA per player from history strictly before ``gw``.

    Players with few minutes are shrunk toward a position baseline so noisy
    cameo rates don't blow up. Returns columns:
        player_id, xg90, xa90, minutes_sample, pos
    """
    halflife_days = float(halflife_days if halflife_days is not None
                          else getattr(config, "OUTPUT_XG_HALFLIFE_DAYS", 75.0))
    min_trust = float(min_minutes_trust if min_minutes_trust is not None
                      else getattr(config, "OUTPUT_MIN_MINUTES_TRUST", 270.0))
    base_xg90 = getattr(config, "OUTPUT_POSITION_BASE_XG90", {})
    base_xa90 = getattr(config, "OUTPUT_POSITION_BASE_XA90", {})

    if match_df is None or match_df.empty:
        return pd.DataFrame(columns=["player_id", "xg90", "xa90", "minutes_sample", "pos"])

    df = match_df.copy()
    needed = ["element", "minutes", "expected_goals"]
    if any(c not in df.columns for c in needed):
        return pd.DataFrame(columns=["player_id", "xg90", "xa90", "minutes_sample", "pos"])

    df["element"] = pd.to_numeric(df["element"], errors="coerce")
    df["minutes"] = pd.to_numeric(df["minutes"], errors="coerce").fillna(0.0)
    df["xg"] = pd.to_numeric(df["expected_goals"], errors="coerce").fillna(0.0)
    if "expected_assists" in df.columns:
        df["xa"] = pd.to_numeric(df["expected_assists"], errors="coerce").fillna(0.0)
    else:
        df["xa"] = 0.0

    gw_col = "event" if "event" in df.columns else ("round" if "round" in df.columns else None)
    if gw_col:
        ev = pd.to_numeric(df[gw_col], errors="coerce")
        df = df[ev.notna() & (ev < int(gw))].copy()
    df = df[df["element"].notna()].copy()
    if df.empty:
        return pd.DataFrame(columns=["player_id", "xg90", "xa90", "minutes_sample", "pos"])
    df["element"] = df["element"].astype(int)

    ts_col = "kickoff_time_x" if "kickoff_time_x" in df.columns else (
        "kickoff_time" if "kickoff_time" in df.columns else None)
    df["w"] = fixture_difficulty._decay_weights(
        df[ts_col] if ts_col else pd.Series(pd.NaT, index=df.index),
        None, halflife_days,
    )

    pos_lookup = {}
    if "element_type" in df.columns:
        et = df.groupby("element")["element_type"].first()
        pos_lookup = {int(k): _ELEMENT_TYPE_TO_POS.get(int(v), "MID")
                      for k, v in et.items() if pd.notna(v)}

    rows = []
    for pid, g in df.groupby("element"):
        w = g["w"].astype("float64")
        weighted_minutes = float((g["minutes"] * w).sum())
        raw_minutes = float(g["minutes"].sum())
        if weighted_minutes <= 0:
            continue
        xg90 = float((g["xg"] * w).sum() / weighted_minutes * 90.0)
        xa90 = float((g["xa"] * w).sum() / weighted_minutes * 90.0)
        pos = pos_lookup.get(int(pid), "MID")

        # Shrink toward position baseline using minutes as the confidence weight.
        conf = min(1.0, raw_minutes / min_trust) if min_trust > 0 else 1.0
        bxg = float(base_xg90.get(pos, 0.1))
        bxa = float(base_xa90.get(pos, 0.1))
        xg90 = conf * xg90 + (1.0 - conf) * bxg
        xa90 = conf * xa90 + (1.0 - conf) * bxa

        rows.append({
            "player_id": int(pid),
            "xg90": max(0.0, xg90),
            "xa90": max(0.0, xa90),
            "minutes_sample": raw_minutes,
            "pos": pos,
        })
    return pd.DataFrame(rows)


def compute_dc_rates(match_df, gw, halflife_days=None, min_games_trust=None):
    """
    Per-player probability of banking defensive-contribution points, from
    history strictly before ``gw``.

    For each 60+ minute game we mark whether the player's ``defensive_contribution``
    reached the position threshold, then take a time-decayed mean of that
    indicator, shrunk toward a position base rate by sample size. Returns
    columns: ``player_id, dc_clear_rate, pos``. Empty frame when the column is
    absent (older history) so the caller degrades to no DC term.
    """
    halflife_days = float(halflife_days if halflife_days is not None
                          else getattr(config, "OUTPUT_DC_HALFLIFE_DAYS", 75.0))
    min_trust = float(min_games_trust if min_games_trust is not None
                      else getattr(config, "OUTPUT_DC_MIN_GAMES_TRUST", 6.0))
    thresholds = getattr(config, "OUTPUT_DC_THRESHOLD", {})
    base_rate = getattr(config, "OUTPUT_DC_BASE_RATE", {})

    empty = pd.DataFrame(columns=["player_id", "dc_clear_rate", "pos"])
    if match_df is None or match_df.empty:
        return empty
    df = match_df.copy()
    if any(c not in df.columns for c in ["element", "minutes", "defensive_contribution"]):
        return empty

    df["element"] = pd.to_numeric(df["element"], errors="coerce")
    df["minutes"] = pd.to_numeric(df["minutes"], errors="coerce").fillna(0.0)
    df["dc"] = pd.to_numeric(df["defensive_contribution"], errors="coerce").fillna(0.0)

    gw_col = "event" if "event" in df.columns else ("round" if "round" in df.columns else None)
    if gw_col:
        ev = pd.to_numeric(df[gw_col], errors="coerce")
        df = df[ev.notna() & (ev < int(gw))].copy()
    # Rate is defined over games the player actually started; cameo appearances
    # can't realistically reach the threshold and would depress every rate.
    df = df[df["element"].notna() & (df["minutes"] >= 60)].copy()
    if df.empty:
        return empty
    df["element"] = df["element"].astype(int)

    pos_lookup = {}
    if "element_type" in df.columns:
        et = df.groupby("element")["element_type"].first()
        pos_lookup = {int(k): _ELEMENT_TYPE_TO_POS.get(int(v), "MID")
                      for k, v in et.items() if pd.notna(v)}

    ts_col = "kickoff_time_x" if "kickoff_time_x" in df.columns else (
        "kickoff_time" if "kickoff_time" in df.columns else None)
    df["w"] = fixture_difficulty._decay_weights(
        df[ts_col] if ts_col else pd.Series(pd.NaT, index=df.index),
        None, halflife_days,
    )

    rows = []
    for pid, g in df.groupby("element"):
        pos = pos_lookup.get(int(pid), "MID")
        thr = float(thresholds.get(pos, 12))
        cleared = (g["dc"] >= thr).astype("float64")
        w = g["w"].astype("float64")
        wsum = float(w.sum())
        if wsum <= 0:
            continue
        rate = float((cleared * w).sum() / wsum)
        n_games = int(len(g))

        conf = min(1.0, n_games / min_trust) if min_trust > 0 else 1.0
        prior = float(base_rate.get(pos, 0.05))
        rate = conf * rate + (1.0 - conf) * prior
        rows.append({"player_id": int(pid), "dc_clear_rate": max(0.0, min(1.0, rate)), "pos": pos})

    return pd.DataFrame(rows) if rows else empty


# ---------------------------------------------------------------------------
# Expected points per fixture
# ---------------------------------------------------------------------------

def _resolve_pos(row):
    pos = row.get("pos")
    if isinstance(pos, str) and pos:
        return pos
    et = row.get("element_type")
    try:
        return _ELEMENT_TYPE_TO_POS.get(int(et), "MID")
    except (TypeError, ValueError):
        return "MID"


def expected_points(elements_df, fixtures, ratings, player_rates, minutes_df, gw, dc_rates=None):
    """
    Expected FPL points per player for a single GW (DGW-aware: sums per fixture).

    Returns a DataFrame keyed by ``id`` with the total ``exp_points`` plus a
    breakdown column per scoring source.

    ``dc_rates`` (optional, from ``compute_dc_rates``) adds the
    defensive-contribution scoring category. Left as None it contributes 0, so
    existing callers keep their exact behaviour.
    """
    try:
        from . import transforms
    except Exception:  # pragma: no cover
        import transforms  # type: ignore

    goal_pts = getattr(config, "OUTPUT_GOAL_POINTS", {})
    assist_pts = float(getattr(config, "OUTPUT_ASSIST_POINTS", 3.0))
    cs_pts = getattr(config, "OUTPUT_CS_POINTS", {})
    conceded_pen = getattr(config, "OUTPUT_GOALS_CONCEDED_PENALTY_PER_2", {})
    saves_per_xga = float(getattr(config, "OUTPUT_SAVES_PER_XGA", 2.0))
    save_pts_per = float(getattr(config, "OUTPUT_SAVE_POINTS_PER_SAVE", 1.0 / 3.0))
    bonus_per_xgi = float(getattr(config, "OUTPUT_BONUS_PER_XGI", 0.9))
    cs_bonus_per = getattr(config, "OUTPUT_CS_BONUS_PER_CS", {})
    max_goals = float(getattr(config, "OUTPUT_MAX_GOALS_PER_GAME", 2.5))
    max_assists = float(getattr(config, "OUTPUT_MAX_ASSISTS_PER_GAME", 2.0))
    home_mult = float(getattr(config, "FDR_HOME_XG_MULT", 1.10))
    away_mult = float(getattr(config, "FDR_AWAY_XG_MULT", 0.92))

    if elements_df is None or elements_df.empty or "id" not in elements_df.columns:
        return pd.DataFrame(columns=["exp_points"])

    by_team = transforms.fixtures_by_team_for_gw(fixtures, int(gw)) if fixtures is not None else {}

    rates = player_rates.set_index("player_id") if (
        player_rates is not None and not player_rates.empty) else pd.DataFrame()
    mins = minutes_df if (minutes_df is not None and not minutes_df.empty) else pd.DataFrame()

    apply_dc = bool(getattr(config, "OUTPUT_APPLY_DC", True))
    dc_points = float(getattr(config, "OUTPUT_DC_POINTS", 2.0))
    dcr = dc_rates.set_index("player_id") if (
        apply_dc and dc_rates is not None and not dc_rates.empty) else pd.DataFrame()

    el = elements_df.copy()
    el["id"] = pd.to_numeric(el["id"], errors="coerce")
    el = el[el["id"].notna()].copy()
    el["id"] = el["id"].astype(int)

    rows = []
    for _, r in el.iterrows():
        pid = int(r["id"])
        team_id = pd.to_numeric(r.get("team"), errors="coerce")
        if pd.isna(team_id):
            continue
        team_id = int(team_id)
        fixtures_for_team = by_team.get(team_id, [])
        if not fixtures_for_team:
            continue  # blank GW -> no points

        pos = _resolve_pos(r)

        # Per-90 attacking rates (own player history; fall back to position base).
        if pid in rates.index:
            xg90 = float(rates.loc[pid, "xg90"])
            xa90 = float(rates.loc[pid, "xa90"])
        else:
            xg90 = float(getattr(config, "OUTPUT_POSITION_BASE_XG90", {}).get(pos, 0.05))
            xa90 = float(getattr(config, "OUTPUT_POSITION_BASE_XA90", {}).get(pos, 0.05))

        # Minutes projection.
        if pid in mins.index:
            exp_min = float(mins.loc[pid, "exp_minutes"])
            prob_appear = float(mins.loc[pid, "prob_appear"])
            prob_60 = float(mins.loc[pid, "prob_60"])
        else:
            exp_min = 0.0
            prob_appear = 0.0
            prob_60 = 0.0

        minutes_frac = exp_min / 90.0

        exp_goals = exp_assists = clean_sheet = conceded = saves = 0.0
        for it in fixtures_for_team:
            opp = int(it.get("opp"))
            is_home = bool(it.get("is_home"))
            _, opp_def = fixture_difficulty._team_rating(ratings, opp)
            venue = home_mult if is_home else away_mult

            # Attacking: opponent defense + venue (own attack already in xg90).
            exp_goals += xg90 * minutes_frac * opp_def * venue
            exp_assists += xa90 * minutes_frac * opp_def * venue

            # Defensive: team's expected xG-against this fixture.
            _, team_xga = fixture_difficulty.expected_xg_for_fixture(ratings, team_id, opp, is_home)
            clean_sheet += np.exp(-max(0.0, team_xga)) * prob_60  # Poisson P(0 conceded), need 60'
            conceded += team_xga
            saves += team_xga * saves_per_xga

        exp_goals = float(np.clip(exp_goals, 0.0, max_goals))
        exp_assists = float(np.clip(exp_assists, 0.0, max_assists))

        # Points by source.
        pts_appearance = prob_appear * 1.0 + prob_60 * 1.0  # 1 for playing, +1 for 60'
        pts_goals = exp_goals * float(goal_pts.get(pos, 4))
        pts_assists = exp_assists * assist_pts
        pts_cs = float(cs_pts.get(pos, 0)) * clean_sheet
        # Conceded penalty applies to GKP/DEF, scaled by playing 60'.
        pts_conceded = float(conceded_pen.get(pos, 0.0)) * (conceded / 2.0) * prob_60
        pts_saves = (saves * save_pts_per * prob_60) if pos == "GKP" else 0.0
        # Defensive-contribution points: banked only in a 60'+ appearance, so
        # scale the clearance rate by prob_60 the same way clean sheets are.
        dc_rate = float(dcr.loc[pid, "dc_clear_rate"]) if pid in dcr.index else 0.0
        pts_dc = dc_points * dc_rate * prob_60
        # Attacking bonus (goals/assists BPS) + defensive bonus (clean-sheet /
        # clearance / block BPS) so defenders/keepers aren't left with only
        # their raw clean-sheet points.
        pts_bonus = ((exp_goals + exp_assists) * bonus_per_xgi
                     + clean_sheet * float(cs_bonus_per.get(pos, 0.0)))

        total = (pts_appearance + pts_goals + pts_assists + pts_cs
                 + pts_conceded + pts_saves + pts_bonus + pts_dc)

        rows.append({
            "id": pid,
            "exp_points": float(total),
            "ep_appearance": float(pts_appearance),
            "ep_goals": float(pts_goals),
            "ep_assists": float(pts_assists),
            "ep_clean_sheet": float(pts_cs),
            "ep_conceded": float(pts_conceded),
            "ep_saves": float(pts_saves),
            "ep_bonus": float(pts_bonus),
            "ep_dc": float(pts_dc),
            "exp_goals": exp_goals,
            "exp_assists": exp_assists,
            "exp_minutes": float(exp_min),
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["exp_points"]).set_index(pd.Index([], name="id"))
    return out.set_index("id")
