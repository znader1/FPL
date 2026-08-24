"""Pure-function tests for the --planner arm helpers added to
scripts/backtest_season.py (Task 6, transfer-planner-v2 A/B backtest).

Covers:
  - build_planner_proj: reshapes the backtest's per-GW projection frames
    (player_id/name/pos/team/price_m/xpts) into the wide xpts_gw{N} frame
    transfer_planner.plan_transfers expects (id/web_name/team_short naming).
  - _apply_squad_move: the single move-application helper shared by every
    transfer-decision mode (simple, --smart-transfers, --planner).
  - run_backtest(planner=True): ft_state must accrue every GW under the
    src/ft_tracker.py rule, INCLUDING wildcard/free_hit chip GWs (used=0),
    not just the GWs that go through the planner's own transfer branch.
"""
import pandas as pd

import scripts.backtest_season as bts
from scripts.backtest_season import build_planner_proj, _apply_squad_move, run_backtest


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


# ---------- ft_state accrual regression (wildcard/free_hit GWs) ----------

_SQUAD_SHAPE = [("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)]


def _make_synthetic_universe():
    """15 players matching SQUAD_SHAPE exactly, all identical stats and on the
    same team. Since the "market" pool below is exactly these 15 players (no
    extra candidates ever exist), transfer_planner.plan_transfers can never
    find a swap (no unowned candidates) -- every non-chip GW deterministically
    rolls, regardless of squad composition drift from a wildcard rebuild. That
    isolates the thing this test cares about: whether ft_state accrues on a
    GW where the planner's own transfer branch never runs.
    """
    players = []
    pid = 1
    for pos, count in _SQUAD_SHAPE:
        for _ in range(count):
            players.append({"player_id": pid, "name": f"P{pid}", "pos": pos,
                             "team": "T1", "price_m": 5.0})
            pid += 1
    return players


def _synthetic_history(players, gws):
    rows = []
    for g in gws:
        for p in players:
            rows.append({**p, "gw": g, "minutes": 90, "total_points": 2})
    return pd.DataFrame(rows)


def test_planner_ft_state_accrues_through_wildcard_gw(monkeypatch, tmp_path):
    """Regression for the coordinator's finding: ft_state must follow
    ft = min(5, max(ft - used, 0) + 1) every GW, with used=0 on wildcard/
    free_hit GWs -- not stay frozen because the planner's transfer branch
    (which used to own the ft_state update) is skipped on those chip GWs.
    """
    players = _make_synthetic_universe()
    squad_ids = [p["player_id"] for p in players]
    history = _synthetic_history(players, gws=[1, 2, 3])

    teams_df = pd.DataFrame({"id": [1, 2], "name": ["T1", "T2"]})
    fixtures_df = pd.DataFrame([
        {"event": g, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3}
        for g in (1, 2, 3, 4)
    ])
    actuals_df = pd.DataFrame([
        {"player_id": p["player_id"], "total_points": 2, "minutes": 90} for p in players
    ])

    monkeypatch.setattr(bts, "load_teams", lambda season: teams_df)
    monkeypatch.setattr(bts, "load_fixtures", lambda season: fixtures_df)
    monkeypatch.setattr(bts, "player_actuals_through", lambda gw, season: history)
    monkeypatch.setattr(bts, "player_actuals_at", lambda gw, season: actuals_df)

    squad_csv = tmp_path / "squad.csv"
    pd.DataFrame({"player_id": squad_ids}).to_csv(squad_csv, index=False)

    log = run_backtest(
        season="2025-26",
        start_gw=2,
        end_gw=4,
        initial_squad_csv=str(squad_csv),
        min_transfer_gain=0.6,
        use_engine=False,
        enable_chips=False,
        enable_can_bonus=False,
        manual_chip_plan={"wildcard": 3},
        smart_transfers=False,
        planner=True,
    )

    by_gw = log.set_index("gw")
    # GW2: normal GW, no swap possible (closed player universe) -> rolls, ft 1->2.
    assert by_gw.loc[2, "action"] == "roll"
    assert by_gw.loc[2, "ft"] == 2
    # GW3: wildcard -- the planner branch is skipped entirely, but ft_state must
    # still accrue (used=0) per src/ft_tracker.py, not stay frozen at 2.
    assert by_gw.loc[3, "chip"] == "wildcard"
    assert by_gw.loc[3, "ft"] == 3
    # GW4: back to normal, accrues again from the post-wildcard state.
    assert by_gw.loc[4, "ft"] == 4
