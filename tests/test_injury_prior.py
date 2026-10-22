import pandas as pd

from src import config, injury_prior


def _bootstrap(status_by_id):
    return {"elements": [{"id": i, "status": s, "chance_of_playing_next_round": None} for i, s in status_by_id.items()]}


def test_injury_prior_missing_file_is_zero_not_nan(tmp_path):
    out = injury_prior.player_injury_prior(str(tmp_path / "nope.csv"))
    assert out.empty
    merged = injury_prior.attach(pd.DataFrame({"id": [1, 2]}), out)
    assert merged["p_miss"].tolist() == [0.0, 0.0]
    assert merged["injury_flag"].tolist() == [False, False]


def test_status_snapshot_upserts_last_status_per_event(tmp_path):
    path = str(tmp_path / "status_history.csv")
    injury_prior.append_status_snapshot(_bootstrap({1: "a", 2: "a"}), 8, path)   # Monday
    injury_prior.append_status_snapshot(_bootstrap({1: "i", 2: "a"}), 8, path)   # Friday
    df = pd.read_csv(path)
    assert len(df) == 2
    assert df.loc[df["element"] == 1, "status"].iloc[0] == "i"


def test_p_miss_shrinks_with_few_gws(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHIP_WILDCARD_INJURY_PRIOR_SHRINK_GWS", 6.0, raising=False)
    path = str(tmp_path / "status_history.csv")
    for gw, s in enumerate(["i", "i", "a", "a"], start=1):
        injury_prior.append_status_snapshot(_bootstrap({1: s}), gw, path)
    out = injury_prior.player_injury_prior(path).set_index("element")
    assert abs(float(out.loc[1, "p_miss"]) - 2.0 / (4.0 + 6.0)) < 1e-9


def test_injury_flag_from_current_status_or_high_prior(tmp_path):
    path = str(tmp_path / "status_history.csv")
    for gw, s in enumerate(["i"] * 6, start=1):
        injury_prior.append_status_snapshot(_bootstrap({1: s, 2: "a"}), gw, path)
    out = injury_prior.player_injury_prior(path).set_index("element")
    assert bool(out.loc[1, "injury_flag"]) is True
    assert bool(out.loc[2, "injury_flag"]) is False


def _bootstrap_season(status_by_id, year):
    b = _bootstrap(status_by_id)
    b["events"] = [{"id": 1, "deadline_time": f"{year}-08-15T17:30:00Z"}]
    return b


def test_status_history_is_keyed_by_season(tmp_path):
    path = str(tmp_path / "status_history.csv")
    # last season: player 1 injured for 6 GWs
    for gw in range(1, 7):
        injury_prior.append_status_snapshot(_bootstrap_season({1: "i"}, 2025), gw, path)
    # new season: same id, fit, one GW on file
    injury_prior.append_status_snapshot(_bootstrap_season({1: "a"}, 2026), 1, path)
    out = injury_prior.player_injury_prior(path).set_index("element")
    assert float(out.loc[1, "p_miss"]) == 0.0
    assert bool(out.loc[1, "injury_flag"]) is False
    df = pd.read_csv(path)
    assert set(df["season"]) == {"2026-27"}
