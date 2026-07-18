import pandas as pd

from src import backtest_metrics as m


def _frame(rows):
    # rows: list of (player_id, xpts, actual, position, minutes)
    return pd.DataFrame(rows, columns=["player_id", "xpts", "actual", "position", "minutes"])


def test_projection_mae_over_played_and_top_n():
    # top_n large so universe = all played (minutes>0). Errors: |5-4|=1, |2-6|=4 -> MAE 2.5.
    f = _frame([(1, 5.0, 4.0, "MID", 90), (2, 2.0, 6.0, "FWD", 90), (3, 9.0, 9.0, "DEF", 0)])
    # player 3 didn't play (minutes 0) but is top-1 by xpts -> included by top_n; |9-9|=0.
    # universe = {1,2,3}; errors 1,4,0 -> mean = 5/3.
    assert abs(m.projection_mae([f], top_n=40) - (5.0 / 3.0)) < 1e-9


def test_captain_hit_rate():
    # g1: top-proj p1 (xpts 9, actual 8); actual top-2 = {p2(10), p1(8)} -> p1 in -> hit.
    g1 = _frame([(1, 9.0, 8.0, "MID", 90), (2, 3.0, 10.0, "FWD", 90)])
    # g2: top-proj p1 (xpts 9, actual 2); actual top-1 = {p3(12)} -> p1 out -> miss.
    g2 = _frame([(1, 9.0, 2.0, "MID", 90), (3, 1.0, 12.0, "FWD", 90)])
    assert m.captain_hit_rate([g1], top_k=2) == 1.0
    assert m.captain_hit_rate([g2], top_k=1) == 0.0
    # g1 at top_k=1: actual top-1 is p2(10), top-proj p1 not in -> miss.
    assert m.captain_hit_rate([g1], top_k=1) == 0.0
    # both at top_k=1: g1 miss + g2 miss -> 0/2.
    assert m.captain_hit_rate([g1, g2], top_k=1) == 0.0


def test_captain_regret():
    # GW: top-proj p1 (actual 8); best actual 10 -> regret 2.
    g = _frame([(1, 9.0, 8.0, "MID", 90), (2, 3.0, 10.0, "FWD", 90)])
    assert abs(m.captain_regret([g]) - 2.0) < 1e-9


def test_top_n_precision():
    # top-2 proj = {p1,p2}; top-2 actual = {p2,p3}; overlap {p2} -> 1/2.
    g = _frame([(1, 9.0, 1.0, "MID", 90), (2, 8.0, 9.0, "FWD", 90), (3, 1.0, 10.0, "DEF", 90)])
    assert abs(m.top_n_precision([g], n=2) - 0.5) < 1e-9


def test_mae_by_position():
    f = _frame([(1, 5.0, 4.0, "MID", 90), (2, 2.0, 6.0, "MID", 90), (3, 3.0, 3.0, "DEF", 90)])
    out = m.mae_by_position([f], top_n=40)
    assert abs(out["MID"] - 2.5) < 1e-9  # (|5-4|+|2-6|)/2
    assert abs(out["DEF"] - 0.0) < 1e-9
