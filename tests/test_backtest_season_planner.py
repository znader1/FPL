"""Pure-function tests for the --planner arm helpers added to
scripts/backtest_season.py (Task 6, transfer-planner-v2 A/B backtest).

Covers:
  - build_planner_proj: reshapes the backtest's per-GW projection frames
    (player_id/name/pos/team/price_m/xpts) into the wide xpts_gw{N} frame
    transfer_planner.plan_transfers expects (id/web_name/team_short naming).
  - _apply_squad_move: the single move-application helper shared by every
    transfer-decision mode (simple, --smart-transfers, --planner).
"""
import pandas as pd

from scripts.backtest_season import build_planner_proj, _apply_squad_move


def _gw_frame(rows):
    """rows: list of (player_id, name, pos, team, price_m, xpts)."""
    return pd.DataFrame(
        rows, columns=["player_id", "name", "pos", "team", "price_m", "xpts"]
    )


def test_build_planner_proj_wide_columns_per_gw():
    horizon_proj = {
        5: _gw_frame([
            (1, "Alice", "MID", "ARS", 8.0, 5.5),
            (2, "Bob", "DEF", "CHE", 5.0, 3.0),
        ]),
        6: _gw_frame([
            (1, "Alice", "MID", "ARS", 8.0, 4.2),
            (2, "Bob", "DEF", "CHE", 5.0, 3.1),
        ]),
    }
    out = build_planner_proj(horizon_proj)

    assert set(out["id"]) == {1, 2}
    assert list(out.columns[:5]) == ["id", "web_name", "pos", "team_short", "price_m"]
    assert "xpts_gw5" in out.columns and "xpts_gw6" in out.columns

    alice = out[out["id"] == 1].iloc[0]
    assert alice["xpts_gw5"] == 5.5
    assert alice["xpts_gw6"] == 4.2
    assert alice["web_name"] == "Alice"
    assert alice["team_short"] == "ARS"


def test_build_planner_proj_handles_player_missing_from_later_gw():
    """A player who drops out of a later GW's frame (e.g. no fixture) still
    appears with the metadata from whichever frame had them, and NaN xpts for
    the GW they were missing from is filled to 0.0 (never left as NaN)."""
    horizon_proj = {
        5: _gw_frame([(1, "Alice", "MID", "ARS", 8.0, 5.5)]),
        6: _gw_frame([(2, "Bob", "DEF", "CHE", 5.0, 3.1)]),
    }
    out = build_planner_proj(horizon_proj)

    assert set(out["id"]) == {1, 2}
    alice = out[out["id"] == 1].iloc[0]
    bob = out[out["id"] == 2].iloc[0]
    assert alice["xpts_gw5"] == 5.5
    assert alice["xpts_gw6"] == 0.0
    assert bob["xpts_gw5"] == 0.0
    assert bob["xpts_gw6"] == 3.1


def test_build_planner_proj_empty_input():
    out = build_planner_proj({})
    assert list(out.columns) == ["id", "web_name", "pos", "team_short", "price_m"]
    assert out.empty


def test_apply_squad_move_swaps_player():
    squad = pd.DataFrame([
        {"player_id": 1, "name": "Alice", "pos": "MID", "team": "ARS", "price_m": 8.0},
        {"player_id": 2, "name": "Bob", "pos": "DEF", "team": "CHE", "price_m": 5.0},
    ])
    market = pd.DataFrame([
        {"player_id": 2, "name": "Bob", "pos": "DEF", "team": "CHE", "price_m": 5.0},
        {"player_id": 3, "name": "Cara", "pos": "MID", "team": "LIV", "price_m": 9.0},
    ])

    new_squad = _apply_squad_move(squad, market, sell_id=1, buy_id=3)

    assert set(new_squad["player_id"]) == {2, 3}
    cara = new_squad[new_squad["player_id"] == 3].iloc[0]
    assert cara["name"] == "Cara"
    assert cara["team"] == "LIV"
    assert cara["price_m"] == 9.0
