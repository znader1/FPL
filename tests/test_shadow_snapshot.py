import pandas as pd
import pytest

from scripts import shadow_snapshot as ss
from src import config


def _proj(values, gw=9):
    return pd.DataFrame({"id": list(values), f"xpts_gw{gw}": list(values.values())})


def test_shadow_rows_pair_runner_and_shadow_xpts():
    rows = ss.shadow_rows(_proj({1: 4.12345, 2: 3.0}), _proj({1: 3.98765, 2: 2.5}),
                          "2026-27", 9, "2026-10-22.blend70")
    by_id = {r["player_id"]: r for r in rows}
    assert by_id[1] == {"season": "2026-27", "gw": 9, "player_id": 1, "runner_xpts": 4.123,
                        "shadow_xpts": 3.988, "shadow_model_version": "2026-10-22.blend70"}
    assert by_id[2]["shadow_xpts"] == 2.5


def _boom(*a, **k):
    raise AssertionError("network must not be touched")


def test_no_overrides_means_no_work(monkeypatch):
    monkeypatch.setattr(config, "PROJ_SHADOW_OVERRIDES", {})
    monkeypatch.setattr(ss.requests, "get", _boom)
    monkeypatch.setattr(ss.requests, "post", _boom)
    monkeypatch.setattr(ss, "refresh_local_data", _boom)
    assert ss.main() == 0


def _stub_run(monkeypatch, project):
    monkeypatch.setattr(config, "PROJ_SHADOW_OVERRIDES", {"PROJ_MODEL_BLEND_WEIGHT": 0.5})
    monkeypatch.setattr(config, "PROJ_SHADOW_MODEL_VERSION", "prev")
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    monkeypatch.setattr(ss, "refresh_local_data", lambda: {"season": "2026-27", "gw": 9, "deadline_open": True})
    monkeypatch.setattr(ss, "project_next_gw", project)
    sent = []
    monkeypatch.setattr(ss, "upsert", lambda url, key, rows: sent.append(rows))
    return sent


def test_shadow_runs_under_overrides_and_restores_config(monkeypatch):
    before = config.PROJ_MODEL_BLEND_WEIGHT
    seen = []

    def project(gw):
        seen.append(config.PROJ_MODEL_BLEND_WEIGHT)
        return _proj({1: 4.0}, gw)

    sent = _stub_run(monkeypatch, project)
    assert ss.main() == 0
    assert seen == [before, 0.5]          # runner (current config) first, then the shadow
    assert config.PROJ_MODEL_BLEND_WEIGHT == before
    assert sent and sent[0][0]["shadow_model_version"] == "prev"


def test_projection_failure_never_fails_the_job(monkeypatch):
    def project(gw):
        raise RuntimeError("engine blew up")

    sent = _stub_run(monkeypatch, project)
    assert ss.main() == 0
    assert sent == []


def test_closed_deadline_writes_nothing(monkeypatch):
    sent = _stub_run(monkeypatch, lambda gw: _proj({1: 4.0}, gw))
    monkeypatch.setattr(ss, "refresh_local_data", lambda: {"season": "2026-27", "gw": 9, "deadline_open": False})
    assert ss.main() == 0
    assert sent == []
