"""Projected points on the squad payload — so a future GW isn't a row of dashes."""
import pandas as pd
import pytest

from api import main as api_main


@pytest.fixture(autouse=True)
def clear_caches():
    api_main._projections_cache.clear()
    yield
    api_main._projections_cache.clear()


def _proj(gw, values):
    return pd.DataFrame([{"id": pid, f"xpts_gw{gw}": v} for pid, v in values.items()])


def test_projections_are_cached_per_gameweek_window(monkeypatch):
    calls = []

    def _fake(gw_start, horizon, **kw):
        calls.append((gw_start, horizon))
        return _proj(gw_start, {1: 4.2})

    monkeypatch.setattr(api_main.projections, "project_elements_next_gws",
                        lambda **kw: _fake(kw["gw_start"], kw["horizon_gws"]))
    monkeypatch.setattr(api_main, "get_bootstrap_cached", lambda: {"elements": [], "teams": []})
    monkeypatch.setattr(api_main, "get_fixtures_cached", lambda: pd.DataFrame())
    monkeypatch.setattr(api_main.transforms, "tables_from_bootstrap",
                        lambda b: (pd.DataFrame(), pd.DataFrame({"id": [], "short_name": []}), None))

    api_main.get_projections_cached(3, 1)
    api_main.get_projections_cached(3, 1)
    assert calls == [(3, 1)], "a second call within the TTL must not recompute"

    api_main.get_projections_cached(4, 1)
    assert len(calls) == 2, "a different gameweek must not be served from GW3's entry"


def test_a_different_horizon_gets_its_own_entry(monkeypatch):
    calls = []
    monkeypatch.setattr(api_main.projections, "project_elements_next_gws",
                        lambda **kw: (calls.append(kw["horizon_gws"]) or _proj(kw["gw_start"], {1: 1.0})))
    monkeypatch.setattr(api_main, "get_bootstrap_cached", lambda: {"elements": [], "teams": []})
    monkeypatch.setattr(api_main, "get_fixtures_cached", lambda: pd.DataFrame())
    monkeypatch.setattr(api_main.transforms, "tables_from_bootstrap",
                        lambda b: (pd.DataFrame(), pd.DataFrame({"id": [], "short_name": []}), None))
    api_main.get_projections_cached(3, 1)
    api_main.get_projections_cached(3, 3)
    assert calls == [1, 3], "the squad and recommendation horizons must not evict each other"


def test_refresh_clears_and_warms_the_projection_cache(monkeypatch):
    """
    New history invalidates every projection, and a cold rebuild costs seconds on
    a shared-cpu machine. The scheduled refresh should absorb that, not the next
    person to open the app.
    """
    warmed = []
    api_main._projections_cache[(99, 1)] = {"ts": 1.0, "data": "stale"}

    monkeypatch.setattr(api_main, "get_projections_cached",
                        lambda gw, h, fin=None: warmed.append((gw, h)))
    monkeypatch.setattr(api_main, "check_admin_key", lambda **kw: None)
    monkeypatch.setattr(api_main, "get_bootstrap_cached",
                        lambda: {"events": [{"id": 1, "finished": True}], "elements": [], "teams": []})
    monkeypatch.setattr(api_main, "get_fixtures_cached", lambda: pd.DataFrame())
    monkeypatch.setattr(api_main, "build_next_event_summary",
                        lambda bootstrap=None, fixtures=None: {"event_id": 3})
    monkeypatch.setattr(api_main, "refresh_match_history", lambda b, f: {"appended_events": [1]})

    api_main.admin_refresh(payload={"run_snapshot": False})

    assert (99, 1) not in api_main._projections_cache, "stale entries must be dropped"
    assert (3, 1) in warmed, "the next gameweek's squad-view horizon must be warmed"
    assert len(warmed) == 2, f"squad and recommendation horizons both warmed: {warmed}"
