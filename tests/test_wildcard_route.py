import pandas as pd
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import wildcard as wc_module
from src import config
from tests.wildcard_market_fixture import wildcard_market


def _bootstrap():
    teams = [{"id": t, "name": f"Team {t}", "short_name": f"T{t:02d}", "code": t} for t in range(1, 21)]
    elements = [{"id": int(r.id), "goals_scored": 48 if int(r.id) == 1 else 3, "assists": 1, "clean_sheets": 0}
                for r in wildcard_market().itertuples()]
    events = [{"id": g, "is_next": g == 8, "is_current": g == 7, "finished": g < 8} for g in range(1, 39)]
    return {"teams": teams, "elements": elements, "events": events}


def _fixtures():
    rows = []
    fid = 1
    for gw in range(8, 16):
        for h in range(1, 21, 2):
            rows.append({"id": fid, "event": gw, "team_h": h, "team_a": h + 1, "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": False})
            fid += 1
    return pd.DataFrame(rows)


def _projections(**kw):
    m = wildcard_market()
    gw_start, horizon = int(kw["gw_start"]), int(kw["horizon_gws"])
    out = m.copy()
    out["team_name"] = out["team"].map(lambda t: f"Team {t}")
    out["team_short"] = out["team"].map(lambda t: f"T{t:02d}")
    out["xpts_horizon"] = 0.0
    for gw in range(gw_start, gw_start + horizon):
        out[f"xpts_gw{gw}"] = (out["wildcard_score"] / 5.0).round(2)
        out[f"fixture_count_gw{gw}"] = 1
        out[f"fixtures_gw{gw}"] = "OPP (H)"
        out["xpts_horizon"] += out[f"xpts_gw{gw}"]
    return out.drop(columns=["wildcard_score"])


def _context(entry_id, squad_event_id=None, with_fixtures=True):
    elements = wildcard_market()[["id", "web_name", "pos", "team", "price_m", "status"]].copy()
    elements["team_name"] = elements["team"].map(lambda t: f"Team {t}")
    elements["team_short"] = elements["team"].map(lambda t: f"T{t:02d}")
    elements["now_cost"] = (elements["price_m"] * 10).astype(int)
    squad_ids = list(range(1, 16))
    return {
        "entry_id": int(entry_id), "squad_event_id": 7, "max_event_id": 38,
        "bootstrap": _bootstrap(), "fixtures": _fixtures(), "elements": elements,
        "teams": pd.DataFrame(_bootstrap()["teams"]),
        "teams_short": {t: f"T{t:02d}" for t in range(1, 21)}, "teams_code": {t: t for t in range(1, 21)},
        "myteam": {}, "squad_df": pd.DataFrame({"player_id": squad_ids}),
        "notes": [], "derived_itb_m": 0.4, "derived_free_transfers": 1,
        "entry_history": {"value": 1004, "bank": 4},
    }


@pytest.fixture
def stubbed(monkeypatch):
    monkeypatch.setattr(wc_module, "_load_context", _context)
    monkeypatch.setattr(wc_module.projections, "project_elements_next_gws", lambda **kw: _projections(**kw))
    monkeypatch.setattr(wc_module.projections, "attach_wildcard_signals",
                        lambda df, gw_start, match_df=None, status_path=None: df.assign(wildcard_trend=0.0, p_miss=0.0, injury_flag=False))
    monkeypatch.setattr(wc_module.player_knowledge, "apply", lambda df, gws, request_pk=None: (df, []))
    monkeypatch.setattr(wc_module.fixture_difficulty, "load_match_history", lambda: pd.DataFrame())
    yield


def test_drafts_returns_three_presets_and_core(stubbed):
    body = wc_module.build_wildcard_drafts({"entry_id": 123, "horizon_gws": 5})
    assert body["event_id"] == 8 and body["horizon_gws"] == 5
    assert body["budget_breakdown"]["source"] == "entry_value" and body["budget_breakdown"]["budget_m"] == 100.4
    assert [p["name"] for p in body["presets"]] == list(config.CHIP_WILDCARD_PRESET_ORDER)
    for p in body["presets"]:
        assert len(p["squad"]) == 15 and len(p["xi_ids"]) == 11
        assert p["squad_cost_m"] <= 100.4 + 1e-9
        assert isinstance(p["captain_id"], int) and p["captain_id"] in p["xi_ids"]
        assert p["transfers_from_current"] >= 0
        rec = p["squad"][0]
        assert "score_breakdown" in rec and "wildcard" in rec["score_breakdown"]
        assert rec["score_breakdown"]["wildcard"]["role"] in {"xi", "pinned", "gk2", "def_cover", "dc_mid", "free", "enabler"}
    assert set(body["core_ids"]) <= set(body["presets"][0]["xi_ids"])
    assert body["presets"][0]["premiums"] == 3 and body["presets"][1]["premiums"] == 2


def test_drafts_honours_pins_and_excludes(stubbed):
    body = wc_module.build_wildcard_drafts({"entry_id": 1, "pinned_ids": [150], "excluded_ids": [12]})
    for p in body["presets"]:
        ids = {r["player_id"] for r in p["squad"]}
        assert 150 in ids and 12 not in ids


def test_drafts_requires_auth(stubbed):
    from api.main import app
    app.dependency_overrides = {}
    client = TestClient(app)
    r = client.post("/wildcard/drafts", json={"entry_id": 1})
    assert r.status_code == 401


def test_drafts_route_ok_with_auth(stubbed):
    from api.main import app
    from src.auth import require_user
    app.dependency_overrides[require_user] = lambda: {"sub": "test-user"}
    try:
        client = TestClient(app)
        r = client.post("/wildcard/drafts", json={"entry_id": 1, "horizon_gws": 3})
        assert r.status_code == 200, r.text
        assert len(r.json()["presets"]) == 3
    finally:
        app.dependency_overrides = {}


def test_unknown_preset_422():
    from api import main as api_main
    with pytest.raises(HTTPException) as e:
        api_main.resolve_wildcard_preset({"chip_strategy": "wildcard", "wildcard_preset": "nope"})
    assert e.value.status_code == 422
    name, preset = api_main.resolve_wildcard_preset({"chip_strategy": "wildcard"})
    assert name == "balanced" and preset is config.CHIP_WILDCARD_PRESETS["balanced"]
    assert api_main.resolve_wildcard_preset({"chip_strategy": "none"}) == (None, None)


def test_drafts_rejects_bad_pin_lists_422(stubbed):
    from api.main import app
    from src.auth import require_user
    app.dependency_overrides[require_user] = lambda: {"sub": "test-user"}
    try:
        client = TestClient(app)
        assert client.post("/wildcard/drafts", json={"entry_id": 1, "pinned_ids": "123"}).status_code == 422
        assert client.post("/wildcard/drafts", json={"entry_id": 1, "pinned_ids": 5}).status_code == 422
        assert client.post("/wildcard/drafts", json={"entry_id": 1, "excluded_ids": list(range(40))}).status_code == 422
        assert client.post("/wildcard/drafts", json={"entry_id": 1, "pinned_ids": [1, "x"]}).status_code == 422
        assert client.post("/wildcard/drafts", json={"pinned_ids": [1]}).status_code == 422
    finally:
        app.dependency_overrides = {}


def test_recommendations_id_lists_validated():
    from api import main as api_main
    with pytest.raises(HTTPException) as e:
        api_main.parse_id_list({"pinned_ids": "12"}, "pinned_ids")
    assert e.value.status_code == 422
    assert api_main.parse_id_list({"pinned_ids": [3, 3, "4"]}, "pinned_ids") == [3, 4]
    assert api_main.parse_id_list({}, "pinned_ids") == []
