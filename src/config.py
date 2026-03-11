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
    # Transfer momentum
    "transfers_in_event","transfers_out_event",
    # Set-piece signals
    "penalties_order","penalties_text",
    "direct_freekicks_order","direct_freekicks_text",
    "corners_and_indirect_freekicks_order","corners_and_indirect_freekicks_text",
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

# -----------------------------
# Projection tuning
# -----------------------------
PROJ_DEFAULT_LATEST_N_MATCHES = 3
PROJ_DEFAULT_PPG_WEIGHT = 0.55
PROJ_DEFAULT_FORM_WEIGHT = 0.45
PROJ_FORM_SCALE_PER_MATCH = 0.04
PROJ_FORM_SCALE_BASE_MATCHES = 3
PROJ_LATEST_N_MIN = 1
PROJ_LATEST_N_MAX = 8

PROJ_NEUTRAL_TEAM_PPG = 1.5
PROJ_HOME_MULT_HOME = 1.06
PROJ_HOME_MULT_AWAY = 0.94
PROJ_OPP_FORM_FACTOR = 0.12
PROJ_OPP_FORM_MIN = 0.86
PROJ_OPP_FORM_MAX = 1.14
PROJ_TEAM_FORM_FACTOR = 0.08
PROJ_TEAM_FORM_MIN = 0.90
PROJ_TEAM_FORM_MAX = 1.12

# -----------------------------
# Captain tuning
# -----------------------------
CAPTAIN_POSITION_MULTIPLIER = {
    "FWD": 1.16,
    "MID": 1.12,
    "DEF": 0.92,
    "GKP": 0.85,
}

# -----------------------------
# Transfer recommender tuning
# -----------------------------
TRANSFER_ATTACK_BONUS = {
    "FWD": 0.70,
    "MID": 0.55,
    "DEF": 0.12,
    "GKP": 0.0,
}

TRANSFER_BASE_PPG_WEIGHT = 0.58
TRANSFER_BASE_FORM_WEIGHT = 0.42
TRANSFER_HOT_FORM_WEIGHT = 0.52
TRANSFER_HOT_PPG_WEIGHT = 0.26
TRANSFER_HOT_MOMENTUM_WEIGHT = 0.10
TRANSFER_HOT_SELECTED_WEIGHT = 0.12
TRANSFER_HOT_SELECTED_SCALE = 10.0
TRANSFER_HOT_SCORE_BLEND = 0.30
TRANSFER_KEEP_CAPTAIN_PENALTY = 2.5
TRANSFER_KEEP_VICE_PENALTY = 1.5
TRANSFER_MIN_SCORE_GAIN = 0.05
TRANSFER_HIT_POINTS_STEP = 4
TRANSFER_MAX_MOVES = 10
TRANSFER_DEFAULT_HOT_TOPN = 5

TRANSFER_SET_PIECE_WEIGHTS = {
    "penalties": {1: 2.0, 2: 1.0, 3: 0.35},
    "direct_free_kicks": {1: 0.75, 2: 0.35},
    "corners_indirect": {1: 0.55, 2: 0.25},
}
