from pathlib import Path

import pandas as pd

from . import config, transforms


DIFFICULTY_MULTIPLIER = {
    1: 1.15,
    2: 1.08,
    3: 1.00,
    4: 0.93,
    5: 0.86,
}


_PLAYER_GW_HISTORY_CACHE = {"path": None, "mtime": None, "data": None}


def clamp(value, low, high):
    """Clamp a numeric value between low and high with safe fallbacks."""
    if value is None:
        return low
    try:
        v = float(value)
    except Exception:
        return low
    if v < float(low):
        return float(low)
    if v > float(high):
        return float(high)
    return float(v)


def difficulty_multiplier(diff_avg):
    """Map FPL difficulty (1..5) to a simple multiplier."""
    if pd.isna(diff_avg):
        return 1.0
    try:
        d = int(round(float(diff_avg)))
    except Exception:
        return 1.0
    d = max(1, min(5, d))
    return float(DIFFICULTY_MULTIPLIER.get(d, 1.0))


def _numeric_series(df, col, default=0.0):
    """Return a numeric Series for a column, or a constant default when missing."""
    if col not in df.columns:
        return pd.Series(float(default), index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(float(default))


def _weight_list(raw_weights, length, fallback=1.0):
    """Pad/truncate configured weights to the requested horizon length."""
    weights = []
    for value in list(raw_weights or []):
        try:
            weights.append(float(value))
        except Exception:
            continue
    if not weights:
        weights = [float(fallback)]
    if len(weights) < int(length):
        weights.extend([weights[-1]] * (int(length) - len(weights)))
    return weights[: int(length)]


def baseline_points_per_gw(
    elements,
    ppg_weight=config.PROJ_DEFAULT_PPG_WEIGHT,
    form_weight=config.PROJ_DEFAULT_FORM_WEIGHT,
    latest_n_matches=config.PROJ_DEFAULT_LATEST_N_MATCHES,
):
    """
    Fallback baseline when ep_next is missing: blend points_per_game and form.
    `latest_n_matches` is used as a small form emphasis control.
    """
    ppg = pd.to_numeric(elements.get("points_per_game", 0), errors="coerce").fillna(0.0)
    form = pd.to_numeric(elements.get("form", 0), errors="coerce").fillna(0.0)
    n = max(config.PROJ_LATEST_N_MIN, min(config.PROJ_LATEST_N_MAX, int(latest_n_matches or config.PROJ_DEFAULT_LATEST_N_MATCHES)))
    form_scale = 1.0 + (float(n) - float(config.PROJ_FORM_SCALE_BASE_MATCHES)) * float(config.PROJ_FORM_SCALE_PER_MATCH)
    return float(ppg_weight) * ppg + float(form_weight) * form * form_scale


def team_recent_ppg_map(fixtures, gw_start, latest_n_matches=config.PROJ_DEFAULT_LATEST_N_MATCHES):
    """
    Build team form from last N finished fixtures before gw_start.
    Returns {team_id: recent_points_per_game}.
    """
    if fixtures is None or fixtures.empty:
        return {}

    fx = fixtures.copy()
    if "event" not in fx.columns:
        return {}

    fx["event"] = pd.to_numeric(fx["event"], errors="coerce")
    fx = fx[fx["event"].notna()].copy()
    fx["event"] = fx["event"].astype(int)
    fx = fx[fx["event"] < int(gw_start)].copy()
    if fx.empty:
        return {}

    if "finished" in fx.columns:
        fx = fx[fx["finished"] == True].copy()
    if fx.empty:
        return {}

    for col in ["team_h_score", "team_a_score", "team_h", "team_a"]:
        if col not in fx.columns:
            return {}
        fx[col] = pd.to_numeric(fx[col], errors="coerce")

    fx = fx[
        fx["team_h_score"].notna()
        & fx["team_a_score"].notna()
        & fx["team_h"].notna()
        & fx["team_a"].notna()
    ].copy()
    if fx.empty:
        return {}

    if "kickoff_time" in fx.columns:
        fx["kickoff_time"] = pd.to_datetime(fx["kickoff_time"], errors="coerce", utc=True)
    else:
        fx["kickoff_time"] = pd.NaT

    home = pd.DataFrame(
        {
            "team_id": fx["team_h"].astype(int),
            "event": fx["event"].astype(int),
            "kickoff_time": fx["kickoff_time"],
            "points": ((fx["team_h_score"] > fx["team_a_score"]).astype(int) * 3)
            + ((fx["team_h_score"] == fx["team_a_score"]).astype(int) * 1),
        }
    )
    away = pd.DataFrame(
        {
            "team_id": fx["team_a"].astype(int),
            "event": fx["event"].astype(int),
            "kickoff_time": fx["kickoff_time"],
            "points": ((fx["team_a_score"] > fx["team_h_score"]).astype(int) * 3)
            + ((fx["team_a_score"] == fx["team_h_score"]).astype(int) * 1),
        }
    )
    tm = pd.concat([home, away], ignore_index=True)
    tm = tm.sort_values(["team_id", "event", "kickoff_time"]).reset_index(drop=True)

    n = max(config.PROJ_LATEST_N_MIN, min(config.PROJ_LATEST_N_MAX, int(latest_n_matches or config.PROJ_DEFAULT_LATEST_N_MATCHES)))
    out = {}
    for team_id, g in tm.groupby("team_id"):
        tail = g.tail(n)
        out[int(team_id)] = float(pd.to_numeric(tail["points"], errors="coerce").fillna(0.0).mean())
    return out


def load_latest_player_gw_history(path=None, base_dir="data/processed/fpl"):
    """Load and cache the latest player-by-GW history file when available."""
    selected_path = str(path or find_latest_gw_history(base_dir=base_dir) or "")
    if not selected_path:
        return None

    fp = Path(selected_path)
    if not fp.exists():
        return None

    mtime = fp.stat().st_mtime
    cached = _PLAYER_GW_HISTORY_CACHE
    if cached.get("path") == selected_path and cached.get("mtime") == mtime and cached.get("data") is not None:
        return cached["data"].copy()

    try:
        df = pd.read_csv(fp)
    except Exception:
        return None

    required = ["player_id", "gw", "gw_total_points", "gw_fixture_count"]
    if any(col not in df.columns for col in required):
        return None

    df = df.copy()
    for col in ["player_id", "gw", "gw_total_points", "gw_fixture_count", "gw_minutes", "gw_starts"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df[df["player_id"].notna() & df["gw"].notna()].copy()
    if df.empty:
        return None

    df["player_id"] = df["player_id"].astype(int)
    df["gw"] = df["gw"].astype(int)
    df = df.sort_values(["player_id", "gw"]).reset_index(drop=True)

    cached["path"] = selected_path
    cached["mtime"] = mtime
    cached["data"] = df
    return df.copy()


def player_recent_gw_map(gw_start, window=None, history_df=None, base_dir="data/processed/fpl"):
    """
    Build recent player-by-GW averages before `gw_start`.
    Uses GW-level rows so missed/zero-minute weeks count when present.
    """
    hist = history_df if history_df is not None else load_latest_player_gw_history(base_dir=base_dir)
    if hist is None or hist.empty:
        return pd.DataFrame()

    gw_start = int(gw_start)
    window = max(1, int(window or getattr(config, "PROJ_PLAYER_RECENT_GW_WINDOW", 5) or 5))

    df = hist[hist["gw"] < gw_start].copy()
    if df.empty:
        return pd.DataFrame()

    history_max_gw = int(pd.to_numeric(df["gw"], errors="coerce").max())
    df = df.sort_values(["player_id", "gw"]).groupby("player_id", group_keys=False).tail(window)
    if df.empty:
        return pd.DataFrame()

    agg_map = {
        "gw_total_points": "mean",
        "gw_fixture_count": "mean",
        "gw": ["count", "max"],
    }
    if "gw_minutes" in df.columns:
        agg_map["gw_minutes"] = "mean"
    if "gw_starts" in df.columns:
        agg_map["gw_starts"] = "mean"

    out = df.groupby("player_id", dropna=False).agg(agg_map)
    out.columns = ["_".join(str(x) for x in tup if x) for tup in out.columns.to_flat_index()]
    out = out.reset_index().rename(
        columns={
            "gw_total_points_mean": "recent_gw_avg_points",
            "gw_fixture_count_mean": "recent_gw_avg_fixture_count",
            "gw_count": "recent_gw_samples",
            "gw_max": "recent_gw_last",
            "gw_minutes_mean": "recent_gw_avg_minutes",
            "gw_starts_mean": "recent_gw_avg_starts",
        }
    )
    out["recent_history_window_gws"] = int(window)
    out["recent_history_max_gw"] = int(history_max_gw)
    return out


def team_gw_context_multipliers(fixtures, gw, team_recent_ppg):
    """
    Per-team multipliers for a specific GW:
      - home_away_mult: home advantage / away penalty
      - opp_form_mult: weaker opponent boosts xPts
      - team_form_mult: in-form own team boosts xPts
    """
    by_team = transforms.fixtures_by_team_for_gw(fixtures, int(gw))
    out = {}
    neutral_ppg = float(config.PROJ_NEUTRAL_TEAM_PPG)

    for team_id, lst in by_team.items():
        if not lst:
            out[int(team_id)] = {"home_away_mult": 1.0, "opp_form_mult": 1.0, "team_form_mult": 1.0}
            continue

        home_away = []
        opp_ppg = []
        for it in lst:
            home_away.append(float(config.PROJ_HOME_MULT_HOME) if bool(it.get("is_home")) else float(config.PROJ_HOME_MULT_AWAY))
            opp = int(it.get("opp"))
            opp_ppg.append(float(team_recent_ppg.get(opp, neutral_ppg)))

        own_ppg = float(team_recent_ppg.get(int(team_id), neutral_ppg))
        home_away_mult = sum(home_away) / float(len(home_away))
        opp_ppg_avg = sum(opp_ppg) / float(len(opp_ppg)) if opp_ppg else neutral_ppg

        opp_form_mult = clamp(
            1.0 + (neutral_ppg - opp_ppg_avg) * float(config.PROJ_OPP_FORM_FACTOR),
            float(config.PROJ_OPP_FORM_MIN),
            float(config.PROJ_OPP_FORM_MAX),
        )
        team_form_mult = clamp(
            1.0 + (own_ppg - neutral_ppg) * float(config.PROJ_TEAM_FORM_FACTOR),
            float(config.PROJ_TEAM_FORM_MIN),
            float(config.PROJ_TEAM_FORM_MAX),
        )

        out[int(team_id)] = {
            "home_away_mult": float(home_away_mult),
            "opp_form_mult": float(opp_form_mult),
            "team_form_mult": float(team_form_mult),
        }

    return out


def project_elements_next_gws(
    elements,
    fixtures,
    teams_short_map,
    gw_start,
    horizon_gws=3,
    ppg_weight=config.PROJ_DEFAULT_PPG_WEIGHT,
    form_weight=config.PROJ_DEFAULT_FORM_WEIGHT,
    latest_n_matches=config.PROJ_DEFAULT_LATEST_N_MATCHES,
):
    """
    Lightweight next-N gameweeks projection table (FPL-only baseline).

    - Uses `ep_next` for the first GW when available, blended with recent-GW player history.
    - Falls back to a simple `ppg+form` baseline when no recent history is available.
    - Adjusts for fixture difficulty and doubles/blanks.
    - Applies playing probability (chance_of_playing_next_round) for the immediate GW only.
    """
    gw_start = int(gw_start)
    horizon_gws = int(horizon_gws)
    gws = [gw_start + i for i in range(horizon_gws)]

    df = elements.copy()
    latest_n_matches = max(
        config.PROJ_LATEST_N_MIN,
        min(config.PROJ_LATEST_N_MAX, int(latest_n_matches or config.PROJ_DEFAULT_LATEST_N_MATCHES)),
    )
    base_fallback = baseline_points_per_gw(
        df,
        ppg_weight=ppg_weight,
        form_weight=form_weight,
        latest_n_matches=latest_n_matches,
    )

    recent_window = max(1, int(getattr(config, "PROJ_PLAYER_RECENT_GW_WINDOW", 5) or 5))
    recent_min_samples = max(1, int(getattr(config, "PROJ_PLAYER_RECENT_MIN_SAMPLES", 2) or 2))
    recent_blend_weight = clamp(getattr(config, "PROJ_PLAYER_RECENT_BLEND_WEIGHT", 0.65), 0.0, 1.0)
    ep_next_blend_weight = clamp(getattr(config, "PROJ_EP_NEXT_BLEND_WEIGHT", 0.45), 0.0, 1.0)

    recent_gw = player_recent_gw_map(gw_start=gw_start, window=recent_window)
    recent_history_max_gw = None
    if recent_gw is not None and not recent_gw.empty:
        if "recent_history_max_gw" in recent_gw.columns:
            non_null_hist_gw = pd.to_numeric(recent_gw["recent_history_max_gw"], errors="coerce").dropna()
            if not non_null_hist_gw.empty:
                recent_history_max_gw = int(non_null_hist_gw.max())
        df = df.merge(recent_gw, left_on="id", right_on="player_id", how="left")
        df = df.drop(columns=["player_id"], errors="ignore")
    else:
        df["recent_gw_avg_points"] = pd.NA
        df["recent_gw_avg_fixture_count"] = pd.NA
        df["recent_gw_samples"] = pd.NA
        df["recent_gw_last"] = pd.NA
        df["recent_gw_avg_minutes"] = pd.NA
        df["recent_gw_avg_starts"] = pd.NA
        df["recent_history_window_gws"] = int(recent_window)
        df["recent_history_max_gw"] = pd.NA

    recent_avg_points = pd.to_numeric(df.get("recent_gw_avg_points"), errors="coerce")
    recent_samples = pd.to_numeric(df.get("recent_gw_samples"), errors="coerce").fillna(0.0)
    has_recent_history = recent_avg_points.notna() & (recent_samples >= float(recent_min_samples))
    recent_player_base = recent_avg_points.where(has_recent_history, base_fallback)
    blended_base = (
        recent_player_base * float(recent_blend_weight)
        + base_fallback * float(1.0 - recent_blend_weight)
    ).where(has_recent_history, base_fallback)

    df["baseline_long_term_xpts"] = base_fallback.round(3)
    df["baseline_recent_gw_xpts"] = recent_avg_points.round(3)
    df["baseline_blended_xpts"] = blended_base.round(3)
    df["recent_history_available"] = has_recent_history.astype(bool)

    if "ep_next" in df.columns:
        ep_next = pd.to_numeric(df["ep_next"], errors="coerce")
    else:
        ep_next = pd.Series(pd.NA, index=df.index)
    ep_next_only = ep_next.where(ep_next.notna(), blended_base).fillna(0.0)
    base_gw0 = (
        ep_next_only * float(ep_next_blend_weight)
        + blended_base * float(1.0 - ep_next_blend_weight)
    ).where(has_recent_history & ep_next.notna(), ep_next_only)
    df["baseline_gw1_xpts"] = base_gw0.round(3)
    if recent_history_max_gw is not None:
        df["recent_history_max_gw"] = int(recent_history_max_gw)

    if "chance_of_playing_next_round" in df.columns:
        chance_next = pd.to_numeric(df["chance_of_playing_next_round"], errors="coerce")
        play_prob = (chance_next / 100.0).fillna(1.0).clip(lower=0.0, upper=1.0)
    else:
        play_prob = pd.Series(1.0, index=df.index)

    team_recent_ppg = team_recent_ppg_map(fixtures, gw_start=gw_start, latest_n_matches=latest_n_matches)

    horizon_total = pd.Series(0.0, index=df.index, dtype="float64")

    for i, gw in enumerate(gws):
        ann = transforms.annotate_elements_with_gw_fixtures(df, fixtures, int(gw), teams_short_map)
        fixture_count = pd.to_numeric(ann["gw_fixture_count"], errors="coerce").fillna(0.0)
        diff_avg = pd.to_numeric(ann["gw_diff_avg"], errors="coerce").fillna(0.0)
        diff_mult = diff_avg.apply(difficulty_multiplier)

        team_ctx = team_gw_context_multipliers(fixtures, int(gw), team_recent_ppg)
        home_away_mult = ann["team"].apply(
            lambda t: float(team_ctx.get(int(t), {}).get("home_away_mult", 1.0))
            if pd.notna(t)
            else 1.0
        )
        opp_form_mult = ann["team"].apply(
            lambda t: float(team_ctx.get(int(t), {}).get("opp_form_mult", 1.0))
            if pd.notna(t)
            else 1.0
        )
        team_form_mult = ann["team"].apply(
            lambda t: float(team_ctx.get(int(t), {}).get("team_form_mult", 1.0))
            if pd.notna(t)
            else 1.0
        )

        base = base_gw0 if i == 0 else blended_base
        xpts = base * fixture_count * diff_mult * home_away_mult * opp_form_mult * team_form_mult
        if i == 0:
            xpts = xpts * play_prob

        df[f"fixtures_gw{gw}"] = ann["gw_fixtures"].fillna("")
        df[f"fixture_count_gw{gw}"] = fixture_count.astype(int)
        df[f"diff_avg_gw{gw}"] = diff_avg
        df[f"home_away_mult_gw{gw}"] = home_away_mult
        df[f"opp_form_mult_gw{gw}"] = opp_form_mult
        df[f"team_form_mult_gw{gw}"] = team_form_mult
        df[f"xpts_gw{gw}"] = xpts

        horizon_total = horizon_total + xpts.fillna(0.0)

    df["xpts_horizon"] = horizon_total

    keep_base = [
        "id",
        "web_name",
        "pos",
        "team",
        "team_short",
        "team_name",
        "price_m",
        "now_cost",
        "status",
        "chance_of_playing_next_round",
        "form",
        "points_per_game",
        "total_points",
        "selected_by_percent",
        "ep_next",
        "baseline_long_term_xpts",
        "baseline_recent_gw_xpts",
        "baseline_blended_xpts",
        "baseline_gw1_xpts",
        "recent_gw_avg_points",
        "recent_gw_avg_fixture_count",
        "recent_gw_avg_minutes",
        "recent_gw_avg_starts",
        "recent_gw_samples",
        "recent_gw_last",
        "recent_history_window_gws",
        "recent_history_max_gw",
        "recent_history_available",
        "transfers_in_event",
        "transfers_out_event",
        "penalties_order",
        "direct_freekicks_order",
        "corners_and_indirect_freekicks_order",
    ]
    keep = [c for c in keep_base if c in df.columns]
    for gw in gws:
        keep.extend(
            [
                f"xpts_gw{gw}",
                f"fixtures_gw{gw}",
                f"fixture_count_gw{gw}",
                f"diff_avg_gw{gw}",
                f"home_away_mult_gw{gw}",
                f"opp_form_mult_gw{gw}",
                f"team_form_mult_gw{gw}",
            ]
        )
    keep.append("xpts_horizon")

    out = df[[c for c in keep if c in df.columns]].copy()
    out = out.sort_values("xpts_horizon", ascending=False)
    return out


def add_wildcard_scores(projections_df, gw_start, horizon_gws):
    """
    Add a dedicated wildcard score that favors:
      - strong next-fixture runs,
      - future double gameweeks within the horizon,
      - premium captaincy-ready attackers.
    """
    if projections_df is None or projections_df.empty:
        return projections_df

    gw_start = int(gw_start)
    horizon_gws = max(1, int(horizon_gws or 1))
    out = projections_df.copy()

    weights = _weight_list(
        getattr(config, "CHIP_WILDCARD_GW_WEIGHTS", []),
        length=horizon_gws,
        fallback=1.0,
    )
    dgw_bonus_per_extra_fixture = float(getattr(config, "CHIP_WILDCARD_DGW_BONUS_PER_EXTRA_FIXTURE", 1.25) or 1.25)
    dgw_xpts_weight = float(getattr(config, "CHIP_WILDCARD_DGW_XPTS_WEIGHT", 0.12) or 0.12)
    late_dgw_weight_step = float(getattr(config, "CHIP_WILDCARD_LATE_DGW_WEIGHT_STEP", 0.08) or 0.08)

    weighted_xpts = pd.Series(0.0, index=out.index, dtype="float64")
    future_dgw_bonus = pd.Series(0.0, index=out.index, dtype="float64")
    future_extra_fixtures = pd.Series(0.0, index=out.index, dtype="float64")

    for idx in range(horizon_gws):
        gw = int(gw_start) + idx
        xpts = _numeric_series(out, f"xpts_gw{gw}", default=0.0)
        fixture_count = _numeric_series(out, f"fixture_count_gw{gw}", default=0.0)
        extra_fixtures = (fixture_count - 1.0).clip(lower=0.0)
        weighted_xpts = weighted_xpts + (xpts * float(weights[idx]))

        late_weight = 1.0 + float(idx) * late_dgw_weight_step
        future_dgw_bonus = future_dgw_bonus + (
            extra_fixtures * late_weight * (dgw_bonus_per_extra_fixture + (xpts * dgw_xpts_weight))
        )
        future_extra_fixtures = future_extra_fixtures + extra_fixtures

    price_m = _numeric_series(out, "price_m", default=0.0)
    form = _numeric_series(out, "form", default=0.0).clip(lower=0.0)
    penalties_order = _numeric_series(out, "penalties_order", default=99.0)
    next_xpts = _numeric_series(out, f"xpts_gw{gw_start}", default=0.0)

    pos = out.get("pos", pd.Series("", index=out.index)).astype(str)
    is_attacker = pos.isin(["MID", "FWD"]).astype(float)
    pos_mult = pos.map(config.CAPTAIN_POSITION_MULTIPLIER).fillna(1.0).astype(float)

    premium_floor = float(
        getattr(
            config,
            "CHIP_WILDCARD_PREMIUM_ATTACKER_FLOOR",
            getattr(config, "CAPTAIN_PREMIUM_PRICE_FLOOR", 9.0),
        )
        or getattr(config, "CAPTAIN_PREMIUM_PRICE_FLOOR", 9.0)
    )
    premium_base_bonus = float(getattr(config, "CHIP_WILDCARD_PREMIUM_ATTACKER_BASE_BONUS", 0.8) or 0.8)
    captaincy_weight = float(getattr(config, "CHIP_WILDCARD_CAPTAINCY_WEIGHT", 0.32) or 0.32)

    captain_signal = (
        next_xpts * pos_mult
        + ((price_m - premium_floor).clip(lower=0.0) * float(getattr(config, "CAPTAIN_PREMIUM_PRICE_BONUS_PER_M", 0.1)) * is_attacker)
        + (form * float(getattr(config, "CAPTAIN_FORM_CEILING_WEIGHT", 0.04)) * is_attacker)
        + (
            (penalties_order == 1.0).astype(float)
            * float(getattr(config, "CAPTAIN_SET_PIECE_PENALTY_WEIGHT", 0.55))
            * is_attacker
        )
    )
    is_premium_attacker = ((price_m >= premium_floor).astype(float) * is_attacker).astype(float)
    captaincy_bonus = is_premium_attacker * (premium_base_bonus + (captain_signal * captaincy_weight))

    out["wildcard_weighted_xpts"] = weighted_xpts.round(3)
    out["wildcard_future_dgw_bonus"] = future_dgw_bonus.round(3)
    out["wildcard_captaincy_bonus"] = captaincy_bonus.round(3)
    out["wildcard_extra_fixtures"] = future_extra_fixtures.astype(int)
    out["wildcard_score"] = (weighted_xpts + future_dgw_bonus + captaincy_bonus).round(3)
    out = out.sort_values(["wildcard_score", "xpts_horizon"], ascending=[False, False]).reset_index(drop=True)
    return out


def _spearman_rank_corr(a, b):
    """Compute Spearman rank correlation with pandas rank + corr."""
    ar = pd.Series(a).rank(method="average")
    br = pd.Series(b).rank(method="average")
    corr = ar.corr(br)
    if pd.isna(corr):
        return None
    return float(corr)


def find_latest_gw_history(base_dir="data/processed/fpl"):
    """Return latest `player_gw_history_*.csv` file path under base_dir."""
    base = Path(base_dir)
    if not base.exists():
        return None
    paths = list(base.glob("*/player_gw_history_*.csv"))
    if not paths:
        return None
    return str(max(paths, key=lambda p: p.stat().st_mtime))


def evaluate_xpts_history(history_df, window=3, min_gw=2, topk=25):
    """
    Evaluate baseline xPts versus actual GW points from a history DataFrame.

    Expected columns: `player_id`, `gw`, `gw_total_points`, `gw_fixture_count`.
    Optional: `gw_team_difficulty_avg` for difficulty adjustment.
    """
    if history_df is None or history_df.empty:
        return {"ok": False, "error": "Empty history dataset."}

    required = ["player_id", "gw", "gw_total_points", "gw_fixture_count"]
    missing = [c for c in required if c not in history_df.columns]
    if missing:
        return {"ok": False, "error": f"Missing required columns: {missing}"}

    df = history_df.copy()
    df["gw"] = pd.to_numeric(df["gw"], errors="coerce")
    df["player_id"] = pd.to_numeric(df["player_id"], errors="coerce")
    df = df[df["gw"].notna() & df["player_id"].notna()].copy()
    if df.empty:
        return {"ok": False, "error": "No valid rows after cleaning."}

    df["gw"] = df["gw"].astype(int)
    df["player_id"] = df["player_id"].astype(int)
    df["gw_total_points"] = pd.to_numeric(df["gw_total_points"], errors="coerce").fillna(0.0)
    df["gw_fixture_count"] = pd.to_numeric(df["gw_fixture_count"], errors="coerce").fillna(0.0)
    df = df.sort_values(["player_id", "gw"]).reset_index(drop=True)

    window = max(1, int(window or 3))
    min_gw = max(1, int(min_gw or 2))
    topk = max(1, int(topk or 25))

    df["pred_base"] = (
        df.groupby("player_id")["gw_total_points"]
        .apply(lambda s: s.shift(1).rolling(window, min_periods=1).mean())
        .reset_index(level=0, drop=True)
    )

    diff_col = "gw_team_difficulty_avg" if "gw_team_difficulty_avg" in df.columns else None
    if diff_col:
        df["diff_mult"] = pd.to_numeric(df[diff_col], errors="coerce").apply(difficulty_multiplier)
    else:
        df["diff_mult"] = 1.0

    df["pred_xpts"] = df["pred_base"].fillna(0.0) * df["gw_fixture_count"] * df["diff_mult"]
    df["actual"] = df["gw_total_points"]

    eval_df = df[df["gw"] >= int(min_gw)].copy()
    if eval_df.empty:
        return {"ok": False, "error": "No rows available for selected min_gw."}

    eval_df["error"] = eval_df["pred_xpts"] - eval_df["actual"]
    eval_df["abs_error"] = eval_df["error"].abs()
    mae = float(eval_df["abs_error"].mean())
    rmse = float((eval_df["error"] ** 2).mean() ** 0.5)
    bias = float(eval_df["error"].mean())

    per_gw = []
    for gw, gw_df in eval_df.groupby("gw"):
        if len(gw_df) < 10:
            continue
        corr = _spearman_rank_corr(gw_df["pred_xpts"], gw_df["actual"])
        pred_top = set(gw_df.sort_values("pred_xpts", ascending=False).head(topk)["player_id"].astype(int).tolist())
        act_top = set(gw_df.sort_values("actual", ascending=False).head(topk)["player_id"].astype(int).tolist())
        per_gw.append(
            {
                "gw": int(gw),
                "rows": int(len(gw_df)),
                "spearman": corr,
                "topk_overlap": int(len(pred_top.intersection(act_top))),
            }
        )

    avg_spearman = None
    if per_gw:
        vals = [r.get("spearman") for r in per_gw if r.get("spearman") is not None]
        if vals:
            avg_spearman = float(sum(vals) / float(len(vals)))
    avg_topk_overlap = float(sum(r["topk_overlap"] for r in per_gw) / float(len(per_gw))) if per_gw else None

    sample_cols = [c for c in ["player_id", "gw", "pred_xpts", "actual", "error", "abs_error"] if c in eval_df.columns]
    worst_rows = (
        eval_df[sample_cols]
        .sort_values("abs_error", ascending=False)
        .head(25)
        .to_dict(orient="records")
    )

    return {
        "ok": True,
        "summary": {
            "rows_evaluated": int(len(eval_df)),
            "players_evaluated": int(eval_df["player_id"].nunique()),
            "gws_evaluated": int(eval_df["gw"].nunique()),
            "window": int(window),
            "min_gw": int(min_gw),
            "topk": int(topk),
            "mae": mae,
            "rmse": rmse,
            "bias": bias,
            "avg_spearman_per_gw": avg_spearman,
            "avg_topk_overlap_per_gw": avg_topk_overlap,
        },
        "per_gw": per_gw,
        "worst_errors": worst_rows,
    }


def evaluate_xpts_history_file(path=None, base_dir="data/processed/fpl", window=3, min_gw=2, topk=25):
    """Load history CSV and run xPts-vs-actual evaluation metrics."""
    selected_path = path or find_latest_gw_history(base_dir=base_dir)
    if not selected_path:
        return {"ok": False, "error": "No player_gw_history CSV found.", "input_path": None}

    try:
        df = pd.read_csv(selected_path)
    except Exception as exc:
        return {"ok": False, "error": f"Could not read CSV: {exc}", "input_path": str(selected_path)}

    out = evaluate_xpts_history(df, window=window, min_gw=min_gw, topk=topk)
    out["input_path"] = str(selected_path)
    return out
