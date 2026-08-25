import json
from pathlib import Path
from src import replay_snapshot


def _write_raw(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "entry.json").write_text(json.dumps({"id": 588004}))
    (raw / "history.json").write_text(json.dumps({"current": []}))
    (raw / "picks_gw01.json").write_text(json.dumps({
        "active_chip": None,
        "entry_history": {"points": 53, "bank": 0, "event_transfers": 0},
        "picks": [{"element": 351, "is_captain": True, "is_vice_captain": False, "multiplier": 2},
                  {"element": 233, "is_captain": False, "is_vice_captain": True, "multiplier": 1}],
    }))
    (raw / "picks_gw02.json").write_text(json.dumps({
        "active_chip": "wildcard",
        "entry_history": {"points": 44, "bank": 15, "event_transfers": 1},
        "picks": [{"element": 351, "is_captain": True, "is_vice_captain": False, "multiplier": 2},
                  {"element": 99, "is_captain": False, "is_vice_captain": True, "multiplier": 1}],
    }))
    return raw


def test_build_entry_snapshot_shape_and_transfers(tmp_path):
    raw = _write_raw(tmp_path)
    snap = replay_snapshot.build_entry_snapshot(str(raw), season="2025-26")
    assert snap["entry_id"] == 588004
    assert snap["season"] == "2025-26"
    g1, g2 = snap["gws"][1], snap["gws"][2]
    assert g1["captain"] == 351 and g1["vice"] == 233 and g1["points"] == 53
    assert g1["transfers"] == {"in": [], "out": []}       # first GW: no prior
    assert g1["chip"] is None
    # GW2 squad dropped 233, added 99 vs GW1
    assert g2["transfers"] == {"in": [99], "out": [233]}
    assert g2["chip"] == "wildcard"
    assert g2["bank"] == 1.5                                # 15 tenths -> £1.5m


def test_derive_transfers_empty_prev():
    assert replay_snapshot.derive_transfers([], [1, 2]) == {"in": [], "out": []}
    assert replay_snapshot.derive_transfers([1, 2], [2, 3]) == {"in": [3], "out": [1]}
