# Config Reference (`src/config.py`)

This file explains every parameter in `src/config.py`, what it controls, and where the logic is implemented.

## How to tune safely

1. Change values only in `src/config.py`.
2. Test locally with:
   - `uvicorn api.main:app --reload --port 8001`
   - `curl "http://127.0.0.1:8001/recommendations?entry_id=<ENTRY>&include_transfers=true"`
3. If behavior is wrong, adjust the **script listed in the “Logic lives in” column**, not the frontend.

## 1) HTTP / networking

| Parameter | What it controls | Logic lives in |
|---|---|---|
| `UA` | Default browser user-agent string intended for HTTP calls. | Currently not wired. Runtime UA is in `src/fpl_client.py` (`UA_PC`, `UA_ANDROID`). To wire config, edit `src/fpl_client.py` in `new_session`. |
| `REQUESTS_CA_BUNDLE_ENV` | Name of env var for custom CA bundle. | Currently not wired. TLS verify reads `REQUESTS_CA_BUNDLE` directly in `src/fpl_client.py` (`_verify`). |

## 2) Cache / API frequency

| Parameter | What it controls | Logic lives in |
|---|---|---|
| `BOOTSTRAP_TTL` | Cache lifetime (seconds) for bootstrap-static data. | `api/main.py` (`get_bootstrap_cached`) and `fpl_app_v1.py` (`_bootstrap` cache). |
| `FIXTURES_TTL` | Cache lifetime (seconds) for fixtures data. | `api/main.py` (`get_fixtures_cached`) and `fpl_app_v1.py` (`_fixtures_df`, `_projections_df`). |

## 3) Data shaping / Streamlit UI

| Parameter | What it controls | Logic lives in |
|---|---|---|
| `ELEMENTS_KEEP` | Columns kept from FPL `elements` payload. | `src/transforms.py` (`tables_from_bootstrap`). |
| `POS_CHOICES` | Position options in Streamlit filter. | `fpl_app_v1.py` sidebar controls. |
| `METRIC_MAP` | UI metric label -> column mapping. | `fpl_app_v1.py` metric dropdown and `src/transforms.py` (`top_performers`). |
| `SQUAD_COLUMNS` | Output columns for squad dataframe. | `src/transforms.py` (`picks_to_df`). |
| `UI_TOPN_DEFAULT` | Intended default top-N UI value. | Currently not wired. Use it in `fpl_app_v1.py` (`topn` slider default). |
| `UI_FIXTURES_TO_SHOW` | Intended default “next fixtures shown” value. | Currently not wired. Use it in `fpl_app_v1.py` (`nfx` slider default). |

## 4) Projection model (xPts baseline)

| Parameter | What it controls | Logic lives in |
|---|---|---|
| `PROJ_DEFAULT_LATEST_N_MATCHES` | Default form window length (N matches). | `api/main.py` (request parsing) + `src/projections.py` defaults. |
| `PROJ_DEFAULT_PPG_WEIGHT` | Weight of `points_per_game` in baseline xPts. | `src/projections.py` (`baseline_points_per_gw`, `project_elements_next_gws`). |
| `PROJ_DEFAULT_FORM_WEIGHT` | Weight of `form` in baseline xPts. | `src/projections.py` (`baseline_points_per_gw`, `project_elements_next_gws`). |
| `PROJ_FORM_SCALE_PER_MATCH` | Extra form scaling per +1 match in N window. | `src/projections.py` (`baseline_points_per_gw`). |
| `PROJ_FORM_SCALE_BASE_MATCHES` | Neutral N value for form scaling baseline. | `src/projections.py` (`baseline_points_per_gw`). |
| `PROJ_LATEST_N_MIN` | Minimum allowed N window. | `api/main.py` + `src/projections.py` clamping logic. |
| `PROJ_LATEST_N_MAX` | Maximum allowed N window. | `api/main.py` + `src/projections.py` clamping logic. |
| `PROJ_NEUTRAL_TEAM_PPG` | Neutral team strength baseline for context multipliers. | `src/projections.py` (`team_gw_context_multipliers`). |
| `PROJ_HOME_MULT_HOME` | Home-game multiplier. | `src/projections.py` (`team_gw_context_multipliers`). |
| `PROJ_HOME_MULT_AWAY` | Away-game multiplier. | `src/projections.py` (`team_gw_context_multipliers`). |
| `PROJ_OPP_FORM_FACTOR` | Sensitivity of xPts to opponent recent team form. | `src/projections.py` (`team_gw_context_multipliers`). |
| `PROJ_OPP_FORM_MIN` | Lower bound for opponent-form multiplier. | `src/projections.py` (`team_gw_context_multipliers`). |
| `PROJ_OPP_FORM_MAX` | Upper bound for opponent-form multiplier. | `src/projections.py` (`team_gw_context_multipliers`). |
| `PROJ_TEAM_FORM_FACTOR` | Sensitivity of xPts to player-team recent form. | `src/projections.py` (`team_gw_context_multipliers`). |
| `PROJ_TEAM_FORM_MIN` | Lower bound for own-team-form multiplier. | `src/projections.py` (`team_gw_context_multipliers`). |
| `PROJ_TEAM_FORM_MAX` | Upper bound for own-team-form multiplier. | `src/projections.py` (`team_gw_context_multipliers`). |

## 5) Captain selection

| Parameter | What it controls | Logic lives in |
|---|---|---|
| `CAPTAIN_POSITION_MULTIPLIER` | Bias for captain pick by position (usually MID/FWD favored). | `src/optimizer.py` (`optimize_lineup`, `captain_score`). |
| `CAPTAIN_PREMIUM_PRICE_FLOOR` | Price threshold to treat MID/FWD as premium captain options. | `src/optimizer.py` (`optimize_lineup`, `captain_score`). |
| `CAPTAIN_PREMIUM_PRICE_BONUS_PER_M` | Extra captain score per £1m above premium floor for MID/FWD. | `src/optimizer.py` (`optimize_lineup`, `captain_score`). |
| `CAPTAIN_FORM_CEILING_WEIGHT` | Extra captain score from form for MID/FWD ceiling upside. | `src/optimizer.py` (`optimize_lineup`, `captain_score`). |
| `CAPTAIN_SET_PIECE_PENALTY_WEIGHT` | Bonus for primary penalty takers in captain ranking. | `src/optimizer.py` (`optimize_lineup`, `captain_score`). |

## 6) Transfer recommender

### 6.1 Core scoring

| Parameter | What it controls | Logic lives in |
|---|---|---|
| `TRANSFER_ATTACK_BONUS` | Position bonus added to transfer score. | `src/recommender.py` (`position_attack_bonus`). |
| `TRANSFER_BASE_PPG_WEIGHT` | Base score weight for points per game. | `src/recommender.py` (`build_transfer_scores`). |
| `TRANSFER_BASE_FORM_WEIGHT` | Base score weight for form. | `src/recommender.py` (`build_transfer_scores`). |
| `TRANSFER_CONSISTENCY_TOTAL_POINTS_WEIGHT` | Weight of season stability from total points. | `src/recommender.py` (`build_transfer_scores`, `consistency_score`). |
| `TRANSFER_CONSISTENCY_MINUTES_WEIGHT` | Weight of minutes reliability in transfer score. | `src/recommender.py` (`build_transfer_scores`, `consistency_score`). |
| `TRANSFER_CONSISTENCY_TOTAL_POINTS_SCALE` | Scale used to normalize total-points consistency term. | `src/recommender.py` (`build_transfer_scores`, `series_ratio_clip`). |
| `TRANSFER_CONSISTENCY_MINUTES_TARGET` | Minutes target used to normalize reliability term. | `src/recommender.py` (`build_transfer_scores`, `series_ratio_clip`). |
| `TRANSFER_HOT_FORM_WEIGHT` | Hot-score form weight. | `src/recommender.py` (`build_transfer_scores`). |
| `TRANSFER_HOT_PPG_WEIGHT` | Hot-score points-per-game weight. | `src/recommender.py` (`build_transfer_scores`). |
| `TRANSFER_HOT_MOMENTUM_WEIGHT` | Hot-score transfer-in/out momentum weight. | `src/recommender.py` (`build_transfer_scores`). |
| `TRANSFER_HOT_SELECTED_WEIGHT` | Hot-score ownership weight. | `src/recommender.py` (`build_transfer_scores`). |
| `TRANSFER_HOT_SELECTED_SCALE` | Scale factor for ownership %. | `src/recommender.py` (`build_transfer_scores`). |
| `TRANSFER_HOT_SCORE_BLEND` | Blend factor: `transfer_score += blend * hot_score`. | `src/recommender.py` (`build_transfer_scores`). |
| `TRANSFER_SET_PIECE_WEIGHTS` | Points for penalties/FK/corners orders. | `src/recommender.py` (`set_piece_score`). |
| `TRANSFER_SET_PIECE_PRIMARY_BONUS` | Extra certainty bonus for primary takers (order=1). | `src/recommender.py` (`set_piece_score`). |

### 6.2 Seller prioritization

| Parameter | What it controls | Logic lives in |
|---|---|---|
| `TRANSFER_KEEP_CAPTAIN_PENALTY` | Protect current captain from being sold. | `src/recommender.py` (`suggest_transfers`, `keep_penalty`). |
| `TRANSFER_KEEP_VICE_PENALTY` | Protect current vice-captain from being sold. | `src/recommender.py` (`suggest_transfers`, `keep_penalty`). |
| `TRANSFER_SELL_STARTER_BOOST` | Protect current XI players from sale. | `src/recommender.py` (`suggest_transfers`, `starter_sell_boost`). |
| `TRANSFER_SELL_BENCH_PENALTY` | De-prioritize bench churn. | `src/recommender.py` (`suggest_transfers`, `bench_sell_penalty`). |
| `TRANSFER_SELL_GKP_PENALTY` | De-prioritize GK transfers unless needed. | `src/recommender.py` (`suggest_transfers`, `gkp_sell_penalty`). |
| `TRANSFER_SELL_PREMIUM_PRICE_FLOOR` | Price threshold defining “premium” sell logic. | `src/recommender.py` (`suggest_transfers`, `premium_sell_boost`). |
| `TRANSFER_SELL_PREMIUM_BOOST` | Extra pressure to upgrade weak expensive slots. | `src/recommender.py` (`suggest_transfers`, `premium_sell_boost`). |
| `TRANSFER_SELL_INJURY_BOOST` | Strength of injury/availability sell pressure. | `src/recommender.py` (`suggest_transfers`, `injury_sell_boost`). |

### 6.3 Buyer prioritization

| Parameter | What it controls | Logic lives in |
|---|---|---|
| `TRANSFER_BUY_PREMIUM_PRICE_FLOOR` | Price threshold for premium buy bonus. | `src/recommender.py` (`suggest_transfers`, `buy_premium_bonus`). |
| `TRANSFER_BUY_PREMIUM_BONUS` | Bonus for premium MID/FWD targets. | `src/recommender.py` (`suggest_transfers`, `buy_premium_bonus`). |
| `TRANSFER_BUY_OWNERSHIP_BONUS` | Weight on selected-by-percent consensus. | `src/recommender.py` (`suggest_transfers`, `buy_ownership_bonus`). |
| `TRANSFER_BUY_AVAILABILITY_WEIGHT` | Weight on chance-of-playing availability. | `src/recommender.py` (`suggest_transfers`, `buy_availability_bonus`). |

### 6.4 Transfer plan size and filters

| Parameter | What it controls | Logic lives in |
|---|---|---|
| `TRANSFER_MIN_SCORE_GAIN` | Minimum score gain needed to execute a move. | `src/recommender.py` (`suggest_transfers`). |
| `TRANSFER_MIN_SCORE_GAIN_BENCH` | Higher minimum gain required for bench churn. | `src/recommender.py` (`required_gain_for_seller`). |
| `TRANSFER_MIN_SCORE_GAIN_GKP` | Higher minimum gain required for GK transfers. | `src/recommender.py` (`required_gain_for_seller`). |
| `TRANSFER_GUARDRAIL_INJURY_OVERRIDE` | If injury risk is high enough, bypass bench/GK guardrail thresholds. | `src/recommender.py` (`required_gain_for_seller`). |
| `TRANSFER_HIT_POINTS_STEP` | Every N hit points allows one extra move in planner simulation. | `src/recommender.py` (`suggest_transfers`, `extra_from_hits`). |
| `TRANSFER_MAX_MOVES` | Hard cap on generated moves. | `src/recommender.py` (`suggest_transfers`, `transfer_count`). |
| `TRANSFER_DEFAULT_HOT_TOPN` | Number of hot targets shown per position. | `src/recommender.py` (`hot_by_position`, `recommend`). |
| `TRANSFER_BEAM_WIDTH` | Number of candidate transfer paths kept at each search step. | `src/recommender.py` (`suggest_transfers`, beam search loop). |
| `TRANSFER_BEAM_SELLERS` | Number of top seller candidates expanded per state. | `src/recommender.py` (`pick_sellers_for_state`). |
| `TRANSFER_BEAM_BUYERS` | Number of top buy candidates expanded per seller. | `src/recommender.py` (`pick_buy_candidates`). |

## 7) Strategy recommendation output

| Parameter | What it controls | Logic lives in |
|---|---|---|
| `STRATEGY_MIN_GAIN_PER_TRANSFER_GW1` | Gain threshold per move to act for 1-GW horizon. | `api/main.py` (`_build_strategy_recommendation`). |
| `STRATEGY_MIN_GAIN_PER_TRANSFER_MULTI` | Gain threshold per move for multi-GW horizons. | `api/main.py` (`_build_strategy_recommendation`). |
| `STRATEGY_CHIP_BENCH_BOOST_MIN_XPTS` | Bench xPts trigger for `bench_boost` suggestion. | `api/main.py` (`_build_strategy_recommendation`). |
| `STRATEGY_CHIP_TRIPLE_CAPTAIN_MIN_XPTS` | Captain xPts trigger for `triple_captain` suggestion. | `api/main.py` (`_build_strategy_recommendation`). |
| `STRATEGY_MAX_BENCH_MOVES` | Maximum bench swaps returned in strategy block. | `api/main.py` (`_build_bench_moves`). |

## 8) Chip draft tuning

| Parameter | What it controls | Logic lives in |
|---|---|---|
| `CHIP_WILDCARD_DEFAULT_HORIZON_GWS` | Default wildcard planning horizon when the request does not provide one. | `api/main.py` (`build_recommendations`). |
| `CHIP_MAX_PER_TEAM` | Max players allowed per real-life team in chip drafts. | `src/optimizer.py` (`build_chip_squad`). |
| `CHIP_SQUAD_SHAPE` | Required 15-man squad structure for chip drafts. | `src/optimizer.py` (`_chip_shape`, `build_chip_squad`). |
| `CHIP_UPGRADE_MAX_ITERS` | Maximum greedy upgrade passes when building a chip draft. | `src/optimizer.py` (`build_chip_squad`). |
| `CHIP_WILDCARD_GW_WEIGHTS` | Weights used to emphasize the next fixtures inside the wildcard score. | `src/projections.py` (`add_wildcard_scores`). |
| `CHIP_WILDCARD_DGW_BONUS_PER_EXTRA_FIXTURE` | Base bonus for each extra fixture in a wildcard horizon double-GW. | `src/projections.py` (`add_wildcard_scores`). |
| `CHIP_WILDCARD_DGW_XPTS_WEIGHT` | Extra wildcard bonus tied to the xPts of double-GW weeks. | `src/projections.py` (`add_wildcard_scores`). |
| `CHIP_WILDCARD_LATE_DGW_WEIGHT_STEP` | Additional emphasis on doubles that arrive later in the wildcard horizon. | `src/projections.py` (`add_wildcard_scores`). |
| `CHIP_WILDCARD_PREMIUM_ATTACKER_FLOOR` | Price threshold that defines a premium MID/FWD for wildcard captaincy coverage. | `src/projections.py` (`add_wildcard_scores`). |
| `CHIP_WILDCARD_PREMIUM_ATTACKER_BASE_BONUS` | Flat wildcard bonus for premium captaincy-ready attackers. | `src/projections.py` (`add_wildcard_scores`). |
| `CHIP_WILDCARD_CAPTAINCY_WEIGHT` | How strongly captaincy upside affects the wildcard score. | `src/projections.py` (`add_wildcard_scores`). |

## 9) If you want to switch to ML tuning later

- Keep `src/config.py` as your **fallback rules** even when ML is added.
- Add a model output column (for example `xpts_model`) in `src/projections.py`.
- In `api/main.py`, switch `score_col` used by optimizer/recommender from rule-based to model-based.
- Keep all strategy thresholds (`STRATEGY_*`) active as guardrails until model calibration is stable.
