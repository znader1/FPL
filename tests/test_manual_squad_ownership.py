"""Ownership enforcement on manual-squad writes (audit finding C4).

Before this, any authenticated caller could overwrite or delete *any* entry's
manual squad by passing someone else's entry_id — the JWT `sub` claim was never
read, so auth was a turnstile rather than a lock. These tests lock in that the
persisted squad records its owner and that a different owner is refused.

Callers authenticated with the static service key (server-to-server scripts,
the refresh cron) pass ``owner=None`` and are deliberately exempt.
"""
import json

import pytest

from src import auth, manual_squad


@pytest.fixture(autouse=True)
def _isolate_squad_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FPL_MANUAL_SQUAD_DIR", str(tmp_path))
    yield


def _ids():
    return list(range(1, 16))


# --- auth: the authenticated caller's identity must be recoverable --------

def test_authenticated_subject_returns_sub_for_valid_jwt(monkeypatch):
    monkeypatch.delenv("FPL_API_KEY", raising=False)
    monkeypatch.setattr(auth, "verify_supabase_jwt", lambda tok: {"sub": "user-1"})
    got = auth.authenticated_subject(authorization="Bearer good.token")
    assert got == {"kind": "user", "sub": "user-1"}


def test_authenticated_subject_returns_service_for_static_key(monkeypatch):
    monkeypatch.setenv("FPL_API_KEY", "s3cret")
    assert auth.authenticated_subject(x_api_key="s3cret") == {"kind": "service", "sub": None}


def test_authenticated_subject_returns_none_without_credentials(monkeypatch):
    monkeypatch.delenv("FPL_API_KEY", raising=False)
    monkeypatch.setattr(auth, "verify_supabase_jwt", lambda tok: None)
    assert auth.authenticated_subject(authorization="Bearer bad.token") is None


# --- manual squad: writes are owner-scoped -------------------------------

def test_save_records_the_owner():
    manual_squad.save_manual_squad(111, _ids(), owner="user-1")
    stored = json.loads(manual_squad._path_for(111).read_text())
    assert stored["owner_sub"] == "user-1"


def test_clear_rejects_a_different_owner():
    manual_squad.save_manual_squad(111, _ids(), owner="user-1")
    with pytest.raises(manual_squad.OwnershipError):
        manual_squad.clear_manual_squad(111, owner="attacker")
    assert manual_squad._path_for(111).exists()


def test_save_rejects_a_different_owner():
    manual_squad.save_manual_squad(111, _ids(), owner="user-1")
    with pytest.raises(manual_squad.OwnershipError):
        manual_squad.save_manual_squad(111, _ids(), owner="attacker")


def test_clear_allows_the_same_owner():
    manual_squad.save_manual_squad(111, _ids(), owner="user-1")
    assert manual_squad.clear_manual_squad(111, owner="user-1") is True


def test_service_caller_bypasses_ownership():
    """The refresh cron / scripts authenticate with the static key, no sub."""
    manual_squad.save_manual_squad(111, _ids(), owner="user-1")
    assert manual_squad.clear_manual_squad(111, owner=None) is True


def test_legacy_squad_without_an_owner_is_claimed_on_write():
    """Squads persisted before this change carry no owner_sub."""
    manual_squad.save_manual_squad(111, _ids(), owner=None)
    stored = json.loads(manual_squad._path_for(111).read_text())
    assert stored.get("owner_sub") is None

    manual_squad.save_manual_squad(111, _ids(), owner="user-1")
    stored = json.loads(manual_squad._path_for(111).read_text())
    assert stored["owner_sub"] == "user-1"


def test_clearing_a_missing_squad_is_still_false():
    assert manual_squad.clear_manual_squad(999, owner="user-1") is False
