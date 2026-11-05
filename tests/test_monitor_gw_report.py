"""The gameweek report is the contract the dashboard page reads. GW9 uses the
real 2026-27 fixture; the other gameweeks reuse its players with hand-set
picks, chips and points so each rule has a case."""
import json
import pathlib

import pandas as pd

from src import config
from src.monitor_gw_report import build_gw_report

FIX = pathlib.Path("tests/fixtures/monitor")
E = json.loads((FIX / "gw9_expected.json").read_text())
CSV = pd.read_csv(FIX / "gw9_snapshots.csv")
OWNER = E["owner_picks"]
GW6_PICKS = OWNER
FREE_HIT_PICKS = [1, 4, 60, 61, 64, 67, 68, 13, 15, 79, 106, 57, 31, 40, 26]
ENTRY = 107342


def _picks(ids, captain, vice):
    return [{"element": pid, "position": i + 1, "multiplier": 2 if pid == captain else (1 if i < 11 else 0),
             "is_captain": pid == captain, "is_vice_captain": pid == vice} for i, pid in enumerate(ids)]


def _actuals(ids, captain, vice, points, bench=0, chip=None, transfers=None, cost=0):
    return {"picks": _picks(ids, captain, vice), "transfers": transfers or [], "chip": chip, "points": points,
            "points_on_bench": bench, "transfer_cost": cost, "bank_m": 0.3, "value_m": 101.2}


def _scout_row(series="selection", unmatched=None, stated=False, needs_review=False, ids=None, gw=9):
    ids = ids if ids is not None else E["scout_ids"]
    price = dict(zip(CSV.player_id.astype(int), CSV.price_m.astype(float)))
    return {
        "gw": gw, "series": series, "url": "https://www.premierleague.com/en/news/4750445",
        "published_at": "2026-10-29T11:53:00Z",
        "players": [{"name_raw": f"n{i}", "club_raw": "c", "price_m": price.get(i), "reason": "", "fpl_player_id": i}
                    for i in ids],
        "unmatched": unmatched or [], "captain_player_id": 411 if stated else None,
        "vice_player_id": 379 if stated else None, "captain_stated": stated,
        "captain_inferred_player_id": None if stated else 411,
        "needs_review": needs_review or bool(unmatched), "review_reason": None,
    }


def _data(**changes):
    pts = dict(zip(CSV.player_id.astype(int), CSV.actual_points.astype(int)))
    mins = dict(zip(CSV.player_id.astype(int), CSV.actual_minutes.astype(int)))
    data = {
        "season": "2026-27", "last_finished_gw": 9, "next_gw": 10, "code_version": "v-test",
        "snapshots_by_gw": {g: CSV.copy() for g in (6, 7, 8, 9, 10)},
        "points_by_gw": {g: dict(pts) for g in (1, 6, 7, 8, 9)},
        "minutes_by_gw": {g: dict(mins) for g in (1, 6, 7, 8, 9)},
        "bootstrap_players": {int(r.player_id): {"name": r.web_name, "club": r.team_short, "pos": r.pos}
                              for r in CSV.itertuples()} | {418: {"name": "Maguire", "club": "MUN", "pos": "DEF"}},
        "chips": [{"name": "bboost", "event": 1}, {"name": "freehit", "event": 7}],
        "actuals_by_gw": {
            1: _actuals(OWNER, 411, 154, 56, chip="bboost"),
            6: _actuals(GW6_PICKS, 411, 154, 75),
            7: _actuals(FREE_HIT_PICKS, 79, 68, 76, chip="freehit",
                        transfers=[{"sell_id": 8, "buy_id": 1}, {"sell_id": 94, "buy_id": 67}]),
            8: _actuals(OWNER, 411, 154, 32, transfers=[{"sell_id": 12, "buy_id": 154}]),
            9: _actuals(OWNER, 411, 154, 64, bench=22, transfers=[{"sell_id": 418, "buy_id": 112}]),
        },
        "expert": {(9, "selection"): _scout_row(), (10, "selection"): _scout_row(stated=True, gw=10),
                   (9, "transfer_radar"): _scout_row("transfer_radar", ids=[53, 237])},
        "advice": {
            (9, "transfer_plan"): {"origin": "replay", "model_version": "v-test", "payload": {
                "available": True, "action": "move", "moves": [{"sell_id": 534, "buy_id": 566}],
                "dropped_squad_ids": [423], "plan": {"verdict": "move"}}},
            (9, "buy_targets"): {"origin": "replay", "model_version": "v-test", "payload": {
                "available": True, "player_ids": [566, 4, 68, 156, 411, 79]}},
            (9, "wildcard_drafts"): {"origin": "replay", "model_version": "v-test", "payload": {
                "available": True, "notes": ["injury prior rebuilt"],
                "presets": {"aggressive": FREE_HIT_PICKS, "balanced": FREE_HIT_PICKS, "gems": None}}},
        },
        "parity": {9: {"status": "no_same_version_baseline", "mae": None, "corr": None, "n": 0}},
    }
    data.update(changes)
    return data


def build(gw, **changes):
    return build_gw_report(gw, ENTRY, _data(**changes))


def collect_ids(report):
    ids = set()
    for part in ("app_xi", "scout_xi", "you", "best_xi"):
        ids |= set(report[part].get("ids") or [])
    for side in ("app", "you"):
        for m in report["transfers"][side].get("moves") or []:
            ids |= {m["sell_id"], m["buy_id"]}
    for side in ("app", "scout"):
        ids |= {p["id"] for p in report["buy_lists"][side].get("players") or []}
    ids |= set(report["wildcard"]["kept"].get("ids") or [])
    for preset in (report["wildcard"]["app"].get("presets") or {}).values():
        ids |= set((preset or {}).get("ids") or [])
    for line in report["captain"].values():
        if line:
            ids.add(line["id"])
    return ids


def test_gw9_headline_is_70_69_64_115_without_captain():
    r = build(9)
    assert r["state"] == "finished"
    assert r["headline"] == {"basis": "no_captain", "app": 70, "scout": 69, "you": 64, "best": 115}
    assert r["app_xi"]["ids"] == E["app_xi_ids"]
    assert (r["app_xi"]["captain_id"], r["app_xi"]["vice_id"]) == (E["app_captain"], E["app_vice"])
    assert (r["app_xi"]["points_with_captain"], round(r["app_xi"]["projected"], 1)) == (72, 60.0)
    assert r["scout_xi"]["points_with_captain"] == 71
    assert (r["scout_xi"]["captain_stated"], r["scout_xi"]["captain_inferred_id"]) == (False, 411)
    assert r["you"]["points_on_bench"] == 22 and r["you"]["xi_ids"] == OWNER[:11]
    assert r["you"]["bench_ids"] == OWNER[11:] and r["you"]["captain_id"] == 411


def test_a_stated_scout_captain_makes_the_headline_with_captain():
    r = build(9, expert={(9, "selection"): _scout_row(stated=True)})
    assert r["headline"]["basis"] == "with_captain"
    assert (r["headline"]["app"], r["headline"]["scout"]) == (72, 71)


def test_gw9_transfers_score_the_real_move_and_the_replayed_advice():
    t = build(9)["transfers"]
    assert t["chip_week"] is False and t["verdict_window"] == config.MONITOR_TRANSFER_VERDICT_WINDOW_GWS
    assert t["you"]["moves"] == [{"sell_id": 418, "buy_id": 112}]
    assert t["you"]["windows"]["1"] == {"gain": 15, "played": 1, "complete": True}
    assert t["app"]["origin"] == "replay" and t["app"]["action"] == "move"
    assert t["app"]["windows"]["1"]["gain"] == 8 - 1          # Silva 8 for Hume 1
    assert t["verdict"] is None                                # the 3-gameweek window is not finished


def test_gw9_captain_card_has_four_lines():
    c = build(9)["captain"]
    assert c["you"] == {"id": 411, "points": 2}
    assert c["scout"] == {"id": 411, "points": 2, "stated": False}
    assert c["app_for_you"] == {"id": 411, "points": 2}
    assert c["best_in_squad"] == {"id": 112, "points": 15} and c["best_overall"] == {"id": 112, "points": 15}


def test_gw9_buy_lists_average_points_per_player():
    b = build(9)["buy_lists"]
    assert [p["id"] for p in b["app"]["players"]] == [566, 4, 68, 156, 411, 79]
    assert b["app"]["avg"]["1"] == (8 + 6 + 3 + 3 + 2 + 9) / 6
    assert [p["id"] for p in b["scout"]["players"]] == [53, 237] and b["scout"]["avg"]["1"] == (7 + 2) / 2
    assert b["scout"]["url"].startswith("https://www.premierleague.com/")


def test_gw9_wildcard_compares_the_draft_with_the_squad_he_kept():
    w = build(9)["wildcard"]
    assert w["window"] == config.MONITOR_WILDCARD_WINDOW_GWS
    assert sorted(w["kept"]["ids"]) == sorted(OWNER) and (w["kept"]["played"], w["kept"]["complete"]) == (1, False)
    assert w["app"]["headline_preset"] == config.MONITOR_WILDCARD_HEADLINE_PRESET
    assert w["app"]["presets"]["gems"] is None and w["app"]["presets"]["balanced"]["played"] == 1
    assert w["scout"] == {"available": False, "reason": "no Scout wildcard squad this gameweek"}
    assert w["actual"] == {"points": 64, "played": 1} and w["verdict"] is None


def test_a_confirmed_scout_wildcard_squad_is_scored_and_an_unconfirmed_one_is_not():
    squad = _scout_row("wildcard", ids=FREE_HIT_PICKS)
    r = build(9, expert={(9, "wildcard"): squad})
    assert r["wildcard"]["scout"]["available"] is True and r["wildcard"]["scout"]["played"] == 1
    r = build(9, expert={(9, "wildcard"): dict(squad, needs_review=True)})
    assert r["wildcard"]["scout"] == {"available": False, "reason": "squad article needs review",
                                      "url": squad["url"]}


def test_gw1_has_no_app_column_but_still_has_the_owner():
    r = build(1, snapshots_by_gw={g: CSV.copy() for g in (2, 3, 4, 5, 9)},
              expert={(1, "season_squad"): _scout_row("season_squad", gw=1)})
    assert r["app_xi"] == {"available": False, "reason": "no pre-deadline snapshot"}
    assert r["you"]["available"] is True and r["transfers"]["app"]["available"] is False
    assert r["you"]["points"] == 56 and r["best_xi"]["available"] is True     # real points exist without a snapshot
    assert all(r["players"][str(i)]["points"] is not None for i in r["you"]["xi_ids"])
    assert all(r["players"][str(i)]["xpts"] is None for i in r["you"]["xi_ids"])
    assert r["scout_xi"] == {"available": False, "reason": "season squad, not an eleven"}
    assert r["captain"]["app_for_you"] is None
    assert r["wildcard"]["kept"]["no_projection_gws"] == [1]


def test_before_the_deadline_picks_show_and_points_are_null():
    r = build(10)
    assert r["state"] == "before_deadline"
    assert r["scout_xi"]["ids"] and r["scout_xi"]["points_no_captain"] is None
    assert r["app_xi"]["ids"] and r["app_xi"]["points_with_captain"] is None
    assert r["you"] == {"available": False, "reason": "picks are published after the deadline"}
    assert r["best_xi"] == {"available": False, "reason": "gameweek not finished"}
    assert r["headline"] == {"basis": "with_captain", "app": None, "scout": None, "you": None, "best": None}
    assert all(p["points"] is None for p in r["players"].values())


def test_free_hit_week_has_no_transfer_line_and_keeps_the_permanent_squad():
    r = build(7)
    assert r["transfers"]["chip_week"] is True and r["transfers"]["verdict"] is None
    assert r["transfers"]["you"] == {"available": False, "reason": "chip week"}
    assert r["transfers"]["app"] == {"available": False, "reason": "chip week"}
    assert sorted(r["wildcard"]["kept"]["ids"]) == sorted(GW6_PICKS)
    assert r["you"]["chip"] == "freehit" and r["you"]["ids"] == FREE_HIT_PICKS


def test_an_unmatched_scout_name_is_listed_and_flagged():
    stranger = [{"name_raw": "New Signing", "club_raw": "Chelsea"}]
    r = build(9, expert={(9, "selection"): _scout_row(unmatched=stranger, ids=E["scout_ids"][:10])})
    assert r["scout_xi"]["needs_review"] is True and r["scout_xi"]["unmatched"] == stranger
    assert len(r["scout_xi"]["ids"]) == 10 and r["scout_xi"]["available"] is True


def test_unavailable_replay_does_not_break_the_report():
    r = build(9, advice={(9, "transfer_plan"): {"origin": "replay", "model_version": "v", "payload": {
        "available": False, "reason": "ValueError: boom"}}})
    assert r["transfers"]["app"] == {"available": False, "reason": "ValueError: boom"}
    assert r["buy_lists"]["app"]["available"] is False and r["wildcard"]["app"]["available"] is False
    assert r["headline"]["scout"] == 69 and r["transfers"]["you"]["windows"]["1"]["gain"] == 15


def test_no_scout_article_means_a_missing_column_not_a_crash():
    r = build(9, expert={})
    assert r["scout_xi"] == {"available": False, "reason": "no Scout Selection found for this gameweek"}
    assert r["buy_lists"]["scout"]["available"] is False
    assert r["headline"] == {"basis": "no_captain", "app": 70, "scout": None, "you": 64, "best": 115}
    assert r["captain"]["scout"] is None


def test_dropped_squad_players_and_parity_are_reported():
    r = build(9)
    assert r["replay"]["dropped_squad_ids"] == [423]
    assert r["replay"]["parity"]["status"] == "no_same_version_baseline"
    assert any("today's engine" in n for n in r["replay"]["notes"])


def test_every_player_referenced_is_in_players():
    r = build(9)
    assert collect_ids(r) <= {int(k) for k in r["players"]}
    assert r["players"]["418"] == {"name": "Maguire", "club": "MUN", "pos": "DEF", "price_m": None,
                                   "xpts": None, "points": None, "minutes": None}
    assert r["players"]["411"]["points"] == 2 and r["players"]["411"]["xpts"] == 7.07


def test_report_is_json_serialisable_and_has_every_top_level_key():
    r = build(9)
    json.dumps(r)
    assert set(r) == {"season", "gw", "entry_id", "state", "players", "app_xi", "scout_xi", "you", "best_xi",
                      "headline", "captain", "transfers", "buy_lists", "wildcard", "replay"}
