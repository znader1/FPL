from src.odds_client import aggregate_event, match_fpl_team


def _event():
    def book(h, d, a, over, under, line=2.5):
        return {
            "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "Manchester City", "price": h},
                    {"name": "Draw", "price": d},
                    {"name": "Hull City", "price": a},
                ]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "point": line, "price": over},
                    {"name": "Under", "point": line, "price": under},
                ]},
            ]
        }
    return {
        "home_team": "Manchester City",
        "away_team": "Hull City",
        "bookmakers": [book(1.2, 7.0, 13.0, 1.9, 1.9),
                       book(1.25, 6.5, 12.0, 1.95, 1.87),
                       book(1.22, 6.8, 15.0, 1.92, 1.9)],
    }


def test_aggregate_event_medians():
    agg = aggregate_event(_event())
    assert agg["h2h"] == [1.22, 6.8, 13.0]
    assert agg["totals"]["line"] == 2.5
    assert agg["totals"]["over"] == 1.92


def test_aggregate_event_missing_totals_returns_none():
    ev = _event()
    for b in ev["bookmakers"]:
        b["markets"] = [m for m in b["markets"] if m["key"] == "h2h"]
    assert aggregate_event(ev) is None


def test_match_fpl_team_aliases_and_substrings():
    fpl = {1: "Man City", 2: "Spurs", 3: "Nott'm Forest", 4: "Hull", 5: "Arsenal"}
    assert match_fpl_team("Manchester City", fpl) == 1
    assert match_fpl_team("Tottenham Hotspur", fpl) == 2
    assert match_fpl_team("Nottingham Forest", fpl) == 3
    assert match_fpl_team("Hull City", fpl) == 4
    assert match_fpl_team("Arsenal", fpl) == 5
    assert match_fpl_team("Real Madrid", fpl) is None


def _full_events():
    ev = _event()
    return [ev]


def test_lambdas_by_team_for_and_against(monkeypatch):
    from src import odds_client
    monkeypatch.setattr(odds_client, "fetch_epl_odds", lambda **k: _full_events())
    fpl = {1: "Man City", 4: "Hull"}
    out = odds_client.odds_lambdas_by_team(fpl)
    assert set(out) == {1, 4}
    # City heavy favourites: their lam_for is Hull's lam_against and vice versa
    assert out[1]["lam_for"] > out[4]["lam_for"]
    assert abs(out[1]["lam_against"] - out[4]["lam_for"]) < 1e-9
    assert abs(out[4]["lam_against"] - out[1]["lam_for"]) < 1e-9


def test_market_difficulty_scale(monkeypatch):
    from src import odds_client
    monkeypatch.setattr(odds_client, "fetch_epl_odds", lambda **k: _full_events())
    fpl = {1: "Man City", 4: "Hull"}
    diff = odds_client.market_difficulty_by_team(fpl)
    assert set(diff) == {1, 4}
    # High expected goals = easy fixture (low difficulty); both clamped 1-5
    assert 1.0 <= diff[1] < diff[4] <= 5.0


def test_cache_only_mode_never_fetches(monkeypatch):
    from src import odds_client

    def boom(**k):
        raise AssertionError("network fetch attempted in cache_only mode")

    monkeypatch.setattr(odds_client, "_fetch_live", boom, raising=False)
    monkeypatch.setattr(odds_client, "_read_cache", lambda ttl: None)
    assert odds_client.odds_lambdas_by_team({1: "Arsenal"}, cache_only=True) == {}
