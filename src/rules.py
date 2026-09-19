"""The Fantasy Premier League rulebook.

These are not parameters. Every value here is fixed by the game itself, so it
can only change when FPL changes the rules — never to tune a recommendation.
They live apart from ``config.py`` so nobody tries to "improve" a result by
editing the points awarded for a goal.

``config.py`` re-exports all of them, so existing ``config.NAME`` reads keep
working; this module is the single definition site.

Source: the official FPL rules page. Update on a rules change only, and note
the season the change took effect.
"""

# --- Squad and transfer rules -------------------------------------------
# Maximum players from any one Premier League club.
CHIP_MAX_PER_TEAM = 3
TRANSFER_MAX_PER_TEAM = 3

# Points deducted per transfer beyond the free ones.
TRANSFER_HIT_POINTS_STEP = 4

# Free transfers bank up to this many (raised from 2 to 5 for 2026-27).
FT_MAX = 5

# --- Season and chip structure ------------------------------------------
# Chips come in two sets; the first must be used by this gameweek.
CHIP_PLAN_PHASE_SPLIT_GW = 19
CHIP_PLAN_SEASON_END_GW = 38

# --- Scoring ------------------------------------------------------------
# Points per goal, by position.
OUTPUT_GOAL_POINTS = {"GKP": 6, "DEF": 6, "MID": 5, "FWD": 4}

# Points per assist (same for every position).
OUTPUT_ASSIST_POINTS = 3.0

# Points for a clean sheet, by position.
OUTPUT_CS_POINTS = {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}

# Deduction per 2 goals conceded — keepers and defenders only.
OUTPUT_GOALS_CONCEDED_PENALTY_PER_2 = {"GKP": -1.0, "DEF": -1.0, "MID": 0.0, "FWD": 0.0}

# 1 point per 3 saves.
OUTPUT_SAVE_POINTS_PER_SAVE = 1.0 / 3.0

# Defensive contributions: points awarded for clearing the threshold, and the
# threshold itself (defenders count CBIT, midfielders CBIRT).
OUTPUT_DC_POINTS = 2.0
OUTPUT_DC_THRESHOLD = {"GKP": 10, "DEF": 10, "MID": 12, "FWD": 12}
