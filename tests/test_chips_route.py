import pandas as pd
from fastapi.testclient import TestClient


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
