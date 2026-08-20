"""Cold-start adapters that feed output_model.expected_points from last-season
per-90 bootstrap aggregates (retained pre-season).

``rates_from_bootstrap`` and ``minutes_from_bootstrap`` stand in for
``output_model.compute_player_rates`` / ``minutes_model.minutes_projection``
before any current-season match history exists: they read the bootstrap's
carried-over last-season per-90 and appearance totals instead of a decayed
match-history table. Contract notes (confirmed against the real
``output_model.expected_points`` / ``fixture_difficulty`` code, not just the
docstrings):

* ``expected_points`` calls ``player_rates.set_index("player_id")`` itself --
  the frame passed in must have ``player_id`` as a plain column, NOT already
  indexed by it (double-indexing raises ``KeyError``).
* ``expected_points`` reads ``exp_minutes``, ``prob_appear`` **and**
  ``prob_60`` off ``minutes_df`` (not just ``p_start``/``exp_minutes``) --
  ``minutes_from_bootstrap`` must supply all four.
* ``fixture_difficulty.resolve_team_ratings(pd.DataFrame(), teams_short_map=...)``
  degrades cleanly at cold start: with no seed match for a team's short name
  it falls back to the promoted-team defaults; with no seed file at all it
  falls back further to ``compute_team_ratings`` (league-average only). Both
  paths return the same ``{team_id: {"attack":..., "defense":...}, "_league":...}``
  structure ``expected_points`` expects.
"""
import pandas as pd

from src import config, fixture_difficulty, output_model, transforms

_ET_TO_POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _pos(row):
    if row.get("pos") in ("GKP", "DEF", "MID", "FWD"):
        return row["pos"]
    return _ET_TO_POS.get(int(row.get("element_type", 3)), "MID")


def rates_from_bootstrap(elements):
    """
    Cold-start per-90 xG/xA rates from the bootstrap's carried-over last-season
    aggregates (``expected_goals_per_90`` / ``expected_assists_per_90``),
    shrunk toward the position baseline by minutes played -- mirrors
    ``output_model.compute_player_rates``'s shrinkage so it satisfies
    ``expected_points``'s ``player_rates`` contract.

    Returns one row per input row, columns: player_id, xg90, xa90,
    minutes_sample, pos.
    """
    df = elements.copy()
    mins = pd.to_numeric(df.get("minutes"), errors="coerce").fillna(0.0)
    xg90_raw = pd.to_numeric(df.get("expected_goals_per_90"), errors="coerce").fillna(0.0)
    xa90_raw = pd.to_numeric(df.get("expected_assists_per_90"), errors="coerce").fillna(0.0)
    pos = df.apply(_pos, axis=1)

    base_xg = getattr(config, "OUTPUT_POSITION_BASE_XG90", {})
    base_xa = getattr(config, "OUTPUT_POSITION_BASE_XA90", {})
    min_trust = float(getattr(config, "OUTPUT_MIN_MINUTES_TRUST", 270.0) or 270.0)
    conf = (mins / min_trust).clip(upper=1.0) if min_trust > 0 else pd.Series(1.0, index=df.index)

    xg90 = conf * xg90_raw + (1.0 - conf) * pos.map(lambda pp: float(base_xg.get(pp, 0.1)))
    xa90 = conf * xa90_raw + (1.0 - conf) * pos.map(lambda pp: float(base_xa.get(pp, 0.1)))

    return pd.DataFrame({
        "player_id": pd.to_numeric(df["id"], errors="coerce"),
        "xg90": xg90.clip(lower=0.0),
        "xa90": xa90.clip(lower=0.0),
        "minutes_sample": mins,
        "pos": pos,
    })


def minutes_from_bootstrap(elements, season_matches=None):
    """
    Cold-start minutes projection from the bootstrap's carried-over
    last-season ``minutes``/``starts`` totals (proxy for
    ``minutes_model.minutes_projection`` before any current-season history
    exists). ``expected_points`` reads ``exp_minutes``, ``prob_appear`` and
    ``prob_60`` off this frame, so all three are populated (not just
    ``p_start``/``exp_minutes``). Players with zero last-season minutes AND
    zero starts (no top-flight history to carry over -- new signings,
    promoted-team players) get ``prob_appear``/``prob_60``/``exp_minutes``
    forced to 0.0 rather than the sub-appearance floor, since cold start has
    no signal that they'll feature at all.

    Returns a DataFrame indexed by player id (name ``"id"``), columns:
    p_start, exp_minutes, prob_appear, prob_60.
    """
    df = elements.copy()
    mins = pd.to_numeric(df.get("minutes"), errors="coerce").fillna(0.0)
    starts = pd.to_numeric(df.get("starts"), errors="coerce").fillna(0.0)

    # Denominator: pre-season the bootstrap carries 38-match aggregates; once
    # the season starts FPL resets the stats, so dividing current starts by 38
    # would bury every new first-choice (2 starts after GW2 -> p_start 0.05).
    # In-season callers pass the finished-GW count; a pseudo-match of 0.5
    # starts shrinks tiny samples so one GW doesn't overcommit.
    if season_matches is not None and 0 < int(season_matches) < 38:
        n = float(int(season_matches))
        shrink = float(getattr(config, "MINUTES_INSEASON_SHRINK_PSEUDO", 1.0))
        p_start = ((starts + 0.5 * shrink) / (n + shrink)).clip(0.0, 1.0)
    else:
        # Pre-season: last season had up to 38 apps.
        p_start = (starts / 38.0).clip(0.0, 1.0)
    avg_min_when_start = (mins / starts.where(starts > 0, other=1)).clip(0.0, 90.0)
    exp_minutes = (p_start * avg_min_when_start).clip(0.0, 90.0)

    sub_app_prob = float(getattr(config, "MINUTES_SUB_APP_PROB", 0.45))
    p60_given_start = float(getattr(config, "MINUTES_P60_GIVEN_START", 0.86))
    prob_appear = (p_start + (1.0 - p_start) * sub_app_prob).clip(0.0, 1.0)
    prob_60 = (p_start * p60_given_start).clip(0.0, 1.0)

    # Cold-start unknowns: a player with zero last-season minutes AND zero
    # starts (new signing / promoted-team player with no top-flight history)
    # has no basis for the sub-appearance probability floor -- without this
    # guard they'd get prob_appear~=sub_app_prob (phantom appearance points)
    # despite exp_minutes==0. Players with any minutes are untouched.
    no_history = (mins == 0.0) & (starts == 0.0)
    exp_minutes = exp_minutes.mask(no_history, 0.0)
    prob_appear = prob_appear.mask(no_history, 0.0)
    prob_60 = prob_60.mask(no_history, 0.0)

    out = pd.DataFrame({
        "p_start": p_start,
        "exp_minutes": exp_minutes,
        "prob_appear": prob_appear,
        "prob_60": prob_60,
    })
    ids = pd.to_numeric(df["id"], errors="coerce")
    out = out[ids.notna()].copy()
    out.index = ids[ids.notna()].astype(int)
    out.index.name = "id"
    return out[~out.index.duplicated(keep="last")]


def season_matches_from_fixtures(fixtures):
    """Count fully finished GWs in the fixtures frame — the in-season
    denominator for ``minutes_from_bootstrap``. Returns None pre-season
    (no finished GW), which keeps the 38-match carryover behaviour."""
    if fixtures is None or len(fixtures) == 0:
        return None
    if "finished" not in fixtures.columns or "event" not in fixtures.columns:
        return None
    fin = fixtures.groupby("event")["finished"].all()
    n = int(fin.sum())
    return n if n > 0 else None


def _nudges_to_discount(team_nudges):
    """Convert [{team_short, attack, defense}] to the knowledge_discount 'teams' dict."""
    if not team_nudges:
        return None
    teams = {}
    for n in team_nudges:
        if not isinstance(n, dict):
            continue
        key = n.get("team_short")
        if not key:
            continue
        entry = {}
        if n.get("attack") is not None:
            entry["attack"] = float(n["attack"])
        if n.get("defense") is not None:
            entry["defense"] = float(n["defense"])
        if entry:
            teams[str(key)] = entry
    return {"teams": teams} if teams else None


def _ratings(elements, teams_short, team_nudges=None):
    """Cold-start team attack/defense ratings: prior-season carryover seed (or
    promoted defaults where a team has no seed entry) blended with either the
    per-request ``team_nudges`` (when given) or the manual knowledge-discount
    file (default). Both calls degrade gracefully with an empty current-season
    xG frame."""
    ratings = fixture_difficulty.resolve_team_ratings(pd.DataFrame(), teams_short_map=teams_short)
    # Sharpen the flat carryover defenses with last season's clean-sheet record
    # BEFORE the manual nudges, so user overrides stay the final word.
    ratings = fixture_difficulty.apply_cs_prior(ratings, elements)
    discount = _nudges_to_discount(team_nudges)
    ratings = fixture_difficulty.apply_knowledge_discount(
        ratings, discount=discount, teams_short_map=teams_short)
    return ratings


def xg_projection(elements, fixtures, teams_short, gw_start, horizon, blend_weight=0.0, ppg_proj=None,
                   team_nudges=None):
    """
    Per-GW expected points via ``output_model.expected_points``, fed by the
    two cold-start adapters above. Returns one row per input row with an
    ``xpts_gw{N}`` column for each GW in ``[gw_start, gw_start+horizon)``,
    a ``fixture_count_gw{N}`` column per GW, plus all original ``elements``
    columns passed through (so downstream squad-building code -- which reads
    ``team``, ``price_m``, ``pos``, ``web_name``, ``penalties_order``,
    ``selected_by_percent``, etc. -- keeps working regardless of basis).

    Whenever ``ppg_proj`` is given (and non-empty), each ``xpts_gw{N}``
    becomes
        blend_weight * xg_value + (1 - blend_weight) * ppg_value
    ``blend_weight=0.0`` is a pure-ppg passthrough; ``blend_weight=1.0`` is a
    pure-xg passthrough -- this is how the "xg" basis (as opposed to "blend")
    reuses this same code path (it always passes ``blend_weight=1.0``, so the
    ``ppg_value`` term is zeroed out regardless of what ``ppg_proj`` holds).
    """
    gw_start = int(gw_start)
    horizon = max(1, int(horizon))
    gw_range = [gw_start + i for i in range(horizon)]

    rates = rates_from_bootstrap(elements)
    rates = rates.dropna(subset=["player_id"]).copy()
    rates["player_id"] = rates["player_id"].astype(int)
    # Guard against duplicate ids: output_model.expected_points does
    # rates.loc[pid, "xg90"] after set_index, which returns a Series (not a
    # scalar) on a non-unique index and would raise inside float(...).
    rates = rates.drop_duplicates(subset=["player_id"], keep="last")

    minutes_df = minutes_from_bootstrap(
        elements, season_matches=season_matches_from_fixtures(fixtures))
    ratings = _ratings(elements, teams_short, team_nudges)

    base = elements.copy()
    base["id"] = pd.to_numeric(base["id"], errors="coerce")
    out = base.copy()

    for idx in range(horizon):
        gw = gw_start + idx
        ann = transforms.annotate_elements_with_gw_fixtures(base, fixtures, gw, teams_short)
        out[f"fixture_count_gw{gw}"] = pd.to_numeric(
            ann["gw_fixture_count"], errors="coerce").fillna(0).astype(int)

        ep = output_model.expected_points(base, fixtures, ratings, rates, minutes_df, gw)
        col = f"xpts_gw{gw}"
        if ep is not None and not ep.empty and "exp_points" in ep.columns:
            ep_map = pd.to_numeric(ep["exp_points"], errors="coerce").to_dict()
            out[col] = out["id"].map(ep_map).fillna(0.0)
        else:
            out[col] = 0.0

    if ppg_proj is not None and not ppg_proj.empty:
        w = float(blend_weight)
        pm = ppg_proj.drop_duplicates("id").set_index("id")
        for idx in range(horizon):
            gw = gw_start + idx
            col = f"xpts_gw{gw}"
            if col in ppg_proj.columns:
                ppg_col = out["id"].map(pd.to_numeric(pm[col], errors="coerce").to_dict()).fillna(0.0)
            else:
                ppg_col = 0.0
            out[col] = w * out[col] + (1.0 - w) * ppg_col

    # projections.add_wildcard_scores (called right after basis routing in
    # build_squad_from_frames, before it recomputes its own xpts_horizon)
    # sorts on "xpts_horizon" and requires it to already be present -- mirror
    # project_elements_next_gws, which sets it before returning.
    xpts_cols = [f"xpts_gw{gw}" for gw in gw_range]
    out["xpts_horizon"] = out[xpts_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).sum(axis=1)

    return out
