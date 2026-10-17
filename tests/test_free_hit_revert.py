"""A Free Hit squad lasts one gameweek.

GW7 played with Free Hit, GW8 not locked yet: planning GW8 must start from the
permanent GW6 squad. The frontend always asks /squad for an explicit event_id,
so the step-back can't depend on the request being implicit.
"""
import importlib

import pytest

from src import fpl_client

FH_GW = 7
BOOTSTRAP = {
    "events": [
        {"id": 6, "is_current": False, "is_next": False, "is_previous": True, "finished": True},
        {"id": FH_GW, "is_current": True, "is_next": False, "is_previous": False, "finished": False},
        {"id": 8, "is_current": False, "is_next": True, "is_previous": False, "finished": False},
    ],
    "elements": [],
    "teams": [],
    "element_types": [],
}


def _picks(gw, chip=None):
    return {
        "picks": [{"element": 100 * gw + i, "position": i, "multiplier": 1, "is_captain": i == 1, "is_vice_captain": i == 2} for i in range(1, 16)],
        "active_chip": chip,
        "entry_history": {"event": gw, "bank": 5, "event_transfers": 0},
    }


@pytest.fixture()
def main(monkeypatch):
    import api.main as main_mod
    importlib.reload(main_mod)
    monkeypatch.setattr(main_mod, "get_bootstrap_cached", lambda: BOOTSTRAP)
    monkeypatch.setattr(main_mod.transforms, "tables_from_bootstrap", _tables)
    monkeypatch.setattr(fpl_client, "get_entry_history", lambda entry_id: None)

    def get_picks(entry_id, gw):
        if gw == FH_GW:
            return _picks(FH_GW, chip="freehit")
        if gw < FH_GW:
            return _picks(gw)
        raise RuntimeError("404: picks not published before the deadline")

    monkeypatch.setattr(fpl_client, "get_entry_picks", get_picks)
    return main_mod


def _tables(bootstrap):
    import pandas as pd
    teams = pd.DataFrame({"id": [1], "short_name": ["ARS"], "code": [3]})
    elements = pd.DataFrame(columns=["id", "web_name", "team", "team_name", "team_short", "pos"])
    return elements, teams, pd.DataFrame()


def _squad_gw(ctx):
    return {p["element"] // 100 for p in ctx["myteam"]["picks"]}


def test_planning_the_gw_after_a_free_hit_uses_the_permanent_squad(main):
    ctx = main.load_fpl_context(1, 8, with_fixtures=False)
    assert _squad_gw(ctx) == {6}
    assert ctx["free_hit_reverted_from"] == FH_GW
    assert any("Free hit" in n for n in ctx["notes"])


def test_implicit_request_after_a_free_hit_uses_the_permanent_squad(main):
    ctx = main.load_fpl_context(1, None, with_fixtures=False)
    assert _squad_gw(ctx) == {6}


def test_viewing_the_free_hit_gw_itself_shows_the_free_hit_squad(main):
    ctx = main.load_fpl_context(1, FH_GW, with_fixtures=False)
    assert _squad_gw(ctx) == {FH_GW}
    assert ctx["free_hit_reverted_from"] is None
