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


def _twins():
    df = _proj()
    twin = df[df["id"] == 2].copy()
    twin["id"] = 4
    twin["selected_by_percent"] = 55.0  # same player, template ownership
    df.loc[df["id"] == 2, "selected_by_percent"] = 5.0
    return pd.concat([df, twin], ignore_index=True)


def test_ownership_term_is_a_preset_weight():
    # Balanced/aggressive carry a small template-protection term; gems and the
    # legacy (no preset) path carry none.
    bal = projections.add_wildcard_scores(_twins(), gw_start=8, horizon_gws=2, preset=config.CHIP_WILDCARD_PRESETS["balanced"]).set_index("id")
    gems = projections.add_wildcard_scores(_twins(), gw_start=8, horizon_gws=2, preset=config.CHIP_WILDCARD_PRESETS["gems"]).set_index("id")
    legacy = projections.add_wildcard_scores(_twins(), gw_start=8, horizon_gws=2).set_index("id")
    w = float(config.CHIP_WILDCARD_PRESETS["balanced"]["ownership_weight"])
    assert w > 0
    assert abs(float(bal.loc[4, "wildcard_ownership_term"]) - w * 55.0) < 1e-6
    assert float(bal.loc[4, "wildcard_score"]) - float(bal.loc[2, "wildcard_score"]) > 0
    assert float(gems.loc[4, "wildcard_score"]) == float(gems.loc[2, "wildcard_score"])
    assert float(legacy.loc[4, "wildcard_ownership_term"]) == 0.0
    # One full template player (55%) is worth about one xPt over the horizon, not more.
    assert w * 55.0 <= 2.0


def _market(players, gws):
    """players: (id, pos, price, [xpts per gw]) → a minimal scored-market frame."""
    rows = []
    for pid, pos, price, xs in players:
        row = {"id": pid, "pos": pos, "price_m": price, "penalties_order": 99.0}
        for g, x in zip(gws, xs):
            row[f"xpts_gw{g}"] = x
            row[f"fixture_count_gw{g}"] = 1.0
        rows.append(row)
    return pd.DataFrame(rows)


def test_palmer_case_gets_no_captaincy_bonus():
    gws = [9, 10, 11, 12, 13]
    market = _market([
        (411, "FWD", 15.7, [6.64, 6.10, 6.40, 5.20, 6.30]),   # Haaland
        (154, "MID", 9.8, [4.07, 3.90, 4.20, 3.60, 4.50]),    # Palmer
        (2, "DEF", 5.0, [4.0, 4.0, 4.0, 4.0, 4.0]),
    ], gws)
    out = projections.add_wildcard_scores(market, gw_start=9, horizon_gws=5).set_index("id")
    assert float(out.loc[154, "wildcard_captaincy_bonus"]) == 0.0
    assert float(out.loc[154, "wildcard_captain_share"]) == 0.0
    assert float(out.loc[411, "wildcard_captaincy_bonus"]) > 0.0
    assert float(out.loc[411, "wildcard_captain_share"]) == 1.0


def test_shared_captaincy_is_proportional():
    gws = [9, 10, 11, 12]
    market = _market([
        (1, "MID", 12.0, [8.0, 5.0, 8.0, 5.0]),
        (2, "FWD", 12.0, [5.0, 8.0, 5.0, 8.0]),
    ], gws)
    out = projections.add_wildcard_scores(market, gw_start=9, horizon_gws=4).set_index("id")
    assert float(out.loc[1, "wildcard_captain_share"]) == 0.5
    assert float(out.loc[2, "wildcard_captain_share"]) == 0.5


def test_blank_market_gw_gives_no_bonus():
    gws = [9, 10]
    market = _market([
        (1, "MID", 12.0, [0.0, 7.0]),
        (2, "FWD", 12.0, [0.0, 6.9]),
    ], gws)
    out = projections.add_wildcard_scores(market, gw_start=9, horizon_gws=2).set_index("id")
    assert float(out.loc[1, "wildcard_captain_share"]) == 0.5   # GW9 blank counts as not plausible
    assert float(out.loc[2, "wildcard_captain_share"]) == 0.5
