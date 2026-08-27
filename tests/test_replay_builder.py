from pathlib import Path

import pandas as pd
import pytest

from src import replay_builder

# These integration tests replay real GW7 data from the local Vaastav mirror,
# which is gitignored (data/*) and therefore absent in CI.
requires_vaastav = pytest.mark.skipif(
    not Path("data/vaastav/2025-26/gws/gw7.csv").exists(),
    reason="local Vaastav 2025-26 data not present",
)


def test_optimal_captain_picks_max_actual_in_squad():
    actuals = pd.DataFrame({"player_id": [1, 2, 3], "total_points": [4, 12, 7]})
    assert replay_builder.optimal_captain([1, 2, 3], actuals) == 2
    assert replay_builder.optimal_captain([1, 3], actuals) == 3   # 2 excluded
    assert replay_builder.optimal_captain([99], actuals) is None  # not present


def test_optimal_captain_empty():
    assert replay_builder.optimal_captain([], pd.DataFrame({"player_id": [], "total_points": []})) is None


@requires_vaastav
def test_build_gw_record_gw7_real_data():
    snap = {"season": "2025-26", "gws": {7: {"picks": [351, 233, 99], "captain": 351}}}
    rec = replay_builder.build_gw_record(7, "2025-26", snap, horizon=3)
    assert rec["gw"] == 7 and rec["setup_gw"] is False
    assert len(rec["players"]) == 3
    assert all(set(p) == {"element", "model_xpts", "actual_points"} for p in rec["players"])
    assert rec["optimal_captain"] in (351, 233, 99)
    assert rec["model_captain"] in (351, 233, 99)
    assert any(p["model_xpts"] > 0 for p in rec["players"])


def test_build_gw_record_gw1_is_setup():
    snap = {"season": "2025-26", "gws": {1: {"picks": [351]}}}
    rec = replay_builder.build_gw_record(1, "2025-26", snap)
    assert rec["setup_gw"] is True and rec["players"] == []


@requires_vaastav
def test_gw_global_ownership_normalized():
    own = replay_builder._gw_global_ownership(7, "2025-26")
    assert own                              # non-empty
    assert max(own.values()) == 1.0         # normalized to the most-selected
    assert all(0.0 <= v <= 1.0 for v in own.values())


@requires_vaastav
def test_build_gw_record_dedupes_duplicated_vaastav_player():
    # element 100 has duplicated rows in real GW7 Vaastav data
    snap = {"season": "2025-26", "gws": {7: {"picks": [351, 233, 100]}}}
    rec = replay_builder.build_gw_record(7, "2025-26", snap, horizon=3)
    assert len(rec["players"]) == 3
    ids = [p["element"] for p in rec["players"]]
    assert len(ids) == len(set(ids))   # no duplicate players


@requires_vaastav
def test_sp2_candidates_present_and_labeled():
    snap = {"season": "2025-26", "gws": {7: {"picks": [351, 233, 99], "captain": 351}}}
    rec = replay_builder.build_gw_record(7, "2025-26", snap, horizon=3)
    assert isinstance(rec["sp2_candidates"], list) and len(rec["sp2_candidates"]) > 0
    c = rec["sp2_candidates"][0]
    assert set(c) == {"element", "differential_ev", "template_xpts", "global_ownership", "ownership_basis"}
    assert c["ownership_basis"] == "global"
    # sorted descending by differential_ev
    evs = [x["differential_ev"] for x in rec["sp2_candidates"]]
    assert evs == sorted(evs, reverse=True)
