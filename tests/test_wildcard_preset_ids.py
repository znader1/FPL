from api import wildcard as wc_module
from tests.test_wildcard_route import _bootstrap, _projections, stubbed  # noqa: F401 (fixture)


def test_preset_squad_ids_match_the_drafts_route(stubbed):
    body = wc_module.build_wildcard_drafts({"entry_id": 123, "horizon_gws": 5})
    balanced = next(p for p in body["presets"] if p["name"] == "balanced")
    route_ids = {int(r["player_id"]) for r in balanced["squad"]}

    ids = wc_module.preset_squad_ids(
        _projections(gw_start=8, horizon_gws=5), _bootstrap(), 8, 5,
        body["budget_breakdown"]["budget_m"], "balanced",
    )
    assert ids == route_ids
    assert len(ids) == 15


def test_preset_squad_ids_none_when_the_build_fails(stubbed, monkeypatch):
    monkeypatch.setattr(wc_module.optimizer, "build_chip_squad", lambda **kw: {"ok": False, "reason": "x"})
    assert wc_module.preset_squad_ids(_projections(gw_start=8, horizon_gws=5), _bootstrap(), 8, 5, 100.4, "balanced") is None
