import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from src import news_auto as na


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def test_latest_past_deadline():
    ev = [{"id": 11, "deadline_time": "2026-11-14T10:00:00Z"},
          {"id": 12, "deadline_time": "2026-11-28T10:00:00Z"}]
    assert na.latest_past_deadline(ev, _dt(2026, 11, 21)) == datetime(2026, 11, 14, 10, tzinfo=timezone.utc)
    assert na.latest_past_deadline(ev, _dt(2026, 1, 1)) is None


def test_is_fresh_uses_published_then_fetched():
    since = _dt(2026, 2, 19)
    assert na.is_fresh({"published": "Thu, 19 Feb 2026 23:25:00 +0000"}, since)
    assert not na.is_fresh({"published": "Thu, 19 Feb 2026 23:25:00 +0000"}, _dt(2026, 2, 20))
    assert na.is_fresh({"published": None, "fetched": "2026-02-20T01:00:00Z"}, since)
    assert na.is_fresh({"published": None, "fetched": None}, None)
    assert not na.is_fresh({"published": None, "fetched": None}, since)


def test_unprocessed_filters_seen_urls():
    arts = [{"url": "a"}, {"url": "b"}]
    assert na.unprocessed(arts, {"a"}) == [{"url": "b"}]


def test_group_by_team_aliases_and_unknown():
    teams = [{"id": 1, "name": "Arsenal", "short_name": "ARS"},
             {"id": 2, "name": "Tottenham Hotspur", "short_name": "TOT"}]
    a = {"url": "x", "teams": ["Spurs", "Arsenal"]}
    out = na.group_by_team([a, {"url": "y", "teams": ["Barcelona"]}, {"url": "z"}], teams)
    assert out == {1: [a], 2: [a]}


SQUAD = [
    {"id": 10, "web_name": "A", "position": "MID", "status": "a", "chance_of_playing_next_round": 100},
    {"id": 11, "web_name": "B", "position": "DEF", "status": "a", "chance_of_playing_next_round": 100},
]


def test_guard_clamps_and_whitelists():
    raw = json.dumps({"cuts": [{"player_id": 10, "minutes_mult": 0.0, "reason": "r"},
                               {"player_id": 99, "minutes_mult": 0.8},
                               {"player_id": 11, "minutes_mult": 1.1}]})
    out = na.guard_cuts(raw, SQUAD, 0.7)
    assert len(out) == 1 and out[0]["player_id"] == 10 and out[0]["minutes_mult"] == 0.7


def test_guard_excludes_flagged_players():
    squad = [dict(SQUAD[0], status="d", chance_of_playing_next_round=75),
             dict(SQUAD[1], chance_of_playing_next_round=float("nan"))]
    raw = json.dumps({"cuts": [{"player_id": 10, "minutes_mult": 0.8}, {"player_id": 11, "minutes_mult": 0.8}]})
    assert [c["player_id"] for c in na.guard_cuts(raw, squad, 0.7)] == [11]
    squad[1]["chance_of_playing_next_round"] = None
    assert [c["player_id"] for c in na.guard_cuts(raw, squad, 0.7)] == [11]


def test_guard_rejects_malformed_output():
    for raw in ["no news", "{bad", '{"cuts":"x"}', "[]", None]:
        assert na.guard_cuts(raw, SQUAD, 0.7) == []
    out = na.guard_cuts('{"cuts":[{"player_id":"10","minutes_mult":"0.8"},'
                        '{"player_id":"abc","minutes_mult":"0.8"},{"player_id":11,"minutes_mult":"x"},'
                        '{"player_id":true,"minutes_mult":0.8},{"player_id":11,"minutes_mult":NaN}]}', SQUAD, 0.7)
    assert [(c["player_id"], c["minutes_mult"]) for c in out] == [(10, 0.8)]


def test_guard_dedupes_and_truncates_reason():
    raw = json.dumps({"cuts": [{"player_id": 10, "minutes_mult": 0.8, "reason": "x" * 500},
                               {"player_id": 10, "minutes_mult": 0.75}]})
    out = na.guard_cuts(raw, SQUAD, 0.7)
    assert len(out) == 1 and len(out[0]["reason"]) <= 200


def test_build_entries_shape():
    e = na.build_entries({1: [{"player_id": 10, "minutes_mult": 0.8, "reason": "rotated"}]},
                         {1: ["u1"]}, {1: "ARS"}, 12, "run1")
    assert e["10"] == {"availability": 1.0, "available_from_gw": None, "minutes_mult": 0.8,
                       "note": "auto (news): rotated", "source": "news_auto", "sources": ["u1"],
                       "team": "ARS", "created_gw": 12, "expires_after_gw": 12, "run_id": "run1"}


def _e(gw, **kw):
    return dict({"minutes_mult": 0.8, "created_gw": gw, "expires_after_gw": gw, "run_id": "r"}, **kw)


def test_merge_auto_add_refresh_expire_tombstone():
    prev = {"players": {"1": _e(11), "2": _e(12), "3": _e(12)},
            "tombstones": {"5": {"until_gw": 12}, "6": {"until_gw": 11}}}
    new = {"2": _e(12, minutes_mult=0.7), "4": _e(12), "5": _e(12)}
    auto, log = na.merge_auto(prev, new, 12, "2026-11-21T00:00:00Z")
    assert set(auto["players"]) == {"2", "3", "4"}
    assert auto["players"]["2"]["minutes_mult"] == 0.7
    assert set(auto["tombstones"]) == {"5"}
    assert auto["as_of"] == "2026-11-21T00:00:00Z"
    kinds = {(l["kind"], l["player_id"]) for l in log}
    assert kinds == {("expire", "1"), ("refresh", "2"), ("add", "4"), ("skip_tombstone", "5")}


def test_revert_by_player_and_by_run():
    auto = {"players": {"1": _e(12, run_id="a"), "2": _e(12, run_id="b"), "3": _e(12, run_id="b")},
            "tombstones": {}}
    out, log = na.revert(auto, ["1"], None, 12)
    assert set(out["players"]) == {"2", "3"} and out["tombstones"]["1"] == {"until_gw": 12}
    assert [l["kind"] for l in log] == ["revert"]
    out, log = na.revert(auto, None, "b", 12)
    assert set(out["players"]) == {"1"} and set(out["tombstones"]) == {"2", "3"}
    assert na.revert(auto, None, None, 12)[0]["players"] == auto["players"]


def test_squad_list_and_prompt():
    df = pd.DataFrame([{"id": 1, "web_name": "X", "team": 3, "pos": "MID", "status": "a",
                        "chance_of_playing_next_round": None},
                       {"id": 2, "web_name": "Y", "team": 4, "pos": "DEF", "status": "a",
                        "chance_of_playing_next_round": 100}])
    sq = na.squad_list(df, 3)
    assert [s["id"] for s in sq] == [1]
    p = na.build_team_prompt("Arsenal", [{"title": "T", "summary": "S", "url": "u"}], sq, 12)
    assert sq[0]["position"] == "MID" and "(MID)" in p
    assert "Arsenal" in p and "X" in p and "T" in p
    assert "data" in na.SYSTEM_TEAM and "injur" in na.SYSTEM_TEAM


FPL_TEAMS = [
    {"id": 1, "name": "Man Utd", "short_name": "MUN"},
    {"id": 2, "name": "Spurs", "short_name": "TOT"},
    {"id": 3, "name": "Man City", "short_name": "MCI"},
    {"id": 4, "name": "Nott'm Forest", "short_name": "NFO"},
    {"id": 5, "name": "Newcastle", "short_name": "NEW"},
    {"id": 6, "name": "Leeds", "short_name": "LEE"},
    {"id": 7, "name": "Brighton", "short_name": "BHA"},
    {"id": 8, "name": "Bournemouth", "short_name": "BOU"},
]


@pytest.mark.parametrize("name,tid", [
    ("Manchester United", 1), ("Tottenham Hotspur", 2), ("Tottenham", 2),
    ("Manchester City", 3), ("Nottingham Forest", 4), ("Newcastle United", 5),
    ("Leeds United", 6), ("Brighton & Hove Albion", 7), ("AFC Bournemouth", 8),
    ("Man Utd", 1), ("SPURS", 2), ("NFO", 4),
])
def test_group_by_team_resolves_corpus_long_names(name, tid):
    a = {"url": "u", "teams": [name]}
    assert na.group_by_team([a], FPL_TEAMS) == {tid: [a]}


def test_aliases_resolve_through_bootstrap_not_fixed_ids():
    # same clubs, different ids: aliases must follow short_name, never an id
    teams = [dict(t, id=t["id"] + 100) for t in FPL_TEAMS]
    a = {"url": "u", "teams": ["Manchester United"]}
    assert na.group_by_team([a], teams) == {101: [a]}
    # a club not in the bootstrap (relegated) resolves to nothing
    assert na.group_by_team([{"url": "v", "teams": ["Aston Villa", "Villa"]}], FPL_TEAMS) == {}


def test_alias_table_is_shared_with_relevance_terms():
    from src import config, news_fetch
    assert not hasattr(news_fetch, "_PL_EXTRA")
    terms = news_fetch.pl_terms_from_teams(FPL_TEAMS)
    for t in ("manchester united", "tottenham hotspur", "afc bournemouth", "leeds united"):
        assert t in terms
    assert all(isinstance(v, list) for v in config.NEWS_TEAM_ALIASES.values())


def test_guard_accepts_fenced_json():
    raw = '```json\n' + json.dumps({"cuts": [{"player_id": 11, "minutes_mult": 0.8}]}) + '\n```'
    assert [c["player_id"] for c in na.guard_cuts(raw, SQUAD, 0.7)] == [11]
