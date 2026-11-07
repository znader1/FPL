"""Scout articles name players as "Full Name (Club)"; FPL uses short names with
diacritics. A wrong match scores the wrong player, so anything unclear must come
back unmatched rather than guessed."""
from src import scout_names

TEAMS = [
    {"name": "Arsenal", "short_name": "ARS"}, {"name": "Aston Villa", "short_name": "AVL"},
    {"name": "Bournemouth", "short_name": "BOU"}, {"name": "Brighton", "short_name": "BHA"},
    {"name": "Chelsea", "short_name": "CHE"}, {"name": "Ipswich", "short_name": "IPS"},
    {"name": "Man City", "short_name": "MCI"}, {"name": "Spurs", "short_name": "TOT"},
]

PLAYERS = [
    {"id": 1, "first_name": "Đorđe", "second_name": "Petrović", "web_name": "Petrović", "team_short": "BOU"},
    {"id": 154, "first_name": "Cole", "second_name": "Palmer", "web_name": "Palmer", "team_short": "CHE"},
    {"id": 700, "first_name": "Alex", "second_name": "Palmer", "web_name": "Palmer", "team_short": "IPS"},
    {"id": 112, "first_name": "Jan Paul", "second_name": "van Hecke", "web_name": "Van Hecke", "team_short": "TOT"},
    {"id": 300, "first_name": "Nicolas", "second_name": "Jackson", "web_name": "N.Jackson", "team_short": "AVL"},
    {"id": 5, "first_name": "Gabriel", "second_name": "dos Santos Magalhães", "web_name": "Gabriel", "team_short": "ARS"},
    {"id": 6, "first_name": "Gabriel", "second_name": "Martinelli Silva", "web_name": "Martinelli", "team_short": "ARS"},
    {"id": 7, "first_name": "Gabriel", "second_name": "Fernando de Jesus", "web_name": "G.Jesus", "team_short": "ARS"},
    {"id": 8, "first_name": "Rayan", "second_name": "Vitor Simplício Rocha", "web_name": "Rayan", "team_short": "BOU"},
    {"id": 9, "first_name": "Luka", "second_name": "Vušković", "web_name": "Vušković", "team_short": "BHA"},
    {"id": 20, "first_name": "Adam", "second_name": "Smith", "web_name": "Smith", "team_short": "BOU"},
    {"id": 21, "first_name": "Marcos", "second_name": "Smith", "web_name": "M.Smith", "team_short": "BOU"},
]


def _match(name, club, overrides=None):
    return scout_names.match_player(name, club, PLAYERS, TEAMS, overrides)


def test_normalise_transliterates_letters_that_do_not_decompose():
    assert scout_names.normalise("Đorđe Petrović") == "djordje petrovic"
    assert scout_names.normalise("Pascal Groß") == "pascal gross"
    assert scout_names.normalise("  Martin  Ødegaard ") == "martin odegaard"
    assert scout_names.normalise("Brighton &amp; Hove Albion") == "brighton hove albion"
    assert scout_names.normalise("N.Jackson") == "n jackson"


def test_club_variants_resolve_to_the_fpl_short_name():
    for raw, short in [("AFC Bournemouth", "BOU"), ("Bournemouth", "BOU"), ("Spurs", "TOT"),
                       ("Tottenham Hotspur", "TOT"), ("Man City", "MCI"), ("Manchester City", "MCI"),
                       ("Brighton &amp; Hove Albion", "BHA"), ("Brighton", "BHA"), ("Arsenal", "ARS")]:
        assert scout_names.club_short(raw, TEAMS) == short, raw
    assert scout_names.club_short("Atlantis FC", TEAMS) is None


def test_a_full_name_matches_the_fpl_short_name_at_that_club():
    assert _match("Djordje Petrovic", "AFC Bournemouth") == {"player_id": 1, "status": "matched"}
    assert _match("Cole Palmer", "Chelsea") == {"player_id": 154, "status": "matched"}
    assert _match("Jan Paul van Hecke", "Spurs") == {"player_id": 112, "status": "matched"}
    assert _match("Nicolas Jackson", "Aston Villa") == {"player_id": 300, "status": "matched"}
    assert _match("Luka Vuskovic", "Brighton &amp; Hove Albion") == {"player_id": 9, "status": "matched"}


def test_a_single_name_matches_the_exact_short_name_over_first_names():
    assert _match("Gabriel", "Arsenal") == {"player_id": 5, "status": "matched"}
    assert _match("Rayan", "AFC Bournemouth") == {"player_id": 8, "status": "matched"}


def test_the_club_separates_two_players_with_one_surname():
    assert _match("Palmer", "Chelsea")["player_id"] == 154
    assert _match("Palmer", "Arsenal") == {"player_id": None, "status": "not_found"}


def test_an_unknown_club_is_not_searched_league_wide():
    assert _match("Cole Palmer", "Atlantis FC") == {"player_id": None, "status": "unknown_club"}


def test_two_candidates_at_one_club_are_ambiguous_not_guessed():
    players = PLAYERS + [{"id": 22, "first_name": "Bob", "second_name": "Smith",
                          "web_name": "Smith", "team_short": "BOU"}]
    out = scout_names.match_player("Smith", "Bournemouth", players, TEAMS)
    assert out == {"player_id": None, "status": "ambiguous"}


def test_a_full_name_picks_one_of_two_same_surname_team_mates():
    assert _match("Marcos Smith", "Bournemouth") == {"player_id": 21, "status": "matched"}


def test_an_override_wins_and_says_so():
    ov = {"smith|BOU": 21}
    assert _match("Smith", "Bournemouth", ov) == {"player_id": 21, "status": "override"}


# --- found by the GW1-GW10 dry run -------------------------------------------------------------

TEAMS_2026 = TEAMS + [{"name": "Coventry City", "short_name": "COV"}, {"name": "Hull City", "short_name": "HUL"},
                      {"name": "Leeds", "short_name": "LEE"}, {"name": "Sunderland", "short_name": "SUN"},
                      {"name": "Man Utd", "short_name": "MUN"}]


def test_a_shortened_or_lengthened_club_name_resolves_when_only_one_club_fits():
    assert scout_names.club_short("Coventry", TEAMS_2026) == "COV"
    assert scout_names.club_short("Hull", TEAMS_2026) == "HUL"
    assert scout_names.club_short("Leeds United", TEAMS_2026) == "LEE"
    assert scout_names.club_short("Man", TEAMS_2026) is None          # Man City and Man Utd both fit


def test_a_shortened_first_name_matches_the_full_one():
    players = [{"id": 532, "first_name": "Daniel", "second_name": "Ballard", "web_name": "Ballard", "team_short": "SUN"},
               {"id": 533, "first_name": "Nordi", "second_name": "Mukiele", "web_name": "Mukiele", "team_short": "SUN"}]
    assert scout_names.match_player("Dan Ballard", "Sunderland", players, TEAMS_2026) == {
        "player_id": 532, "status": "matched"}
    assert scout_names.match_player("Dan Mukiele", "Sunderland", players, TEAMS_2026)["player_id"] is None


def test_a_misspelt_surname_is_not_matched_by_guesswork():
    players = [{"id": 427, "first_name": "Bryan", "second_name": "Mbeumo", "web_name": "Mbeumo", "team_short": "MUN"}]
    assert scout_names.match_player("Bryan Mbuemo", "Man Utd", players, TEAMS_2026) == {
        "player_id": None, "status": "not_found"}
    assert scout_names.match_player("Bryan Mbuemo", "Man Utd", players, TEAMS_2026,
                                    {"bryan mbuemo|MUN": 427}) == {"player_id": 427, "status": "override"}
