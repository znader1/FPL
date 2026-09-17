import json

import pandas as pd

from src import european


def _events(start="2026-09-12T10:00:00Z", n=6, gap_days=7):
    base = pd.Timestamp(start)
    out = []
    for i in range(n):
        out.append({"id": i + 1, "deadline_time": (base + pd.Timedelta(days=gap_days * i)).isoformat()})
    return out


CAL = {
    "teams": {"Arsenal": "ucl", "Aston Villa": "uel", "Burnley": "nope"},
    "matchdays": [
        # GW1 deadline Sat 12 Sep; GW2 deadline Sat 19 Sep. Tue 15 Sep sits
        # inside GW1's window (after its round) and 4 days before GW2's deadline.
        {"competition": "ucl", "label": "MD1", "dates": ["2026-09-15", "2026-09-16"]},
        {"competition": "uel", "label": "MD1", "dates": ["2026-09-24"]},
    ],
    "cup_rounds": [
        {"competition": "fa_cup", "label": "QF", "dates": ["2026-10-03"], "likely_blank": True},
    ],
}


def test_gw_windows_close_at_next_deadline_and_last_plus_7d():
    w = european.gw_windows(_events(n=2))
    assert w[1][1] == w[2][0]
    assert (w[2][1] - w[2][0]).days == 7


def test_gw_windows_skips_malformed_events():
    ev = _events(n=2) + [{"id": "x", "deadline_time": None}, {"deadline_time": "garbage"}]
    assert set(european.gw_windows(ev)) == {1, 2}


def test_european_weeks_flags_after_for_the_gw_before_and_before_for_the_next():
    euro = european.european_weeks_by_gw(_events(), CAL)
    assert euro[1]["Arsenal"]["when"] == "after"
    assert euro[2]["Arsenal"]["when"] == "before"
    assert euro[2]["Arsenal"]["days_before"] == 3   # Wed 16 Sep -> Sat 19 Sep
    assert euro[2]["Arsenal"]["competition"] == "ucl"
    assert euro[2]["Arsenal"]["label"] == "MD1"
    # UEL Thu 24 Sep: inside GW2's window (19->26 Sep) and 2 days before GW3.
    assert euro[2]["Aston Villa"]["when"] == "after"
    assert euro[3]["Aston Villa"]["when"] == "before"
    # Unknown competition never flags; Arsenal isn't in the UEL.
    assert "Burnley" not in euro.get(1, {})
    assert "Aston Villa" not in euro[1]


def test_european_weeks_empty_without_teams_or_events():
    assert european.european_weeks_by_gw(_events(), {}) == {}
    assert european.european_weeks_by_gw(_events(), {"teams": {}, "matchdays": CAL["matchdays"]}) == {}
    assert european.european_weeks_by_gw([], CAL) == {}


def test_european_weeks_before_window_is_configurable():
    # Wed 16 Sep is 3 days before GW2's deadline: a 2-day window drops it.
    euro = european.european_weeks_by_gw(_events(), CAL, before_days=2)
    assert "Arsenal" not in euro.get(2, {})


def test_cup_clashes_land_in_the_gw_window():
    clashes = european.cup_clashes_by_gw(_events(), CAL)
    # 3 Oct is inside GW4 (deadline 3 Oct 10:00? no: GW4 deadline = 12 Sep + 21d = 3 Oct 10:00,
    # the date normalizes to 3 Oct 00:00 which is inside GW3's window (26 Sep -> 3 Oct 10:00)).
    assert clashes == {3: {"competition": "fa_cup", "label": "QF", "likely_blank": True}}


def test_normalize_calendar_teams_maps_aliases_and_drops_bad_competitions():
    cal = european.normalize_calendar_teams(
        {"teams": {"ARS": "UCL", "7": "uel", "Chelsea": "ucl", "X": "lol"}},
        {"ARS": "Arsenal", "7": "Aston Villa", "Chelsea": "Chelsea"},
    )
    assert cal["teams"] == {"Arsenal": "ucl", "Aston Villa": "uel", "Chelsea": "ucl"}


def test_load_calendar_missing_or_malformed_is_empty(tmp_path):
    assert european.load_european_calendar(str(tmp_path / "nope.json")) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert european.load_european_calendar(str(bad)) == {}
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(CAL), encoding="utf-8")
    assert european.load_european_calendar(str(ok))["teams"]["Arsenal"] == "ucl"


def test_shipped_seed_calendar_parses_and_names_known_competitions():
    cal = european.load_european_calendar()
    assert cal, "data/models/european_calendar.json must ship"
    # The team map is user-maintained per season: every entry must name a
    # known competition, and the file must say which season it describes.
    assert isinstance(cal["teams"], dict)
    assert cal["teams"], "2026-27 qualifiers filled in on 2026-09-17"
    assert set(cal["teams"].values()) <= {"ucl", "uel", "uecl"}
    assert cal.get("season") == "2026-27"
    assert any(m["competition"] == "ucl" for m in cal["matchdays"])
    assert any(r.get("likely_blank") for r in cal["cup_rounds"])


def _market():
    return pd.DataFrame({
        "player_id": [1, 2, 3],
        "name": ["a", "b", "c"],
        "pos": ["MID", "MID", "FWD"],
        "team": ["Arsenal", "Burnley", "Arsenal"],
        "price_m": [8.0, 5.0, 9.0],
        "xpts": [6.0, 4.0, 8.0],
        "fixture_count": [1, 1, 1],
    })


def test_discount_projections_scales_only_european_teams_that_gw():
    gw_projections = {5: _market(), 6: _market()}
    euro = {5: {"Arsenal": {"competition": "ucl", "when": "before"}}}
    out = european.discount_projections(gw_projections, euro, 0.9)
    assert out[5].loc[out[5]["team"] == "Arsenal", "xpts"].tolist() == [5.4, 7.2]
    assert out[5].loc[out[5]["team"] == "Burnley", "xpts"].tolist() == [4.0]
    assert out[6] is gw_projections[6]           # untouched frame is shared
    assert gw_projections[5]["xpts"].tolist() == [6.0, 4.0, 8.0]  # input not mutated


def test_discount_projections_noop_at_mult_1_or_no_map():
    gw_projections = {5: _market()}
    assert european.discount_projections(gw_projections, {}, 0.9) is gw_projections
    assert european.discount_projections(gw_projections, {5: {"Arsenal": {}}}, 1.0) is gw_projections


def test_squad_exposure_lists_players_in_european_weeks():
    rows = european.squad_exposure(_market(), {"Arsenal": {"competition": "ucl", "when": "after"}})
    assert [r["name"] for r in rows] == ["a", "c"]
    assert rows[0] == {"name": "a", "team": "Arsenal", "competition": "ucl", "when": "after"}
    assert european.squad_exposure(_market(), {}) == []
