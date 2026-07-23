import pandas as pd

from src import squad_draft, squad_draft_xg
from tests.test_squad_draft import _synthetic_elements, _synthetic_fixtures, _teams_short


def test_rates_from_bootstrap_shape():
    els = _synthetic_elements()
    rates = squad_draft_xg.rates_from_bootstrap(els)
    assert set(["player_id", "xg90", "xa90", "minutes_sample", "pos"]).issubset(rates.columns)
    assert len(rates) == len(els)
    assert (rates["xg90"] >= 0).all()


def test_minutes_from_bootstrap_shape():
    els = _synthetic_elements()
    m = squad_draft_xg.minutes_from_bootstrap(els)
    assert "exp_minutes" in m.columns and "p_start" in m.columns
    assert (m["exp_minutes"] >= 0).all() and (m["p_start"] <= 1.0).all()


def test_minutes_from_bootstrap_has_columns_output_model_actually_reads():
    # output_model.expected_points reads exp_minutes/prob_appear/prob_60 off
    # minutes_df (not just p_start/exp_minutes) -- lock that contract down so
    # a future edit can't silently drop what expected_points needs.
    els = _synthetic_elements()
    m = squad_draft_xg.minutes_from_bootstrap(els)
    assert {"prob_appear", "prob_60"}.issubset(m.columns)
    assert (m["prob_appear"] <= 1.0).all() and (m["prob_60"] <= 1.0).all()
    assert (m["prob_appear"] >= 0).all() and (m["prob_60"] >= 0).all()
    assert m.index.name == "id"


def test_xg_projection_produces_xpts_columns():
    els, fx, ts = _synthetic_elements(), _synthetic_fixtures(), _teams_short()
    proj = squad_draft_xg.xg_projection(els, fx, ts, gw_start=1, horizon=5,
                                        blend_weight=0.0, ppg_proj=None)
    assert "xpts_gw1" in proj.columns
    assert "id" in proj.columns and "pos" in proj.columns
    assert len(proj) == len(els)


def test_xg_projection_passthrough_columns_present():
    els, fx, ts = _synthetic_elements(), _synthetic_fixtures(), _teams_short()
    proj = squad_draft_xg.xg_projection(els, fx, ts, gw_start=1, horizon=1,
                                        blend_weight=0.0, ppg_proj=None)
    for col in ["web_name", "team_short", "team", "price_m", "points_per_game",
                "penalties_order", "selected_by_percent", "fixture_count_gw1"]:
        assert col in proj.columns, col
    assert (proj["fixture_count_gw1"] >= 0).all()
    # Every synthetic team has exactly one fixture per GW.
    assert (proj["fixture_count_gw1"] == 1).all()


def test_xg_projection_values_are_finite_and_nonnegative():
    els, fx, ts = _synthetic_elements(), _synthetic_fixtures(), _teams_short()
    proj = squad_draft_xg.xg_projection(els, fx, ts, gw_start=1, horizon=3,
                                        blend_weight=0.0, ppg_proj=None)
    for gw in (1, 2, 3):
        col = proj[f"xpts_gw{gw}"]
        assert col.notna().all()
        assert (col >= 0).all()


def test_xg_projection_blend_weight_zero_and_one_are_pure_xg_and_identical():
    # blend_weight falsy skips blending entirely; blend_weight=1.0 takes the
    # blend branch but is a pure-xg passthrough (1.0*xg + 0.0*ppg) -- this is
    # exactly how squad_draft.build_squad_from_frames invokes the "xg" basis.
    els, fx, ts = _synthetic_elements(), _synthetic_fixtures(), _teams_short()
    ppg_stub = pd.DataFrame({"id": els["id"], "xpts_gw1": 999.0})
    no_blend = squad_draft_xg.xg_projection(els, fx, ts, gw_start=1, horizon=1,
                                            blend_weight=0.0, ppg_proj=None)
    full_xg_weight = squad_draft_xg.xg_projection(els, fx, ts, gw_start=1, horizon=1,
                                                  blend_weight=1.0, ppg_proj=ppg_stub)
    pd.testing.assert_series_equal(
        no_blend["xpts_gw1"].reset_index(drop=True),
        full_xg_weight["xpts_gw1"].reset_index(drop=True),
    )


def test_xg_projection_blend_matches_weighted_formula():
    els, fx, ts = _synthetic_elements(), _synthetic_fixtures(), _teams_short()
    pure_xg = squad_draft_xg.xg_projection(els, fx, ts, gw_start=1, horizon=2,
                                           blend_weight=0.0, ppg_proj=None)
    ppg_proj = pd.DataFrame({
        "id": pure_xg["id"].values,
        "xpts_gw1": pure_xg["xpts_gw1"].values + 10.0,
        "xpts_gw2": pure_xg["xpts_gw2"].values + 5.0,
    })
    w = 0.3
    blended = squad_draft_xg.xg_projection(els, fx, ts, gw_start=1, horizon=2,
                                           blend_weight=w, ppg_proj=ppg_proj)
    merged = pure_xg[["id", "xpts_gw1", "xpts_gw2"]].merge(
        blended[["id", "xpts_gw1", "xpts_gw2"]], on="id", suffixes=("_xg", "_blend"))
    expected_gw1 = w * merged["xpts_gw1_xg"] + (1 - w) * (merged["xpts_gw1_xg"] + 10.0)
    expected_gw2 = w * merged["xpts_gw2_xg"] + (1 - w) * (merged["xpts_gw2_xg"] + 5.0)
    assert (merged["xpts_gw1_blend"] - expected_gw1).abs().max() < 1e-9
    assert (merged["xpts_gw2_blend"] - expected_gw2).abs().max() < 1e-9


def test_build_squad_from_frames_ppg_path_unchanged():
    # Guard: routing in the "xg"/"blend" basis must not perturb the default
    # ppg path (existing behaviour + tests/test_squad_draft.py must still hold).
    els, fx, ts = _synthetic_elements(), _synthetic_fixtures(), _teams_short()
    res = squad_draft.build_squad_from_frames(
        els, fx, ts, {"gw_start": 1, "horizon_gws": 5, "budget_m": 100.0, "projection_basis": "ppg"})
    assert res["ok"] is True, res.get("reason")
    assert res["projection_basis"] == "ppg"
    assert len(res["squad"]) == 15


def test_build_squad_from_frames_basis_xg():
    els, fx, ts = _synthetic_elements(), _synthetic_fixtures(), _teams_short()
    res = squad_draft.build_squad_from_frames(
        els, fx, ts, {"gw_start": 1, "horizon_gws": 5, "budget_m": 100.0, "projection_basis": "xg"})
    assert res["ok"] is True, res.get("reason")
    squad = pd.DataFrame(res["squad"])
    assert len(squad) == 15
    counts = squad["pos"].value_counts().to_dict()
    assert counts == {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    assert res["squad_cost_m"] <= 100.0 + 1e-6
    assert res["projection_basis"] == "xg"


def test_build_squad_from_frames_basis_blend():
    els, fx, ts = _synthetic_elements(), _synthetic_fixtures(), _teams_short()
    res = squad_draft.build_squad_from_frames(
        els, fx, ts, {"gw_start": 1, "horizon_gws": 5, "budget_m": 100.0,
                     "projection_basis": "blend", "blend_weight": 0.4})
    assert res["ok"] is True, res.get("reason")
    assert len(res["squad"]) == 15
    assert res["projection_basis"] == "blend"
