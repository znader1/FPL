"""Set-piece duty in the transfer score: penalties are already in xPts
(PROJ_PENALTY_TAKER_UPLIFT), so the transfer ranking must not add them again;
corners / direct free kicks are a small per-GW edge that scales with the
horizon, not a flat +2 that outweighs a GW of xPts."""
import pandas as pd

from src import config, recommender


def _el(**over):
    base = {"id": 1, "web_name": "p", "team": 1, "team_short": "T", "pos": "MID", "price_m": 6.0,
            "form": 4.0, "points_per_game": 4.0, "total_points": 28, "minutes": 630,
            "selected_by_percent": 10.0, "transfers_in_event": 0, "transfers_out_event": 0,
            "status": "a", "chance_of_playing_next_round": 100, "xh": 5.0,
            "penalties_order": None, "direct_freekicks_order": None, "corners_and_indirect_freekicks_order": None}
    base.update(over)
    return base


def _scores(rows, horizon):
    el = pd.DataFrame(rows)
    out = recommender.build_transfer_scores(el, score_col="xh", horizon_gws=horizon)
    return out.set_index("id")


def test_penalty_taker_gets_no_extra_transfer_score():
    out = _scores([_el(id=1, penalties_order=1), _el(id=2)], horizon=1)
    assert out.loc[1, "set_piece_score"] == 0.0
    assert out.loc[1, "transfer_score"] == out.loc[2, "transfer_score"]


def test_corner_and_freekick_edge_is_per_gw_and_scales_with_horizon():
    one = _scores([_el(id=1, direct_freekicks_order=1, corners_and_indirect_freekicks_order=1)], horizon=1)
    five = _scores([_el(id=1, direct_freekicks_order=1, corners_and_indirect_freekicks_order=1)], horizon=5)
    per_gw = (config.TRANSFER_SET_PIECE_PER_GW["direct_free_kicks"][1]
              + config.TRANSFER_SET_PIECE_PER_GW["corners_indirect"][1])
    assert one.loc[1, "set_piece_score"] == per_gw
    assert five.loc[1, "set_piece_score"] == 5 * per_gw
    # One GW of corner+FK duty is worth well under one xPt.
    assert per_gw < 0.5
