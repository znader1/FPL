import pandas as pd

from src import config, projections


def _proj():
    rows = [
        # id, pos, price, gw8, gw9, form, own, ep_goals, ep_assists, ep_dc, ep_saves, p_miss, trend
        (1, "MID", 11.0, 7.0, 6.0, 9.0, 50.0, 0.6, 0.3, 0.1, 0.0, 0.0, 0.0),
        (2, "DEF", 5.0, 4.0, 4.0, 2.0, 5.0, 0.2, 0.1, 1.2, 0.0, 0.0, 0.0),
        (3, "FWD", 8.0, 5.0, 5.0, 7.0, 20.0, 0.5, 0.1, 0.0, 0.0, 0.5, 0.0),
    ]
    df = pd.DataFrame(rows, columns=[
        "id", "pos", "price_m", "xpts_gw8", "xpts_gw9", "form", "selected_by_percent",
        "ep_goals", "ep_assists", "ep_dc", "ep_saves", "p_miss", "wildcard_trend",
    ])
    df["fixture_count_gw8"] = 1.0
    df["fixture_count_gw9"] = 1.0
    df["recent_gw_avg_points"] = 4.0
    df["recent_gw_samples"] = 3.0
    df["penalties_order"] = 99.0
    return df


def test_wildcard_score_has_no_form_or_ownership_terms():
    out = projections.add_wildcard_scores(_proj(), gw_start=8, horizon_gws=2)
    assert "wildcard_form_bonus" not in out.columns
    assert "wildcard_ownership_bonus" not in out.columns
    for col in ["wildcard_trend", "wildcard_upside", "wildcard_injury_mult", "wildcard_captaincy_bonus"]:
        assert col in out.columns, col


def test_defender_gets_upside_from_dc_and_goals():
    out = projections.add_wildcard_scores(_proj(), gw_start=8, horizon_gws=2).set_index("id")
    expected = config.CHIP_WILDCARD_UPSIDE_WEIGHT * (0.2 + 0.1 + 1.2 + 0.0)
    assert abs(float(out.loc[2, "wildcard_upside"]) - expected) < 1e-6


def test_injury_prior_multiplies_score_down():
    out = projections.add_wildcard_scores(_proj(), gw_start=8, horizon_gws=2).set_index("id")
    assert abs(float(out.loc[3, "wildcard_injury_mult"]) - (1.0 - 0.5 * config.CHIP_WILDCARD_INJURY_PRIOR_WEIGHT)) < 1e-9
    assert float(out.loc[3, "wildcard_score"]) < float(out.loc[3, "wildcard_weighted_xpts"])


def test_captaincy_zero_under_gems_preset():
    out = projections.add_wildcard_scores(
        _proj(), gw_start=8, horizon_gws=2, preset=config.CHIP_WILDCARD_PRESETS["gems"]
    ).set_index("id")
    assert float(out.loc[1, "wildcard_captaincy_bonus"]) == 0.0


def test_captaincy_bonus_has_no_form_term():
    base = _proj()
    hot = base.copy()
    hot.loc[hot["id"] == 1, "form"] = 20.0
    a = projections.add_wildcard_scores(base, gw_start=8, horizon_gws=2).set_index("id")
    b = projections.add_wildcard_scores(hot, gw_start=8, horizon_gws=2).set_index("id")
    assert float(a.loc[1, "wildcard_captaincy_bonus"]) == float(b.loc[1, "wildcard_captaincy_bonus"])


def test_trend_scaled_by_preset_mult():
    df = _proj()
    df.loc[df["id"] == 2, "wildcard_trend"] = 0.4
    plain = projections.add_wildcard_scores(df, gw_start=8, horizon_gws=2).set_index("id")
    gems = projections.add_wildcard_scores(
        df, gw_start=8, horizon_gws=2, preset=config.CHIP_WILDCARD_PRESETS["gems"]
    ).set_index("id")
    assert abs(float(gems.loc[2, "wildcard_trend_term"]) - 2.0 * float(plain.loc[2, "wildcard_trend_term"])) < 1e-9


def test_attach_wildcard_signals_defaults_to_zero_without_data(tmp_path):
    df = pd.DataFrame({"id": [1, 2]})
    out = projections.attach_wildcard_signals(
        df, gw_start=8, match_df=pd.DataFrame(), status_path=str(tmp_path / "none.csv")
    )
    assert out["wildcard_trend"].tolist() == [0.0, 0.0]
    assert out["p_miss"].tolist() == [0.0, 0.0]
    assert out["injury_flag"].tolist() == [False, False]


def test_attach_wildcard_signals_joins_trend_by_id():
    match = pd.DataFrame([
        {"element": 1, "element_type": 3, "team_id": 1, "event": ev, "minutes": 90,
         "expected_goals": 0.1 if ev <= 6 else 0.9, "expected_assists": 0.0,
         "expected_goals_conceded": 1.0, "defensive_contribution": 0, "starts": 1}
        for ev in range(1, 13)
    ])
    df = pd.DataFrame({"id": [1, 2]})
    out = projections.attach_wildcard_signals(df, gw_start=13, match_df=match, status_path=None).set_index("id")
    assert float(out.loc[1, "wildcard_trend"]) > 0.0
    assert float(out.loc[2, "wildcard_trend"]) == 0.0


def test_attach_wildcard_signals_fails_soft_on_broken_history(monkeypatch):
    def boom(match_df, as_of_event):
        raise ValueError("bad row")
    import src.trend as _trend
    monkeypatch.setattr(_trend, "player_trend", boom)
    out = projections.attach_wildcard_signals(pd.DataFrame({"id": [1]}), gw_start=8, match_df=pd.DataFrame({"x": [1]}), status_path=None)
    assert out["wildcard_trend"].tolist() == [0.0]
