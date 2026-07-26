import pandas as pd

from src import news_digest as nd

ARTICLE = """# Saka injury update

- Source: example.com
- URL: http://x
- Published: Tue, 17 Feb 2026
- Fetched: 2026-02-18T15:06:14Z

## Summary
- Bukayo Saka picked up a hamstring injury.
- Expected back in three weeks.

## Entities
- Players: Bukayo Saka
- Teams: Arsenal

## Tags
- injury
- return
"""


def _els():
    return pd.DataFrame({"id": [1, 2], "web_name": ["Saka", "Rice"]})


def test_parse_article():
    a = nd._parse_article(ARTICLE, "p.md")
    assert a["title"].startswith("Saka")
    assert a["players"] == ["Bukayo Saka"]
    assert "injury" in a["tags"]
    assert "hamstring" in a["summary"]


def test_load_articles(tmp_path):
    d = tmp_path / "news" / "src"
    d.mkdir(parents=True)
    (d / "a.md").write_text(ARTICLE)
    arts = nd.load_news_articles(str(tmp_path / "news"))
    assert len(arts) == 1 and arts[0]["players"] == ["Bukayo Saka"]


def test_index_by_player_matches_surname():
    idx = nd.index_by_player([nd._parse_article(ARTICLE, "p.md")], _els())
    assert 1 in idx and len(idx[1]) == 1  # "Bukayo Saka" -> web_name "Saka"


def test_propose_uses_injected_generate():
    idx = nd.index_by_player([nd._parse_article(ARTICLE, "p.md")], _els())
    fake = lambda prompt: '{"change": true, "availability": 0, "available_from_gw": 4, "minutes_mult": 1, "note": "hamstring"}'
    out = nd.propose_player_knowledge(idx, _els(), generate=fake, current_gw=1)
    assert out["players"]["1"]["availability"] == 0
    assert out["players"]["1"]["available_from_gw"] == 4
    assert out["players"]["1"]["source"] == "p.md"


EVENTS = [
    {"id": 1, "deadline_time": "2026-08-15T17:30:00Z"},
    {"id": 2, "deadline_time": "2026-08-22T17:30:00Z"},
    {"id": 3, "deadline_time": "2026-08-29T17:30:00Z"},
    {"id": 4, "deadline_time": "2026-09-12T17:30:00Z"},
]


def test_parse_return_gw_expected_back():
    # 21 Aug -> first deadline on/after = GW2 (2026-08-22)
    assert nd._parse_return_gw("Groin injury - Expected back 21 Aug", EVENTS) == 2


def test_parse_return_gw_suspended_until():
    # 29 Aug -> GW3 deadline is exactly 2026-08-29 (>=)
    assert nd._parse_return_gw("Suspended until 29 Aug", EVENTS) == 3


def test_parse_return_gw_unknown_returns_none():
    assert nd._parse_return_gw("Back injury - Unknown return date", EVENTS) is None
    assert nd._parse_return_gw("Knee injury - 75% chance of playing", EVENTS) is None


def test_parse_return_gw_after_last_event_is_beyond_horizon():
    gw = nd._parse_return_gw("Expected back 20 Oct", EVENTS)
    assert gw == 5  # past last event (GW4) -> GW beyond the fixtures we have


def _bootstrap_elements():
    return pd.DataFrame({
        "id": [1, 2, 3, 4, 5],
        "web_name": ["Timber", "Saliba", "Kamara", "Salah", "Christie"],
        "status": ["i", "i", "d", "a", "s"],
        "news": [
            "Groin injury - Expected back 21 Aug",
            "Back injury - Unknown return date",
            "Knee injury - 75% chance of playing",
            "",
            "Suspended until 29 Aug",
        ],
        "chance_of_playing_next_round": [0, 0, 75, 100, 0],
    })


def test_digest_bootstrap_news_maps_states():
    out = nd.digest_bootstrap_news(_bootstrap_elements(), EVENTS, current_gw=1)
    p = out["players"]
    # available player 'a' with no news is skipped
    assert "4" not in p
    # injured with a return date -> fit once back, out until the return GW
    assert p["1"]["availability"] == 1.0 and p["1"]["available_from_gw"] == 2
    assert p["1"]["source"] == "fpl_bootstrap"
    assert "Groin" in p["1"]["note"]
    # injured, unknown return -> zeroed whole horizon
    assert p["2"]["availability"] == 0.0 and p["2"]["available_from_gw"] is None
    # doubtful -> availability from chance
    assert p["3"]["availability"] == 0.75 and p["3"]["available_from_gw"] is None
    # suspended with a return date
    assert p["5"]["availability"] == 1.0 and p["5"]["available_from_gw"] == 3


def test_digest_bootstrap_skips_already_returned():
    # return date on/before current GW == available now -> no entry
    els = pd.DataFrame({
        "id": [1], "web_name": ["X"], "status": ["i"],
        "news": ["Expected back 15 Aug"], "chance_of_playing_next_round": [0],
    })
    out = nd.digest_bootstrap_news(els, EVENTS, current_gw=2)  # GW1 return, already back
    assert out["players"] == {}


def test_team_news_rollup_groups_by_team():
    els = pd.DataFrame({
        "id": [1, 2, 3, 4],
        "web_name": ["Saliba", "Timber", "Salah", "Gomez"],
        "team_short": ["ARS", "ARS", "LIV", "LIV"],
        "status": ["i", "i", "a", "i"],
        "news": ["Back injury - Unknown return date",
                 "Groin injury - Expected back 21 Aug", "", "Muscular injury - Unknown return date"],
        "chance_of_playing_next_round": [0, 0, 100, 0],
    })
    out = nd.team_news_rollup(els, EVENTS, current_gw=1)
    assert out["total"] == 3          # Salah (available) not counted
    assert set(out["teams"]) == {"ARS", "LIV"}
    assert len(out["teams"]["ARS"]) == 2
    ars = {p["web_name"]: p for p in out["teams"]["ARS"]}
    assert ars["Saliba"]["availability"] == 0.0
    assert ars["Timber"]["available_from_gw"] == 2
    # out (avail 0) sorts before the one with a return date
    assert out["teams"]["ARS"][0]["web_name"] == "Saliba"


def test_merge_bootstrap_wins_on_conflict():
    article = {"players": {"1": {"availability": 0.5, "note": "rumour", "source": "a.md"}}}
    boot = {"players": {"1": {"availability": 0.0, "note": "injury", "source": "fpl_bootstrap"}}}
    merged = nd.merge_proposals(article, boot)
    assert merged["players"]["1"]["source"] == "fpl_bootstrap"
    assert merged["players"]["1"]["availability"] == 0.0


def test_merge_keeps_article_only_entries():
    article = {"players": {"2": {"availability": 0.7, "source": "a.md"}}}
    boot = {"players": {"1": {"availability": 0.0, "source": "fpl_bootstrap"}}}
    merged = nd.merge_proposals(article, boot)
    assert set(merged["players"]) == {"1", "2"}


def test_propose_no_change_skips():
    idx = nd.index_by_player([nd._parse_article(ARTICLE, "p.md")], _els())
    out = nd.propose_player_knowledge(idx, _els(), generate=lambda p: '{"change": false}', current_gw=1)
    assert out["players"] == {}
