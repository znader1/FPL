# config.py
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# If set, requests will use it. Else, system trust store.
REQUESTS_CA_BUNDLE_ENV = "REQUESTS_CA_BUNDLE"

# Caching / API
BOOTSTRAP_TTL = 300  # seconds
FIXTURES_TTL  = 300

# Elements features you care about
ELEMENTS_KEEP = [
    "id","web_name","team","element_type","total_points","form",
    "points_per_game","now_cost","selected_by_percent",
    # Useful for projections / risk
    "ep_next","ep_this","minutes",
    "status","news",
    "chance_of_playing_this_round","chance_of_playing_next_round",
    # UI icons
    "photo","code",
]

# Position labels to show
POS_CHOICES = ["GKP","DEF","MID","FWD"]

# Metrics exposed in UI → underlying column
METRIC_MAP = {
    "Total points": "total_points",
    "Form": "form",
    "Pts per game": "points_per_game",
}

# Output columns for the squad table
SQUAD_COLUMNS = [
    "player_id","web_name","pos","team_short","team_name",
    "is_captain","is_vice_captain","multiplier"
]

UI_TOPN_DEFAULT = 15
UI_FIXTURES_TO_SHOW = 3
