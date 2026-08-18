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
    "ep_next","ep_this","minutes","event_points",
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
    # xG / expected-points stack (retained last-season per-90 aggregates pre-season)
    "expected_goals_per_90","expected_assists_per_90","expected_goals_conceded_per_90",
    "saves_per_90","starts",
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
PROJ_PLAYER_RECENT_GW_WINDOW = 5
PROJ_PLAYER_RECENT_MIN_SAMPLES = 2
PROJ_PLAYER_RECENT_BLEND_WEIGHT = 0.65
PROJ_EP_NEXT_BLEND_WEIGHT = 0.50
PROJ_DGW_EXTRA_FIXTURE_DISCOUNT = 0.65   # DGW extra fixture counts as 65% of a normal fixture
PROJ_INJURY_FUTURE_GW_FADE = 0.50        # Future GW injury discount fades by 50% per GW

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
CAPTAIN_PREMIUM_PRICE_FLOOR = 9.0
CAPTAIN_PREMIUM_PRICE_BONUS_PER_M = 0.10
CAPTAIN_FORM_CEILING_WEIGHT = 0.04
CAPTAIN_SET_PIECE_PENALTY_WEIGHT = 0.55

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
TRANSFER_CONSISTENCY_TOTAL_POINTS_WEIGHT = 0.14
TRANSFER_CONSISTENCY_MINUTES_WEIGHT = 0.34
TRANSFER_CONSISTENCY_TOTAL_POINTS_SCALE = 120.0
TRANSFER_CONSISTENCY_MINUTES_TARGET = 1800.0
TRANSFER_HOT_FORM_WEIGHT = 0.52
TRANSFER_HOT_PPG_WEIGHT = 0.26
TRANSFER_HOT_MOMENTUM_WEIGHT = 0.10
TRANSFER_HOT_SELECTED_WEIGHT = 0.12
TRANSFER_HOT_SELECTED_SCALE = 10.0
TRANSFER_HOT_SCORE_BLEND = 0.30
TRANSFER_KEEP_CAPTAIN_PENALTY = 2.5
TRANSFER_KEEP_VICE_PENALTY = 1.5
TRANSFER_MIN_SCORE_GAIN = 0.60
TRANSFER_HIT_POINTS_STEP = 4
TRANSFER_MAX_MOVES = 5
TRANSFER_DEFAULT_HOT_TOPN = 5

TRANSFER_SET_PIECE_WEIGHTS = {
    "penalties": {1: 3.1, 2: 1.2, 3: 0.35},
    "direct_free_kicks": {1: 1.0, 2: 0.35},
    "corners_indirect": {1: 0.75, 2: 0.25},
}
TRANSFER_SET_PIECE_PRIMARY_BONUS = {
    "penalties": 1.1,
    "direct_free_kicks": 0.35,
    "corners_indirect": 0.25,
}

TRANSFER_SELL_STARTER_BOOST = 1.25
TRANSFER_SELL_BENCH_PENALTY = 1.55
TRANSFER_SELL_GKP_PENALTY = 1.8
TRANSFER_SELL_PREMIUM_PRICE_FLOOR = 8.0
TRANSFER_SELL_PREMIUM_BOOST = 0.32
TRANSFER_SELL_INJURY_BOOST = 3.8

TRANSFER_BUY_PREMIUM_PRICE_FLOOR = 8.5
TRANSFER_BUY_PREMIUM_BONUS = 0.26
TRANSFER_BUY_OWNERSHIP_BONUS = 0.08
TRANSFER_BUY_AVAILABILITY_WEIGHT = 0.9
TRANSFER_MIN_SCORE_GAIN_BENCH = 0.85
TRANSFER_MIN_SCORE_GAIN_GKP = 1.05
TRANSFER_GUARDRAIL_INJURY_OVERRIDE = 2.5
TRANSFER_BEAM_WIDTH = 8
TRANSFER_BEAM_SELLERS = 8
TRANSFER_BEAM_BUYERS = 6

# -----------------------------
# Strategy recommendation tuning
# -----------------------------
STRATEGY_MIN_GAIN_PER_TRANSFER_GW1 = 1.4
STRATEGY_MIN_GAIN_PER_TRANSFER_MULTI = 1.1
STRATEGY_CHIP_BENCH_BOOST_MIN_XPTS = 15.0
STRATEGY_CHIP_TRIPLE_CAPTAIN_MIN_XPTS = 10.0
STRATEGY_MAX_BENCH_MOVES = 6

# -----------------------------
# Chip strategy tuning
# -----------------------------
CHIP_WILDCARD_DEFAULT_HORIZON_GWS = 5
CHIP_MAX_PER_TEAM = 3
CHIP_SQUAD_SHAPE = {
    "GKP": 2,
    "DEF": 5,
    "MID": 5,
    "FWD": 3,
}
CHIP_UPGRADE_MAX_ITERS = 320
CHIP_WILDCARD_GW_WEIGHTS = [1.0, 0.95, 0.9, 0.86, 0.82, 0.78, 0.74, 0.7]
CHIP_WILDCARD_DGW_BONUS_PER_EXTRA_FIXTURE = 1.25
CHIP_WILDCARD_DGW_XPTS_WEIGHT = 0.12
CHIP_WILDCARD_LATE_DGW_WEIGHT_STEP = 0.08
CHIP_WILDCARD_SHORT_HORIZON_DGW_MULTIPLIER = 1.4
CHIP_WILDCARD_PREMIUM_ATTACKER_FLOOR = 8.5
CHIP_WILDCARD_PREMIUM_ATTACKER_BASE_BONUS = 0.8
CHIP_WILDCARD_CAPTAINCY_WEIGHT = 0.32
CHIP_WILDCARD_FORM_BONUS_WEIGHT = 0.12
CHIP_WILDCARD_OWNERSHIP_BONUS_WEIGHT = 0.55
CHIP_WILDCARD_OWNERSHIP_BONUS_SCALE = 40.0
CHIP_WILDCARD_MIN_PREMIUM_CAPTAINS = 1
CHIP_WILDCARD_PREMIUM_CAPTAIN_PRICE_FLOOR = 10.5
CHIP_WILDCARD_PREMIUM_CAPTAIN_POSITIONS = ["MID", "FWD"]

# ---------------------------------------------------------------------------
# xG expected-points model (fixture_difficulty / minutes_model / output_model)
# These feed src/expected_points.py, which produces a parallel `xpts_model_*`
# column that project_elements_next_gws blends in via PROJ_MODEL_BLEND_WEIGHT.
# ---------------------------------------------------------------------------

# --- fixture_difficulty.py: xG-based team strength ---
FDR_XG_HALFLIFE_DAYS = 60.0          # exponential time-decay half-life on team-match xG samples
FDR_XG_SHRINKAGE_MATCHES = 6.0       # pseudo-matches of league-average prior (shrinks thin samples)
FDR_HOME_XG_MULT = 1.10              # home attacking boost when projecting a fixture's xG
FDR_AWAY_XG_MULT = 0.92              # away attacking penalty
FDR_RATING_MIN = 0.50                # clamp on attack/defense rating multipliers
FDR_RATING_MAX = 1.80
FDR_LEAGUE_AVG_XG_FALLBACK = 1.40    # per-team per-match league-average xG when data is thin
FDR_KNOWLEDGE_DISCOUNT_PATH = "data/models/knowledge_discount.json"
# Player-level knowledge (news/injury) for the squad picker.
PLAYER_KNOWLEDGE_PATH = "data/models/player_knowledge.json"
PLAYER_KNOWLEDGE_STALE_DAYS = 10

# News corpus (Approach B: RSS refresh routine -> news_digest reads this dir).
NEWS_KB_DIR = "kb/auto/news"
NEWS_MAX_AGE_DAYS = 14   # digest only items this fresh; prune older md
NEWS_FEEDS = [           # RSS sources (verified live 2026-07-26)
    {"source": "sportsmole.co.uk", "url": "https://www.sportsmole.co.uk/football/rss.xml"},
    {"source": "football-talk.co.uk", "url": "https://football-talk.co.uk/feed/"},
    {"source": "betting.betfair.com", "url": "https://betting.betfair.com/football/rss.xml"},
]

# Cross-season carryover (season-start cold start). At a new season's launch there
# is no current-season xG, so ratings start from the prior season's frozen seed
# (regressed toward the mean) and the live signal takes over as matches accrue.
FDR_RATINGS_SEED_PATH = "data/models/team_ratings_seed.json"
FDR_CS_PRIOR_WEIGHT = 0.35           # blend of clean-sheet-implied defense into the carryover rating (0 = off)
FDR_CS_PRIOR_MIN_MATCHES = 6.0       # GK starts needed before the CS record counts as signal (guards season-reset stats)
FDR_CARRYOVER_PRIOR_MATCHES = 8.0    # pseudo-matches of weight given to the prior-season seed
FDR_CARRYOVER_REGRESSION = 0.30      # regress the prior-season rating this far toward 1.0 (mean)
# Promoted teams have no top-flight xG and no seed: assume a weak default until games arrive.
FDR_PROMOTED_DEFAULT_ATTACK = 0.82
FDR_PROMOTED_DEFAULT_DEFENSE = 1.20  # >1 => concedes more xG than average (weaker defense)
# Difficulty bands for the fixture ticker: (max_score, label, color). Score is the
# attacking-difficulty a team faces (higher = harder), centered near 3.0 like FPL's FDR.
FDR_TICKER_BANDS = [
    [2.2, "very_easy", "#1a9850"],
    [2.7, "easy", "#66bd63"],
    [3.3, "medium", "#fee08b"],
    [3.8, "hard", "#f46d43"],
    [9.9, "very_hard", "#d73027"],
]

# --- minutes_model.py: P(start) + expected minutes ---
MINUTES_HALFLIFE_GWS = 5.0           # decay half-life (in GWs) on start/minutes history
MINUTES_START_PRIOR = 0.55           # prior P(start) for players with no history
MINUTES_PRIOR_WEIGHT = 2.0           # pseudo-GWs of prior weight (shrinks thin samples)
MINUTES_E_MIN_GIVEN_START = 82.0     # assumed E[minutes | started] with no history
MINUTES_CAMEO_MINUTES = 22.0         # assumed E[minutes | sub appearance]
MINUTES_SUB_APP_PROB = 0.45          # P(appear | did not start) baseline
MINUTES_P60_GIVEN_START = 0.86       # P(>=60 min | started) baseline
MINUTES_STATUS_AVAILABILITY = {      # hard availability cap by FPL status code
    "a": 1.0, "d": 0.5, "i": 0.0, "s": 0.0, "u": 0.0, "n": 0.0,
}

# --- output_model.py: xG-based structural points ---
OUTPUT_XG_HALFLIFE_DAYS = 75.0       # decay half-life on player per-90 xG/xA samples
OUTPUT_MIN_MINUTES_TRUST = 270.0     # minutes before a player's own rates are trusted over position prior
OUTPUT_GOAL_POINTS = {"GKP": 6, "DEF": 6, "MID": 5, "FWD": 4}
OUTPUT_ASSIST_POINTS = 3.0
OUTPUT_CS_POINTS = {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}
OUTPUT_GOALS_CONCEDED_PENALTY_PER_2 = {"GKP": -1.0, "DEF": -1.0, "MID": 0.0, "FWD": 0.0}
OUTPUT_SAVES_PER_XGA = 2.0           # rough expected saves per unit opponent xG (GKP)
OUTPUT_SAVE_POINTS_PER_SAVE = 1.0 / 3.0
OUTPUT_BONUS_PER_XGI = 0.9           # rough bonus points per expected goal involvement
# Defensive bonus: BPS from clean sheets, clearances, blocks, recoveries earns
# defenders/keepers bonus that attacking xGI misses. Bonus points per expected
# clean sheet, by position (0 for FWD).
OUTPUT_CS_BONUS_PER_CS = {"GKP": 1.0, "DEF": 1.2, "MID": 0.3, "FWD": 0.0}
OUTPUT_POSITION_BASE_XG90 = {"GKP": 0.01, "DEF": 0.06, "MID": 0.12, "FWD": 0.30}
OUTPUT_POSITION_BASE_XA90 = {"GKP": 0.01, "DEF": 0.06, "MID": 0.14, "FWD": 0.16}
OUTPUT_MAX_GOALS_PER_GAME = 2.5      # sanity clamp on a single player's expected goals
OUTPUT_MAX_ASSISTS_PER_GAME = 2.0

# --- blend of the xG model into the baseline projection ---
# 0.0 => baseline projections unchanged (preserves backtest parity). Raise to
# weight the xG model's per-GW xpts against the existing engine output.
PROJ_MODEL_BLEND_WEIGHT = 0.0

# --- minutes/rotation-risk multiplier (surgical, applied in projections.py) ---
# Master flag: when True, project_elements_next_gws replaces the crude
# chance_of_playing discount with a rotation-risk multiplier. Default off so
# committed behavior is unchanged; flip True after scripts/spotcheck_minutes.py.
PROJ_APPLY_MINUTES_MODEL = False
MINUTES_NAILED_START_REF = 0.85   # prob_start at/above which a player is "nailed" (mult caps at 1.0)
MINUTES_CAMEO_POINT_VALUE = 0.30  # value of a likely cameo relative to a start

# --- mini-league ownership-adjusted EV (src/ownership_ev.py + league_strategy.py) ---
LEAGUE_EV_RANKING = True                      # rank candidates by differential EV (False = legacy raw-xPts sort)
LEAGUE_EV_CAPTAIN_PREMIUM_FLOOR = 85          # now_cost (tenths) floor for a "premium" captain (£8.5m)
LEAGUE_EV_CAPTAIN_DIFF_MAX_OWNERSHIP = 0.10   # alternative must be under this league ownership to flag
