"""Cross-tenant protection on the manual-squad write routes (audit finding C4).

The exploit these lock out: sign up for a free account, then
``DELETE /squad/manual?entry_id=<someone else's>`` with your own valid token.
Entry ids are public and enumerable, so this scripted across the whole user base.
"""
import importlib
import json

import pytest

from src import auth, manual_squad


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("FPL_API_KEY", raising=False)
    monkeypatch.setenv("FPL_MANUAL_SQUAD_DIR", str(tmp_path))
    from fastapi.testclient import TestClient
    import api.main as main
    importlib.reload(main)
    return TestClient(main.app)


def _as_user(monkeypatch, sub):
    """Make every presented bearer token verify as this Supabase user."""
    monkeypatch.setattr(auth, "verify_supabase_jwt", lambda tok: {"sub": sub})


def _seed_squad_owned_by(entry_id, sub):
    manual_squad.save_manual_squad(entry_id, list(range(1, 16)), owner=sub)


def test_delete_refuses_another_users_squad(client, monkeypatch):
    _seed_squad_owned_by(4242, "victim-sub")
    _as_user(monkeypatch, "attacker-sub")

    res = client.delete(
        "/squad/manual",
        params={"entry_id": 4242},
        headers={"Authorization": "Bearer attacker.token"},
    )

    assert res.status_code == 403
    assert manual_squad.load_manual_squad(4242) is not None, "victim's squad was deleted"


def test_delete_allows_the_owner(client, monkeypatch):
    _seed_squad_owned_by(4242, "owner-sub")
    _as_user(monkeypatch, "owner-sub")

    res = client.delete(
        "/squad/manual",
        params={"entry_id": 4242},
        headers={"Authorization": "Bearer owner.token"},
    )

    assert res.status_code == 200
    assert res.json()["removed"] is True
    assert manual_squad.load_manual_squad(4242) is None


def test_post_refuses_overwriting_another_users_squad(client, monkeypatch):
    _seed_squad_owned_by(4242, "victim-sub")
    _as_user(monkeypatch, "attacker-sub")

    res = client.post(
        "/squad/manual",
        json={"entry_id": 4242, "player_ids": list(range(1, 16))},
        headers={"Authorization": "Bearer attacker.token"},
    )

    assert res.status_code == 403
    stored = json.loads(manual_squad._path_for(4242).read_text())
    assert stored["owner_sub"] == "victim-sub"
