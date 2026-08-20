import pandas as pd

from src.squad_draft import _apply_min_minutes


def _pool():
    return pd.DataFrame(
        [
            {"id": 1, "pos": "DEF", "minutes": 565},   # fringe (O'Nien-like)
            {"id": 2, "pos": "DEF", "minutes": 812},   # rotation
            {"id": 3, "pos": "DEF", "minutes": 3000},  # nailed
            {"id": 4, "pos": "MID", "minutes": 200},   # fringe MID
            {"id": 5, "pos": "FWD", "minutes": 400},   # fringe FWD
            {"id": 6, "pos": "GKP", "minutes": 0},     # backup GK — always exempt
        ]
    )


def test_min_minutes_filters_all_outfield_positions_but_not_gk():
    out = _apply_min_minutes(_pool(), min_minutes=600, min_fwd_minutes=0)
    assert sorted(out["id"].tolist()) == [2, 3, 6]


def test_zero_min_minutes_keeps_everyone():
    out = _apply_min_minutes(_pool(), min_minutes=0, min_fwd_minutes=0)
    assert len(out) == 6


def test_min_fwd_minutes_still_composes_as_the_stricter_fwd_bound():
    out = _apply_min_minutes(_pool(), min_minutes=100, min_fwd_minutes=500)
    ids = out["id"].tolist()
    assert 5 not in ids  # FWD 400 < 500
    assert 4 in ids      # MID 200 >= 100


def test_missing_minutes_column_treated_as_zero():
    df = pd.DataFrame([{"id": 1, "pos": "DEF"}, {"id": 2, "pos": "GKP"}])
    out = _apply_min_minutes(df, min_minutes=600, min_fwd_minutes=0)
    assert out["id"].tolist() == [2]
