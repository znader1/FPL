"""
xG-based team strength ratings with time decay and a manual knowledge discount.

This module turns per-match expected-goals data (from the processed
``player_match_history`` table) into per-team **attack** and **defense** ratings,
expressed as multipliers around the league average:

    attack_rating  > 1.0  => scores more xG than an average team
    defense_rating > 1.0  => concedes more xG than an average team (i.e. weaker)

Recent matches are weighted more heavily via an exponential time decay, and a
user-maintained JSON file (``data/models/knowledge_discount.json``) can nudge
individual teams up or down to encode information the xG history can't see yet
(new signings, injuries to key players, a manager change, etc.).

Ratings then drive a per-fixture expected-xG estimate, consumed by
``output_model.py`` to scale player attacking output and clean-sheet odds.

Design notes
------------
* DataFrame-in / DataFrame-out so the backtest harness can inject data.
* Loaders degrade gracefully (return empty) when files are absent, so callers
  must tolerate empty inputs.
* All tunables live in ``config`` (``FDR_*``) and are read with ``getattr``.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from . import config
except Exception:  # pragma: no cover - flat script usage
    import config  # type: ignore


# ---------------------------------------------------------------------------
# Loading / aggregation
# ---------------------------------------------------------------------------

def find_latest_match_history(base_dir="data/processed/fpl"):
    """Return the newest ``player_match_history_*.csv`` path under base_dir."""
    base = Path(base_dir)
    if not base.exists():
        return None
    paths = list(base.glob("*/player_match_history_*.csv"))
    if not paths:
        paths = list(base.glob("player_match_history_*.csv"))
    if not paths:
        return None
    return str(max(paths, key=lambda p: p.stat().st_mtime))


_match_history_cache = {"key": None, "df": None}


def load_match_history(path=None, base_dir="data/processed/fpl"):
    """
    Load the player-match history CSV, or return an empty frame if missing.

    Cached on (path, mtime, size): the squad view and the recommendation view
    both trigger a model build, and re-reading the same file for each one was
    costing ~80ms of every request for nothing. A refresh rewrites the file,
    which changes the key, so the cache cannot serve stale history.
    """
    selected = str(path or find_latest_match_history(base_dir=base_dir) or "")
    if not selected or not Path(selected).exists():
        return pd.DataFrame()
    try:
        stat = Path(selected).stat()
        key = (selected, stat.st_mtime_ns, stat.st_size)
    except OSError:
        key = None
    if key is not None and _match_history_cache["key"] == key:
        return _match_history_cache["df"]
    try:
        df = pd.read_csv(selected)
    except Exception:
        return pd.DataFrame()
    if key is not None:
        _match_history_cache["key"] = key
        _match_history_cache["df"] = df
    return df


def build_team_match_xg(match_df):
    """
    Collapse the player-level match history into one row per (fixture, team).

    Team xG-for is the sum of its players' ``expected_goals`` in that fixture.
    Team xG-against is the opponent's xG-for in the same fixture (cleaner than
    summing the per-player ``expected_goals_conceded`` column, which double
    counts across players).

    Returns columns:
        fixture, team_id, gw, kickoff_time, was_home, xg_for, xg_against
    """
    if match_df is None or match_df.empty:
        return pd.DataFrame()

    df = match_df.copy()
    required = ["fixture", "team_id", "expected_goals"]
    if any(c not in df.columns for c in required):
        return pd.DataFrame()

    df["fixture"] = pd.to_numeric(df["fixture"], errors="coerce")
    df["team_id"] = pd.to_numeric(df["team_id"], errors="coerce")
    df["expected_goals"] = pd.to_numeric(df["expected_goals"], errors="coerce").fillna(0.0)
    df = df[df["fixture"].notna() & df["team_id"].notna()].copy()
    if df.empty:
        return pd.DataFrame()
    df["fixture"] = df["fixture"].astype(int)
    df["team_id"] = df["team_id"].astype(int)

    gw_col = "event" if "event" in df.columns else ("round" if "round" in df.columns else None)
    ko_col = "kickoff_time_x" if "kickoff_time_x" in df.columns else (
        "kickoff_time" if "kickoff_time" in df.columns else None
    )

    agg = {"expected_goals": "sum"}
    grp_cols = ["fixture", "team_id"]
    extra = {}
    if gw_col:
        extra["gw"] = (gw_col, "first")
    if ko_col:
        extra["kickoff_time"] = (ko_col, "first")
    if "was_home" in df.columns:
        extra["was_home"] = ("was_home", "first")

    team_fx = (
        df.groupby(grp_cols)
        .agg(xg_for=("expected_goals", "sum"), **extra)
        .reset_index()
    )

    # xg_against = the *other* team's xg_for within the same fixture.
    opp = team_fx[["fixture", "team_id", "xg_for"]].rename(
        columns={"team_id": "opp_team_id", "xg_for": "xg_against"}
    )
    merged = team_fx.merge(opp, on="fixture")
    merged = merged[merged["team_id"] != merged["opp_team_id"]].copy()
    merged = merged.drop(columns=["opp_team_id"])

    if "gw" in merged.columns:
        merged["gw"] = pd.to_numeric(merged["gw"], errors="coerce")
    if "kickoff_time" in merged.columns:
        merged["kickoff_time"] = pd.to_datetime(merged["kickoff_time"], errors="coerce", utc=True)
    if "was_home" in merged.columns:
        merged["was_home"] = merged["was_home"].astype(bool)

    return merged.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Time decay
# ---------------------------------------------------------------------------

def _decay_weights(timestamps, asof, halflife_days):
    """Exponential half-life weights from match age in days. NaT -> small weight."""
    halflife = max(1e-6, float(halflife_days))
    ts = pd.to_datetime(pd.Series(timestamps), errors="coerce", utc=True)
    asof_ts = pd.to_datetime(asof, utc=True) if asof is not None else ts.max()
    if pd.isna(asof_ts):
        return pd.Series(1.0, index=ts.index, dtype="float64")
    age_days = (asof_ts - ts).dt.total_seconds() / 86400.0
    age_days = age_days.clip(lower=0.0)
    weights = np.power(0.5, age_days / halflife)
    # Matches with no timestamp still count, just lightly.
    weights = weights.where(ts.notna(), 0.25)
    return weights.astype("float64")


# ---------------------------------------------------------------------------
# Ratings
# ---------------------------------------------------------------------------

def _decayed_team_means(team_match_xg, asof=None, halflife_days=None):
    """
    Time-decayed weighted mean xG-for / xG-against per team, plus the weighted
    league average. Returns (means_by_team, league_avg) where means_by_team is
    {team_id: {"xgf": float, "xga": float, "weight": float, "samples": int}}.
    """
    halflife_days = float(halflife_days if halflife_days is not None
                          else getattr(config, "FDR_XG_HALFLIFE_DAYS", 60.0))
    league_fallback = float(getattr(config, "FDR_LEAGUE_AVG_XG_FALLBACK", 1.40))

    if team_match_xg is None or team_match_xg.empty:
        return {}, league_fallback

    df = team_match_xg.copy()
    ts_col = "kickoff_time" if "kickoff_time" in df.columns else None
    df["w"] = _decay_weights(df[ts_col] if ts_col else pd.Series(pd.NaT, index=df.index),
                             asof, halflife_days)

    total_w = float(df["w"].sum())
    if total_w <= 0:
        return {}, league_fallback

    league_avg = float((df["xg_for"] * df["w"]).sum() / total_w)
    if not np.isfinite(league_avg) or league_avg <= 0:
        league_avg = league_fallback

    means = {}
    for team_id, g in df.groupby("team_id"):
        w = g["w"].astype("float64")
        wsum = float(w.sum())
        if wsum <= 0:
            continue
        means[int(team_id)] = {
            "xgf": float((g["xg_for"] * w).sum() / wsum),
            "xga": float((g["xg_against"] * w).sum() / wsum),
            "weight": wsum,
            "samples": int(len(g)),
        }
    return means, league_avg


def compute_team_ratings(team_match_xg, asof=None, halflife_days=None,
                         shrinkage_matches=None, rating_min=None, rating_max=None):
    """
    Decayed, shrunk attack/defense ratings per team (shrunk toward league average).

    Returns a dict keyed by ``team_id``:
        {team_id: {"attack": float, "defense": float,
                   "xg_for": float, "xg_against": float,
                   "samples": float, "weight": float}}
    plus a special key ``"_league"`` with the league-average per-team xG used as
    the rating denominator. For season-start carryover use ``resolve_team_ratings``.
    """
    shrinkage = float(shrinkage_matches if shrinkage_matches is not None
                      else getattr(config, "FDR_XG_SHRINKAGE_MATCHES", 6.0))
    rmin = float(rating_min if rating_min is not None else getattr(config, "FDR_RATING_MIN", 0.5))
    rmax = float(rating_max if rating_max is not None else getattr(config, "FDR_RATING_MAX", 1.8))

    means, league_avg = _decayed_team_means(team_match_xg, asof=asof, halflife_days=halflife_days)
    if not means:
        return {"_league": league_avg}

    ratings = {"_league": league_avg}
    for team_id, m in means.items():
        n_eff = m["weight"]
        denom = n_eff + shrinkage
        xgf_shrunk = (m["xgf"] * n_eff + league_avg * shrinkage) / denom
        xga_shrunk = (m["xga"] * n_eff + league_avg * shrinkage) / denom
        ratings[int(team_id)] = {
            "attack": float(np.clip(xgf_shrunk / league_avg, rmin, rmax)),
            "defense": float(np.clip(xga_shrunk / league_avg, rmin, rmax)),
            "xg_for": xgf_shrunk,
            "xg_against": xga_shrunk,
            "samples": float(m["samples"]),
            "weight": n_eff,
        }
    return ratings


# ---------------------------------------------------------------------------
# Cross-season carryover (season-start cold start)
# ---------------------------------------------------------------------------

def freeze_ratings(ratings, teams_short_map, path, season=None):
    """
    Persist end-of-season ratings as a seed for next season's cold start.

    Keyed by team **short name** (stable across seasons, unlike FPL team ids).
    Returns the written payload.
    """
    teams_short_map = teams_short_map or {}
    teams_block = {}
    for team_id, r in ratings.items():
        if team_id == "_league" or not isinstance(r, dict):
            continue
        short = teams_short_map.get(int(team_id))
        if not short:
            continue
        teams_block[str(short)] = {
            "attack": round(float(r.get("attack", 1.0)), 4),
            "defense": round(float(r.get("defense", 1.0)), 4),
            "xg_for": round(float(r.get("xg_for", 0.0)), 4),
            "xg_against": round(float(r.get("xg_against", 0.0)), 4),
            "samples": float(r.get("samples", 0.0)),
        }
    payload = {
        "season": season,
        "league_avg_xg": round(float(ratings.get("_league", 0.0)), 4),
        "teams": teams_block,
    }
    fp = Path(path)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(payload, indent=2))
    return payload


def load_ratings_seed(path=None):
    """
    Load the prior-season ratings seed. Returns a dict keyed by short name:
        {short: {"attack": float, "defense": float, ...}}
    Empty dict if the file is absent or invalid.
    """
    selected = str(path or getattr(config, "FDR_RATINGS_SEED_PATH",
                                   "data/models/team_ratings_seed.json"))
    fp = Path(selected)
    if not fp.exists():
        return {}
    try:
        payload = json.loads(fp.read_text())
    except Exception:
        return {}
    teams = payload.get("teams", {}) if isinstance(payload, dict) else {}
    return {str(k).upper(): v for k, v in teams.items() if isinstance(v, dict)}


def resolve_team_ratings(team_match_xg, teams_short_map=None, seed=None, seed_path=None,
                         asof=None, halflife_days=None):
    """
    Season-aware ratings that blend current-season xG with the prior-season seed.

    At a season's start ``team_match_xg`` is empty, so every team falls back to
    its regressed prior-season rating; teams with no seed entry (newly promoted)
    get the weak promoted default. As current-season matches accrue, the live
    signal overtakes the prior (pseudo-count ``FDR_CARRYOVER_PRIOR_MATCHES``).

    Requires ``teams_short_map`` ({team_id: short}) to know the current team set
    and to map seed entries (keyed by short name) onto current ids. Without a map
    or a seed it degrades to ``compute_team_ratings`` (live-only).
    """
    if seed is None:
        seed = load_ratings_seed(seed_path)
    # No carryover possible -> live-only behaviour.
    if not teams_short_map or not seed:
        return compute_team_ratings(team_match_xg, asof=asof, halflife_days=halflife_days)

    rmin = float(getattr(config, "FDR_RATING_MIN", 0.5))
    rmax = float(getattr(config, "FDR_RATING_MAX", 1.8))
    prior_matches = float(getattr(config, "FDR_CARRYOVER_PRIOR_MATCHES", 8.0))
    regression = float(getattr(config, "FDR_CARRYOVER_REGRESSION", 0.30))
    promoted_atk = float(getattr(config, "FDR_PROMOTED_DEFAULT_ATTACK", 0.82))
    promoted_def = float(getattr(config, "FDR_PROMOTED_DEFAULT_DEFENSE", 1.20))

    means, league_avg = _decayed_team_means(team_match_xg, asof=asof, halflife_days=halflife_days)

    def _regress(value):
        return 1.0 + (float(value) - 1.0) * (1.0 - regression)

    ratings = {"_league": league_avg}
    for team_id, short in teams_short_map.items():
        team_id = int(team_id)
        seed_entry = seed.get(str(short).upper()) if short else None
        if seed_entry:
            prior_attack = _regress(seed_entry.get("attack", 1.0))
            prior_defense = _regress(seed_entry.get("defense", 1.0))
            source = "carryover"
        else:
            prior_attack = promoted_atk
            prior_defense = promoted_def
            source = "promoted"

        prior_xgf = league_avg * prior_attack
        prior_xga = league_avg * prior_defense

        live = means.get(team_id)
        w = float(live["weight"]) if live else 0.0
        live_xgf = float(live["xgf"]) if live else 0.0
        live_xga = float(live["xga"]) if live else 0.0

        denom = w + prior_matches
        blended_xgf = (live_xgf * w + prior_xgf * prior_matches) / denom
        blended_xga = (live_xga * w + prior_xga * prior_matches) / denom

        if live and w > 0:
            source = "live" if w >= prior_matches else "blend"

        ratings[team_id] = {
            "attack": float(np.clip(blended_xgf / league_avg, rmin, rmax)),
            "defense": float(np.clip(blended_xga / league_avg, rmin, rmax)),
            "xg_for": blended_xgf,
            "xg_against": blended_xga,
            "samples": float(live["samples"]) if live else 0.0,
            "weight": w,
            "source": source,
        }
    return ratings


# ---------------------------------------------------------------------------
# Knowledge discount (user-maintained JSON)
# ---------------------------------------------------------------------------

def load_knowledge_discount(path=None):
    """Load the manual knowledge-discount JSON. Returns {} if absent/invalid."""
    selected = str(path or getattr(config, "FDR_KNOWLEDGE_DISCOUNT_PATH",
                                   "data/models/knowledge_discount.json"))
    fp = Path(selected)
    if not fp.exists():
        return {}
    try:
        return json.loads(fp.read_text())
    except Exception:
        return {}


def apply_cs_prior(ratings, elements, weight=None):
    """
    Blend last season's clean-sheet record into each team's ``defense``
    multiplier. The carried-over xG defense ratings shrink hard toward 1.0,
    which flattens P(clean sheet) across teams; actual CS counts are a sharper
    cold-start signal of defensive quality.

    Per team, the GK rows' summed ``clean_sheets`` over their summed ``starts``
    (the team's matches with a recorded GK start) implies a per-match xGA via
    Poisson inversion ``implied_xga = -ln(CS/matches)``, hence an implied
    defense multiplier ``implied_xga / league_avg``. The new rating is
    ``(1 - weight) * carryover + weight * implied``, clamped like every other
    rating.

    Bootstrap stats reset each season, so early-season samples are tiny and a
    1-CS-in-1-start record would invert the signal; teams with fewer than
    ``FDR_CS_PRIOR_MIN_MATCHES`` GK starts (or zero CS, or no GK rows) are
    left untouched. Pre-season, the carried-over totals (~38 starts) pass the
    gate. Returns a copy of ``ratings``.
    """
    w = float(weight if weight is not None else getattr(config, "FDR_CS_PRIOR_WEIGHT", 0.35))
    out = dict(ratings)
    if w <= 0.0 or elements is None or len(elements) == 0:
        return out
    df = elements
    if "clean_sheets" not in df.columns or "team" not in df.columns:
        return out

    is_gk = pd.to_numeric(df.get("element_type"), errors="coerce") == 1
    gks = df[is_gk]
    if gks.empty:
        return out
    team_key = pd.to_numeric(gks["team"], errors="coerce")
    cs_by_team = (
        pd.to_numeric(gks["clean_sheets"], errors="coerce").fillna(0.0).groupby(team_key).sum()
    )
    starts_by_team = (
        pd.to_numeric(gks.get("starts"), errors="coerce").fillna(0.0).groupby(team_key).sum()
    )

    league = float(out.get("_league", getattr(config, "FDR_LEAGUE_AVG_XG_FALLBACK", 1.40)))
    lo = float(getattr(config, "FDR_RATING_MIN", 0.50))
    hi = float(getattr(config, "FDR_RATING_MAX", 1.80))
    min_matches = float(getattr(config, "FDR_CS_PRIOR_MIN_MATCHES", 6.0))

    for team_id, cs in cs_by_team.items():
        if not np.isfinite(team_id) or cs <= 0:
            continue
        matches = float(starts_by_team.get(team_id, 0.0))
        if matches < min_matches:
            continue
        r = out.get(int(team_id))
        if not isinstance(r, dict):
            continue
        cs_rate = min(float(cs), matches - 1.0) / matches  # avoid ln(0) at a perfect record
        implied_xga = -np.log(cs_rate)
        implied_def = implied_xga / league if league > 0 else 1.0
        blended = (1.0 - w) * float(r.get("defense", 1.0)) + w * float(implied_def)
        out[int(team_id)] = {**r, "defense": float(np.clip(blended, lo, hi))}
    return out


def apply_knowledge_discount(ratings, discount=None, teams_short_map=None, path=None):
    """
    Apply per-team manual attack/defense multipliers from the knowledge file.

    The JSON ``teams`` map may key by numeric team id (as string) or by team
    short name (e.g. ``"ARS"``); ``teams_short_map`` ({id: short}) resolves names.
    Each entry may set ``attack`` and/or ``defense`` multipliers (default 1.0).
    Mutates and returns a copy of ``ratings``.
    """
    disc = discount if discount is not None else load_knowledge_discount(path)
    teams_block = (disc or {}).get("teams", {}) if isinstance(disc, dict) else {}
    if not teams_block:
        return dict(ratings)

    short_to_id = {}
    if teams_short_map:
        short_to_id = {str(v).upper(): int(k) for k, v in teams_short_map.items()}

    rmin = float(getattr(config, "FDR_RATING_MIN", 0.5))
    rmax = float(getattr(config, "FDR_RATING_MAX", 1.8))

    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in ratings.items()}
    for key, adj in teams_block.items():
        if not isinstance(adj, dict):
            continue
        team_id = None
        try:
            team_id = int(key)
        except (TypeError, ValueError):
            team_id = short_to_id.get(str(key).upper())
        if team_id is None or team_id not in out or not isinstance(out[team_id], dict):
            continue
        atk = float(adj.get("attack", 1.0) or 1.0)
        dfn = float(adj.get("defense", 1.0) or 1.0)
        out[team_id]["attack"] = float(np.clip(out[team_id]["attack"] * atk, rmin, rmax))
        out[team_id]["defense"] = float(np.clip(out[team_id]["defense"] * dfn, rmin, rmax))
        out[team_id]["knowledge_attack_mult"] = atk
        out[team_id]["knowledge_defense_mult"] = dfn
    return out


# ---------------------------------------------------------------------------
# Per-fixture expected xG
# ---------------------------------------------------------------------------

def _team_rating(ratings, team_id):
    r = ratings.get(int(team_id)) if team_id is not None else None
    if isinstance(r, dict):
        return float(r.get("attack", 1.0)), float(r.get("defense", 1.0))
    return 1.0, 1.0


def expected_xg_for_fixture(ratings, team_id, opp_id, is_home):
    """
    Expected xG **for** ``team_id`` and **against** it in a single fixture.

    expected_for     = league * attack(team) * defense(opp) * home/away
    expected_against = league * attack(opp)  * defense(team) * away/home

    Returns (expected_for, expected_against).
    """
    league = float(ratings.get("_league", getattr(config, "FDR_LEAGUE_AVG_XG_FALLBACK", 1.40)))
    home_mult = float(getattr(config, "FDR_HOME_XG_MULT", 1.10))
    away_mult = float(getattr(config, "FDR_AWAY_XG_MULT", 0.92))

    atk_t, def_t = _team_rating(ratings, team_id)
    atk_o, def_o = _team_rating(ratings, opp_id)

    team_venue = home_mult if is_home else away_mult
    opp_venue = away_mult if is_home else home_mult

    expected_for = league * atk_t * def_o * team_venue
    expected_against = league * atk_o * def_t * opp_venue
    return float(max(0.0, expected_for)), float(max(0.0, expected_against))


def fixture_difficulty_table(ratings, fixtures, gw):
    """
    Per-team expected xG for a single GW (handles doubles by summing rows).

    Uses ``transforms.fixtures_by_team_for_gw`` to expand fixtures so DGWs and
    blanks are handled the same way the rest of the engine handles them.

    Returns a DataFrame keyed by ``team_id`` with:
        team_id, gw, n_fixtures, xg_for, xg_against,
        opp_defense_rating, own_defense_rating (fixture-count-weighted means)
    """
    try:
        from . import transforms
    except Exception:  # pragma: no cover
        import transforms  # type: ignore

    by_team = transforms.fixtures_by_team_for_gw(fixtures, int(gw)) if fixtures is not None else {}
    rows = []
    for team_id, lst in by_team.items():
        if not lst:
            continue
        xg_for = xg_against = 0.0
        opp_def_sum = own_def_sum = 0.0
        for it in lst:
            opp = int(it.get("opp"))
            is_home = bool(it.get("is_home"))
            ef, ea = expected_xg_for_fixture(ratings, int(team_id), opp, is_home)
            xg_for += ef
            xg_against += ea
            _, def_t = _team_rating(ratings, team_id)
            _, def_o = _team_rating(ratings, opp)
            opp_def_sum += def_o
            own_def_sum += def_t
        n = len(lst)
        rows.append({
            "team_id": int(team_id),
            "gw": int(gw),
            "n_fixtures": int(n),
            "xg_for": float(xg_for),
            "xg_against": float(xg_against),
            "opp_defense_rating": float(opp_def_sum / n) if n else 1.0,
            "own_defense_rating": float(own_def_sum / n) if n else 1.0,
        })
    return pd.DataFrame(rows)


def _difficulty_band(score):
    """Map a 1-5 difficulty score to a (label, color) from config bands."""
    bands = getattr(config, "FDR_TICKER_BANDS", [])
    for entry in bands:
        try:
            ceil, label, color = entry[0], entry[1], entry[2]
        except (IndexError, TypeError):
            continue
        if float(score) <= float(ceil):
            return label, color
    return "medium", "#fee08b"


def attack_difficulty(ratings, team_id, opp_id, is_home):
    """
    1-5 attacking difficulty for ``team_id`` facing ``opp_id`` (higher = harder
    to score), centered near 3.0 like FPL's own FDR. Driven by the opponent's
    defense rating and venue. Opponent that concedes a lot of xG => easier.
    """
    home_mult = float(getattr(config, "FDR_HOME_XG_MULT", 1.10))
    away_mult = float(getattr(config, "FDR_AWAY_XG_MULT", 0.92))
    _, opp_def = _team_rating(ratings, opp_id)
    venue = home_mult if is_home else away_mult
    # opp_def > 1 (leaky) and home venue both lower the difficulty.
    score = 3.0 / max(0.3, opp_def * venue)
    return float(np.clip(score, 1.0, 5.0))


def build_fixture_ticker(ratings, fixtures, teams_short_map, gw_start, horizon_gws=6):
    """
    Per-team fixture-difficulty ticker over ``[gw_start, gw_start+horizon-1]``.

    Returns a dict:
        {
          "gw_start": int, "horizon_gws": int, "gws": [...],
          "teams": [ {team_id, team_short, avg_difficulty, sum_difficulty,
                      n_fixtures, gws: {gw: {opponents:[{opp,home,difficulty,band,color}],
                                            difficulty, count}}} ],
          "easiest_runs": [team_short...], "hardest_runs": [team_short...]
        }
    Teams are returned sorted by ascending average difficulty (best runs first).
    Blank GWs contribute a neutral 3.0 so a team that doesn't play isn't flattered.
    """
    try:
        from . import transforms
    except Exception:  # pragma: no cover
        import transforms  # type: ignore

    gw_start = int(gw_start)
    horizon_gws = max(1, int(horizon_gws))
    gws = [gw_start + i for i in range(horizon_gws)]
    teams_short_map = teams_short_map or {}

    by_gw = {gw: transforms.fixtures_by_team_for_gw(fixtures, gw) if fixtures is not None else {}
             for gw in gws}

    rows = []
    for team_id, short in teams_short_map.items():
        team_id = int(team_id)
        gw_cells = {}
        diffs = []
        n_fix = 0
        for gw in gws:
            lst = by_gw.get(gw, {}).get(team_id, [])
            if not lst:
                gw_cells[gw] = {"opponents": [], "difficulty": None, "count": 0, "blank": True}
                diffs.append(3.0)  # blank GW = neutral, not free
                continue
            opps = []
            cell_diffs = []
            for it in lst:
                opp = int(it.get("opp"))
                is_home = bool(it.get("is_home"))
                d = attack_difficulty(ratings, team_id, opp, is_home)
                label, color = _difficulty_band(d)
                opps.append({
                    "opp_id": opp,
                    "opp_short": teams_short_map.get(opp, "?"),
                    "home": is_home,
                    "difficulty": round(d, 2),
                    "band": label,
                    "color": color,
                })
                cell_diffs.append(d)
            cell_diff = float(np.mean(cell_diffs)) if cell_diffs else 3.0
            n_fix += len(lst)
            gw_cells[gw] = {
                "opponents": opps,
                "difficulty": round(cell_diff, 2),
                "count": len(lst),
                "blank": False,
            }
            diffs.append(cell_diff)

        avg_diff = float(np.mean(diffs)) if diffs else 3.0
        label, color = _difficulty_band(avg_diff)
        rows.append({
            "team_id": team_id,
            "team_short": short,
            "avg_difficulty": round(avg_diff, 2),
            "sum_difficulty": round(float(np.sum(diffs)), 2),
            "n_fixtures": int(n_fix),
            "band": label,
            "color": color,
            "gws": gw_cells,
        })

    rows.sort(key=lambda r: r["avg_difficulty"])
    return {
        "gw_start": gw_start,
        "horizon_gws": horizon_gws,
        "gws": gws,
        "teams": rows,
        "easiest_runs": [r["team_short"] for r in rows[:5]],
        "hardest_runs": [r["team_short"] for r in rows[-5:]][::-1],
    }


def team_ratings_table(ratings):
    """Flatten the ratings dict into a tidy DataFrame (excludes ``_league``)."""
    rows = []
    for team_id, r in ratings.items():
        if team_id == "_league" or not isinstance(r, dict):
            continue
        row = {"team_id": int(team_id)}
        row.update(r)
        rows.append(row)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("attack", ascending=False).reset_index(drop=True)
    return df
