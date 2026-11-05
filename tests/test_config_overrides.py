import pytest

from src import config
from src.config_overrides import config_overrides


def test_overrides_apply_and_restore():
    before = config.PROJ_MODEL_BLEND_WEIGHT
    with config_overrides({"PROJ_MODEL_BLEND_WEIGHT": 0.123}):
        assert config.PROJ_MODEL_BLEND_WEIGHT == 0.123
    assert config.PROJ_MODEL_BLEND_WEIGHT == before


def test_restores_on_exception():
    before = config.PROJ_SHRINKAGE_GAMES
    with pytest.raises(RuntimeError):
        with config_overrides({"PROJ_SHRINKAGE_GAMES": 0.0}):
            raise RuntimeError("boom")
    assert config.PROJ_SHRINKAGE_GAMES == before


def test_unknown_key_rejected_before_any_change():
    before = config.PROJ_MODEL_BLEND_WEIGHT
    with pytest.raises(KeyError, match="NOT_A_KEY"):
        with config_overrides({"PROJ_MODEL_BLEND_WEIGHT": 0.9, "NOT_A_KEY": 1}):
            pass
    assert config.PROJ_MODEL_BLEND_WEIGHT == before
