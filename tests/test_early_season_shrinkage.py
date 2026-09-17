"""Early-season shrinkage: 2-GW ppg/form noise must not outrank price class."""
import pandas as pd

from src import config
from src.projections import shrink_toward_price_prior


def _series(vals):
    return pd.Series(vals, dtype="float64")


def test_hot_cheap_player_shrinks_hard_early_season():
    # GW3 (2 finished games): a 4.1m defender averaging 10.0 must land near his
    # price prior, not keep the premium-striker number.
    blended = _series([10.0])
    now_cost = _series([41])
    etype = _series([2])  # DEF
    shrunk = shrink_toward_price_prior(blended, now_cost, etype, gw_start=3)
    assert shrunk.iloc[0] < 5.0
    assert shrunk.iloc[0] > 2.0  # still credits the hot start a little


def test_quiet_premium_recovers_toward_price_prior():
    # 7.0m midfielder with two quiet games (blended 2.0) should be pulled UP
    # toward his price class, not buried.
    blended = _series([2.0])
    now_cost = _series([70])
    etype = _series([3])  # MID
    shrunk = shrink_toward_price_prior(blended, now_cost, etype, gw_start=3)
    assert shrunk.iloc[0] > 2.4


def test_shrinkage_fades_as_season_progresses():
    blended = _series([10.0])
    now_cost = _series([41])
    etype = _series([2])
    early = shrink_toward_price_prior(blended, now_cost, etype, gw_start=3)
    late = shrink_toward_price_prior(blended, now_cost, etype, gw_start=30)
    assert late.iloc[0] > early.iloc[0]
    assert late.iloc[0] > 8.0  # 29 games of evidence ≈ trusted


def test_disabled_when_config_zero(monkeypatch):
    monkeypatch.setattr(config, "PROJ_SHRINKAGE_GAMES", 0.0, raising=False)
    blended = _series([10.0])
    shrunk = shrink_toward_price_prior(blended, _series([41]), _series([2]), gw_start=3)
    assert shrunk.iloc[0] == 10.0
