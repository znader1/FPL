import pandas as pd

from src.backtest_metrics import band_bias, calibration_table, price_band


def _frame(rows):
    return pd.DataFrame(rows, columns=["player_id", "position", "price_m", "xpts", "actual",
                                       "minutes", "had_fixture"])


def test_price_band_edges():
    assert price_band(5.95) == "<6"
    assert price_band(6.0) == "6-8"
    assert price_band(7.95) == "6-8"
    assert price_band(8.0) == "8+"


def test_premium_mid_bias_and_population():
    f1 = _frame([(1, "MID", 9.8, 5.0, 3.0, 90, True),
                 (2, "DEF", 4.5, 3.0, 6.0, 0, True),      # benched: in n, not in n_app
                 (3, "FWD", 7.0, 4.0, 0.0, 0, False)])    # blank GW: excluded
    f2 = _frame([(1, "MID", 9.8, 5.0, 3.0, 90, True)])
    t = calibration_table([f1, f2]).set_index(["pos", "band"])
    assert t.loc[("MID", "8+"), "bias"] == 2.0
    assert t.loc[("MID", "8+"), "n"] == 2
    assert t.loc[("DEF", "<6"), "n"] == 1
    assert t.loc[("DEF", "<6"), "n_app"] == 0
    assert ("FWD", "6-8") not in t.index
    assert t.loc[("ALL", "ALL"), "n"] == 3
    assert abs(t.loc[("ALL", "ALL"), "mae"] - (2 + 3 + 2) / 3) < 1e-9


def test_spearman_needs_three_rows():
    t = calibration_table([_frame([(1, "MID", 9.8, 5.0, 3.0, 90, True)])]).set_index(["pos", "band"])
    assert t.loc[("MID", "8+"), "spearman"] is None


def test_band_bias_ignores_small_cells_and_the_all_row():
    rows = [(i, "MID", 9.0, 5.0, 3.0, 90, True) for i in range(20)]          # bias +2, n=20
    rows += [(100 + i, "DEF", 4.5, 2.0, 3.0, 90, True) for i in range(20)]    # bias -1, n=20
    rows += [(200, "GKP", 4.5, 9.0, 0.0, 90, True)]                           # n=1, ignored
    t = calibration_table([_frame(rows)])
    assert abs(band_bias(t) - 1.5) < 1e-9
