import pandas as pd

from src import player_knowledge as pk


def test_load_absent_returns_empty(tmp_path):
    d = pk.load_player_knowledge(str(tmp_path / "nope.json"))
    assert d == {"as_of": None, "players": {}}


def test_load_reads_file(tmp_path):
    p = tmp_path / "pk.json"
    p.write_text('{"as_of":"2026-07-26","players":{"5":{"availability":0.0}}}')
    d = pk.load_player_knowledge(str(p))
    assert d["as_of"] == "2026-07-26"
    assert d["players"]["5"]["availability"] == 0.0


def test_load_malformed_returns_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert pk.load_player_knowledge(str(p)) == {"as_of": None, "players": {}}


def test_resolve_keys_id_and_webname():
    els = pd.DataFrame({"id": [1, 2], "web_name": ["Saka", "Jesús"]})
    pkd = {"players": {"1": {"availability": 1.0},
                       "jesus": {"availability": 0.0},   # accent + case insensitive
                       "Ghost": {"availability": 0.0}}}
    by_id, notes = pk.resolve_keys(pkd, els)
    assert by_id[1]["availability"] == 1.0
    assert by_id[2]["availability"] == 0.0
    assert any("Ghost" in n for n in notes)
    assert 2 in by_id and len(notes) == 1


def test_merge_request_overrides_file():
    f = {"as_of": "x", "players": {"1": {"availability": 1.0}, "2": {"availability": 1.0}}}
    r = {"players": {"2": {"availability": 0.0}}}
    m = pk.merge_request(f, r)
    assert m["players"]["1"]["availability"] == 1.0
    assert m["players"]["2"]["availability"] == 0.0


def test_merge_request_none_is_file():
    f = {"as_of": "x", "players": {"1": {"availability": 1.0}}}
    assert pk.merge_request(f, None)["players"] == f["players"]
