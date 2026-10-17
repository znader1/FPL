"""Top-10k effective ownership sample (frontend handoff 1b, step 1 of the
backend numbers).

The FPL API has no top-10k EO. We sample entries from the overall league's
top ranks, read their picks for the current GW and aggregate. EO follows the
sites' definition: the sum of pick multipliers (0 bench, 1 start, 2 captain,
3 triple captain) over the sample size.
"""
import json

import pytest

from src import top10k_eo


def _picks(*items):
    """items: (element, multiplier)."""
    return {"picks": [{"element": e, "multiplier": m} for e, m in items]}


def test_aggregate_sums_multipliers_over_the_sample():
    payloads = [
        _picks((1, 2), (2, 1), (3, 0)),   # captains 1, starts 2, benches 3
        _picks((1, 1), (2, 1), (4, 3)),   # starts 1 and 2, triple-captains 4
    ]
    out = top10k_eo.aggregate(payloads)
    assert out[1] == {"owned_pct": 100.0, "captained_pct": 50.0, "eo_pct": 150.0}
    assert out[2] == {"owned_pct": 100.0, "captained_pct": 0.0, "eo_pct": 100.0}
    # Benched: owned but zero effective ownership.
    assert out[3] == {"owned_pct": 50.0, "captained_pct": 0.0, "eo_pct": 0.0}
    assert out[4] == {"owned_pct": 50.0, "captained_pct": 50.0, "eo_pct": 150.0}


def test_aggregate_ignores_payloads_without_picks():
    out = top10k_eo.aggregate([_picks((1, 1)), {"detail": "Not found."}, None])
    assert out[1]["owned_pct"] == 100.0  # N counts only readable entries


def test_aggregate_empty_sample():
    assert top10k_eo.aggregate([]) == {}


def test_page_spread_covers_the_pool_evenly():
    # 10k ranks at 50 per page = 200 pages; 1000 entries = 20 pages, spread out.
    pages = top10k_eo.page_spread(pool_ranks=10_000, sample_entries=1_000, page_size=50)
    assert len(pages) == 20
    assert pages[0] == 1 and pages[-1] <= 200
    assert pages == sorted(set(pages))
    assert pages[1] - pages[0] == 10


def test_page_spread_never_exceeds_the_pool():
    assert top10k_eo.page_spread(pool_ranks=100, sample_entries=1_000, page_size=50) == [1, 2]


def test_is_current_matches_season_and_event():
    data = {"season": "2026-27", "event_id": 7}
    assert top10k_eo.is_current(data, season="2026-27", event_id=7)
    assert not top10k_eo.is_current(data, season="2026-27", event_id=8)
    assert not top10k_eo.is_current(data, season="2025-26", event_id=7)
    assert not top10k_eo.is_current(None, season="2026-27", event_id=7)


def test_eo_map_for_reads_the_file_once_and_guards_the_season(tmp_path):
    path = tmp_path / "top10k_eo.json"
    path.write_text(json.dumps({
        "season": "2026-27", "event_id": 6, "sample_n": 2,
        "players": {"1": {"owned_pct": 100.0, "captained_pct": 50.0, "eo_pct": 150.0}},
    }))
    loaded = top10k_eo.load_eo(path=path, season="2026-27")
    assert loaded["event_id"] == 6
    assert loaded["players"][1]["eo_pct"] == 150.0  # keys back to int
    assert top10k_eo.load_eo(path=path, season="2025-26") is None
    assert top10k_eo.load_eo(path=tmp_path / "missing.json", season="2026-27") is None


def test_build_sample_fetches_pages_then_picks_and_tolerates_failures(monkeypatch):
    standings = {
        1: {"standings": {"results": [{"entry": 11, "rank": 1}, {"entry": 12, "rank": 2}]}},
        2: {"standings": {"results": [{"entry": 21, "rank": 51}]}},
    }
    picks = {
        11: _picks((1, 2), (2, 1)),
        12: _picks((1, 1), (3, 1)),
    }

    def fake_standings(league_id, page=1, session=None):
        return standings[page]

    def fake_picks(entry_id, event_id, session=None):
        if entry_id == 21:
            raise RuntimeError("404")
        return picks[entry_id]

    out = top10k_eo.build_sample(
        event_id=6, season="2026-27", pages=[1, 2],
        fetch_standings=fake_standings, fetch_picks=fake_picks, concurrency=2,
    )
    assert out["event_id"] == 6 and out["season"] == "2026-27"
    assert out["sample_n"] == 2 and out["errors"] == 1
    assert out["players"][1]["eo_pct"] == 150.0
    assert out["sampled_at_utc"].endswith("Z")
    # Per-entry picks are kept (compact [element, multiplier] pairs) so the
    # field's projected totals can be computed later, per request.
    assert out["entries"] == [
        {"entry": 11, "rank": 1, "picks": [[1, 2], [2, 1]]},
        {"entry": 12, "rank": 2, "picks": [[1, 1], [3, 1]]},
    ]


def test_build_sample_aborts_when_every_entry_is_blocked():
    def fake_standings(league_id, page=1, session=None):
        return {"standings": {"results": [{"entry": 1}, {"entry": 2}]}}

    def blocked(entry_id, event_id, session=None):
        raise RuntimeError("403 /api/entry/.../picks (blocked by network/bot protection).")

    with pytest.raises(RuntimeError, match="blocked"):
        top10k_eo.build_sample(event_id=6, season="2026-27", pages=[1], fetch_standings=fake_standings, fetch_picks=blocked, concurrency=2)
