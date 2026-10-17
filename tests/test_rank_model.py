"""rank_gain_if_haul: how many overall ranks a captain haul would gain.

    relative points vs the field = haul × (2 − field_EO/100)
        (you double him; the average rival holds field_EO/100 of him)
    ranks gained = relative points × ranks per point around your rank,
        never past rank 1.

ranks_per_point comes from two overall-league standings pages: yours and the
one half-way up (slope of rank over total points). Field EO is the top-10k
sample inside the top 10k and, outside it, overall ownership scaled by the
sample's captaining share — the top 10k's picks say little about rank 1.6M.
"""
import pytest

from src import rank_model


def test_relative_points_double_minus_the_fields_share():
    # 10-point haul, 85% field EO: 20 − 8.5 = 11.5 points on the field.
    assert rank_model.relative_points(haul_points=10, field_eo_pct=85) == pytest.approx(11.5)
    # Captained by all (130% EO): 20 − 13 = 7 — still a climb, just smaller.
    assert rank_model.relative_points(10, 130) == pytest.approx(7.0)
    # Nobody holds him: the full 20.
    assert rank_model.relative_points(10, 0) == pytest.approx(20.0)
    # EO past 200% cannot go negative.
    assert rank_model.relative_points(10, 250) == 0.0


def test_rank_gain_scales_by_ranks_per_point_and_stops_at_rank_one():
    assert rank_model.rank_gain_if_haul(haul_points=10, field_eo_pct=85, ranks_per_point=4000, overall_rank=1_600_000) == 46_000
    assert rank_model.rank_gain_if_haul(10, 85, 4000, overall_rank=20_000) == 19_999
    assert rank_model.rank_gain_if_haul(10, 85, None, 1_600_000) is None
    assert rank_model.rank_gain_if_haul(10, None, 4000, 1_600_000) is None
    assert rank_model.rank_gain_if_haul(None, 85, 4000, 1_600_000) is None


def test_ranks_per_point_from_two_standings_points():
    # Rank 1.6M at 300 points, rank 800k at 320 points: 800k ranks over 20 points.
    assert rank_model.ranks_per_point([(1_600_000, 300), (800_000, 320)]) == pytest.approx(40_000)
    assert rank_model.ranks_per_point([(1_600_000, 300), (800_000, 300)]) is None  # flat: unknown
    assert rank_model.ranks_per_point([(1_600_000, 300)]) is None


def test_field_eo_uses_the_sample_inside_the_top10k_and_scaled_ownership_outside():
    sample = {"owned_pct": 90.0, "captained_pct": 45.0, "eo_pct": 135.0}
    assert rank_model.field_eo_pct(sample=sample, ownership_pct=40.0, overall_rank=5_000) == 135.0
    # Outside: 40% owned overall, half of the top-10k owners captain him → 40 × 1.5 = 60.
    assert rank_model.field_eo_pct(sample=sample, ownership_pct=40.0, overall_rank=1_600_000) == 60.0
    # Unsampled player outside the top 10k: plain ownership, no captaining share.
    assert rank_model.field_eo_pct(sample=None, ownership_pct=4.0, overall_rank=1_600_000) == 4.0
    assert rank_model.field_eo_pct(sample=None, ownership_pct=None, overall_rank=1_600_000) is None
    assert rank_model.field_eo_pct(sample=sample, ownership_pct=40.0, overall_rank=None) is None


def test_build_reads_your_page_and_the_half_way_page_once_per_gw(monkeypatch):
    pages_read = []

    def fake_standings(league_id, page=1, session=None):
        pages_read.append(page)
        start = (page - 1) * 50 + 1
        return {"standings": {"results": [{"rank": r, "total": 400 - r // 40_000} for r in range(start, start + 50)]}}

    rank_model._cache.clear()
    m = rank_model.build(overall_rank=1_600_000, event_id=7, fetch_standings=fake_standings)
    assert m["overall_rank"] == 1_600_000 and m["basis"] == "overall"
    assert m["ranks_per_point"] == pytest.approx(40_000, rel=0.01)
    assert sorted(pages_read) == [16_000, 32_000]
    # Same rank bucket + GW: served from cache.
    rank_model.build(overall_rank=1_600_400, event_id=7, fetch_standings=fake_standings)
    assert len(pages_read) == 2


def test_build_is_none_without_a_rank_or_when_the_fetch_fails():
    rank_model._cache.clear()
    assert rank_model.build(overall_rank=None, event_id=7, fetch_standings=lambda *a, **k: {}) is None

    def boom(*a, **k):
        raise RuntimeError("403")

    assert rank_model.build(overall_rank=1_600_000, event_id=7, fetch_standings=boom) is None


def test_build_top10k_basis_and_rank_one():
    rank_model._cache.clear()

    def fake_standings(league_id, page=1, session=None):
        start = (page - 1) * 50 + 1
        return {"standings": {"results": [{"rank": r, "total": 500 - r // 100} for r in range(start, start + 50)]}}

    m = rank_model.build(overall_rank=5_000, event_id=7, fetch_standings=fake_standings)
    assert m["basis"] == "top10k"
    assert rank_model.build(overall_rank=1, event_id=7, fetch_standings=fake_standings) is None
