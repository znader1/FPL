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
