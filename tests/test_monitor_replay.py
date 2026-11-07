"""Replaying past advice as of a gameweek. The engine itself is covered by
test_season_replay / test_backtest_live_season; here the engine call is replaced
so the tests pin what the replay feeds it and what it does with the answer."""
import pathlib

import pandas as pd
import pytest

from src import config, injury_prior, monitor_replay, season_replay, transfer_planner

STATE = {"squad_ids": [1, 2, 3, 423], "bank_m": 1.2, "value_m": 100.4, "free_transfers": 2}
INPUTS = {
    "bootstrap": {"teams": [{"id": 1, "short_name": "AAA"}, {"id": 2, "short_name": "BBB"},
                            {"id": 3, "short_name": "CCC"}, {"id": 4, "short_name": "DDD"}]},
    "fixtures": pd.DataFrame({"event": [9, 9, 10], "team_h": [1, 3, 1], "team_a": [2, 4, 3]}),
    "history_df": pd.DataFrame(), "match_df": pd.DataFrame({"event": [7, 8, 9], "x": [1, 2, 3]}),
    "snapshots_df": pd.DataFrame(),
}


def _proj(ids=(1, 2, 3, 423, 50, 51)):
    return pd.DataFrame({"id": list(ids), "xpts_gw9": 4.0, "xpts_horizon": 12.0})


# --- squad and state before a gameweek -------------------------------------------------

def test_squad_before_gw8_is_the_gw6_squad_because_gw7_was_a_free_hit():
    picks = {6: list(range(1, 16)), 7: list(range(101, 116))}
    chips = [{"name": "bboost", "event": 1}, {"name": "freehit", "event": 7}]
    assert monitor_replay.permanent_squad_before(8, picks, chips) == list(range(1, 16))
    assert monitor_replay.permanent_squad_before(7, picks, chips) == list(range(1, 16))
    assert monitor_replay.permanent_squad_before(1, picks, chips) is None
    assert monitor_replay.permanent_squad_before(6, picks, chips) is None   # GW5 picks missing


def test_a_bench_boost_week_does_not_change_the_squad_rule():
    picks = {1: list(range(1, 16))}
    assert monitor_replay.permanent_squad_before(2, picks, [{"name": "bboost", "event": 1}]) == list(range(1, 16))


def test_entry_state_reads_bank_value_and_free_transfers_from_history():
    history = {"current": [{"event": 1, "bank": 5, "value": 1000, "event_transfers": 0},
                           {"event": 2, "bank": 12, "value": 1004, "event_transfers": 0}], "chips": []}
    s = monitor_replay.entry_state_before(3, {2: list(range(1, 16))}, history)
    assert s == {"squad_ids": list(range(1, 16)), "bank_m": 1.2, "value_m": 100.4, "free_transfers": 2}


def test_entry_state_after_a_free_hit_uses_the_week_before_it_for_squad_and_money():
    history = {"current": [{"event": 6, "bank": 3, "value": 1010, "event_transfers": 1},
                           {"event": 7, "bank": 40, "value": 990, "event_transfers": 8}],
               "chips": [{"name": "freehit", "event": 7}]}
    s = monitor_replay.entry_state_before(8, {6: [1, 2], 7: [9, 9]}, history)
    assert (s["squad_ids"], s["bank_m"], s["value_m"]) == ([1, 2], 0.3, 101.0)


def test_entry_state_is_none_without_the_needed_picks_or_history_row():
    assert monitor_replay.entry_state_before(1, {}, {"current": [], "chips": []}) is None
    assert monitor_replay.entry_state_before(3, {2: [1]}, {"current": [], "chips": []}) is None


# --- as-of status history -----------------------------------------------------------------

def test_as_of_status_history_has_no_row_from_the_target_gameweek_or_later(tmp_path):
    snaps = pd.DataFrame({"gw": [5, 6, 7, 8], "player_id": [1, 1, 1, 1],
                          "status": ["a", "i", "a", "d"], "chance": [None, 0, None, 50]})
    n = monitor_replay.write_status_history_as_of(snaps, "2026-27", 7, tmp_path / "s.csv")
    out = pd.read_csv(tmp_path / "s.csv")
    assert n == 2 and out.event.max() == 6 and list(out.columns) == list(injury_prior.COLUMNS)
    assert list(out.status) == ["a", "i"] and set(out.season.astype(str)) == {"2026-27"}
    prior = injury_prior.player_injury_prior(tmp_path / "s.csv")
    assert list(prior.element) == [1]          # the production reader accepts the file


# --- transfer plan --------------------------------------------------------------------------

def _record_plan(monkeypatch, seen, moves):
    monkeypatch.setattr(season_replay, "project_as_of", lambda *a, **k: _proj())

    def fake(proj, squad_ids, gws, **kw):
        seen.update(kw, gws=list(gws), squad_ids=list(squad_ids), proj_ids=list(proj["id"]))
        return {"plan": [{"gw": gws[0], "moves": moves}, {"gw": gws[1], "moves": [{"sell": {"id": 7}, "buy": {"id": 8}}]}]}

    monkeypatch.setattr(transfer_planner, "plan_transfers", fake)


def test_transfer_plan_is_called_with_production_arguments(monkeypatch):
    seen = {}
    _record_plan(monkeypatch, seen, [{"sell": {"id": 3}, "buy": {"id": 50}}])
    out = monitor_replay.replay_transfer_plan(9, STATE, INPUTS)
    assert seen["gws"] == [9, 10, 11]
    assert seen["allow_hits"] is bool(config.TRANSFER_PLAN_ALLOW_HITS)
    assert seen["max_moves_per_gw"] == int(config.TRANSFER_PLAN_MAX_MOVES_PER_GW)
    assert seen["min_gain"] == transfer_planner.scaled_min_gain(3)
    assert (seen["start_ft"], seen["itb_m"], seen["ft_cap"], seen["prioritize_injured"]) == (2, 1.2, 5, True)
    assert seen["opponents_by_gw"][9] == {"AAA": {"BBB"}, "BBB": {"AAA"}, "CCC": {"DDD"}, "DDD": {"CCC"}}
    assert seen["opponents_by_gw"][11] == {}
    assert out["available"] is True and out["action"] == "move"
    assert out["moves"] == [{"sell_id": 3, "buy_id": 50}]          # only the target gameweek's moves


def test_a_plan_that_rolls_has_no_moves(monkeypatch):
    _record_plan(monkeypatch, {}, [])
    out = monitor_replay.replay_transfer_plan(9, STATE, INPUTS)
    assert (out["action"], out["moves"]) == ("roll", [])


def test_engine_error_becomes_unavailable_with_a_reason(monkeypatch):
    def boom(*a, **k):
        raise ValueError("boom")
    monkeypatch.setattr(season_replay, "project_as_of", boom)
    assert monitor_replay.replay_transfer_plan(9, STATE, INPUTS) == {"available": False, "reason": "ValueError: boom"}
    assert monitor_replay.replay_buy_targets(9, INPUTS) == {"available": False, "reason": "ValueError: boom"}
    assert monitor_replay.replay_wildcard_squads(9, 100.0, INPUTS, "x.csv") == {
        "available": False, "reason": "ValueError: boom"}


def test_a_squad_player_missing_from_the_snapshot_is_named(monkeypatch):
    seen = {}
    _record_plan(monkeypatch, seen, [])
    monkeypatch.setattr(season_replay, "project_as_of", lambda *a, **k: _proj(ids=(1, 2, 3, 50)))
    out = monitor_replay.replay_transfer_plan(9, STATE, INPUTS)
    assert out["dropped_squad_ids"] == [423]


def test_no_state_means_no_plan():
    assert monitor_replay.replay_transfer_plan(9, None, INPUTS) == {
        "available": False, "reason": "no squad known before this gameweek"}


# --- wildcard squads ------------------------------------------------------------------------

def test_wildcard_uses_as_of_inputs_and_never_the_live_loaders(monkeypatch):
    from api import wildcard as wc
    from src import projections
    seen = {}
    monkeypatch.setattr(season_replay, "project_as_of",
                        lambda gw, horizon, inputs, overrides=None: seen.update(horizon=horizon) or _proj())
    monkeypatch.setattr(wc, "european_haircut", lambda proj, gws, bootstrap, calendar_path=None: proj)

    def signals(df, gw_start, match_df=None, status_path=None):
        seen.update(gw_start=gw_start, status_path=status_path, match_events=list(match_df["event"]))
        return df

    monkeypatch.setattr(projections, "attach_wildcard_signals", signals)

    def build(scoring, play_event_id, horizon, budget_m, preset_name, pinned_ids=None, excluded_ids=None):
        seen.setdefault("budgets", []).append(budget_m)
        if preset_name == "gems":
            return None, {"ok": False, "squad_df": None}
        return None, {"ok": True, "squad_df": pd.DataFrame({"id": range(15, 0, -1)})}

    monkeypatch.setattr(wc, "_build_preset", build)
    for live in ("preset_squad_ids", "_scoring_frame", "build_wildcard_drafts"):
        monkeypatch.setattr(wc, live, lambda *a, **k: pytest.fail("live loader called in replay"))

    out = monitor_replay.replay_wildcard_squads(9, 101.3, INPUTS, "as_of.csv")
    assert seen["horizon"] == int(config.CHIP_WILDCARD_DEFAULT_HORIZON_GWS)
    assert (seen["gw_start"], seen["status_path"]) == (9, "as_of.csv")
    assert seen["match_events"] == [7, 8]                      # match history capped below the gameweek
    assert seen["budgets"] == [101.3, 101.3, 101.3]
    assert out["available"] is True
    assert out["presets"]["balanced"] == list(range(1, 16)) and out["presets"]["gems"] is None
    assert set(out["presets"]) == set(config.CHIP_WILDCARD_PRESET_ORDER)
    assert any("injury prior" in n for n in out["notes"]) and any("European" in n for n in out["notes"])


# --- buy targets ------------------------------------------------------------------------------

def test_buy_targets_are_the_top_of_each_outfield_position_with_no_squad(monkeypatch):
    from src import recommender
    seen = {}
    monkeypatch.setattr(season_replay, "project_as_of", lambda *a, **k: _proj())
    monkeypatch.setattr(recommender, "prepare_market",
                        lambda el, score_col=None, horizon_gws=1: seen.update(score_col=score_col, h=horizon_gws) or el)

    def hot(el, owned_ids, n=5, xpts_col=None):
        seen.update(owned=list(owned_ids), n=n)
        return {"GKP": [{"id": 90}], "DEF": [{"id": 1}, {"id": 2}], "MID": [{"id": 3}, {"id": 4}],
                "FWD": [{"id": 5}, {"id": 6}]}

    monkeypatch.setattr(recommender, "hot_by_position", hot)
    out = monitor_replay.replay_buy_targets(9, INPUTS)
    assert out == {"available": True, "player_ids": [1, 2, 3, 4, 5, 6]}
    assert (seen["owned"], seen["n"]) == ([], int(config.MONITOR_BUY_LIST_PER_POSITION))
    assert (seen["score_col"], seen["h"]) == ("xpts_horizon", int(config.MONITOR_ADVICE_HORIZON_GWS))


# --- parity -----------------------------------------------------------------------------------

def test_parity_needs_a_same_version_row():
    snaps = pd.DataFrame({"gw": [9], "player_id": [1], "model_xpts": [4.0], "model_version": ["old"]})
    proj = pd.DataFrame({"id": [1], "xpts_gw9": [4.0]})
    assert monitor_replay.parity(proj, snaps, 9, "new") == {
        "status": "no_same_version_baseline", "mae": None, "corr": None, "n": 0}
    no_column = snaps.drop(columns=["model_version"])
    assert monitor_replay.parity(proj, no_column, 9, "new")["status"] == "no_same_version_baseline"


def test_parity_passes_or_fails_on_the_configured_marks():
    ids = list(range(1, 21))
    stored = [float(i) / 4 for i in ids]
    snaps = pd.DataFrame({"gw": 9, "player_id": ids, "model_xpts": stored, "model_version": "v"})
    close = pd.DataFrame({"id": ids, "xpts_gw9": [s + 0.01 for s in stored]})
    far = pd.DataFrame({"id": ids, "xpts_gw9": [s + 0.5 for s in stored]})
    good = monitor_replay.parity(close, snaps, 9, "v")
    assert good["status"] == "pass" and good["n"] == 20 and good["mae"] < 0.02
    assert monitor_replay.parity(far, snaps, 9, "v")["status"] == "fail"


# --- the boundary -----------------------------------------------------------------------------

def test_replay_modules_do_not_read_the_knowledge_files():
    for path in ("src/monitor_replay.py", "src/season_replay.py"):
        assert "player_knowledge" not in pathlib.Path(path).read_text()


def test_project_as_of_lives_in_src_and_the_script_delegates_to_it():
    from scripts import backtest_live_season
    assert callable(season_replay.project_as_of)
    assert "season_replay.project_as_of" in pathlib.Path("scripts/backtest_live_season.py").read_text()
    assert callable(backtest_live_season.project_gw)


# --- final review: today's set-piece takers must not reach a replayed gameweek ---------------

def test_set_piece_orders_are_switched_off_before_the_engine_sees_them(monkeypatch):
    seen = {}

    def fake(gw, horizon, inputs, overrides=None):
        seen["elements"] = inputs["bootstrap"]["elements"]
        return _proj()

    monkeypatch.setattr(season_replay, "project_as_of", fake)
    inputs = dict(INPUTS, bootstrap=dict(INPUTS["bootstrap"], elements=[
        {"id": 1, "web_name": "Taker", "penalties_order": 1, "direct_freekicks_order": 2,
         "corners_and_indirect_freekicks_order": 1, "team": 1}]))
    monitor_replay.project(9, 3, inputs)
    el = seen["elements"][0]
    assert (el["penalties_order"], el["direct_freekicks_order"], el["corners_and_indirect_freekicks_order"]) == (
        None, None, None)
    assert el["web_name"] == "Taker" and el["team"] == 1
    assert inputs["bootstrap"]["elements"][0]["penalties_order"] == 1     # the caller's data is untouched


def test_every_replay_goes_through_the_switched_off_projection(monkeypatch):
    calls = []
    monkeypatch.setattr(monitor_replay, "project", lambda gw, horizon, inputs: calls.append(horizon) or _proj())
    monkeypatch.setattr(transfer_planner, "plan_transfers", lambda *a, **k: {"plan": []})
    monitor_replay.replay_transfer_plan(9, STATE, INPUTS)
    monitor_replay.replay_buy_targets(9, INPUTS)
    assert calls == [int(config.MONITOR_ADVICE_HORIZON_GWS)] * 2
