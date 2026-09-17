import pytest

from api import main as api_main
from src import fpl_client


@pytest.fixture(autouse=True)
def clear_live_cache():
    api_main._event_live_cache.clear()
    yield
    api_main._event_live_cache.clear()


def _payload():
    return {
        "elements": [
            {"id": 42, "stats": {"total_points": 9, "minutes": 90, "bonus": 2, "bps": 41}},
            {"id": 7, "stats": {"total_points": 1, "minutes": 27, "bonus": 0, "bps": 3}},
            {"id": None, "stats": {"total_points": 5}},
        ]
    }


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_get_event_live_keys_by_player_id(monkeypatch):
    class _Session:
        def get(self, url, **kwargs):
            assert "/api/event/2/live/" in url
            return _Resp(_payload())

    stats = fpl_client.get_event_live(2, session=_Session())
    assert stats[42]["total_points"] == 9
    assert stats[7]["minutes"] == 27
    # An element with no id is skipped rather than keyed on None.
    assert None not in stats


def test_cached_getter_serves_second_call_from_cache(monkeypatch):
    calls = []

    def _fake(event_id, session=None):
        calls.append(event_id)
        return {42: {"total_points": 9}}

    monkeypatch.setattr(api_main.fpl_client, "get_event_live", _fake)
    assert api_main.get_event_live_cached(2)[42]["total_points"] == 9
    assert api_main.get_event_live_cached(2)[42]["total_points"] == 9
    assert calls == [2], "second call within the TTL must not refetch"


def test_cache_is_per_gameweek(monkeypatch):
    monkeypatch.setattr(
        api_main.fpl_client, "get_event_live",
        lambda event_id, session=None: {42: {"total_points": event_id * 10}},
    )
    # GW1 must not serve GW2's scores — the bug bootstrap's event_points would cause.
    assert api_main.get_event_live_cached(1)[42]["total_points"] == 10
    assert api_main.get_event_live_cached(2)[42]["total_points"] == 20


def test_upstream_failure_never_breaks_the_squad(monkeypatch):
    def _boom(event_id, session=None):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(api_main.fpl_client, "get_event_live", _boom)
    assert api_main.get_event_live_cached(3) == {}


def test_none_event_id_returns_empty(monkeypatch):
    monkeypatch.setattr(
        api_main.fpl_client, "get_event_live",
        lambda event_id, session=None: pytest.fail("must not fetch for a null GW"),
    )
    assert api_main.get_event_live_cached(None) == {}
