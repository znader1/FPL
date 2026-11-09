"""Row builders of the monitoring backfill (the network shell is untested, as in
scripts/snapshot_to_db.py). Cases use the owner's real GW9 numbers."""
import json
import pathlib

from scripts import monitor_backfill as mb

TEAMS = [{"name": "Chelsea", "short_name": "CHE"}, {"name": "Man City", "short_name": "MCI"},
         {"name": "Aston Villa", "short_name": "AVL"}]
PLAYERS = [
    {"id": 411, "first_name": "Erling", "second_name": "Haaland", "web_name": "Haaland", "team_short": "MCI"},
    {"id": 154, "first_name": "Cole", "second_name": "Palmer", "web_name": "Palmer", "team_short": "CHE"},
    {"id": 597, "first_name": "Zion", "second_name": "Suzuki", "web_name": "Suzuki", "team_short": "AVL"},
]


def _parsed(players, captain=None, vice=None, stated=False, inferred=None, needs_review=False, gw=9):
    return {"series": "selection", "gw": gw, "article_id": 4750445,
            "url": "https://www.premierleague.com/en/news/4750445", "title": "t",
            "published_at": "2026-10-29T11:53:00Z",
            "players": [{"name_raw": n, "club_raw": c, "price_m": 5.0, "reason": ""} for n, c in players],
            "captain": captain, "vice": vice, "captain_stated": stated, "captain_inferred": inferred,
            "needs_review": needs_review, "review_reason": None}


def test_actuals_row_uses_the_real_score_not_a_sum_of_picks():
    picks = {"active_chip": None,
             "entry_history": {"points": 64, "points_on_bench": 22, "event_transfers_cost": 0, "bank": 3, "value": 1012},
             "picks": [{"element": 411, "position": 10, "multiplier": 2, "is_captain": True, "is_vice_captain": False,
                        "element_type": 4}]}
    transfers = [{"event": 9, "element_in": 112, "element_out": 418, "time": "2026-10-31T09:30:00Z"},
                 {"event": 8, "element_in": 154, "element_out": 12, "time": "2026-10-23T16:18:00Z"}]
    row = mb.actuals_row(107342, "2026-27", 9, picks, transfers, {}, "t")
    assert (row["season"], row["gw"], row["entry_id"], row["captured_at"]) == ("2026-27", 9, 107342, "t")
    assert (row["points"], row["points_on_bench"], row["transfer_cost"]) == (64, 22, 0)
    assert (row["bank_m"], row["value_m"], row["chip"]) == (0.3, 101.2, None)
    assert row["transfers"] == [{"sell_id": 418, "buy_id": 112}]
    assert row["picks"] == [{"element": 411, "position": 10, "multiplier": 2, "is_captain": True,
                             "is_vice_captain": False}]


def test_actuals_row_records_the_chip_played():
    picks = {"active_chip": "freehit", "entry_history": {"points": 76}, "picks": []}
    assert mb.actuals_row(1, "2026-27", 7, picks, [], {}, "t")["chip"] == "freehit"


def test_advice_rows_are_always_replay_and_buy_targets_have_entry_zero():
    plan = {"available": True, "moves": [{"sell_id": 1, "buy_id": 2}], "action": "move", "plan": {"x": 1}}
    wildcard = {"available": True, "presets": {"balanced": [1, 2]}, "notes": []}
    buy = {"available": True, "player_ids": [5, 6]}
    rows = mb.advice_rows(107342, "2026-27", 9, plan, wildcard, buy, "v", "t")
    assert {r["origin"] for r in rows} == {"replay"}
    assert {(r["kind"], r["entry_id"]) for r in rows} == {
        ("transfer_plan", 107342), ("wildcard_drafts", 107342), ("buy_targets", 0)}
    assert all((r["season"], r["gw"], r["model_version"], r["captured_at"]) == ("2026-27", 9, "v", "t") for r in rows)
    json.dumps(rows)


def test_advice_rows_skip_what_was_not_replayed_and_keep_an_unavailable_answer():
    rows = mb.advice_rows(107342, "2026-27", 9, {"available": False, "reason": "boom"}, None, None, "v", "t")
    assert [(r["kind"], r["payload"]) for r in rows] == [("transfer_plan", {"available": False, "reason": "boom"})]


def test_advice_payload_is_made_json_safe():
    import numpy as np
    plan = {"available": True, "moves": [], "action": "roll", "plan": {"n": np.int64(3), "f": np.float64(1.5),
                                                                        "s": {"b", "a"}}}
    payload = mb.advice_rows(1, "2026-27", 9, plan, None, None, "v", "t")[0]["payload"]
    assert payload["plan"] == {"n": 3, "f": 1.5, "s": ["a", "b"]}


def test_expert_row_resolves_ids_and_the_captain():
    parsed = _parsed([("Erling Haaland", "Man City"), ("Cole Palmer", "Chelsea")],
                     captain="Erling Haaland", vice="Cole Palmer", stated=True)
    row = mb.expert_rows([parsed], {9: PLAYERS}, TEAMS, {}, "2026-27", "t")[0]
    assert (row["season"], row["gw"], row["source"], row["series"]) == ("2026-27", 9, "scout", "selection")
    assert [p["fpl_player_id"] for p in row["players"]] == [411, 154]
    assert (row["captain_player_id"], row["vice_player_id"], row["captain_stated"]) == (411, 154, True)
    assert row["unmatched"] == [] and row["needs_review"] is False
    assert row["article_id"] == 4750445 and row["fetched_at"] == "t"


def test_expert_row_keeps_an_inferred_captain_apart_from_a_stated_one():
    parsed = _parsed([("Erling Haaland", "Man City")], inferred="Erling Haaland")
    row = mb.expert_rows([parsed], {9: PLAYERS}, TEAMS, {}, "2026-27", "t")[0]
    assert (row["captain_player_id"], row["captain_stated"], row["captain_inferred_player_id"]) == (None, False, 411)


def test_expert_row_flags_an_unmatched_name():
    parsed = _parsed([("Erling Haaland", "Man City"), ("New Signing", "Chelsea")])
    rows = mb.expert_rows([parsed], {9: PLAYERS}, TEAMS, {}, "2026-27", "t")
    assert rows[0]["needs_review"] is True
    assert rows[0]["unmatched"] == [{"name_raw": "New Signing", "club_raw": "Chelsea"}]
    assert [p["fpl_player_id"] for p in rows[0]["players"]] == [411, None]
    assert "New Signing" in rows[0]["review_reason"]


def test_expert_row_uses_name_overrides_and_falls_back_to_default_players():
    parsed = _parsed([("New Signing", "Chelsea")], gw=1)
    row = mb.expert_rows([parsed], {"default": PLAYERS}, TEAMS, {"names": {"new signing|CHE": 154}},
                         "2026-27", "t")[0]
    assert row["players"][0]["fpl_player_id"] == 154 and row["needs_review"] is False


def test_an_article_without_a_gameweek_or_series_is_not_stored():
    parsed = dict(_parsed([]), series=None, gw=None)
    assert mb.expert_rows([parsed], {9: PLAYERS}, TEAMS, {}, "2026-27", "t") == []


def test_report_row():
    row = mb.report_row({"season": "2026-27", "gw": 9, "entry_id": 107342, "x": 1}, "t", "v")
    assert row == {"season": "2026-27", "gw": 9, "entry_id": 107342,
                   "report": {"season": "2026-27", "gw": 9, "entry_id": 107342, "x": 1},
                   "built_at": "t", "code_version": "v"}


def test_parse_gws():
    assert mb.parse_gws("1-10") == list(range(1, 11))
    assert mb.parse_gws("3,5") == [3, 5]
    assert mb.parse_gws("2-3,9") == [2, 3, 9]


def test_a_live_advice_row_wins_over_a_replayed_one():
    replay = {(9, "transfer_plan"): {"origin": "replay", "payload": {"a": 1}},
              (9, "buy_targets"): {"origin": "replay", "payload": {"b": 1}}}
    live = [{"gw": 9, "kind": "transfer_plan", "origin": "live", "payload": {"a": 2}, "model_version": "v"}]
    out = mb.prefer_live(replay, live)
    assert out[(9, "transfer_plan")]["origin"] == "live" and out[(9, "transfer_plan")]["payload"] == {"a": 2}
    assert out[(9, "buy_targets")]["origin"] == "replay"


def test_season_start_is_a_month_before_the_first_deadline():
    bootstrap = {"events": [{"id": 2, "deadline_time": "2026-08-28T17:30:00Z"},
                            {"id": 1, "deadline_time": "2026-08-21T17:30:00Z"}]}
    assert mb.season_start(bootstrap) == "2026-07-22"


def test_points_and_minutes_come_from_the_live_payload():
    live = {"elements": [{"id": 411, "stats": {"total_points": 2, "minutes": 90}},
                         {"id": 12, "stats": {"total_points": 0, "minutes": 0}}]}
    assert mb.live_points_minutes(live) == ({411: 2, 12: 0}, {411: 90, 12: 0})


def test_workflow_passes_inputs_through_env_not_the_shell_line():
    wf = pathlib.Path(".github/workflows/monitor-backfill.yml").read_text()
    run_lines = [line for line in wf.splitlines() if "monitor_backfill.py" in line]
    assert run_lines and all("${{" not in line for line in run_lines)
    assert "workflow_dispatch" in wf and "secrets.SUPABASE_SERVICE_KEY" in wf


def test_no_print_or_log_line_mentions_the_service_key():
    for line in pathlib.Path("scripts/monitor_backfill.py").read_text().splitlines():
        if "print(" in line or "logger." in line or "logging." in line:
            assert "sb_key" not in line and "service_key" not in line.lower()


def test_the_script_never_writes_or_deletes_live_advice():
    src = pathlib.Path("scripts/monitor_backfill.py").read_text()
    assert '"origin": "live"' not in src and "requests.delete" not in src


# --- final review: a degraded run must not overwrite good rows or exit green -----------------

def test_only_a_404_means_an_entry_has_no_picks():
    class Resp:
        def __init__(self, code):
            self.status_code = code

    import requests
    assert mb.picks_absent(requests.HTTPError(response=Resp(404))) is True
    assert mb.picks_absent(requests.HTTPError(response=Resp(429))) is False
    assert mb.picks_absent(requests.HTTPError(response=Resp(503))) is False
    assert mb.picks_absent(requests.ConnectionError("down")) is False


def test_an_engine_error_is_a_failure_but_a_missing_squad_is_not():
    assert mb.replay_failed({"available": False, "reason": "ValueError: boom"}) is True
    assert mb.replay_failed({"available": False, "reason": "no squad known before this gameweek"}) is False
    assert mb.replay_failed({"available": True}) is False
    assert mb.replay_failed({"available": True, "presets": {"balanced": None, "gems": [1]}}) is False


def test_rows_from_failed_inputs_are_not_written():
    out = {
        "expert_picks": [{"gw": 9}],
        "entry_gw_actuals": [{"entry_id": 1, "gw": 9}],
        "advice_snapshots": [{"entry_id": 1, "gw": 9, "kind": "transfer_plan", "payload": {"available": True}},
                             {"entry_id": 1, "gw": 8, "kind": "transfer_plan",
                              "payload": {"available": False, "reason": "ValueError: boom"}},
                             {"entry_id": 0, "gw": 9, "kind": "buy_targets", "payload": {"available": True}}],
        "monitor_reports": [{"entry_id": 1, "gw": 9}, {"entry_id": 1, "gw": 8}, {"entry_id": 2, "gw": 8}],
    }
    kept = mb.writable(out, failed={(1, 8)}, shared_failure=False)
    assert kept["monitor_reports"] == [{"entry_id": 1, "gw": 9}, {"entry_id": 2, "gw": 8}]
    assert [(r["entry_id"], r["gw"]) for r in kept["advice_snapshots"]] == [(1, 9), (0, 9)]
    assert kept["expert_picks"] == out["expert_picks"] and kept["entry_gw_actuals"] == out["entry_gw_actuals"]


def test_a_gameweek_wide_failure_blocks_every_entrys_report_for_it():
    out = {"expert_picks": [], "entry_gw_actuals": [], "advice_snapshots": [],
           "monitor_reports": [{"entry_id": 1, "gw": 9}, {"entry_id": 2, "gw": 9}, {"entry_id": 2, "gw": 8}]}
    assert mb.writable(out, failed={(None, 9)}, shared_failure=False)["monitor_reports"] == [{"entry_id": 2, "gw": 8}]


def test_a_shared_failure_writes_no_report_at_all():
    out = {"expert_picks": [{"gw": 9}], "entry_gw_actuals": [{"entry_id": 1, "gw": 9}], "advice_snapshots": [],
           "monitor_reports": [{"entry_id": 1, "gw": 9}]}
    kept = mb.writable(out, failed=set(), shared_failure=True)
    assert kept["monitor_reports"] == [] and kept["entry_gw_actuals"] == out["entry_gw_actuals"]


def test_article_prose_is_not_stored():
    parsed = _parsed([("Erling Haaland", "Man City")])
    parsed["players"][0]["reason"] = "The Norwegian has to be backed with the captain's armband."
    row = mb.expert_rows([parsed], {9: PLAYERS}, TEAMS, {}, "2026-27", "t")[0]
    assert "reason" not in row["players"][0]
    assert row["players"][0] == {"name_raw": "Erling Haaland", "club_raw": "Man City", "price_m": 5.0,
                                 "fpl_player_id": 411}


def _events(last_finished, current, nxt, total=38):
    return [{"id": i, "finished": i <= last_finished, "is_current": i == current, "is_next": i == nxt}
            for i in range(1, total + 1)]


def test_auto_gws_are_the_seven_gameweeks_up_to_the_next_deadline():
    # GW10 live (deadline passed, not finished), GW11 next: windows of GW5 (5 gameweeks,
    # GW5-9) are complete and rebuilt once more; GW11 gets its pre-deadline projections.
    assert mb.auto_gws(_events(9, 10, 11)) == [5, 6, 7, 8, 9, 10, 11]


def test_auto_gws_start_at_one_early_in_the_season():
    assert mb.auto_gws(_events(2, 2, 3)) == [1, 2, 3]


def test_auto_gws_without_a_next_event_use_the_finished_one_plus_one():
    events = [{"id": i, "finished": i <= 38} for i in range(1, 39)]
    assert mb.auto_gws(events) == [32, 33, 34, 35, 36, 37, 38]


def test_parse_gws_auto_reads_the_events():
    assert mb.parse_gws("auto", _events(2, 2, 3)) == [1, 2, 3]


def test_current_gw_is_the_live_one_or_the_last_finished():
    assert mb.current_gw(_events(9, 10, 11)) == 10      # live: picks are public
    assert mb.current_gw(_events(9, 9, 10)) == 9        # before GW10's deadline
    assert mb.current_gw([{"id": 1, "finished": False}]) == 0


def test_workflow_runs_on_a_schedule_with_auto_gameweeks():
    wf = pathlib.Path(".github/workflows/monitor-backfill.yml").read_text()
    assert "schedule:" in wf and "cron:" in wf
    assert "'auto'" in wf or '"auto"' in wf
