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
