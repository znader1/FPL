import numpy as np
import pandas as pd

from src import chip_distribution as cd
from src import config
from src import points_distribution


FWD = {"pos": "FWD", "xg90": 0.6, "xa90": 0.2, "p_appear": 0.95, "p_60": 0.82}
DEF = {"pos": "DEF", "xg90": 0.05, "xa90": 0.08, "p_appear": 0.9, "p_60": 0.8}
MID = {"pos": "MID", "xg90": 0.4, "xa90": 0.3, "p_appear": 0.95, "p_60": 0.9}

CEIL = points_distribution.MAX_POINTS   # 30 — the single-player points ceiling


def _bench_four(xpts=5.5):
    """Four bench pmfs summing to ~4 x `xpts` of xPts."""
    return [cd.player_gw_pmf("MID", xpts, MID, 1, 2.0) for _ in range(4)]


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


def test_convolve_sums_means_on_a_wide_enough_axis():
    p = cd.player_gw_pmf("DEF", 2.5, DEF, 1, 3.0)
    four = cd.convolve([p, p, p, p])
    assert abs(four.sum() - 1.0) < 1e-9
    # the sum lives on a 4-player axis, so no mass is folded and the mean is exact
    assert abs(_mean(four) - 4 * _mean(p)) < 1e-6
    assert four.size == 4 * (p.size - 1) + 1
    assert cd.convolve([]) is None
    assert cd.convolve([None, p]) is not None


# ---------- F1: the 30-point ceiling must not swallow multi-player / DGW sums ----------

def test_bench_sum_is_not_pinned_to_the_single_player_ceiling():
    """A bench-4 worth ~22 xPts used to report modal 30 (the folded top bucket)."""
    bench = _bench_four(5.5)
    total_xpts = sum(4 * [5.5])
    assert abs(total_xpts - 22.0) < 1e-9
    bb = cd.convolve(bench)
    d = cd.summarize(bb, bar=12.0, player_thresholds=False)
    assert bb.size > CEIL + 1                     # room for four players
    assert d["modal"] < CEIL                      # not the saturated ceiling
    assert d["p80_low"] <= d["modal"] <= d["p80_high"]
    assert d["p80_high"] < bb.size - 1            # band closed, not clipped
    assert "p80_open" not in d


def test_dgw_captain_pmf_has_room_for_two_fixtures():
    """A 20 xPts double-gameweek captain used to report modal 30."""
    pmf = cd.player_gw_pmf("FWD", 20.0, FWD, n_fixtures=2, difficulty=2.0)
    assert pmf.size >= 2 * CEIL + 1
    d = cd.summarize(pmf)
    assert d["modal"] < CEIL
    assert d["p80_low"] <= d["modal"] <= d["p80_high"]
    share = config.CHIP_PLAN_DIST_CONTINUOUS_SHARE["FWD"]
    assert abs(d["mean"] - 20.0 * (1 - share)) < 0.1   # calibration unchanged


def test_folded_top_bucket_never_wins_argmax_and_marks_the_band_open():
    pmf = np.zeros(11)
    pmf[3] = 0.4
    pmf[10] = 0.6          # the fold sink: mass that is "10 or more", not exactly 10
    d = cd.summarize(pmf)
    assert d["modal"] == 3
    assert d["p80_high"] == 10
    assert d["p80_open"] is True


# ---------- F2: the bar must be compared on the pmf's own axis ----------

def test_continuous_share_is_weighted_by_xpts():
    shares = config.CHIP_PLAN_DIST_CONTINUOUS_SHARE
    s = cd.continuous_share([("GKP", 4.0), ("MID", 6.0)])
    expected = (4.0 * shares["GKP"] + 6.0 * shares["MID"]) / 10.0
    assert abs(s - expected) < 1e-9
    assert cd.continuous_share([]) == 0.0
    assert cd.continuous_share([("MID", 0.0)]) == 0.0


def test_bar_is_scaled_onto_the_pmf_axis_so_odds_are_not_understated():
    share = config.CHIP_PLAN_DIST_CONTINUOUS_SHARE["FWD"]
    pmf = cd.player_gw_pmf("FWD", 13.5, FWD, 1, 2.0)
    d = cd.summarize(pmf, bar=15.0, continuous_share=share)
    # hand-computed from this very pmf: the bar drops onto the pmf's axis
    hand = float(pmf[int(np.ceil(15.0 * (1 - share))):].sum())
    assert abs(d["p_beats_bar"] - hand) < 1e-3
    assert d["bar"] == 15.0                       # still reported in full xPts
    old = float(pmf[15:].sum())                   # the pre-fix, mismatched-axis number
    assert d["p_beats_bar"] > old


def test_zero_bar_does_not_claim_certainty():
    """On the expiry ramp the bar decays to 0; P(>= 0) == 1 is not information."""
    pmf = cd.player_gw_pmf("FWD", 9.0, FWD, 1, 2.0)
    d = cd.summarize(pmf, bar=0.0)
    assert d["bar"] == 0.0
    assert d["p_beats_bar"] == round(float(pmf[1:].sum()), 3)
    assert d["p_beats_bar"] < 1.0


# ---------- F3: per-player thresholds are meaningless on a bench-4 sum ----------

def test_bench_boost_summary_omits_per_player_thresholds():
    bb = cd.convolve(_bench_four(5.5))
    d = cd.summarize(bb, bar=12.0, player_thresholds=False)
    assert {"mean", "modal", "p80_low", "p80_high", "bar", "p_beats_bar"} <= set(d)
    assert "p_return" not in d
    assert "p_haul" not in d
    assert "p_blank" not in d
    # a single-player summary keeps them
    tc = cd.summarize(cd.player_gw_pmf("FWD", 9.0, FWD, 1, 2.0), bar=6.0)
    assert {"p_return", "p_haul", "p_blank"} <= set(tc)


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
