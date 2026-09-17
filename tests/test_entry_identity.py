"""Entry identity lookup — the guard against a season-rolled-over entry id."""
import pytest
from fastapi import HTTPException

from api import main as api_main


ZIAD_2025_26 = {
    "id": 588004, "player_first_name": "Ziad", "player_last_name": "Nader",
    "name": "ZN Elite", "joined_time": "2025-07-21T17:40:54.591240Z",
    "started_event": 1, "years_active": 14, "player_region_name": "France",
    "summary_overall_rank": 73620, "summary_overall_points": 2338, "current_event": 38,
}

# Same id, next season, different human. This is the real observed rollover.
SOMEONE_ELSE_2026_27 = {
    "id": 588004, "player_first_name": "Jon", "player_last_name": "Snow",
    "name": "Stach 'n' Cheese", "joined_time": "2026-07-23T20:52:58.603458Z",
    "started_event": 1, "years_active": 1, "player_region_name": "Isle of Man",
    "summary_overall_rank": 3242957, "summary_overall_points": 44, "current_event": 2,
}


def test_reports_the_manager_behind_an_entry_id(monkeypatch):
    monkeypatch.setattr(api_main.fpl_client, "get_entry", lambda eid, session=None: ZIAD_2025_26)
    out = api_main.build_entry_identity(588004)
    assert out["manager_name"] == "Ziad Nader"
    assert out["team_name"] == "ZN Elite"
    assert out["overall_rank"] == 73620


def test_the_same_id_reports_a_different_manager_after_rollover(monkeypatch):
    """
    The whole reason this endpoint exists: FPL reissues entry ids each season,
    so a stored id resolves to somebody else and the fetch still returns 200.
    """
    monkeypatch.setattr(api_main.fpl_client, "get_entry", lambda eid, session=None: SOMEONE_ELSE_2026_27)
    out = api_main.build_entry_identity(588004)
    assert out["manager_name"] == "Jon Snow"
    assert out["joined_time"] != ZIAD_2025_26["joined_time"]
    assert out["years_active"] == 1


def test_joined_time_is_the_signal_a_client_can_compare_on(monkeypatch):
    monkeypatch.setattr(api_main.fpl_client, "get_entry", lambda eid, session=None: SOMEONE_ELSE_2026_27)
    out = api_main.build_entry_identity(588004)
    assert out["joined_time"] == "2026-07-23T20:52:58.603458Z"


@pytest.mark.parametrize("bad", [None, 0, -5, "abc"])
def test_a_non_positive_id_is_rejected_before_calling_upstream(bad, monkeypatch):
    monkeypatch.setattr(
        api_main.fpl_client, "get_entry",
        lambda eid, session=None: pytest.fail("must not hit FPL for an invalid id"))
    with pytest.raises(HTTPException) as exc:
        api_main.build_entry_identity(bad)
    assert exc.value.status_code == 400


def test_unknown_entry_surfaces_a_404_not_a_crash(monkeypatch):
    def _boom(eid, session=None):
        raise RuntimeError("404 Client Error")
    monkeypatch.setattr(api_main.fpl_client, "get_entry", _boom)
    with pytest.raises(HTTPException) as exc:
        api_main.build_entry_identity(999999999)
    assert exc.value.status_code == 404


def test_blank_manager_name_becomes_null_not_an_empty_string(monkeypatch):
    monkeypatch.setattr(
        api_main.fpl_client, "get_entry",
        lambda eid, session=None: {"id": 1, "name": "Nameless"})
    assert api_main.build_entry_identity(1)["manager_name"] is None
