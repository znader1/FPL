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
