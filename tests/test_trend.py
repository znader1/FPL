import pandas as pd

from src import config, trend


def _match_rows(element, etype, xgi_by_event, minutes=90, xgc=1.0, dc=0):
    rows = []
    for ev, xgi in enumerate(xgi_by_event, start=1):
        rows.append({
            "element": element, "element_type": etype, "team_id": 1, "event": ev,
            "minutes": minutes, "expected_goals": xgi, "expected_assists": 0.0,
            "expected_goals_conceded": xgc, "defensive_contribution": dc, "starts": 1,
        })
    return rows


def test_trend_zero_below_two_matches():
    df = pd.DataFrame(_match_rows(1, 3, [0.9]))
    out = trend.player_trend(df, as_of_event=2).set_index("element")
    assert float(out.loc[1, "trend"]) == 0.0


def test_trend_positive_when_recent_xgi_up():
    df = pd.DataFrame(_match_rows(1, 3, [0.1] * 6 + [0.8] * 6))
    out = trend.player_trend(df, as_of_event=13).set_index("element")
    assert float(out.loc[1, "trend"]) > 0.0


def test_trend_clipped(monkeypatch):
    monkeypatch.setattr(config, "CHIP_WILDCARD_TREND_CLIP", 0.2, raising=False)
    df = pd.DataFrame(_match_rows(1, 3, [0.0] * 6 + [3.0] * 6))
    out = trend.player_trend(df, as_of_event=13).set_index("element")
    assert abs(float(out.loc[1, "trend"])) <= 0.2 + 1e-9


def test_trend_ignores_matches_at_or_after_as_of():
    # the big matches are in the future: they must not count
    df = pd.DataFrame(_match_rows(1, 3, [0.1] * 6 + [5.0] * 6))
    out = trend.player_trend(df, as_of_event=7).set_index("element")
    assert float(out.loc[1, "trend"]) == 0.0


def test_defender_trend_rewards_falling_xgc_and_rising_dc():
    worse = _match_rows(2, 2, [0.0] * 12, xgc=1.0, dc=10)
    for r in worse[:6]:
        r["expected_goals_conceded"] = 0.6
        r["defensive_contribution"] = 12
    for r in worse[6:]:
        r["expected_goals_conceded"] = 1.8
        r["defensive_contribution"] = 4
    out = trend.player_trend(pd.DataFrame(worse), as_of_event=13).set_index("element")
    assert float(out.loc[2, "trend"]) < 0.0


def test_nan_element_type_does_not_crash():
    df = pd.DataFrame(_match_rows(1, 3, [0.1] * 6 + [0.8] * 6))
    df["element_type"] = None
    out = trend.player_trend(df, as_of_event=13).set_index("element")
    assert float(out.loc[1, "trend"]) > 0.0  # treated as an attacker
