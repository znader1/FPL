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

def _is_first_choice(value):
    """True when a set-piece order column marks this player as the primary taker."""
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return False
        return int(float(value)) == 1
    except (TypeError, ValueError):
        return False


def _setpiece_uplift(row, minutes_sample, min_trust):
    """
    Extra per-90 xG/xA from set-piece duty, as ``(xg90_add, xa90_add)``.

    Bootstrap knows who takes penalties; per-90 xG history does not know it until
    the player has actually taken some. So the uplift fills the gap the history
    cannot yet see, and tapers to zero as the player's own sample grows --
    otherwise an established taker's penalties would be counted twice.
    """
    if not bool(getattr(config, "OUTPUT_APPLY_SETPIECE", True)):
        return 0.0, 0.0

    conf = min(1.0, float(minutes_sample) / min_trust) if min_trust > 0 else 1.0
    untrusted = 1.0 - conf
    if untrusted <= 0.0:
        return 0.0, 0.0

    xg_add = xa_add = 0.0
    if _is_first_choice(row.get("penalties_order")):
        xg_add += float(getattr(config, "OUTPUT_SETPIECE_PEN_XG90", 0.11))
    if _is_first_choice(row.get("direct_freekicks_order")):
        xg_add += float(getattr(config, "OUTPUT_SETPIECE_FK_XG90", 0.03))
    if _is_first_choice(row.get("corners_and_indirect_freekicks_order")):
        xa_add += float(getattr(config, "OUTPUT_SETPIECE_CORNER_XA90", 0.05))
    return xg_add * untrusted, xa_add * untrusted


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
    min_minutes_trust = float(getattr(config, "OUTPUT_MIN_MINUTES_TRUST", 270.0))
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

    # League-median keeper save volume, used to turn a keeper's own saves_per_90
    # into a ratio against the flat OUTPUT_SAVES_PER_XGA prior. Median, not mean,
    # so a single backup with a freak rate cannot move the baseline.
    apply_save_rate = bool(getattr(config, "OUTPUT_APPLY_KEEPER_SAVE_RATE", True))
    save_ratio_clamp = tuple(getattr(config, "OUTPUT_SAVE_RATIO_CLAMP", (0.6, 1.6)))
    median_saves90 = None
    if apply_save_rate and "saves_per_90" in el.columns and "element_type" in el.columns:
        keepers = pd.to_numeric(
            el.loc[pd.to_numeric(el["element_type"], errors="coerce") == 1, "saves_per_90"],
            errors="coerce").dropna()
        keepers = keepers[keepers > 0]
        if not keepers.empty:
            median_saves90 = float(keepers.median())

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
            minutes_sample = float(rates.loc[pid, "minutes_sample"]) if (
                "minutes_sample" in rates.columns) else 0.0
        else:
            xg90 = float(getattr(config, "OUTPUT_POSITION_BASE_XG90", {}).get(pos, 0.05))
            xa90 = float(getattr(config, "OUTPUT_POSITION_BASE_XA90", {}).get(pos, 0.05))
            minutes_sample = 0.0

        # Set-piece duty the per-90 history cannot see yet.
        xg_add, xa_add = _setpiece_uplift(r, minutes_sample, min_minutes_trust)
        xg90 += xg_add
        xa90 += xa_add

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
        # P(no clean sheet in any fixture). Tracked as a product so a DGW yields a
        # real probability -- summing per-fixture clean-sheet odds can exceed 1.
        cs_none = 1.0
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
            cs_fixture = np.exp(-max(0.0, team_xga)) * prob_60  # Poisson P(0 conceded), need 60'
            clean_sheet += cs_fixture      # expected COUNT of clean sheets -> points
            cs_none *= (1.0 - min(1.0, max(0.0, cs_fixture)))  # -> P(at least one)
            conceded += team_xga
            saves += team_xga * saves_per_xga

        exp_goals = float(np.clip(exp_goals, 0.0, max_goals))
        exp_assists = float(np.clip(exp_assists, 0.0, max_assists))

        dc_rate = float(dcr.loc[pid, "dc_clear_rate"]) if pid in dcr.index else 0.0

        # Points by source.
        pts_appearance = prob_appear * 1.0 + prob_60 * 1.0  # 1 for playing, +1 for 60'
        pts_goals = exp_goals * float(goal_pts.get(pos, 4))
        pts_assists = exp_assists * assist_pts
        pts_cs = float(cs_pts.get(pos, 0)) * clean_sheet
        # Conceded penalty applies to GKP/DEF, scaled by playing 60'.
        pts_conceded = float(conceded_pen.get(pos, 0.0)) * (conceded / 2.0) * prob_60
        # Keeper save volume varies far more between keepers than a flat
        # saves-per-xGA constant allows. Scale by the keeper's own rate relative
        # to the league median, shrunk toward 1.0 while their sample is thin, and
        # clamped so an outlier cannot run away with it.
        save_ratio = 1.0
        if pos == "GKP" and median_saves90:
            own_saves90 = pd.to_numeric(pd.Series([r.get("saves_per_90")]),
                                        errors="coerce").iloc[0]
            if pd.notna(own_saves90) and float(own_saves90) > 0:
                raw = float(own_saves90) / median_saves90
                conf = (min(1.0, minutes_sample / min_minutes_trust)
                        if min_minutes_trust > 0 else 1.0)
                shrunk = conf * raw + (1.0 - conf) * 1.0
                save_ratio = float(np.clip(shrunk, save_ratio_clamp[0], save_ratio_clamp[1]))
        pts_saves = (saves * save_ratio * save_pts_per * prob_60) if pos == "GKP" else 0.0
        # Defensive-contribution points: banked only in a 60'+ appearance, so
        # scale the clearance rate by prob_60 the same way clean sheets are.
        pts_dc = dc_points * dc_rate * prob_60
        # Attacking bonus (goals/assists BPS) + defensive bonus (clean-sheet /
        # clearance / block BPS) so defenders/keepers aren't left with only
        # their raw clean-sheet points.
        pts_bonus = ((exp_goals + exp_assists) * bonus_per_xgi
                     + clean_sheet * float(cs_bonus_per.get(pos, 0.0)))

        total = (pts_appearance + pts_goals + pts_assists + pts_cs
                 + pts_conceded + pts_saves + pts_bonus + pts_dc)

        # Component probabilities. These are the quantities a manager actually
        # reasons about; the model already computes them, so surface them rather
        # than collapsing everything into a single mean.
        # Poisson P(at least one) from the expected count.
        p_goal = float(1.0 - np.exp(-exp_goals))
        p_assist = float(1.0 - np.exp(-exp_assists))
        p_clean_sheet = float(1.0 - cs_none)
        # DC points need a 60' appearance, same gate the points term applies.
        p_dc = float(dc_rate * prob_60)

        rows.append({
            "id": pid,
            "pos": pos,
            "exp_points": float(total),
            "p_goal": p_goal,
            "p_assist": p_assist,
            "p_clean_sheet": p_clean_sheet,
            "p_appear": float(prob_appear),
            "p_60": float(prob_60),
            "p_dc": p_dc,
            # Expected COUNT of clean sheets (>1 possible in a DGW) and the
            # fixture count, so a points distribution can reproduce this mean.
            "exp_clean_sheets": float(clean_sheet),
            "n_fixtures": int(len(fixtures_for_team)),
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
