"""H2 — every FT reader agrees with /recommendations, and the Chips baseline
plan keeps legacy settings while CHIP_PLAN_BASELINE_HEADLINE_SETTINGS is off."""
import pandas as pd

from src import config


def _history_banked_to(n_banked_gws):
    # n GWs with zero transfers after GW1 → min(FT_MAX, n_banked_gws + 1)... but
    # GW1 is skipped, so GW2..GW(n+1) bank: entering GW(n+2) = min(5, n+1).
    return {"current": [{"event": g, "event_transfers": 0} for g in range(1, n_banked_gws + 2)],
            "chips": []}


def test_chat_free_transfers_use_the_season_walk(monkeypatch):
    """A manager who banked 4 weeks gets 5 FT in chat/chips, not the old '1'."""
    from api import chat
    from src import fpl_client

    picks = {"entry_history": {"bank": 12, "event_transfers": 1}, "active_chip": None}
    monkeypatch.setattr(fpl_client, "get_entry_history", lambda entry_id: _history_banked_to(4))
    assert chat._free_transfers_for(1, current_gw=6, picks_data=picks, picks_event_id=5) == 5


def test_chat_free_transfers_match_recommendations_walk(monkeypatch):
    """Same history → chat answers exactly what ft_tracker.derive_free_transfers says."""
    from api import chat
    from src import fpl_client, ft_tracker

    history = {"current": [{"event": 1, "event_transfers": 0}, {"event": 2, "event_transfers": 2},
                           {"event": 3, "event_transfers": 0}, {"event": 4, "event_transfers": 0}],
               "chips": [{"name": "freehit", "event": 4}]}
    monkeypatch.setattr(fpl_client, "get_entry_history", lambda entry_id: history)
    picks = {"entry_history": {"event_transfers": 0}, "active_chip": "freehit"}
    expected = ft_tracker.derive_free_transfers(history["current"], history["chips"], next_event_id=5)
    assert chat._free_transfers_for(1, current_gw=5, picks_data=picks, picks_event_id=4) == expected


def test_chat_free_transfers_fall_back_when_history_fetch_fails(monkeypatch):
    from api import chat
    from src import fpl_client

    def boom(entry_id):
        raise RuntimeError("403")

    monkeypatch.setattr(fpl_client, "get_entry_history", boom)
    picks = {"entry_history": {"event_transfers": 0}, "active_chip": None}
    assert chat._free_transfers_for(1, current_gw=6, picks_data=picks, picks_event_id=5) == 2
    picks_wc = {"entry_history": {"event_transfers": 0}, "active_chip": "wildcard"}
    assert chat._free_transfers_for(1, current_gw=6, picks_data=picks_wc, picks_event_id=5) == 1


def test_chat_context_falls_back_without_history(monkeypatch):
    from src import ft_tracker
    assert ft_tracker.resolve_free_transfers(None, next_event_id=6, event_transfers=0, squad_event_id=5) == 2


def test_chips_baseline_plan_keeps_legacy_settings_when_flag_off(monkeypatch):
    from api import chips as chips_module
    from src import transfer_planner

    seen = {}

    def fake_plan(proj, squad_ids, gws, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop here")  # baseline failure is swallowed by the route

    monkeypatch.setattr(transfer_planner, "plan_transfers", fake_plan)
    monkeypatch.setattr(config, "CHIP_PLAN_BASELINE_HEADLINE_SETTINGS", False)
    ctx = {"proj": pd.DataFrame({"id": [1], "now_cost": [50], "team": [1]}), "gw_projections": {6: None, 7: None},
           "squad": pd.DataFrame({"player_id": [1]}), "bank_m": 1.2, "free_transfers": 3, "teams_short_map": {}}
    monkeypatch.setattr(chips_module, "_build_context_for_entry", lambda *a, **k: ctx)
    monkeypatch.setattr(chips_module, "build_chip_signals", lambda *a, **k: {}, raising=False)
    try:
        chips_module._build_plan_response(entry_id=1, current_gw=6, model_horizon=2)
    except Exception:
        pass
    assert seen["allow_hits"] is True
    assert seen["ft_cap"] == config.FT_MAX == 5
    assert seen["start_ft"] == 3
    assert "max_moves_per_gw" not in seen and "min_gain" not in seen


def test_chips_baseline_plan_uses_headline_settings_when_flag_on(monkeypatch):
    from api import chips as chips_module
    from src import transfer_planner

    seen = {}

    def fake_plan(proj, squad_ids, gws, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop here")

    monkeypatch.setattr(transfer_planner, "plan_transfers", fake_plan)
    monkeypatch.setattr(config, "CHIP_PLAN_BASELINE_HEADLINE_SETTINGS", True)
    ctx = {"proj": pd.DataFrame({"id": [1], "now_cost": [50], "team": [1]}), "gw_projections": {6: None, 7: None, 8: None},
           "squad": pd.DataFrame({"player_id": [1]}), "bank_m": 1.2, "free_transfers": 3, "teams_short_map": {}}
    monkeypatch.setattr(chips_module, "_build_context_for_entry", lambda *a, **k: ctx)
    monkeypatch.setattr(chips_module, "build_chip_signals", lambda *a, **k: {}, raising=False)
    try:
        chips_module._build_plan_response(entry_id=1, current_gw=6, model_horizon=3)
    except Exception:
        pass
    assert seen["allow_hits"] is bool(config.TRANSFER_PLAN_ALLOW_HITS)
    assert seen["max_moves_per_gw"] == int(config.TRANSFER_PLAN_MAX_MOVES_PER_GW)
    assert seen["min_gain"] == transfer_planner.scaled_min_gain(3)
