"""Window scoring for the monitoring dashboard. The transfer cases are the
owner's real GW8 and GW9 moves (entry 107342, 2026-27)."""
import pandas as pd

from src import monitor_scoring as ms

# Saka 12, Palmer 154, Maguire 418, Van Hecke 112
PTS = {8: {12: 0, 154: -1, 418: 0, 112: 7}, 9: {12: 0, 154: 8, 418: 0, 112: 15}}


def test_window_points_counts_only_finished_gameweeks():
    assert ms.window_points(112, 8, 3, PTS, last_finished_gw=9) == {"points": 22, "played": 2, "complete": False}
    assert ms.window_points(112, 8, 1, PTS, last_finished_gw=9) == {"points": 7, "played": 1, "complete": True}
    assert ms.window_points(112, 10, 3, PTS, last_finished_gw=9) == {"points": 0, "played": 0, "complete": False}


def test_a_player_absent_from_a_finished_gameweek_counts_zero():
    assert ms.window_points(999, 8, 2, PTS, last_finished_gw=9) == {"points": 0, "played": 2, "complete": True}


def test_gw9_maguire_to_van_hecke_is_plus_15_after_one_gameweek():
    w = ms.moves_windows([{"sell_id": 418, "buy_id": 112}], 9, 0, PTS, last_finished_gw=9)
    assert w["1"] == {"gain": 15, "played": 1, "complete": True}
    assert w["3"] == {"gain": 15, "played": 1, "complete": False}
    assert set(w) == {"1", "3", "5"}


def test_gw8_saka_to_palmer_is_minus_1_then_plus_7():
    w = ms.moves_windows([{"sell_id": 12, "buy_id": 154}], 8, 0, PTS, last_finished_gw=9)
    assert w["1"] == {"gain": -1, "played": 1, "complete": True}
    assert w["3"] == {"gain": 7, "played": 2, "complete": False}


def test_a_hit_costs_four_and_no_move_is_zero():
    assert ms.moves_windows([{"sell_id": 418, "buy_id": 112}], 9, 1, PTS, 9)["1"]["gain"] == 11
    assert ms.moves_windows([], 9, 0, PTS, 9)["1"] == {"gain": 0, "played": 1, "complete": True}


def test_no_verdict_until_the_three_gameweek_window_is_complete():
    incomplete = {"3": {"gain": 15, "played": 1, "complete": False}}
    assert ms.transfers_verdict(incomplete, incomplete) is None

    def done(gain):
        return {"3": {"gain": gain, "played": 3, "complete": True}}

    assert ms.transfers_verdict(done(9), done(4)) == "app"
    assert ms.transfers_verdict(done(4), done(9)) == "you"
    assert ms.transfers_verdict(done(4), done(4)) == "level"
    assert ms.transfers_verdict(None, done(4)) is None


def test_chip_weeks():
    assert ms.is_transfer_chip_week("freehit") and ms.is_transfer_chip_week("wildcard")
    assert not ms.is_transfer_chip_week("bboost") and not ms.is_transfer_chip_week("3xc")
    assert not ms.is_transfer_chip_week(None)


def test_list_average_and_points_per_million():
    out = ms.list_windows([112, 154], {112: 4.9, 154: 9.8}, 9, PTS, 9)
    assert [p["id"] for p in out["players"]] == [112, 154]
    assert out["players"][0]["windows"]["1"] == {"points": 15, "played": 1, "complete": True}
    assert out["avg"]["1"] == 11.5
    assert round(out["avg_per_m"]["1"], 3) == round((15 / 4.9 + 8 / 9.8) / 2, 3)


def test_an_empty_list_has_no_average_and_a_missing_price_is_left_out_of_value():
    assert ms.list_windows([], {}, 9, PTS, 9)["avg"] == {"1": None, "3": None, "5": None}
    out = ms.list_windows([112, 154], {112: 4.9}, 9, PTS, 9)
    assert out["avg"]["1"] == 11.5 and round(out["avg_per_m"]["1"], 3) == round(15 / 4.9, 3)
    assert out["players"][1]["price_m"] is None


def _snap(rows):
    return pd.DataFrame(rows, columns=["player_id", "web_name", "pos", "team_short", "price_m", "model_xpts"])


def _squad_rows(xpts):
    """A legal 3-4-3 eleven plus one bench outfielder; `xpts` maps id → projection."""
    shape = [(1, "GKP"), (2, "DEF"), (3, "DEF"), (4, "DEF"), (5, "MID"), (6, "MID"), (7, "MID"),
             (8, "MID"), (9, "FWD"), (10, "FWD"), (11, "FWD"), (12, "MID")]
    return [(i, f"P{i}", pos, f"T{i}", 5.0, xpts.get(i, 3.0)) for i, pos in shape]


def test_squad_window_fields_each_weeks_lineup_on_that_weeks_stored_projection():
    squad = list(range(1, 13))
    # GW2: bench player 12 projects low and sits; GW3: he projects highest of the midfielders.
    snaps = {2: _snap(_squad_rows({12: 0.5, 9: 9.0})), 3: _snap(_squad_rows({12: 8.0, 5: 0.1, 9: 9.0}))}
    pts = {2: {i: 2 for i in squad}, 3: {i: 2 for i in squad}}
    pts[2][12], pts[3][12] = 20, 20
    mins = {2: {i: 90 for i in squad}, 3: {i: 90 for i in squad}}
    out = ms.squad_windows(squad, 2, 2, snaps, pts, mins, last_finished_gw=3)
    assert 12 not in out["by_gw"][2]["xi"] and 12 in out["by_gw"][3]["xi"]
    assert out["by_gw"][2]["captain_id"] == 9
    assert out["by_gw"][2]["points"] == 11 * 2 + 2          # captain 9 doubled
    assert out["by_gw"][3]["points"] == 10 * 2 + 20 + 2
    assert (out["points"], out["played"], out["complete"]) == (24 + 42, 2, True)


def test_squad_window_reports_a_player_with_no_snapshot_row_that_week():
    squad = list(range(1, 13))
    rows = [r for r in _squad_rows({}) if r[0] != 12]
    snaps = {2: _snap(rows)}
    pts = {2: {i: 1 for i in squad}}
    mins = {2: {i: 90 for i in squad}}
    out = ms.squad_windows(squad, 2, 1, snaps, pts, mins, last_finished_gw=2)
    assert out["by_gw"][2]["absent"] == [12] and out["played"] == 1


def test_a_gameweek_with_no_projections_is_skipped_and_named():
    squad = list(range(1, 13))
    snaps = {2: _snap(_squad_rows({}))}                      # nothing for GW1
    pts = {1: {i: 5 for i in squad}, 2: {i: 1 for i in squad}}
    mins = {1: {i: 90 for i in squad}, 2: {i: 90 for i in squad}}
    out = ms.squad_windows(squad, 1, 2, snaps, pts, mins, last_finished_gw=2)
    assert out["no_projection_gws"] == [1] and out["played"] == 1 and out["complete"] is False
    assert list(out["by_gw"]) == [2]


def test_an_unfinished_window_is_partial():
    squad = list(range(1, 13))
    snaps = {2: _snap(_squad_rows({})), 3: _snap(_squad_rows({}))}
    pts = {2: {i: 1 for i in squad}}
    mins = {2: {i: 90 for i in squad}}
    out = ms.squad_windows(squad, 2, 5, snaps, pts, mins, last_finished_gw=2)
    assert (out["played"], out["complete"]) == (1, False) and list(out["by_gw"]) == [2]
