"""
Adapter: convert Vaastav historical data into the DataFrame shape that
src/projections.py expects, so the real engine can be backtested without
needing the live FPL API.

Returns (elements, fixtures, teams_short_map, history_df) for a target GW.
History is capped at gw < target_gw so the engine never peeks at the future.
"""
from __future__ import annotations
import pandas as pd
import numpy as np

from . import backtest_data


POSITION_MAP = {"GKP": "GKP", "GK": "GKP", "DEF": "DEF", "MID": "MID", "FWD": "FWD"}
POSITION_TO_ELEMENT_TYPE = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}


def _team_name_to_id_map(teams: pd.DataFrame) -> dict:
    return dict(zip(teams["name"], teams["id"]))


def _team_short_map(teams: pd.DataFrame) -> dict:
    return dict(zip(teams["id"].astype(int), teams["short_name"]))


def build_history_df(target_gw: int, season: str = "2025-26") -> pd.DataFrame:
    """
    Build the history DataFrame that projections.player_recent_gw_map expects.
    Required columns: player_id, gw, gw_total_points, gw_minutes, gw_starts,
    gw_fixture_count, gw_team_id_end, gw_team_difficulty_avg.
    Only includes GWs < target_gw.
    """
    history_long = backtest_data.player_actuals_through(target_gw - 1, season)
    if history_long.empty:
        return pd.DataFrame()

    teams = backtest_data.load_teams(season)
    team_name_to_id = _team_name_to_id_map(teams)
    fixtures = backtest_data.load_fixtures(season)

    # Build per (team_id, gw) fixture count + average difficulty
    fx_rows = []
    for _, fx in fixtures.iterrows():
        ev = pd.to_numeric(fx.get("event"), errors="coerce")
        if pd.isna(ev):
            continue
        fx_rows.append({"team_id": int(fx["team_h"]), "gw": int(ev), "diff": fx["team_h_difficulty"]})
        fx_rows.append({"team_id": int(fx["team_a"]), "gw": int(ev), "diff": fx["team_a_difficulty"]})
    fx_df = pd.DataFrame(fx_rows)
    fx_grouped = (
        fx_df.groupby(["team_id", "gw"])
        .agg(gw_fixture_count=("diff", "count"), gw_team_difficulty_avg=("diff", "mean"))
        .reset_index()
    )

    df = history_long.copy()
    df["player_id"] = pd.to_numeric(df["element"], errors="coerce").astype("Int64")
    df["gw"] = pd.to_numeric(df["gw"], errors="coerce").astype(int)
    df["gw_total_points"] = pd.to_numeric(df["total_points"], errors="coerce").fillna(0)
    df["gw_minutes"] = pd.to_numeric(df["minutes"], errors="coerce").fillna(0)
    if "starts" in history_long.columns:
        df["gw_starts"] = pd.to_numeric(history_long["starts"], errors="coerce").fillna(0).astype(int).values
    else:
        df["gw_starts"] = (df["gw_minutes"] >= 60).astype(int)  # fallback proxy

    df["gw_team_id_end"] = df["team"].map(team_name_to_id).astype("Int64")

    df = df.merge(fx_grouped, left_on=["gw_team_id_end", "gw"], right_on=["team_id", "gw"], how="left")
    df["gw_fixture_count"] = df["gw_fixture_count"].fillna(0).astype(int)
    df["gw_team_difficulty_avg"] = df["gw_team_difficulty_avg"].fillna(3.0)

    cols = [
        "player_id", "gw", "gw_total_points", "gw_minutes", "gw_starts",
        "gw_fixture_count", "gw_team_id_end", "gw_team_difficulty_avg",
    ]
    return df[cols].copy()


def build_elements_df(target_gw: int, season: str = "2025-26") -> pd.DataFrame:
    """
    Build the elements DataFrame the engine expects.
    Required columns: id, web_name, team, element_type, now_cost,
    points_per_game, form, ep_next, ep_this, status, chance_of_playing_next_round,
    minutes, total_points, selected_by_percent, transfers_in_event, transfers_out_event.
    Derive these from history up to gw < target_gw.
    """
    history = backtest_data.player_actuals_through(target_gw - 1, season)
    if history.empty:
        return pd.DataFrame()

    teams = backtest_data.load_teams(season)
    team_name_to_id = _team_name_to_id_map(teams)

    # Latest snapshot of each player (most recent GW we have)
    latest = history.sort_values("gw").groupby("element").tail(1).reset_index(drop=True)

    # Aggregate season totals up to target_gw - 1
    agg = history.groupby("element").agg(
        total_points=("total_points", "sum"),
        total_minutes=("minutes", "sum"),
        games=("gw", "count"),
    ).reset_index()

    # Form: average points last 4 GWs
    form_window_lo = max(1, target_gw - 4)
    form_window = history[history["gw"] >= form_window_lo]
    form = form_window.groupby("element")["total_points"].mean().reset_index().rename(columns={"total_points": "form"})

    df = latest[["element", "name", "team", "position", "price_m"]].copy()
    df = df.merge(agg, on="element", how="left")
    df = df.merge(form, on="element", how="left")
    df["form"] = df["form"].fillna(0)

    df["id"] = df["element"].astype(int)
    df["web_name"] = df["name"]
    df["team"] = df["team"].map(team_name_to_id).fillna(0).astype(int)
    df["pos"] = df["position"].map(POSITION_MAP).fillna(df["position"])
    df["element_type"] = df["pos"].map(POSITION_TO_ELEMENT_TYPE).fillna(3).astype(int)
    df["now_cost"] = (pd.to_numeric(df["price_m"], errors="coerce").fillna(4.0) * 10).astype(int)
    df["points_per_game"] = df["total_points"] / df["games"].clip(lower=1)
    df["ep_next"] = 0.0  # not used (we disabled ep_next blending in config)
    df["ep_this"] = 0.0
    df["status"] = "a"  # assume available (Vaastav doesn't track this historically)
    df["chance_of_playing_next_round"] = 100
    df["chance_of_playing_this_round"] = 100
    df["minutes"] = df["total_minutes"].fillna(0).astype(int)
    df["selected_by_percent"] = 5.0  # placeholder
    df["transfers_in_event"] = 0
    df["transfers_out_event"] = 0
    df["news"] = ""
    df["event_points"] = 0
    df["penalties_order"] = pd.NA
    df["direct_freekicks_order"] = pd.NA
    df["corners_and_indirect_freekicks_order"] = pd.NA

    keep = [
        "id", "web_name", "team", "element_type", "pos", "now_cost",
        "points_per_game", "form", "ep_next", "ep_this", "status",
        "chance_of_playing_next_round", "chance_of_playing_this_round",
        "minutes", "total_points", "selected_by_percent",
        "transfers_in_event", "transfers_out_event", "news", "event_points",
        "penalties_order", "direct_freekicks_order", "corners_and_indirect_freekicks_order",
    ]
    return df[keep].copy()


def build_fixtures_df(target_gw: int, season: str = "2025-26", horizon: int = 3) -> pd.DataFrame:
    """
    Fixtures for the projection horizon: GWs [target_gw, target_gw+horizon-1].
    """
    fx = backtest_data.load_fixtures(season).copy()
    fx["event"] = pd.to_numeric(fx["event"], errors="coerce")
    fx = fx[fx["event"].notna()].copy()
    fx["event"] = fx["event"].astype(int)
    fx = fx[(fx["event"] >= target_gw) & (fx["event"] < target_gw + horizon)].copy()
    return fx


def build_engine_inputs(target_gw: int, season: str = "2025-26", horizon: int = 3):
    """
    Returns (elements, fixtures, teams_short_map, history_df) ready to pass to
    src.projections.project_elements_next_gws(...).
    """
    history_df = build_history_df(target_gw, season)
    elements = build_elements_df(target_gw, season)
    fixtures = build_fixtures_df(target_gw, season, horizon)
    teams = backtest_data.load_teams(season)
    teams_short_map = _team_short_map(teams)
    return elements, fixtures, teams_short_map, history_df
