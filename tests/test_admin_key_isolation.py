"""The admin key must not collapse into the shared user key (audit finding C5).

`check_admin_key` fell back to FPL_API_KEY, which is *also* accepted on every
user route. With FPL_ADMIN_KEY unset, any holder of the shared user key silently
gained /admin/refresh, /admin/model-snapshot and the squad-picker knowledge
writes — and those knowledge multipliers feed the projection engine.
"""
from fastapi.responses import JSONResponse

from src import auth


def test_user_key_is_not_accepted_as_the_admin_key(monkeypatch):
    monkeypatch.delenv("FPL_ADMIN_KEY", raising=False)
    monkeypatch.setenv("FPL_API_KEY", "shared-user-key")

    res = auth.check_admin_key(x_api_key="shared-user-key")

    assert isinstance(res, JSONResponse)
    assert res.status_code == 503, "must fail closed, not accept the user key"


def test_admin_key_still_accepted_when_configured(monkeypatch):
    monkeypatch.setenv("FPL_ADMIN_KEY", "adm1n")
    monkeypatch.setenv("FPL_API_KEY", "shared-user-key")
    assert auth.check_admin_key(x_api_key="adm1n") is None


def test_user_key_rejected_when_admin_key_is_configured(monkeypatch):
    monkeypatch.setenv("FPL_ADMIN_KEY", "adm1n")
    monkeypatch.setenv("FPL_API_KEY", "shared-user-key")
    res = auth.check_admin_key(x_api_key="shared-user-key")
    assert isinstance(res, JSONResponse) and res.status_code == 401
