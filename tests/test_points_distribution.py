import numpy as np
import pytest

from src import points_distribution as pdist


def _forward(**over):
    """A typical premium forward: plays, scores often."""
    kw = dict(pos="FWD", prob_appear=0.97, prob_60=0.88,
              exp_goals=0.62, exp_assists=0.24,
              exp_clean_sheets=0.0, n_fixtures=1, p_dc=0.0)
    kw.update(over)
    return kw


def _defender(**over):
    kw = dict(pos="DEF", prob_appear=0.95, prob_60=0.90,
              exp_goals=0.08, exp_assists=0.10,
              exp_clean_sheets=0.34, n_fixtures=1, p_dc=0.31)
    kw.update(over)
    return kw


def _keeper(**over):
    kw = dict(pos="GKP", prob_appear=1.0, prob_60=1.0,
              exp_goals=0.0, exp_assists=0.01,
              exp_clean_sheets=0.29, n_fixtures=1, p_dc=0.0)
    kw.update(over)
    return kw


@pytest.mark.parametrize("kw", [_forward(), _defender(), _keeper()])
def test_pmf_is_a_probability_distribution(kw):
    pmf = pdist.player_points_pmf(**kw)
    assert pmf.min() >= 0.0
    assert pmf.sum() == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("kw", [_forward(), _defender(), _keeper()])
def test_pmf_mean_matches_the_discrete_expected_points(kw):
    """
    The distribution must reproduce the model's own discrete mean, or the card
    and the optimizer are telling the user different stories.
    """
    pmf = pdist.player_points_pmf(**kw)
    mean = float((np.arange(pmf.size) * pmf).sum())
    assert mean == pytest.approx(pdist.discrete_expected_points(**kw), abs=0.01)


def test_double_gameweek_keeps_the_clean_sheet_mean_exact():
    kw = _defender(exp_clean_sheets=0.68, n_fixtures=2)
    pmf = pdist.player_points_pmf(**kw)
    mean = float((np.arange(pmf.size) * pmf).sum())
    assert pmf.sum() == pytest.approx(1.0, abs=1e-9)
    assert mean == pytest.approx(pdist.discrete_expected_points(**kw), abs=0.01)


def test_a_player_who_never_plays_scores_zero():
    pmf = pdist.player_points_pmf(**_forward(
        prob_appear=0.0, prob_60=0.0, exp_goals=0.0, exp_assists=0.0))
    assert pmf[0] == pytest.approx(1.0, abs=1e-9)


def test_summary_fields_derive_from_the_pmf():
    kw = _forward()
    pmf = pdist.player_points_pmf(**kw)
    summary = pdist.summarize(pmf)

    assert summary["modal_points"] == int(np.argmax(pmf))
    assert summary["p_return_6"] == pytest.approx(float(pmf[6:].sum()), abs=1e-9)
    assert summary["p_haul_10"] == pytest.approx(float(pmf[10:].sum()), abs=1e-9)
    assert summary["p80_low"] <= summary["modal_points"] <= summary["p80_high"]


def test_a_striker_has_a_fatter_tail_than_a_keeper():
    fwd = pdist.summarize(pdist.player_points_pmf(**_forward()))
    gkp = pdist.summarize(pdist.player_points_pmf(**_keeper()))
    assert fwd["p_haul_10"] > gkp["p_haul_10"]


def test_probability_of_a_return_rises_with_expected_goals():
    low = pdist.summarize(pdist.player_points_pmf(**_forward(exp_goals=0.2)))
    high = pdist.summarize(pdist.player_points_pmf(**_forward(exp_goals=0.9)))
    assert high["p_return_6"] > low["p_return_6"]


def test_prob_60_above_prob_appear_is_clamped_not_negative():
    # Defensive: upstream minutes models can emit a 60' probability that edges
    # above the appearance probability. That must never produce a negative mass.
    pmf = pdist.player_points_pmf(**_forward(prob_appear=0.80, prob_60=0.92))
    assert pmf.min() >= 0.0
    assert pmf.sum() == pytest.approx(1.0, abs=1e-9)
