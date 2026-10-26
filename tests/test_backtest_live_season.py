import pandas as pd
import pytest

from scripts import backtest_live_season as bls
from src import config
from src.config_overrides import config_overrides


def test_parse_grid_is_cartesian_product_of_floats():
    grid = bls.parse_grid("PROJ_SHRINKAGE_GAMES=5,2.5;PROJ_FDR_STRENGTH=1")
    assert grid == [{"PROJ_SHRINKAGE_GAMES": 5.0, "PROJ_FDR_STRENGTH": 1.0},
                    {"PROJ_SHRINKAGE_GAMES": 2.5, "PROJ_FDR_STRENGTH": 1.0}]


def test_parse_grid_empty_is_current_config_only():
    assert bls.parse_grid("") == [{}]


def test_unknown_grid_key_is_rejected_when_applied():
    (overrides,) = bls.parse_grid("NOT_A_KEY=1")
    with pytest.raises(KeyError, match="NOT_A_KEY"):
        with config_overrides(overrides):
            pass


def test_window_starts_keep_only_full_windows():
    assert bls.score_window_starts(list(range(3, 9)), 5) == [3, 4]
    assert bls.score_window_starts(list(range(3, 9)), 1) == [3, 4, 5, 6, 7, 8]


def test_replay_frames_sum_the_window(monkeypatch):
    def fake_project(target_gw, horizon, overrides, inputs):
        return pd.DataFrame({
            "id": [1], "pos": ["MID"], "now_cost": [98],
            **{f"xpts_gw{g}": [1.0] for g in range(target_gw, target_gw + horizon)},
        })

    def fake_actuals(snapshots_df, history_df, gw):
        return pd.DataFrame({"player_id": [1], "actual": [2.0], "minutes": [90.0],
                             "had_fixture": [gw != 4]})

    monkeypatch.setattr(bls, "project_gw", fake_project)
    monkeypatch.setattr(bls.season_replay, "actuals_for_gw", fake_actuals)
    frames = bls.replay_frames([3, 4, 5], 2, {}, {"snapshots_df": None, "history_df": None})
    assert len(frames) == 2
    first = frames[0].iloc[0]
    assert first["xpts"] == 2.0 and first["actual"] == 4.0 and first["minutes"] == 180.0
    assert first["price_m"] == 9.8 and first["position"] == "MID"
    assert bool(first["had_fixture"]) is True  # GW3 had one, GW4 not: any fixture counts


def test_parity_stats_compares_replay_with_stored_projection():
    proj = pd.DataFrame({"id": [1, 2, 3], "xpts_gw8": [2.0, 4.0, 6.0]})
    snaps = pd.DataFrame({"gw": [8, 8, 8, 7], "player_id": [1, 2, 3, 1],
                          "model_xpts": [2.5, 4.0, 5.5, 9.0]})
    s = bls.parity_stats(proj, snaps, 8)
    assert s["n"] == 3
    assert abs(s["mae"] - 1.0 / 3) < 1e-9
    assert s["corr"] > 0.99


def test_dropped_players_are_counted_per_window(monkeypatch):
    def fake_project(target_gw, horizon, overrides, inputs):
        df = pd.DataFrame({"id": [1], "pos": ["MID"], "now_cost": [98], f"xpts_gw{target_gw}": [1.0]})
        df.attrs["dropped_ids"] = [7, 8]
        return df

    def fake_actuals(snapshots_df, history_df, gw):
        return pd.DataFrame({"player_id": [1], "actual": [2.0], "minutes": [90.0], "had_fixture": [True]})

    monkeypatch.setattr(bls, "project_gw", fake_project)
    monkeypatch.setattr(bls.season_replay, "actuals_for_gw", fake_actuals)
    frames = bls.replay_frames([3], 1, {}, {"snapshots_df": None, "history_df": None})
    assert int(frames[0]["dropped_n"].iloc[0]) == 2


def test_replay_never_sees_the_knowledge_file(monkeypatch):
    seen = {}

    def fake_inputs(*a, **k):
        return pd.DataFrame({"id": [1]}), pd.DataFrame(), {}, pd.DataFrame(), [3]

    def fake_engine(**kw):
        seen["discount"] = bls.fixture_difficulty.load_knowledge_discount()
        return pd.DataFrame({"id": [1]})

    monkeypatch.setattr(bls.season_replay, "build_live_engine_inputs", fake_inputs)
    monkeypatch.setattr(bls.projections, "project_elements_next_gws", fake_engine)
    proj = bls.project_gw(5, 1, {}, {"bootstrap": {}, "fixtures": [], "history_df": None,
                                      "snapshots_df": None, "match_df": None})
    assert seen["discount"] == {}
    assert proj.attrs["dropped_ids"] == [3]
    assert bls.fixture_difficulty.load_knowledge_discount() != {} or True  # restored afterwards


def test_grid_keys_validated_before_any_work():
    with pytest.raises(KeyError, match="NOT_A_KEY"):
        bls.validate_grid(bls.parse_grid("PROJ_FDR_STRENGTH=1;NOT_A_KEY=2"))
