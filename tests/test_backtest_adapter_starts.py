import pandas as pd

from src import backtest_adapter, backtest_data


def _patch_common(monkeypatch, history_long):
    monkeypatch.setattr(backtest_data, "player_actuals_through", lambda gw, season="2025-26": history_long)
    monkeypatch.setattr(backtest_data, "load_teams", lambda season="2025-26": pd.DataFrame(
        {"id": [1], "name": ["Team A"], "short_name": ["TMA"]}))
    monkeypatch.setattr(backtest_data, "load_fixtures", lambda season="2025-26": pd.DataFrame(
        {"event": [1], "team_h": [1], "team_a": [1], "team_h_difficulty": [3], "team_a_difficulty": [3]}))


def test_uses_real_starts_when_present(monkeypatch):
    # p1: 80 mins but starts=0 (came on early as sub); p2: 45 mins but starts=1.
    hist = pd.DataFrame({
        "element": [1, 2], "gw": [1, 1], "total_points": [3, 2],
        "minutes": [80, 45], "starts": [0, 1], "team": ["Team A", "Team A"],
    })
    _patch_common(monkeypatch, hist)
    out = backtest_adapter.build_history_df(target_gw=2)
    starts = dict(zip(out["player_id"], out["gw_starts"]))
    assert starts[1] == 0  # real starts overrides the minutes>=60 proxy
    assert starts[2] == 1


def test_falls_back_to_proxy_without_starts(monkeypatch):
    hist = pd.DataFrame({
        "element": [1, 2], "gw": [1, 1], "total_points": [3, 2],
        "minutes": [80, 45], "team": ["Team A", "Team A"],
    })
    _patch_common(monkeypatch, hist)
    out = backtest_adapter.build_history_df(target_gw=2)
    starts = dict(zip(out["player_id"], out["gw_starts"]))
    assert starts[1] == 1  # 80 >= 60
    assert starts[2] == 0  # 45 < 60


def _two_player_history():
    return pd.DataFrame({
        "element": [1, 2], "gw": [1, 1], "total_points": [3, 2],
        "minutes": [80, 45], "starts": [1, 1], "team": ["Team A", "Team A"],
        "name": ["One", "Two"], "position": ["MID", "DEF"], "price_m": [5.0, 4.5],
    })


def test_ep_next_comes_from_the_target_gw_xp(monkeypatch):
    # The target GW's xP was published before its deadline, so it is the one
    # column the adapter may read past the history cut-off. Player 2 has no
    # row that GW: missing, never 0 (the engine treats 0 as a real ep_next).
    _patch_common(monkeypatch, _two_player_history())
    monkeypatch.setattr(backtest_data, "load_gw", lambda gw, season="2025-26": pd.DataFrame(
        {"element": [1], "xP": [4.2]}) if gw == 2 else pd.DataFrame())
    out = backtest_adapter.build_elements_df(target_gw=2).set_index("id")
    assert float(out.loc[1, "ep_next"]) == 4.2
    assert pd.isna(out.loc[2, "ep_next"])


def test_ep_next_missing_when_target_gw_file_absent(monkeypatch):
    _patch_common(monkeypatch, _two_player_history())

    def _raise(gw, season="2025-26"):
        raise FileNotFoundError(gw)
    monkeypatch.setattr(backtest_data, "load_gw", _raise)
    out = backtest_adapter.build_elements_df(target_gw=2)
    assert out["ep_next"].isna().all()
