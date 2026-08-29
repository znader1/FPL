"""Component + distribution blocks on the player score breakdown."""
from src import lineup_builder


def _record(**over):
    rec = {
        "xpts": 4.1, "xpts_horizon": 12.3,
        "p_goal": 0.4612, "p_assist": 0.2134, "p_clean_sheet": 0.3051,
        "p_appear": 0.97, "p_60": 0.881, "p_dc": 0.1234,
        "exp_goals": 0.6201, "exp_assists": 0.2402, "exp_minutes": 84.6,
        "model_exp_points": 5.237,
        "ep_appearance": 1.85, "ep_goals": 2.48, "ep_assists": 0.72,
        "ep_clean_sheet": 0.31, "ep_bonus": 0.78, "ep_dc": 0.25,
        "modal_points": 2, "p_return_6": 0.341, "p_haul_10": 0.118,
        "p80_low": 1, "p80_high": 9,
    }
    rec.update(over)
    return rec


def test_components_are_exposed_and_rounded():
    out = lineup_builder._build_score_breakdown(_record())
    comp = out["components"]
    assert comp["p_goal"] == 0.461
    assert comp["p_60"] == 0.881
    assert comp["exp_minutes"] == 84.6
    assert comp["model_exp_points"] == 5.24


def test_distribution_is_exposed():
    out = lineup_builder._build_score_breakdown(_record())
    dist = out["distribution"]
    assert dist["modal_points"] == 2
    assert dist["p_return_6"] == 0.341
    assert dist["p_haul_10"] == 0.118
    assert (dist["p80_low"], dist["p80_high"]) == (1, 9)


def test_model_points_are_reported_separately_from_the_blended_xpts():
    """
    The headline xpts is a blend of baseline and model, so the components must
    not be presented as a decomposition of it.
    """
    out = lineup_builder._build_score_breakdown(_record())
    assert out["current_gw_xpts"] == 4.1
    assert out["components"]["model_exp_points"] == 5.24
    assert out["current_gw_xpts"] != out["components"]["model_exp_points"]


def test_absent_model_columns_yield_null_blocks_not_a_wall_of_nones():
    """Pre-season, or with no xG history, the model contributes nothing."""
    out = lineup_builder._build_score_breakdown({"xpts": 2.0})
    assert out["components"] is None
    assert out["distribution"] is None


def test_partial_model_output_still_reports_what_it_has():
    out = lineup_builder._build_score_breakdown({"xpts": 2.0, "p_goal": 0.25})
    assert out["components"]["p_goal"] == 0.25
    assert out["components"]["p_assist"] is None
