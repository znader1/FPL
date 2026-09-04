# config.py
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# If set, requests will use it. Else, system trust store.
REQUESTS_CA_BUNDLE_ENV = "REQUESTS_CA_BUNDLE"

# Caching / API
BOOTSTRAP_TTL = 300  # seconds
EVENT_LIVE_TTL = 60  # live GW scores move during matches, so cache far shorter
# Projections only change when the history is refreshed or bootstrap moves
# (prices, injuries), so they can outlive the fixtures cache by a long way. On a
# shared-cpu Fly machine a cold build is seconds, and this is what keeps a squad
# load off that path.
PROJECTIONS_TTL = 1800
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
FT_MAX = 5                              # 2026-27: free transfers bank up to 5

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

# --- Horizon planner injury gate (src/transfer_planner.py) ---
# A squad player in the likely first-GW XI with one of these statuses is
# force-sold ahead of the normal greedy roll/spend decision, even if the
# best replacement's gain is below TRANSFER's min_gain threshold.
TRANSFER_PLANNER_RED_FLAG_STATUSES = ("i", "s", "u")
# chance_of_playing_next_round at/below this also forces a sell (e.g. 0 == ruled out).
TRANSFER_PLANNER_RED_FLAG_MAX_CHANCE = 0.0

# --- Early-season shrinkage (src/projections.py) ---
# FPL's ppg/form over 1-3 games otherwise get taken at face value: a 4.1m
# defender with two clean sheets (ppg 10.0) projects like a premium and the
# transfer planner chases him instead of rolling. Shrink each player's blended
# baseline toward slope[element_type] × price_m, weighted by finished
# gameweeks; fades as the season accumulates evidence. 0 disables.
PROJ_SHRINKAGE_GAMES = 5.0
PROJ_PRICE_PRIOR_SLOPE = {1: 0.55, 2: 0.50, 3: 0.45, 4: 0.42}  # element_type -> prior ppg per £1m

# First-choice penalty takers are worth ~a penalty every 3 games on top of
# open play; ppg/form only sees that historically and shrinkage dilutes it
# early season. Applied AFTER shrinkage so the duty survives a quiet sample.
# The xG shadow model prices this properly — this is the baseline's stand-in
# until that model earns its backtest win.
PROJ_PENALTY_TAKER_UPLIFT = 0.45  # xPts/GW for penalties_order == 1; 0 disables

# --- Positional bar for spending a free transfer (src/transfer_planner.py) ---
# A GKP/DEF swap must clear a higher multiple of min_gain before it beats
# rolling: back-line moves swing fewer real points, and a banked FT is worth
# more than a sideways defender trade. Injury-forced sells bypass this.
TRANSFER_PLAN_POS_GAIN_MULT = {"GKP": 2.0, "DEF": 2.25, "MID": 1.0, "FWD": 1.0}

# XI-aware horizon planning (src/transfer_planner.py): a bench seller's swap
# only credits the points the buyer would add by displacing the weakest
# same-position XI member — upgrading a player who stays on the bench is
# worth nothing, so the planner stops burning transfers (or hits) on subs.
TRANSFER_PLAN_XI_AWARE = True

# One clear recommendation (user product rule, 2026-09-04): the headline plan
# names at most one move per GW and never funds moves with hits. The verdict
# explicitly compares moving now vs rolling for an extra transfer next week;
# injury urgency is the only bypass.
TRANSFER_PLAN_ALLOW_HITS = False
# Upper bound per GW; with MOVES_FOLLOW_FT the effective cap is the free
# transfers actually banked that week (2 FT -> up to 2 moves, never hits).
TRANSFER_PLAN_MAX_MOVES_PER_GW = 2
TRANSFER_PLAN_MOVES_FOLLOW_FT = True

# Head-to-head hedge nudge: buying a player who faces one of your own
# GKP/DEF<->attacker pairs that gameweek caps the pair's joint ceiling (your
# striker scoring kills your defender's clean sheet). Expected points don't
# change — this is a variance preference, so the nudge is small: it breaks
# ties toward the non-conflicting candidate, nothing more. 0 disables.
TRANSFER_H2H_CONFLICT_PENALTY = 0.75  # xPts per directly-opposed own player

# The roll-vs-move verdict is meaningless with no next week to roll into, and
# a 1-GW display slider kept producing exactly that. The planner always
# evaluates at least this many GWs regardless of the display horizon; the
# slider still controls the pitch/optimization view (1 GW remains available).
TRANSFER_PLAN_MIN_HORIZON_GWS = 3

# -----------------------------
# Strategy recommendation tuning
# -----------------------------
STRATEGY_MIN_GAIN_PER_TRANSFER_GW1 = 1.4
STRATEGY_MIN_GAIN_PER_TRANSFER_MULTI = 1.1
STRATEGY_CHIP_BENCH_BOOST_MIN_XPTS = 15.0
STRATEGY_CHIP_TRIPLE_CAPTAIN_MIN_XPTS = 10.0
STRATEGY_MAX_BENCH_MOVES = 6

# -----------------------------
# Chip plan tuning (src/chip_advisor.py — chip timing planner)
# -----------------------------
CHIP_PLAN_PHASE_SPLIT_GW = 19   # last GW of the first-half chip set
CHIP_PLAN_SEASON_END_GW = 38
CHIP_PLAN_HORIZON_GWS = 8       # model zone: full EV math over this many GWs
CHIP_PLAN_MIN_EV = {            # below this, "hold" beats playing the chip
    # Live spot-check (2026-09-02, entry 107342, GW3-10, no DGWs announced):
    # captain xPts clustered 9.9-13.5 and bench xPts clustered 5.2-6.4 every
    # single week with no DGW in sight — the old 3.0/5.0 floors cleared on
    # nearly every candidate GW, which isn't "hold absent a DGW." Raised both
    # well above the observed no-DGW ceiling so a flat threshold does the
    # DGW-detection job the scoring functions don't do themselves.
    "triple_captain": 15.0,
    "bench_boost": 10.0,
    # free_hit: unchanged. The real fix for FH firing on every ordinary week
    # was CHIP_PLAN_FH_MIN_BLANKING (structural — suppresses non-blank GWs
    # before this floor is even checked), not this number. No live blank-GW
    # data was available this session to re-validate 8.0 specifically; it's a
    # reasonable secondary floor for a genuine blank week and is flagged for
    # a follow-up backtest rather than guessed at here.
    "free_hit": 8.0,
    # wildcard: re-tuned after making score_wildcard budget-aware (was
    # comparing against an unbudgeted top-15, no team cap — live spot-check
    # showed a squad-value-blind "optimal" of +281.7 xPts/5GW that included
    # e.g. 4 Hull players). The budget-constrained rebuild against the same
    # entry roughly halved that to +109.56 xPts/5GW — real progress, but the
    # corrected number is still visibly contaminated by a residual
    # projections-engine outlier: CHIP_PLAN_XPTS_CLAMP (9.0/GW) caps the
    # worst offenders, but several genuinely strong players are *also*
    # clamped to that same ceiling, so a clearly-wrong cheap cluster (3 Hull
    # City defenders, all pinned at the clamp) reads as equally valuable as
    # Haaland/Saka and gets picked on price alone. That's a data-quality bug
    # (tracked separately, needs an upstream projections fix), not a real
    # 31%-of-squad edge. Raised well above the observed (still-noisy) ceiling
    # so WC reads "hold" rather than nudging "play now" off a contaminated
    # GW3 number, while staying reachable for a genuinely severe gap once
    # the projections bug is fixed and/or a real one shows up later.
    "wildcard": 120.0,
}
CHIP_PLAN_EXPIRY_RAMP_GWS = 5   # threshold decays linearly to 0 over the last N GWs
CHIP_PLAN_NUDGE_MIN_EV = 4.0    # floor for the next-GW nudge surface
CHIP_PLAN_FH_MIN_BLANKING = 3   # FH model-zone rec suppressed below this many squad blanks
CHIP_PLAN_XPTS_CLAMP = 9.0      # stopgap clip on WC/FH dream-squad market xPts (outlier projections bug)
CHIP_PLAN_BLANK_TEAM_THRESHOLD = 14  # structural zone: <= this many teams playing = blank-heavy GW

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
MINUTES_INSEASON_SHRINK_PSEUDO = 1.0 # pseudo-matches of 0.5 starts mixed into in-season p_start (small-sample damping)
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
# Keeper-specific shot-stopping volume. The flat OUTPUT_SAVES_PER_XGA gives every
# keeper the same save rate; this scales it by the keeper's own saves_per_90
# relative to the league median, shrunk toward 1.0 by minutes played.
OUTPUT_APPLY_KEEPER_SAVE_RATE = True
OUTPUT_SAVE_RATIO_CLAMP = (0.6, 1.6)  # a keeper cannot be 3x the league at stopping shots
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

# Defensive-contribution points (2025-26 rule): a player banks +2 for reaching a
# per-match action threshold (DEF/GKP 10, MID/FWD 12). output_model was blind to
# this scoring category, which is a chunk of why the xG model under-predicts.
# The feature is a shrunk, time-decayed per-player rate of clearing the
# threshold in 60+ minute games — backtest showed that rate is highly stable
# (H1-vs-H2 rank corr 0.88) and predicts next-game clearance better than form.
# Set-piece duty uplift. The xG model reads only per-90 history, which cannot
# know that a player has just been handed penalties. Applied to the position
# PRIOR and tapered away as a player's own minutes sample grows, since their own
# expected_goals already contains the penalties they have taken.
OUTPUT_APPLY_SETPIECE = True          # off restores exact pre-set-piece behaviour
OUTPUT_SETPIECE_PEN_XG90 = 0.11       # league-average penalty xG per 90 for a first-choice taker
OUTPUT_SETPIECE_FK_XG90 = 0.03        # direct free-kick xG per 90 for the designated taker
OUTPUT_SETPIECE_CORNER_XA90 = 0.05    # xA per 90 uplift for the primary corner taker

OUTPUT_APPLY_DC = True                # off restores exact pre-DC output_model behaviour
OUTPUT_DC_POINTS = 2.0                # points banked for clearing the threshold
OUTPUT_DC_HALFLIFE_DAYS = 75.0        # decay half-life on the clearance-rate samples
OUTPUT_DC_MIN_GAMES_TRUST = 6.0       # 60'+ games before own rate is trusted over the prior
OUTPUT_DC_THRESHOLD = {"GKP": 10, "DEF": 10, "MID": 12, "FWD": 12}
OUTPUT_DC_BASE_RATE = {"GKP": 0.0, "DEF": 0.12, "MID": 0.06, "FWD": 0.0}  # shrink prior (GKP/FWD ~never clear)

# --- blend of the xG model into the baseline projection ---
# Set from the Task 8 sweep (docs/superpowers/plans/2026-08-25-transfer-planner-v2.md
# ## Results): scripts.backtest_blend_sweep over 2025-26 GW6-29 (24 GWs), DC=True,
# weight 0.5 beat weight 0.0 on every metric (MAE -0.202/-9.47%, captain hit +0.042,
# top10 +0.029, regret -0.334), with MAE improving monotonically across the whole
# grid and no regression at any weight. 0.5 is the top of the script's default grid,
# not a confirmed interior optimum -- see the Task 8 caveats in the plan doc.
PROJ_MODEL_BLEND_WEIGHT = 0.5

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
