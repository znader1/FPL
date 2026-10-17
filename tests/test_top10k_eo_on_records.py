"""eo_top10k rides on lineup player records when the sample file is present."""
import pandas as pd

from src import lineup_builder


def _record(**over):
    rec = {
        "player_id": 1, "web_name": "Saka", "xpts": 7.4, "xpts_horizon": 20.1,
        "p80_low": 2, "p80_high": 16, "selected_by_percent": 38.4,
        "fixtures_gw29": "H-BHA(D1)", "fixture_count_gw29": 1, "diff_avg_gw29": 1.0, "xpts_gw29": 7.4,
    }
    rec.update(over)
    return rec


def test_record_carries_eo_top10k_from_the_map():
    eo = {"event_id": 28, "players": {1: {"owned_pct": 90.0, "captained_pct": 60.0, "eo_pct": 150.0}}}
    rec = lineup_builder.decorate_projection_record(_record(), gws=[29], eo_top10k=eo)
    assert rec["eo_top10k"] == 150.0
    assert rec["eo_top10k_event_id"] == 28


def test_record_eo_is_null_without_a_sample_or_when_the_player_is_unsampled():
    rec = lineup_builder.decorate_projection_record(_record(), gws=[29], eo_top10k=None)
    assert rec["eo_top10k"] is None and rec["eo_top10k_event_id"] is None
    eo = {"event_id": 28, "players": {99: {"owned_pct": 1.0, "captained_pct": 0.0, "eo_pct": 1.0}}}
    rec = lineup_builder.decorate_projection_record(_record(), gws=[29], eo_top10k=eo)
    assert rec["eo_top10k"] == 0.0  # sampled GW, nobody in the top 10k holds him


def test_pack_lineup_records_threads_the_map():
    starting = pd.DataFrame({"player_id": [1], "pos": ["MID"], "xpts": [7.4]})
    bench = pd.DataFrame({"player_id": [2], "pos": ["DEF"], "xpts": [2.0]})
    elements = pd.DataFrame({"id": [1, 2], "team": [1, 1], "code": [10, 20], "photo": ["10.jpg", "20.jpg"], "web_name": ["Saka", "White"]})
    proj = pd.DataFrame({"id": [1, 2], "xpts_horizon": [20.1, 5.0], "selected_by_percent": [38.4, 5.0], "p80_low": [2, 0], "p80_high": [16, 6]})
    eo = {"event_id": 28, "players": {1: {"owned_pct": 90.0, "captained_pct": 60.0, "eo_pct": 150.0}}}
    s, b = lineup_builder.pack_lineup_records(starting, bench, elements, proj, gws=[], teams_code={}, eo_top10k=eo)
    assert s[0]["eo_top10k"] == 150.0
    assert b[0]["eo_top10k"] == 0.0


def test_record_carries_rank_gain_if_haul_from_the_rank_model():
    eo = {"event_id": 28, "players": {1: {"owned_pct": 90.0, "captained_pct": 45.0, "eo_pct": 135.0}}}
    rm = {"overall_rank": 1_600_000, "ranks_per_point": 4_000, "basis": "overall", "event_id": 29}
    # Outside the top 10k: field EO = 38.4 × 1.5 = 57.6; haul = p90 16 → 32 − 9.216 = 22.784 pts × 4000 = 91,136 ranks.
    rec = lineup_builder.decorate_projection_record(_record(), gws=[29], eo_top10k=eo, rank_model=rm)
    assert rec["rank_gain_if_haul"] == 91_136
    assert rec["rank_gain_basis"] == "overall"
    # No rank model → absent, not zero.
    rec = lineup_builder.decorate_projection_record(_record(), gws=[29], eo_top10k=eo, rank_model=None)
    assert rec["rank_gain_if_haul"] is None
