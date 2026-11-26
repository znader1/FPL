"""The chat/chips context must hand the projection engine a team-id -> short
name map. It once passed the element_types frame instead (third value of
tables_from_bootstrap), the xG blend raised inside a bare except, and the chip
planner silently ran without the xG model."""
import pytest

from src import fpl_client, projections


class _Stop(Exception):
    pass


def _bootstrap():
    return {
        "elements": [
            {"id": 1, "web_name": "A", "team": 1, "element_type": 3, "now_cost": 80, "status": "a"},
            {"id": 2, "web_name": "B", "team": 2, "element_type": 4, "now_cost": 90, "status": "a"},
        ],
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Chelsea", "short_name": "CHE"},
        ],
        "element_types": [
            {"id": 3, "singular_name_short": "MID"},
            {"id": 4, "singular_name_short": "FWD"},
        ],
        "events": [],
    }


def test_context_passes_team_short_name_map_to_projections(monkeypatch):
    from api import chat

    monkeypatch.setattr(fpl_client, "get_bootstrap", _bootstrap)
    monkeypatch.setattr(fpl_client, "get_fixtures", lambda: [])
    monkeypatch.setattr(fpl_client, "get_entry_picks", lambda entry_id, gw: {
        "picks": [{"element": 1, "position": 1, "is_captain": True},
                  {"element": 2, "position": 2}],
        "entry_history": {"bank": 10, "event_transfers": 0},
    })
    monkeypatch.setattr(chat, "_free_transfers_for", lambda *a, **k: 1)

    seen = {}

    def spy(**kwargs):
        seen.update(kwargs)
        raise _Stop

    monkeypatch.setattr(projections, "project_elements_next_gws", spy)

    with pytest.raises(_Stop):
        chat._build_context_for_entry(entry_id=7, current_gw=12, horizon=5)

    assert seen["teams_short_map"] == {1: "ARS", 2: "CHE"}
