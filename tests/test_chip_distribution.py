import numpy as np
import pandas as pd

from src import chip_distribution as cd
from src import config


FWD = {"pos": "FWD", "xg90": 0.6, "xa90": 0.2, "p_appear": 0.95, "p_60": 0.82}
DEF = {"pos": "DEF", "xg90": 0.05, "xa90": 0.08, "p_appear": 0.9, "p_60": 0.8}


def _mean(pmf):
    return float((np.arange(pmf.size) * pmf).sum())


def test_pmf_is_a_distribution_whose_mean_tracks_xpts():
    share = config.CHIP_PLAN_DIST_CONTINUOUS_SHARE["FWD"]
    for xp in (3.0, 6.0, 9.0):
        pmf = cd.player_gw_pmf("FWD", xp, FWD, 1, 2.0)
        assert abs(pmf.sum() - 1.0) < 1e-9
        assert abs(_mean(pmf) - xp * (1 - share)) < 0.05


def test_haul_and_blank_odds_move_with_xpts():
    lo = cd.summarize(cd.player_gw_pmf("FWD", 4.0, FWD, 1, 3.0))
    hi = cd.summarize(cd.player_gw_pmf("FWD", 10.0, FWD, 1, 3.0))
    assert hi["p_haul"] > lo["p_haul"]
    assert hi["p_return"] > lo["p_return"]
    assert hi["p_blank"] < lo["p_blank"]
    assert hi["p80_high"] > lo["p80_high"]


def test_no_prior_means_no_distribution_and_no_fixture_is_a_zero_spike():
    assert cd.player_gw_pmf("FWD", 5.0, None) is None
    assert cd.player_gw_pmf("XYZ", 5.0, FWD) is None
    blank = cd.player_gw_pmf("FWD", 5.0, FWD, n_fixtures=0)
    assert blank[0] == 1.0
    assert cd.summarize(blank)["p_blank"] == 1.0


def test_unavailable_player_cannot_return():
    out = {**FWD, "p_appear": 0.0, "p_60": 0.0}
    pmf = cd.player_gw_pmf("FWD", 5.0, out, 1, 3.0)
    assert pmf[0] == 1.0


def test_summarize_bar_gives_p_beats_bar():
    pmf = cd.player_gw_pmf("FWD", 9.0, FWD, 1, 2.0)
    d = cd.summarize(pmf, bar=6.5)
    assert d["bar"] == 6.5
    assert abs(d["p_beats_bar"] - float(pmf[7:].sum())) < 1e-3   # rounded to 3 dp
    assert "p_beats_bar" not in cd.summarize(pmf)
    assert cd.summarize(None) is None


def test_convolve_sums_means_and_folds_overflow():
    p = cd.player_gw_pmf("DEF", 2.5, DEF, 1, 3.0)
    four = cd.convolve([p, p, p, p])
    assert abs(four.sum() - 1.0) < 1e-9
    assert abs(_mean(four) - 4 * _mean(p)) < 0.3   # overflow folding costs a little
    assert four.size == p.size
    assert cd.convolve([]) is None
    assert cd.convolve([None, p]) is not None


def test_player_priors_from_elements_start_rate_and_availability():
    elements = [
        {"id": 1, "element_type": 4, "expected_goals_per_90": 0.7, "expected_assists_per_90": 0.2,
         "starts": 4, "chance_of_playing_next_round": None, "status": "a"},
        {"id": 2, "element_type": 2, "expected_goals_per_90": 0.0, "expected_assists_per_90": 0.0,
         "starts": 0, "chance_of_playing_next_round": 25, "status": "d"},
        {"id": 3, "element_type": 3, "starts": 4, "status": "u"},
        {"id": "bad"},
    ]
    priors = cd.player_priors_from_elements(elements, finished_gws=4)
    assert set(priors) == {1, 2, 3}
    assert priors[1]["pos"] == "FWD" and priors[1]["xg90"] == 0.7
    # 4 starts in 4 GWs shrunk toward the prior: (4 + 2*0.55) / 6
    assert abs(priors[1]["p_appear"] - (4 + 2 * 0.55) / 6) < 1e-9
    assert priors[1]["p_60"] < priors[1]["p_appear"]
    # zero xG/xA falls back to the position prior; 25% chance scales appearance
    assert priors[2]["xg90"] == config.OUTPUT_POSITION_BASE_XG90["DEF"]
    assert abs(priors[2]["p_appear"] - 0.25 * (2 * 0.55) / 6) < 1e-9
    # unavailable status → cannot appear
    assert priors[3]["p_appear"] == 0.0


def test_player_priors_accepts_dataframe_and_pos_column():
    df = pd.DataFrame([{"id": 9, "pos": "GKP", "starts": 2}])
    priors = cd.player_priors_from_elements(df, finished_gws=2)
    assert priors[9]["pos"] == "GKP"
    assert cd.player_priors_from_elements(None) == {}
    assert cd.player_priors_from_elements(pd.DataFrame()) == {}
