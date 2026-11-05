"""Scout articles from the Premier League content feed. The fixtures are real
article bodies (2026-27), so these tests pin the formats the Scout really uses."""
import json
import pathlib

from src import scout_feed

FIX = pathlib.Path("tests/fixtures/monitor")


def load(name):
    return json.loads((FIX / name).read_text())


def test_classify_real_titles():
    c = scout_feed.classify_article
    assert c("Scout Selection: Best Fantasy team for Gameweek 10") == ("selection", 10)
    assert c("The Scout’s FPL Gameweek 10 transfer radar") == ("transfer_radar", 10)
    assert c("The Scout's GW6 squad for Wildcarders and new starters") == ("wildcard", 6)
    assert c("The Scout's FPL Gameweek 4 Wildcard squad") == ("wildcard", 4)
    assert c("FPL GW3 Wildcard squad: How to own Haaland, Fernandes, Joao Pedro AND Palmer") == ("wildcard", 3)
    assert c("The Scout’s FPL GW2 squad for Wildcarders and new starters") == ("wildcard", 2)
    assert c("Scout Selection: The best Fantasy squad for 2026/27") == ("season_squad", 1)
    assert c("The Scout's FPL Gameweek 9 Differentials") is None
    assert c("Sage on Palace claiming a late point") is None
    assert c("It’s time to go BIG in defence in FPL") is None


def test_gw10_selection_parses_eleven_with_stated_captain():
    a = scout_feed.parse_article(load("article_4756626.json"), {})
    assert (a["series"], a["gw"], a["article_id"]) == ("selection", 10, 4756626)
    assert a["url"] == "https://www.premierleague.com/en/news/4756626"
    assert a["published_at"] == "2026-11-05T10:00:00Z"
    assert [p["name_raw"] for p in a["players"]] == [
        "Djordje Petrovic", "Gabriel", "James Tarkowski", "Maxim De Cuyper", "Morgan Rogers",
        "Martin Odegaard", "Marcus Tavernier", "Pascal Gross", "Erling Haaland", "Alexander Isak",
        "Thierno Barry"]
    first = a["players"][0]
    assert (first["club_raw"], first["price_m"]) == ("AFC Bournemouth", 4.5)
    assert first["reason"].startswith("The Bournemouth goalkeeper has stepped up")
    assert "<" not in first["reason"] and len(first["reason"]) <= 300
    assert (a["captain"], a["vice"], a["captain_stated"]) == ("Erling Haaland", "Alexander Isak", True)
    assert a["captain_inferred"] is None
    assert a["needs_review"] is False


def test_gw9_selection_has_no_stated_captain_but_one_inferred():
    a = scout_feed.parse_article(load("article_4750445.json"), {})
    assert len(a["players"]) == 11
    assert (a["captain"], a["vice"], a["captain_stated"]) == (None, None, False)
    assert a["captain_inferred"] == "Erling Haaland"
    assert a["needs_review"] is False


def test_a_club_captain_mention_is_not_a_captaincy_pick():
    # GW10: Odegaard's section calls him "the Arsenal captain"; Haaland's and Isak's
    # sections both talk about the armband / captaincy. Without the stated sentence
    # nothing may be inferred from three candidate sections.
    art = load("article_4756626.json")
    art["body"] = art["body"].replace("are named captain and vice-captain respectively", "both start")
    a = scout_feed.parse_article(art, {})
    assert (a["captain"], a["captain_stated"], a["captain_inferred"]) == (None, False, None)


def test_gw10_radar_parses_four_tips_with_entity_decoded_club():
    a = scout_feed.parse_article(load("article_4756485.json"), {})
    assert (a["series"], a["gw"]) == ("transfer_radar", 10)
    assert [(p["name_raw"], p["club_raw"], p["price_m"]) for p in a["players"]] == [
        ("Rayan", "AFC Bournemouth", 6.3), ("Cody Gakpo", "Liverpool", 7.1),
        ("Iliman Ndiaye", "Manchester City", 5.8), ("Luka Vuskovic", "Brighton & Hove Albion", 5.2)]
    assert a["needs_review"] is False and a["captain"] is None


def test_prose_squads_are_flagged_not_guessed():
    for f, series, gw in (("article_4726681.json", "wildcard", 6), ("article_4681112.json", "season_squad", 1)):
        a = scout_feed.parse_article(load(f), {})
        assert (a["series"], a["gw"]) == (series, gw)
        assert a["players"] == [] and a["needs_review"] is True and a["review_reason"]


def test_override_supplies_the_picks_for_a_prose_squad_only_once_confirmed():
    squad = [{"name": f"Player {i}", "club": "Arsenal"} for i in range(15)]
    ov = {"articles": {"4726681": {"players": squad, "confirmed_by_owner": True}}}
    a = scout_feed.parse_article(load("article_4726681.json"), ov)
    assert len(a["players"]) == 15 and a["needs_review"] is False
    assert a["players"][0] == {"name_raw": "Player 0", "club_raw": "Arsenal", "price_m": None, "reason": ""}
    ov["articles"]["4726681"]["confirmed_by_owner"] = False
    b = scout_feed.parse_article(load("article_4726681.json"), ov)
    assert len(b["players"]) == 15 and b["needs_review"] is True


def test_a_selection_without_eleven_players_needs_review():
    art = load("article_4750445.json")
    art["body"] = art["body"].replace("<h5>Zion Suzuki (Aston Villa) £5.0m</h5>", "<p>Zion Suzuki</p>")
    a = scout_feed.parse_article(art, {})
    assert len(a["players"]) == 10 and a["needs_review"] is True
    assert "10" in a["review_reason"]


def test_pick_articles_takes_latest_duplicate_and_skips_old_seasons():
    listing = [
        {"id": 1, "title": "Scout Selection: Best Fantasy team for Gameweek 5", "date": "2026-09-17T10:00:00Z"},
        {"id": 2, "title": "Scout Selection: Best Fantasy team for Gameweek 5", "date": "2026-09-18T09:00:00Z"},
        {"id": 3, "title": "Scout Selection: Best Fantasy team for Gameweek 27", "date": "2026-02-20T10:00:00Z"},
        {"id": 4, "title": "Sage on Palace claiming a late point", "date": "2026-11-05T22:00:00Z"},
    ]
    out = scout_feed.pick_articles(listing, season_start="2026-08-01")
    assert out == {(5, "selection"): listing[1]}


def test_pick_articles_returns_nothing_for_an_empty_listing():
    assert scout_feed.pick_articles([], season_start="2026-08-01") == {}


def test_an_override_can_pin_the_article_for_a_gameweek():
    listing = [
        {"id": 1, "title": "Scout Selection: Best Fantasy team for Gameweek 5", "date": "2026-09-17T10:00:00Z"},
        {"id": 2, "title": "Scout Selection: Best Fantasy team for Gameweek 5", "date": "2026-09-18T09:00:00Z"},
    ]
    out = scout_feed.pick_articles(listing, season_start="2026-08-01", overrides={"pins": {"5|selection": 1}})
    assert out[(5, "selection")]["id"] == 1


# --- captain wording varies week to week (found by the GW1-GW10 dry run) -------------------

def test_gw2_captain_is_stated_with_surnames_and_armband_wording():
    # "Fernandes earns the captain's armband, with Erling Haaland (£15.5m) named as vice-captain."
    a = scout_feed.parse_article(load("article_4698605.json"), {})
    assert len(a["players"]) == 11
    assert (a["captain"], a["vice"], a["captain_stated"]) == ("Bruno Fernandes", "Erling Haaland", True)
    assert a["captain_inferred"] is None


def test_gw4_captain_is_stated_as_handed_the_armband():
    # "Palmer is handed the armband, with Joao Pedro named as vice-captain."
    a = scout_feed.parse_article(load("article_4713402.json"), {})
    assert (a["captain"], a["vice"], a["captain_stated"]) == ("Cole Palmer", "Joao Pedro", True)


def test_gw7_stated_captain_wins_over_a_team_mate_called_a_captaincy_alternative():
    # "Haaland is named as the captain, with Saka the vice-captain." De Cuyper's own
    # section calls him "a great alternative for the captaincy": not the pick.
    a = scout_feed.parse_article(load("article_4737338.json"), {})
    assert (a["captain"], a["vice"], a["captain_stated"]) == ("Erling Haaland", "Bukayo Saka", True)


def test_other_real_captain_sentences():
    players = [{"name_raw": n} for n in ("Erling Haaland", "Morgan Gibbs-White", "Bukayo Saka", "Cole Palmer",
                                         "Rayan Cherki")]

    def cap(sentence):
        out = scout_feed.parse_captain(f"<p>{sentence}</p>", players)
        return out["captain"], out["vice"], out["stated"]

    assert cap("The side lines up in a 3-5-2 formation, with Haaland getting the armband and Gibbs-White "
               "named as vice-captain.") == ("Erling Haaland", "Morgan Gibbs-White", True)
    assert cap("Saka is selected as captain, with Erling Haaland (£15.6m) named vice-captain.") == (
        "Bukayo Saka", "Erling Haaland", True)
    assert cap("Erling Haaland (£15.7m) is named as captain for Manchester City's visit to Aston Villa, "
               "with Palmer given the vice-captaincy.") == ("Erling Haaland", "Cole Palmer", True)
    assert cap("Haaland gets the captain's armband, with team-mate Cherki named as vice-captain.") == (
        "Erling Haaland", "Rayan Cherki", True)


def test_a_vice_captain_sentence_naming_an_unlisted_player_is_not_a_statement():
    players = [{"name_raw": "Erling Haaland"}]
    out = scout_feed.parse_captain("<p>Salah takes the armband, with Isak named as vice-captain.</p>", players)
    assert (out["captain"], out["stated"]) == (None, False)


def test_two_listed_players_with_one_surname_are_not_guessed_between():
    players = [{"name_raw": "Antonio Silva"}, {"name_raw": "Bernardo Silva"}, {"name_raw": "Erling Haaland"}]
    out = scout_feed.parse_captain("<p>Silva is handed the armband, with Haaland named as vice-captain.</p>",
                                   players)
    assert (out["captain"], out["stated"]) == (None, False)
