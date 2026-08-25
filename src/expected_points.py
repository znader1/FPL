"""
Combiner: fixture_difficulty + minutes_model + output_model -> expected points.

Produces a parallel, per-player, per-GW expected-points table (``xpts_model_*``)
that ``projections.project_elements_next_gws`` blends into its baseline output
via ``config.PROJ_MODEL_BLEND_WEIGHT`` (default 0.0, so the baseline is
unchanged until the blend weight is raised).

Pipeline per call:
    1. Load team-match xG -> time-decayed team attack/defense ratings.
    2. Apply the user-maintained knowledge discount.
    3. Load player per-90 xG/xA rates and minutes history (once, reused per GW).
    4. For each GW in the horizon: minutes projection -> output model ->
       ``xpts_model_gwN``.
    5. Sum to ``xpts_model_horizon``.

Everything is dependency-injectable for the backtest; the file loaders return
empty frames when data is missing, in which case the model degrades to a
position-baseline estimate (and the caller can simply not blend it in).
"""
from __future__ import annotations

import pandas as pd

try:
    from . import config, fixture_difficulty, minutes_model, output_model
except Exception:  # pragma: no cover - flat script usage
    import config  # type: ignore
    import fixture_difficulty  # type: ignore
    import minutes_model  # type: ignore
    import output_model  # type: ignore


def build_ratings(asof=None, match_df=None, teams_short_map=None,
                  base_dir="data/processed/fpl", knowledge_path=None):
    """Team attack/defense ratings with the knowledge discount applied."""
    if match_df is None:
        match_df = fixture_difficulty.load_match_history(base_dir=base_dir)
    team_match_xg = fixture_difficulty.build_team_match_xg(match_df)
    ratings = fixture_difficulty.compute_team_ratings(team_match_xg, asof=asof)
    ratings = fixture_difficulty.apply_knowledge_discount(
        ratings, teams_short_map=teams_short_map, path=knowledge_path
    )
    return ratings


def build_expected_points(
    elements,
    fixtures,
    teams_short_map,
    gw_start,
    horizon_gws=3,
    match_df=None,
    minutes_history=None,
    base_dir="data/processed/fpl",
    asof=None,
    knowledge_path=None,
):
    """
    Build the ``xpts_model_*`` table over ``[gw_start, gw_start + horizon - 1]``.

    Returns a DataFrame with one row per element id and columns:
        id, xpts_model_gw{N}..., xpts_model_horizon
    Returns an empty DataFrame (with at least an ``id`` column) when there is no
    xG data to work with, so the caller can no-op the blend.
    """
    gw_start = int(gw_start)
    horizon_gws = max(1, int(horizon_gws))
    gws = [gw_start + i for i in range(horizon_gws)]

    if elements is None or elements.empty or "id" not in elements.columns:
        return pd.DataFrame(columns=["id"])

    if match_df is None:
        match_df = fixture_difficulty.load_match_history(base_dir=base_dir)
    if minutes_history is None:
        minutes_history = minutes_model.load_minutes_history(base_dir=base_dir)

    # No xG history at all -> nothing meaningful to add.
    team_match_xg = fixture_difficulty.build_team_match_xg(match_df)
    if team_match_xg.empty:
        return pd.DataFrame({"id": pd.to_numeric(elements["id"], errors="coerce").dropna().astype(int)})

    ratings = fixture_difficulty.compute_team_ratings(team_match_xg, asof=asof)
    ratings = fixture_difficulty.apply_knowledge_discount(
        ratings, teams_short_map=teams_short_map, path=knowledge_path
    )

    out = pd.DataFrame({"id": pd.to_numeric(elements["id"], errors="coerce")})
    out = out[out["id"].notna()].copy()
    out["id"] = out["id"].astype(int)

    horizon_total = pd.Series(0.0, index=out.index, dtype="float64")
    for gw in gws:
        player_rates = output_model.compute_player_rates(match_df, gw)
        dc_rates = output_model.compute_dc_rates(match_df, gw)
        mins = minutes_model.minutes_projection(elements, minutes_history, gw)
        ep = output_model.expected_points(
            elements, fixtures, ratings, player_rates, mins, gw, dc_rates=dc_rates)

        col = f"xpts_model_gw{gw}"
        if ep is None or ep.empty:
            out[col] = 0.0
        else:
            mapped = out["id"].map(ep["exp_points"]).fillna(0.0)
            out[col] = mapped.values
        horizon_total = horizon_total + out[col].fillna(0.0)

    out["xpts_model_horizon"] = horizon_total.values
    return out


def blend_into_projections(projections_df, model_df, weight, gws):
    """
    Blend ``xpts_model_gw{N}`` into the baseline ``xpts_gw{N}`` columns in place.

    blended = (1 - w) * baseline + w * model, per GW, then ``xpts_horizon`` is
    recomputed as the sum of the blended per-GW columns. The original baseline
    columns are preserved as ``xpts_baseline_gw{N}`` for inspection/backtests.

    No-ops (returns the input unchanged) when ``weight <= 0`` or model is empty.
    """
    if (projections_df is None or projections_df.empty
            or model_df is None or model_df.empty or "id" not in model_df.columns):
        return projections_df
    w = float(weight)
    if w <= 0.0:
        return projections_df
    w = min(1.0, w)

    out = projections_df.copy()
    if "id" not in out.columns:
        return projections_df

    out = out.merge(model_df, on="id", how="left", suffixes=("", "_model"))

    blended_total = None
    for gw in gws:
        base_col = f"xpts_gw{gw}"
        model_col = f"xpts_model_gw{gw}"
        if base_col not in out.columns:
            continue
        base_vals = pd.to_numeric(out[base_col], errors="coerce").fillna(0.0)
        out[f"xpts_baseline_gw{gw}"] = base_vals
        if model_col in out.columns:
            model_vals = pd.to_numeric(out[model_col], errors="coerce").fillna(0.0)
            blended = (1.0 - w) * base_vals + w * model_vals
        else:
            blended = base_vals
        out[base_col] = blended
        blended_total = blended if blended_total is None else (blended_total + blended)

    if blended_total is not None:
        out["xpts_horizon"] = blended_total
        out = out.sort_values("xpts_horizon", ascending=False).reset_index(drop=True)
    return out
