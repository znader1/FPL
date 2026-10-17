"""Projected field benchmarks (frontend handoff 1a, backend step 3): the
top-10k and overall average projected totals and where the user's projected
total sits in the field, all from the per-entry picks kept in the sample."""
import pytest

from src import config, field_projection


XPTS = {1: 8.0, 2: 6.0, 3: 4.0, 4: 2.0}


def _entry(*items, rank=1):
    return {"rank": rank, "picks": [[e, m] for e, m in items]}


def test_entry_total_is_multiplier_weighted_xpts_and_unknown_players_count_zero():
    assert field_projection.entry_total([[1, 2], [2, 1], [3, 0], [99, 1]], XPTS) == 22.0


def test_summarize_means_match_the_eo_sum_and_quantiles_span_the_field():
    sample = {
        "event_id": 6,
        "players": {1: {"eo_pct": 150.0}, 2: {"eo_pct": 100.0}, 3: {"eo_pct": 0.0}},
        "entries": [_entry((1, 2), (2, 1), (3, 0)), _entry((1, 1), (2, 1), (3, 0))],
        "overall": {"entries": [_entry((1, 1), (3, 1)), _entry((2, 1), (4, 1)), _entry((4, 1))]},
    }
    s = field_projection.summarize(sample, XPTS)
    # Mean of the per-entry totals == Σ eo_pct/100 × xpts, to float tolerance.
    assert s["top10k_avg"] == pytest.approx((22.0 + 14.0) / 2) == pytest.approx(1.5 * 8 + 1.0 * 6)
    assert s["overall_avg"] == pytest.approx((12.0 + 8.0 + 2.0) / 3, abs=0.005)
    assert s["event_id"] == 6 and s["top10k_n"] == 2 and s["overall_n"] == 3
    q = s["overall_quantiles"]
    assert len(q) == 101 and q[0] == 2.0 and q[100] == 12.0 and q[50] == 8.0


def test_summarize_falls_back_to_the_eo_sum_when_the_file_has_no_entries():
    sample = {"event_id": 6, "players": {1: {"eo_pct": 150.0}, 2: {"eo_pct": 100.0}}}
    s = field_projection.summarize(sample, XPTS)
    assert s["top10k_avg"] == pytest.approx(18.0)
    assert s["overall_avg"] is None and s["overall_quantiles"] is None and s["overall_n"] == 0


def test_summarize_is_none_without_a_sample():
    assert field_projection.summarize(None, XPTS) is None


def test_percentile_is_the_share_of_the_field_strictly_above_you_with_a_floor():
    totals = [10.0, 20.0, 30.0, 40.0]
    assert field_projection.percentile_above(totals, 25.0) == 50.0
    assert field_projection.percentile_above(totals, 40.0) == config.FIELD_PERCENTILE_FLOOR
    assert field_projection.percentile_above(totals, 5.0) == 100.0
    assert field_projection.percentile_above([], 5.0) is None


def test_fields_carry_the_three_response_keys_and_null_without_overall():
    summary = {"top10k_avg": 60.0, "overall_avg": 50.0, "overall_totals": [40.0, 50.0, 60.0, 70.0], "overall_quantiles": [40.0] * 101, "event_id": 6, "top10k_n": 2, "overall_n": 4}
    f = field_projection.fields(summary, 65.0)
    assert f == {"projected_top10k_avg": 60.0, "projected_overall_avg": 50.0, "projected_percentile": 25.0}
    assert field_projection.fields({**summary, "overall_totals": [], "overall_avg": None}, 65.0)["projected_percentile"] is None
    assert field_projection.fields(None, 65.0) == {"projected_top10k_avg": None, "projected_overall_avg": None, "projected_percentile": None}
