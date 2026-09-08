import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import chips as _chips_module


@pytest.fixture(autouse=True)
def _clear_plan_cache():
    _chips_module._plan_cache.clear()
    yield
    _chips_module._plan_cache.clear()


def _fake_context(entry_id, current_gw, horizon=5):
    rows, pid = [], 1
    for pos, n in (("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for _ in range(n):
            rows.append((pid, f"p{pid}", pos, f"T{pid % 5}", 5.0, 3.0, 1))
            pid += 1
    market = pd.DataFrame(rows, columns=[
        "player_id", "name", "pos", "team", "price_m", "xpts", "fixture_count"])
    squad = market[["player_id", "name", "pos", "team", "price_m"]]
    gw_projections = {g: market for g in range(current_gw, current_gw + horizon)}
    proj = pd.DataFrame({
        "id": market["player_id"], "web_name": market["name"], "pos": market["pos"],
        "team_short": market["team"], "price_m": market["price_m"],
        **{f"xpts_gw{g}": market["xpts"] for g in range(current_gw, current_gw + horizon)},
    })
    return {
        "squad": squad, "market": market, "starting_xi": market.head(11),
        "gw_projections": gw_projections, "bank_m": 1.5, "free_transfers": 2,
        "captain_id": 1, "proj": proj,
        "fixtures": pd.DataFrame(columns=["event", "team_h", "team_a"]),
        "teams_short_map": {},
    }


def test_chips_plan_is_cached_within_ttl(monkeypatch):
    from api.main import app
    from api import chips as chips_module
    from src.auth import require_user

    calls = []

    def _counting_context(entry_id, current_gw, horizon=5):
        calls.append(entry_id)
        return _fake_context(entry_id, current_gw, horizon)

    monkeypatch.setattr(chips_module, "_build_context_for_entry", _counting_context)
    monkeypatch.setattr(chips_module, "_get_entry_chips", lambda entry_id: [])
    monkeypatch.setattr(chips_module, "_resolve_current_gw", lambda: 5)
    app.dependency_overrides[require_user] = lambda: {"sub": "test-user"}
    client = TestClient(app)
    r1 = client.get("/chips/plan?entry_id=321")
    r2 = client.get("/chips/plan?entry_id=321")
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json()
    assert len(calls) == 1, "second request within the TTL must not rebuild"
    app.dependency_overrides = {}


def test_chips_plan_route(monkeypatch):
    from api.main import app
    from api import chips as chips_module

    monkeypatch.setattr(chips_module, "_build_context_for_entry", _fake_context)
    monkeypatch.setattr(chips_module, "_get_entry_chips", lambda entry_id: [])
    monkeypatch.setattr(chips_module, "_resolve_current_gw", lambda: 5)
    app.dependency_overrides = {}
    # require_user is applied at include_router time; override it
    from src.auth import require_user
    app.dependency_overrides[require_user] = lambda: {"sub": "test-user"}

    client = TestClient(app)
    r = client.get("/chips/plan?entry_id=123")
    assert r.status_code == 200
    body = r.json()
    assert body["entry_id"] == 123
    assert body["current_gw"] == 5
    assert {c["name"] for c in body["chips_remaining"]} == {
        "wildcard", "free_hit", "bench_boost", "triple_captain"}
    assert isinstance(body["recommendations"], list)
    app.dependency_overrides = {}


def _fake_context_with_boosted_captain(entry_id, current_gw, horizon=5):
    """Same fake market as `_fake_context`, but with one FWD (player_id=13,
    team T3) boosted far above the flat 3.0 xpts baseline. That makes them
    the deterministic model-chosen captain (ties on cap-weighted score would
    otherwise be broken arbitrarily) with a TC uplift that clears
    CHIP_PLAN_MIN_EV["triple_captain"] (15.0) — needed to actually exercise
    the xGI/difficulty wiring under test, not just its absence.
    """
    ctx = _fake_context(entry_id, current_gw, horizon)
    ctx["market"].loc[ctx["market"]["player_id"] == 13, "xpts"] = 20.0
    return ctx


def test_plan_response_carries_new_optional_keys(monkeypatch):
    """/chips/plan wires breaks/team_difficulty_by_gw/swings/xgi_per90 into
    build_chip_plan. Beyond the brief's shape-only asserts, this pins down
    that the wiring actually reaches the engine: with a captain who has xGI
    data and a GW hit by an international break, the TC recommendation must
    carry haul_prob and the nudge must flag wait_for_team_news."""
    from api.main import app
    from api import chips as chips_module
    import api.main as main_module
    from src.auth import require_user

    current_gw = 5

    def _fake_bootstrap():
        # 7-day deadline cadence, except a 14-day gap landing on current_gw
        # (>BREAK_GAP_DAYS=10) — marks GW5 as a post-international-break GW.
        base = pd.Timestamp("2026-08-01T18:00:00Z")
        events = []
        for eid in range(1, 8):
            gap = 14 if eid == current_gw else 7
            if eid > 1:
                base = base + pd.Timedelta(days=gap)
            events.append({"id": eid, "deadline_time": base.isoformat()})
        teams = [{"id": 3, "name": "T3"}]
        elements = [{"id": pid, "expected_goals_per_90": 0.0, "expected_assists_per_90": 0.0}
                    for pid in range(1, 16)]
        for e in elements:
            if e["id"] == 13:
                e["expected_goals_per_90"] = 0.6
                e["expected_assists_per_90"] = 0.3
        return {"events": events, "teams": teams, "elements": elements}

    def _fake_ticker(gw_start=None, horizon_gws=6):
        gws = list(range(gw_start, gw_start + horizon_gws))
        cells = {gw: {"difficulty": 4.0 if gw < gw_start + 3 else 1.0} for gw in gws}
        return {
            "gw_start": gw_start, "horizon_gws": horizon_gws, "gws": gws,
            "teams": [{"team_id": 3, "team_short": "T3", "gws": cells}],
        }

    monkeypatch.setattr(chips_module, "_build_context_for_entry", _fake_context_with_boosted_captain)
    monkeypatch.setattr(chips_module, "_get_entry_chips", lambda entry_id: [])
    monkeypatch.setattr(chips_module, "_resolve_current_gw", lambda: current_gw)
    monkeypatch.setattr(chips_module.fpl_client, "get_bootstrap", _fake_bootstrap)
    monkeypatch.setattr(main_module, "build_fixture_difficulty_payload", _fake_ticker)

    app.dependency_overrides = {}
    app.dependency_overrides[require_user] = lambda: {"sub": "test-user"}
    client = TestClient(app)
    resp = client.get("/chips/plan", params={"entry_id": 1})
    assert resp.status_code == 200
    body = resp.json()

    nudge = body.get("nudge")
    if nudge is not None:
        assert isinstance(nudge.get("wait_for_team_news"), bool)
    for rec in body["recommendations"]:
        if "haul_prob" in rec:
            assert 0.0 <= rec["haul_prob"] <= 1.0

    # The wiring must actually reach the engine, not merely leave the new
    # keys as an inert no-op: the boosted captain (xGI-equipped, on a
    # break-hit GW) should produce a TC rec with a haul_prob, and the nudge
    # (fires for a current-GW rec >= CHIP_PLAN_NUDGE_MIN_EV) should flag
    # wait_for_team_news given the break at GW5.
    tc_recs = [r for r in body["recommendations"] if r.get("chip") == "triple_captain"]
    assert tc_recs, "expected a triple_captain recommendation to clear the EV floor"
    assert tc_recs[0].get("haul_prob") is not None, (
        "xgi_per90 wiring did not reach score_triple_captain")
    assert nudge is not None and nudge.get("chip") == "triple_captain"
    assert nudge["wait_for_team_news"] is True, (
        "breaks wiring did not reach build_chip_plan's nudge")
    app.dependency_overrides = {}
