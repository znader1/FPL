import { authFetch } from "@/lib/authFetch";
export type FplPosition = "GKP" | "DEF" | "MID" | "FWD";

export interface FplTeamRecommendationPlayer {
  player_id: number;
  web_name: string;
  pos: FplPosition;
  team_short: string;
  team_name: string;
  is_captain: boolean;
  is_vice_captain: boolean;
  multiplier: number;
  xpts: number;
  /** Actual points scored in the rendered GW, raw — apply `multiplier` for the captain. */
  event_points?: number | null;
  live_minutes?: number | null;
  live_bonus?: number | null;
  live_bps?: number | null;
  next_fixtures?: string;
  fixtures_horizon?: FplFixturesHorizonItem[];
  is_captain_suggested?: boolean;
  is_vice_suggested?: boolean;
  team?: number;
  code?: number;
  photo?: string;
  badge_url?: string;
  photo_url?: string;
  alerts?: FplPlayerAlert[];
  score_breakdown?: FplPlayerScoreBreakdown;
  /** Captain Lab (2026-10 handoff). None are emitted by today's backend; the
   *  page falls back to `score_breakdown.distribution` for the range and to the
   *  suggested captain for both goals when ownership data is absent. */
  xpts_p10?: number | null;
  xpts_p90?: number | null;
  /** Effective ownership in the top 10k, percent (can exceed 100 with captaincy). No source yet. */
  eo_top10k?: number | null;
  /** The GW the top-10k sample was taken in (picks are readable only after a deadline, so it lags the planned GW by one). */
  eo_top10k_event_id?: number | null;
  /** FPL's overall selected_by_percent — the honest ownership figure the backend does send. */
  ownership_pct?: number | null;
  /** Estimated ranks gained if the player hauls. */
  rank_gain_if_haul?: number | null;
}

export interface FplFixturesHorizonItem {
  event_id: number;
  fixtures: string;
  fixture_count?: number;
  diff_avg?: number;
  xpts?: number;
}

export interface FplTeamRecommendationBenchPlayer extends FplTeamRecommendationPlayer {
  bench_order: number;
}

export interface FplPlayerAlert {
  severity?: "high" | "medium" | "info" | "low" | string;
  category?: string;
  text?: string;
  event_id?: number | null;
  player_id?: number | null;
  player_name?: string;
}

export interface FplWildcardScoreBreakdown {
  score?: number | null;
  weighted_xpts?: number | null;
  future_dgw_bonus?: number | null;
  captaincy_bonus?: number | null;
}

export interface FplRecentFormBreakdown {
  window_gws?: number | null;
  history_max_gw?: number | null;
  samples?: number | null;
  last_gw?: number | null;
  available?: boolean;
  avg_points?: number | null;
  avg_minutes?: number | null;
  avg_fixture_count?: number | null;
  avg_starts?: number | null;
}

export interface FplBaselineBreakdown {
  long_term?: number | null;
  recent_gw?: number | null;
  blended?: number | null;
  gw1_after_ep_next_blend?: number | null;
}

/**
 * Component probabilities behind a projection.
 *
 * These describe the xG MODEL half of the number only: the headline `xpts` is a
 * blend of the ppg baseline and the model, so `model_exp_points` is what the
 * `ep_*` components actually add up to — not `current_gw_xpts`.
 */
export interface FplPlayerComponents {
  p_goal?: number | null;
  p_assist?: number | null;
  p_clean_sheet?: number | null;
  p_appear?: number | null;
  p_60?: number | null;
  p_dc?: number | null;
  exp_goals?: number | null;
  exp_assists?: number | null;
  exp_minutes?: number | null;
  model_exp_points?: number | null;
  ep_appearance?: number | null;
  ep_goals?: number | null;
  ep_assists?: number | null;
  ep_clean_sheet?: number | null;
  ep_bonus?: number | null;
  ep_dc?: number | null;
}

/** The distribution behind the mean — what the player is actually likely to score. */
export interface FplPointsDistribution {
  modal_points?: number | null;
  p_return_6?: number | null;
  p_haul_10?: number | null;
  p80_low?: number | null;
  p80_high?: number | null;
}

export interface FplPlayerScoreBreakdown {
  note?: string;
  current_gw_xpts?: number | null;
  horizon_xpts?: number | null;
  objective_score_col?: string | null;
  objective_score?: number | null;
  objective_explanation?: string;
  wildcard?: FplWildcardScoreBreakdown;
  recent_form?: FplRecentFormBreakdown;
  baseline?: FplBaselineBreakdown;
  components?: FplPlayerComponents | null;
  distribution?: FplPointsDistribution | null;
  fixtures_horizon?: FplFixturesHorizonItem[];
}

export interface FplTransferPlayer {
  id: number;
  name: string;
  team: string;
  price: number;
  /** Next fixture for the target GW, e.g. "BOU (H)"; absent on a blank GW. */
  next_fixture?: string;
}

export interface FplTransferMove {
  position?: FplPosition;
  sell: FplTransferPlayer;
  buy: FplTransferPlayer;
  score_gain?: number;
  /** Immediate-GW slice of score_gain; present on plan moves only. */
  this_gw_gain?: number;
  /** True when this is the multi-GW plan's first-GW move (leads the list). */
  in_plan?: boolean;
  buy_hot_score?: number;
  buy_set_piece_score?: number;
}

export interface FplTransferPlan {
  free_transfers?: number;
  horizon_gws?: number;
  hit_cap?: number;
  transfer_count_target?: number;
  transfer_count_built?: number;
}

// Multi-GW roll/bank plan (additive; the single-GW `transfers` above never
// sequences GWs). Emitted by build_recommendations as `transfer_plan_horizon`.
export interface FplTransferPlanMove {
  position?: string;
  sell: FplTransferPlayer;
  buy: FplTransferPlayer;
  score_gain: number;
  /** Immediate-GW slice of score_gain (score_gain is the remaining-horizon total). */
  this_gw_gain?: number;
  forced_injury?: boolean;
  /** Own GKP/DEF<->attacker players the buy would face that GW (hedge warning). */
  h2h_conflicts?: string[];
  /** Present when the seller carries availability risk (status != "a" or chance < 100). */
  sell_availability?: { status: string; chance: number | null };
}
export interface FplTransferPlanGw {
  gw: number;
  action: "roll" | "transfer";
  free_transfers_before: number;
  free_transfers_after: number;
  hits: number;
  hit_cost: number;
  gw_gain: number;
  net_gain: number;
  bank_after: number;
  moves: FplTransferPlanMove[];
  note: string;
}
export interface FplTransferVerdictMove {
  sell: FplTransferPlayer;
  buy: FplTransferPlayer;
  position?: string;
  this_gw_gain: number;
  horizon_gain: number;
  forced_injury?: boolean;
  h2h_conflicts?: string[];
  /** Present when the seller carries availability risk (status != "a" or chance < 100). */
  sell_availability?: { status: string; chance: number | null };
}

export interface FplTransferRunnerUp extends FplTransferVerdictMove {
  clears_bar: boolean;
}

/** Structured twin of `reasoning`; emitted by plan_transfers as `verdict_detail`. */
export interface FplTransferVerdictDetail {
  action: "spend" | "roll" | "spend_forced_injury";
  horizon: { start_gw: number | null; end_gw: number | null; n: number };
  ft_before: number;
  ft_after: number;
  threshold: number;
  /** First-GW moves; empty on roll. */
  moves: FplTransferVerdictMove[];
  this_gw_gain: number;
  horizon_gain: number;
  hit_cost: number;
  /** total_net_gain of the returned plan. */
  plan_net: number;
  /** The path the counterfactual rejected: the roll walk on spend, the spend walk on a flipped roll. */
  roll_alternative: { net: number; gw: number | null; moves: FplTransferVerdictMove[] } | null;
  /** Roll only: the first later GW the plan transfers in. */
  next_move: { gw: number; moves: FplTransferVerdictMove[]; horizon_gain: number } | null;
  /** Best swap for each other squad player, ranked by horizon gain; the chosen pair is excluded. */
  runner_ups?: FplTransferRunnerUp[];
}

export interface FplTransferPlanHorizon {
  valid?: boolean;
  gws?: number[];
  horizon_gws?: number;
  start_free_transfers?: number;
  ft_cap?: number;
  allow_hits?: boolean;
  total_net_gain?: number;
  final_bank?: number;
  plan?: FplTransferPlanGw[];
  verdict?: "roll" | "spend" | "spend_forced_injury";
  reasoning?: string;
  verdict_detail?: FplTransferVerdictDetail;
  first_gw_ft_before?: number;
  first_gw_ft_after?: number;
}

export interface FplHotPlayer extends FplTransferPlayer {
  pos?: FplPosition;
  xpts?: number;
  xpts_horizon?: number;
  transfer_score?: number;
  hot_score?: number;
  set_piece_score?: number;
}

export type FplMovesByPosition = Partial<Record<FplPosition, number>>;
export type FplHotByPosition = Partial<Record<FplPosition, FplHotPlayer[]>>;
export type FplChipStrategy =
  | "none"
  | "wildcard"
  | "free_hit"
  | "bench_boost"
  | "triple_captain";

export interface FplTransfersRecommendation {
  note?: string;
  transfer_plan?: FplTransferPlan;
  moves_by_position?: FplMovesByPosition;
  hot_by_position?: FplHotByPosition;
  moves: FplTransferMove[];
  remaining_itb?: number;
  max_moves?: number;
  moves_used?: number;
  hit_cost?: number;
  total_score_gain?: number;
  transfer_policy?: {
    max_moves?: number;
    moves_used?: number;
  };
}

export interface FplTeamFixture {
  team_short: string;
  opponent_short: string;
  difficulty?: number;
  is_home?: boolean;
}

export interface FplNextEventSummary {
  event_id: number | null;
  /** The GW in progress, from bootstrap's `is_current`. Null pre-season and between GWs. */
  current_event_id?: number | null;
  deadline_time_utc?: string | null;
  first_fixture_time_utc?: string | null;
  hours_to_deadline?: number | null;
  hours_to_first_fixture?: number | null;
  fixture_count?: number;
}

export interface FplEntryHistory {
  points?: number;
  total_points?: number;
  overall_rank?: number;
  rank?: number;
  event_transfers?: number;
  event_transfers_cost?: number;
  points_on_bench?: number;
  /** In the bank, £m. Not emitted by today's backend; the navbar shows it only when present. */
  bank?: number | null;
}

/**
 * Who an FPL entry id belongs to right now.
 *
 * FPL reissues entry ids each season, so an id stored last season resolves to a
 * different manager. `joined_time` is the field to compare on — it changes when
 * the id is reissued, where renaming a team does not.
 */
export interface FplEntryIdentity {
  entry_id: number;
  manager_name?: string | null;
  team_name?: string | null;
  joined_time?: string | null;
  started_event?: number | null;
  years_active?: number | null;
  region_name?: string | null;
  overall_rank?: number | null;
  overall_points?: number | null;
  current_event?: number | null;
}

export interface FplSquad {
  entry_id: number;
  event_id: number;
  /** Null when the upstream identity lookup failed; never a reason to hide the squad. */
  entry?: FplEntryIdentity | null;
  notes?: string[];
  formation?: [number, number, number];
  captain_player_id?: number;
  vice_player_id?: number;
  starting_xi: FplTeamRecommendationPlayer[];
  bench: FplTeamRecommendationBenchPlayer[];
  entry_history?: FplEntryHistory;
  active_chip?: string | null;
}

export interface FplTransferApplicationSummary {
  requested: number;
  applied: number;
  skipped: number;
  available_moves?: number;
  requested_apply_count?: number;
}

export interface FplTransferImpactSummary {
  base_projected_points_with_captain: number;
  with_transfers_projected_points_with_captain: number;
  delta_projected_points_with_captain: number;
}

export interface FplApiTimingsMs {
  load_context_ms?: number;
  projections_ms?: number;
  optimize_base_ms?: number;
  pack_base_lineup_ms?: number;
  position_panels_ms?: number;
  transfer_preview_ms?: number;
  transfer_apply_and_reoptimize_ms?: number;
  total_ms?: number;
}

export interface FplOptimizedSquad extends FplSquad {
  formation: [number, number, number];
  captain_player_id: number;
  vice_player_id: number;
  projected_points_with_captain: number;
}

export interface FplTransferAppliedStep extends FplOptimizedSquad {
  applied_count: number;
  transfer_application?: FplTransferApplicationSummary;
  transfer_impact?: FplTransferImpactSummary;
}

export interface FplChipStrategySummary {
  selected: FplChipStrategy;
  is_active: boolean;
  objective_score_col?: string | null;
  objective_horizon_gws?: number | null;
  play_event_id?: number | null;
  propagates_to_future_gws?: boolean;
  budget_m?: number | null;
  squad_cost_m?: number | null;
  remaining_budget_m?: number | null;
  objective_score_total?: number | null;
  objective_components?: string[];
  /** Same-team attacker stacks in the draft XI with joint return/blank odds. */
  stack_odds?: {
    team: number;
    team_short?: string;
    n: number;
    players: string[];
    lam: number;
    p_all_return: number;
    p_all_blank: number;
  }[];
  explanation?: string | null;
  profile?: {
    summary?: string;
    focus?: string[];
    premium_attackers?: number;
    future_double_gameweeks?: number[];
    future_double_players?: number;
  } | null;
  reason?: string | null;
}

export interface FplScoringGuide {
  headline?: string;
  bullets?: string[];
  objective_score_col?: string | null;
}

export interface FplSquadInsights {
  summary_points?: FplPlayerAlert[];
  player_flags?: FplPlayerAlert[];
}

export interface FplHistoryContext {
  source?: "csv" | "fallback" | string;
  base_dir?: string;
  path?: string | null;
  max_gw?: number | null;
  updated_at_utc?: string | null;
  season?: string | null;
}

export interface FplTeamRecommendation extends FplSquad {
  entry_id: number;
  event_id: number;
  horizon_gws: number;
  squad_source?: string;
  pre_first_deadline?: boolean;
  formation: [number, number, number];
  captain_player_id: number;
  vice_player_id: number;
  projected_points_with_captain: number;
  /** Command Center benchmarks (2026-10 handoff). None are emitted by today's
   *  backend; the projected card renders its ring and bars only when present. */
  projected_percentile?: number | null;
  projected_top10k_avg?: number | null;
  projected_overall_avg?: number | null;
  chip_strategy?: FplChipStrategySummary;
  transfers?: FplTransfersRecommendation;
  transfer_plan_horizon?: FplTransferPlanHorizon;
  transfer_application?: FplTransferApplicationSummary;
  transfer_impact?: FplTransferImpactSummary;
  squad_with_transfers?: FplOptimizedSquad;
  squad_with_transfers_steps?: FplTransferAppliedStep[];
  timings_ms?: FplApiTimingsMs;
  scoring_guide?: FplScoringGuide;
  squad_insights?: FplSquadInsights;
  history_context?: FplHistoryContext;
  starting_xi: FplTeamRecommendationPlayer[];
  bench: FplTeamRecommendationBenchPlayer[];
}

export const SAMPLE_TEAM_RECOMMENDATION: FplTeamRecommendation = {
  entry_id: 588004,
  event_id: 25,
  horizon_gws: 3,
  formation: [4, 5, 1],
  captain_player_id: 449,
  vice_player_id: 237,
  projected_points_with_captain: 57.931999999999995,
  transfers: {
    note: "Heuristic transfer planner with horizon + hot-player + set-piece weighting.",
    transfer_plan: {
      free_transfers: 1,
      horizon_gws: 3,
      hit_cap: 0,
      transfer_count_target: 4,
      transfer_count_built: 1,
    },
    moves_by_position: {
      GKP: 1,
    },
    hot_by_position: {
      GKP: [
        {
          id: 32,
          name: "Martinez",
          team: "AVL",
          pos: "GKP",
          price: 5,
          transfer_score: 7.8,
          hot_score: 2.2,
          set_piece_score: 0,
        },
      ],
      DEF: [],
      MID: [],
      FWD: [],
    },
    moves: [
      {
        position: "GKP",
        sell: {
          id: 253,
          name: "Henderson",
          team: "CRY",
          price: 5,
        },
        buy: {
          id: 32,
          name: "Martinez",
          team: "AVL",
          price: 5,
        },
        score_gain: 5.1,
        buy_hot_score: 2.2,
        buy_set_piece_score: 0,
      },
    ],
    remaining_itb: 0.5,
  },
  starting_xi: [
    {
      player_id: 5,
      web_name: "Gabriel",
      pos: "DEF",
      team_short: "ARS",
      team_name: "Arsenal",
      is_captain: true,
      is_vice_captain: false,
      multiplier: 3,
      xpts: 5.3,
      is_captain_suggested: false,
      is_vice_suggested: false,
      team: 1,
      code: 226597,
      photo: "226597.jpg",
      badge_url: "https://resources.premierleague.com/premierleague/badges/50/t3.png",
      photo_url:
        "https://resources.premierleague.com/premierleague/photos/players/110x140/p226597.png",
    },
    {
      player_id: 411,
      web_name: "O'Reilly",
      pos: "DEF",
      team_short: "MCI",
      team_name: "Man City",
      is_captain: false,
      is_vice_captain: false,
      multiplier: 1,
      xpts: 4.7,
      is_captain_suggested: false,
      is_vice_suggested: false,
      team: 13,
      code: 472769,
      photo: "472769.jpg",
      badge_url: "https://resources.premierleague.com/premierleague/badges/50/t43.png",
      photo_url:
        "https://resources.premierleague.com/premierleague/photos/players/110x140/p472769.png",
    },
    {
      player_id: 8,
      web_name: "J.Timber",
      pos: "DEF",
      team_short: "ARS",
      team_name: "Arsenal",
      is_captain: false,
      is_vice_captain: false,
      multiplier: 1,
      xpts: 4.2,
      is_captain_suggested: false,
      is_vice_suggested: false,
      team: 1,
      code: 445122,
      photo: "445122.jpg",
      badge_url: "https://resources.premierleague.com/premierleague/badges/50/t3.png",
      photo_url:
        "https://resources.premierleague.com/premierleague/photos/players/110x140/p445122.png",
    },
    {
      player_id: 72,
      web_name: "Senesi",
      pos: "DEF",
      team_short: "BOU",
      team_name: "Bournemouth",
      is_captain: false,
      is_vice_captain: false,
      multiplier: 1,
      xpts: 3.8880000000000003,
      is_captain_suggested: false,
      is_vice_suggested: false,
      team: 4,
      code: 221466,
      photo: "221466.jpg",
      badge_url: "https://resources.premierleague.com/premierleague/badges/50/t91.png",
      photo_url:
        "https://resources.premierleague.com/premierleague/photos/players/110x140/p221466.png",
    },
    {
      player_id: 430,
      web_name: "Haaland",
      pos: "FWD",
      team_short: "MCI",
      team_name: "Man City",
      is_captain: false,
      is_vice_captain: true,
      multiplier: 1,
      xpts: 5.3,
      is_captain_suggested: false,
      is_vice_suggested: false,
      team: 13,
      code: 223094,
      photo: "223094.jpg",
      badge_url: "https://resources.premierleague.com/premierleague/badges/50/t43.png",
      photo_url:
        "https://resources.premierleague.com/premierleague/photos/players/110x140/p223094.png",
    },
    {
      player_id: 253,
      web_name: "Henderson",
      pos: "GKP",
      team_short: "CRY",
      team_name: "Crystal Palace",
      is_captain: false,
      is_vice_captain: false,
      multiplier: 1,
      xpts: 3.024,
      is_captain_suggested: false,
      is_vice_suggested: false,
      team: 8,
      code: 172649,
      photo: "172649.jpg",
      badge_url: "https://resources.premierleague.com/premierleague/badges/50/t31.png",
      photo_url:
        "https://resources.premierleague.com/premierleague/photos/players/110x140/p172649.png",
    },
    {
      player_id: 449,
      web_name: "B.Fernandes",
      pos: "MID",
      team_short: "MUN",
      team_name: "Man Utd",
      is_captain: false,
      is_vice_captain: false,
      multiplier: 1,
      xpts: 7.4,
      is_captain_suggested: true,
      is_vice_suggested: false,
      team: 14,
      code: 141746,
      photo: "141746.jpg",
      badge_url: "https://resources.premierleague.com/premierleague/badges/50/t1.png",
      photo_url:
        "https://resources.premierleague.com/premierleague/photos/players/110x140/p141746.png",
    },
    {
      player_id: 237,
      web_name: "Enzo",
      pos: "MID",
      team_short: "CHE",
      team_name: "Chelsea",
      is_captain: false,
      is_vice_captain: false,
      multiplier: 1,
      xpts: 5.6160000000000005,
      is_captain_suggested: false,
      is_vice_suggested: true,
      team: 7,
      code: 448047,
      photo: "448047.jpg",
      badge_url: "https://resources.premierleague.com/premierleague/badges/50/t8.png",
      photo_url:
        "https://resources.premierleague.com/premierleague/photos/players/110x140/p448047.png",
    },
    {
      player_id: 267,
      web_name: "Sarr",
      pos: "MID",
      team_short: "CRY",
      team_name: "Crystal Palace",
      is_captain: false,
      is_vice_captain: false,
      multiplier: 1,
      xpts: 4.104,
      is_captain_suggested: false,
      is_vice_suggested: false,
      team: 8,
      code: 232185,
      photo: "232185.jpg",
      badge_url: "https://resources.premierleague.com/premierleague/badges/50/t31.png",
      photo_url:
        "https://resources.premierleague.com/premierleague/photos/players/110x140/p232185.png",
    },
    {
      player_id: 21,
      web_name: "Rice",
      pos: "MID",
      team_short: "ARS",
      team_name: "Arsenal",
      is_captain: false,
      is_vice_captain: false,
      multiplier: 1,
      xpts: 3.7,
      is_captain_suggested: false,
      is_vice_suggested: false,
      team: 1,
      code: 204480,
      photo: "204480.jpg",
      badge_url: "https://resources.premierleague.com/premierleague/badges/50/t3.png",
      photo_url:
        "https://resources.premierleague.com/premierleague/photos/players/110x140/p204480.png",
    },
    {
      player_id: 417,
      web_name: "Cherki",
      pos: "MID",
      team_short: "MCI",
      team_name: "Man City",
      is_captain: false,
      is_vice_captain: false,
      multiplier: 1,
      xpts: 3.3,
      is_captain_suggested: false,
      is_vice_suggested: false,
      team: 13,
      code: 466052,
      photo: "466052.jpg",
      badge_url: "https://resources.premierleague.com/premierleague/badges/50/t43.png",
      photo_url:
        "https://resources.premierleague.com/premierleague/photos/players/110x140/p466052.png",
    },
  ],
  bench: [
    {
      player_id: 136,
      web_name: "Thiago",
      pos: "FWD",
      team_short: "BRE",
      team_name: "Brentford",
      is_captain: false,
      is_vice_captain: false,
      multiplier: 0,
      xpts: 2.6,
      bench_order: 1,
      team: 5,
      code: 502500,
      photo: "502500.jpg",
      badge_url: "https://resources.premierleague.com/premierleague/badges/50/t94.png",
      photo_url:
        "https://resources.premierleague.com/premierleague/photos/players/110x140/p502500.png",
    },
    {
      player_id: 691,
      web_name: "Calvert-Lewin",
      pos: "FWD",
      team_short: "LEE",
      team_name: "Leeds",
      is_captain: false,
      is_vice_captain: false,
      multiplier: 0,
      xpts: 2.6,
      bench_order: 2,
      team: 11,
      code: 177815,
      photo: "177815.jpg",
      badge_url: "https://resources.premierleague.com/premierleague/badges/50/t2.png",
      photo_url:
        "https://resources.premierleague.com/premierleague/photos/players/110x140/p177815.png",
    },
    {
      player_id: 191,
      web_name: "Estève",
      pos: "DEF",
      team_short: "BUR",
      team_name: "Burnley",
      is_captain: false,
      is_vice_captain: false,
      multiplier: 0,
      xpts: 2.4,
      bench_order: 3,
      team: 3,
      code: 477717,
      photo: "477717.jpg",
      badge_url: "https://resources.premierleague.com/premierleague/badges/50/t90.png",
      photo_url:
        "https://resources.premierleague.com/premierleague/photos/players/110x140/p477717.png",
    },
    {
      player_id: 470,
      web_name: "Dúbravka",
      pos: "GKP",
      team_short: "BUR",
      team_name: "Burnley",
      is_captain: false,
      is_vice_captain: false,
      multiplier: 0,
      xpts: 2.6,
      bench_order: 4,
      team: 3,
      code: 67089,
      photo: "67089.jpg",
      badge_url: "https://resources.premierleague.com/premierleague/badges/50/t90.png",
      photo_url:
        "https://resources.premierleague.com/premierleague/photos/players/110x140/p67089.png",
    },
  ],
};

export const SAMPLE_SQUAD: FplSquad = {
  entry_id: SAMPLE_TEAM_RECOMMENDATION.entry_id,
  event_id: SAMPLE_TEAM_RECOMMENDATION.event_id,
  formation: SAMPLE_TEAM_RECOMMENDATION.formation,
  captain_player_id: SAMPLE_TEAM_RECOMMENDATION.captain_player_id,
  vice_player_id: SAMPLE_TEAM_RECOMMENDATION.vice_player_id,
  starting_xi: SAMPLE_TEAM_RECOMMENDATION.starting_xi,
  bench: SAMPLE_TEAM_RECOMMENDATION.bench,
  entry_history: {
    points: 54,
    total_points: 1712,
    overall_rank: 1203456,
  },
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);

export const isFplSquad = (value: unknown): value is FplSquad => {
  if (!isRecord(value)) return false;
  if (typeof value.entry_id !== "number") return false;
  if (typeof value.event_id !== "number") return false;
  if (!Array.isArray(value.starting_xi)) return false;
  if (!Array.isArray(value.bench)) return false;
  return true;
};

export const isFplTeamRecommendation = (value: unknown): value is FplTeamRecommendation => {
  if (!isFplSquad(value)) return false;
  if (!isRecord(value)) return false;
  if (typeof value.horizon_gws !== "number") return false;
  if (
    !Array.isArray(value.formation) ||
    value.formation.length !== 3 ||
    value.formation.some((n) => typeof n !== "number")
  ) {
    return false;
  }
  if (typeof value.captain_player_id !== "number") return false;
  if (typeof value.vice_player_id !== "number") return false;
  if (typeof value.projected_points_with_captain !== "number") return false;
  return true;
};

export interface TeamRecommendationParams {
  entryId: number;
  eventId: number;
  horizonGws: number;
  chipStrategy?: FplChipStrategy;
  chipHorizonGws?: number;
  chipPlayEventId?: number;
  /** Chip drafts only: dock template picks by ownership so the squad differs from the crowd. */
  differential?: boolean;
  /** When swaps tie, prefer selling the injured/doubtful player first. Default true server-side. */
  prioritizeInjured?: boolean;
  strategy?: string;
  includeTransfers?: boolean;
  applyTransferCount?: number;
  latestNMatches?: number;
  freeTransfers?: number;
  hitCap?: number;
  panelLimit?: number;
}

export interface SquadParams {
  entryId: number;
  eventId: number;
}

export interface FixturesParams {
  eventId: number;
}

const isFplNextEventSummary = (value: unknown): value is FplNextEventSummary => {
  if (!isRecord(value)) return false;
  if (value.event_id !== null && typeof value.event_id !== "number") return false;
  return true;
};

type UrlTemplateParamValue = string | number | boolean | undefined | null;
type UrlTemplateParams = Record<string, UrlTemplateParamValue>;

export const interpolateUrlTemplate = (template: string, params: UrlTemplateParams): string => {
  return template.replace(/\{([a-zA-Z0-9_]+)\}/g, (_match, key: string) => {
    const value = params[key];
    if (value === undefined || value === null) return "";
    return encodeURIComponent(String(value));
  });
};

const appendMissingQueryParams = (url: string, params: UrlTemplateParams): string => {
  try {
    const base = typeof window !== "undefined" ? window.location.origin : "http://localhost";
    const parsed = new URL(url, base);
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === "") continue;
      if (!parsed.searchParams.has(key)) {
        parsed.searchParams.set(key, String(value));
      }
    }

    const isAbsolute = /^[a-zA-Z][a-zA-Z\d+\-.]*:/.test(url);
    if (isAbsolute) return parsed.toString();
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return url;
  }
};

export const interpolateSquadUrl = (template: string, params: SquadParams): string => {
  const query = { entry_id: params.entryId, event_id: params.eventId };
  const interpolated = interpolateUrlTemplate(template, query);
  return appendMissingQueryParams(interpolated, query);
};

export const interpolateTeamRecommendationUrl = (template: string, params: TeamRecommendationParams): string => {
  const query = {
    entry_id: params.entryId,
    event_id: params.eventId,
    horizon_gws: params.horizonGws,
    chip_strategy: params.chipStrategy,
    chip_horizon_gws: params.chipHorizonGws,
    chip_play_event_id: params.chipPlayEventId,
    differential: params.differential,
    prioritize_injured: params.prioritizeInjured,
    strategy: params.strategy,
    include_transfers: params.includeTransfers,
    apply_transfer_count: params.applyTransferCount,
    latest_n_matches: params.latestNMatches,
    free_transfers: params.freeTransfers,
    hit_cap: params.hitCap,
    panel_limit: params.panelLimit,
  };
  const interpolated = interpolateUrlTemplate(template, query);
  return appendMissingQueryParams(interpolated, query);
};

export const interpolateFixturesUrl = (template: string, params: FixturesParams): string => {
  const query = { event_id: params.eventId };
  const interpolated = interpolateUrlTemplate(template, query);
  return appendMissingQueryParams(interpolated, query);
};

const getEnvString = (key: string): string | undefined => {
  const value = (import.meta.env as Record<string, unknown>)[key];
  return typeof value === "string" && value.length > 0 ? value : undefined;
};

const resolveTemplateWithApiBase = (template: string | undefined): string | undefined => {
  if (!template) return undefined;
  if (!template.startsWith("/")) return template;

  const apiBase = getEnvString("VITE_FPL_API_BASE_URL");
  if (!apiBase) return template;

  try {
    return new URL(template, apiBase).toString();
  } catch {
    return template;
  }
};

// Defaults to the backend's own route so the app works with only
// VITE_FPL_API_BASE_URL set — .env.production defines the base and nothing
// else, and without a default this resolved to undefined, which used to mean
// "silently serve the demo squad".
export const getSquadUrlTemplate = (): string | undefined =>
  resolveTemplateWithApiBase(
    getEnvString("VITE_FPL_SQUAD_URL") ?? "/squad?entry_id={entry_id}&event_id={event_id}",
  );

export const getFixturesUrlTemplate = (): string | undefined =>
  resolveTemplateWithApiBase(getEnvString("VITE_FPL_FIXTURES_URL"));

export const getNextEventUrlTemplate = (): string | undefined =>
  resolveTemplateWithApiBase(getEnvString("VITE_FPL_NEXT_EVENT_URL") ?? "/events/next");

export const getEntryIdentityUrlTemplate = (): string | undefined =>
  resolveTemplateWithApiBase(
    getEnvString("VITE_FPL_ENTRY_IDENTITY_URL") ?? "/entry/identity?entry_id={entry_id}",
  );

export const getRecommendationUrlTemplate = (): string | undefined =>
  resolveTemplateWithApiBase(
    getEnvString("VITE_FPL_RECOMMENDATION_URL") ??
      getEnvString("VITE_FPL_TEAM_RECOMMENDATION_URL") ??
      "/recommendations?entry_id={entry_id}&event_id={event_id}&horizon_gws={horizon_gws}&include_transfers={include_transfers}"
  );

// Backwards-compatible name (older code uses this).
export const getTeamRecommendationUrlTemplate = getRecommendationUrlTemplate;

export const getOptimizeUrlTemplate = (): string | undefined =>
  resolveTemplateWithApiBase(getEnvString("VITE_FPL_OPTIMIZE_URL") ?? "/squad/optimize");

const parseJsonMaybe = (raw: unknown): unknown => {
  if (typeof raw !== "string") return raw;
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return raw;
  }
};

// The diagnostic detail (CORS setup, mixed content, env vars) is for whoever is
// running the app, not the person using it — log it and show a short message.
const formatNetworkHint = (url: string) => {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const protocol = typeof window !== "undefined" ? window.location.protocol : "";
  const isMixedContent = protocol === "https:" && url.startsWith("http://");
  const diagnostic = isMixedContent
    ? `Mixed content: the page is HTTPS but the API URL (${url}) is HTTP. Serve the API over HTTPS.`
    : `Request to ${url} failed before a response. Usually CORS: allow Origin ${origin || "<your-frontend-origin>"} in FPL_API_CORS_ORIGINS, or check VITE_FPL_API_BASE_URL.`;
  if (typeof console !== "undefined") console.warn(diagnostic);
  return "Couldn't reach the server. Check your connection and try again.";
};

const parseJsonResponse = async (response: Response, url: string, endpointLabel: string): Promise<unknown> => {
  const body = await response.text();
  const parsed = parseJsonMaybe(body);
  if (typeof parsed !== "string") return parsed;

  const trimmed = parsed.trim();
  const lower = trimmed.toLowerCase();
  const looksLikeHtml = lower.startsWith("<!doctype") || lower.startsWith("<html");

  if (looksLikeHtml) {
    throw new Error(
      `Expected JSON from ${endpointLabel}, but received HTML. This usually means the request hit the frontend app instead of the backend API. In production set VITE_FPL_API_BASE_URL or use absolute VITE_FPL_*_URL values. URL: ${url}`
    );
  }

  throw new Error(`Invalid JSON from ${endpointLabel}: ${trimmed.slice(0, 240)}`);
};

type FixtureRecord = Record<string, unknown>;

const isFplTeamFixtureRecord = (value: unknown): value is FixtureRecord => {
  if (!isRecord(value)) return false;
  const team = value.team_short ?? value.team;
  const opponent = value.opponent_short ?? value.opponent;
  if (typeof team !== "string" || team.length === 0) return false;
  if (typeof opponent !== "string" || opponent.length === 0) return false;

  const difficulty = value.difficulty ?? value.fdr ?? value.fixture_difficulty;
  if (difficulty !== undefined && typeof difficulty !== "number") return false;

  const isHome = value.is_home ?? value.isHome ?? value.home;
  if (isHome !== undefined && typeof isHome !== "boolean") return false;

  return true;
};

const normalizeTeamFixture = (value: FixtureRecord): FplTeamFixture => {
  const difficultyRaw = value.difficulty ?? value.fdr ?? value.fixture_difficulty;
  const isHomeRaw = value.is_home ?? value.isHome ?? value.home;

  return {
    team_short: String((value.team_short ?? value.team) as string),
    opponent_short: String((value.opponent_short ?? value.opponent) as string),
    difficulty: typeof difficultyRaw === "number" ? difficultyRaw : undefined,
    is_home: typeof isHomeRaw === "boolean" ? isHomeRaw : undefined,
  };
};

export const fetchSquad = async (params: SquadParams, signal?: AbortSignal): Promise<FplSquad> => {
  const template = getSquadUrlTemplate();
  // Returning SAMPLE_SQUAD here used to make a misconfigured deployment look
  // like a working one: this function also validates the entry ID during
  // onboarding, so any ID was accepted and demo players rendered as the
  // user's real squad. Fail loudly instead.
  if (!template) {
    throw new Error(
      "The app is not configured to reach the FPL API (VITE_FPL_SQUAD_URL is unset).",
    );
  }

  const url = interpolateSquadUrl(template, params);
  let response: Response;
  try {
    response = await authFetch(url, { signal });
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    if (typeof err === "object" && err !== null && "name" in err && err.name === "AbortError") throw err;

    const hint = formatNetworkHint(url);
    const message = err instanceof Error ? err.message : String(err);
    throw new Error(`Network error fetching squad. ${hint} (${message})`);
  }

  if (!response.ok) {
    let details = "";
    try {
      details = await response.text();
    } catch {
      details = "";
    }
    const trimmed = details.trim();
    const suffix = trimmed ? `: ${trimmed.slice(0, 300)}` : "";
    throw new Error(`Failed to fetch squad (${response.status})${suffix}`);
  }

  const data = await parseJsonResponse(response, url, "squad endpoint");
  if (!isFplSquad(data)) {
    throw new Error("Invalid squad response");
  }

  return data;
};

export const fetchFixtures = async (params: FixturesParams, signal?: AbortSignal): Promise<FplTeamFixture[]> => {
  const template = getFixturesUrlTemplate();
  if (!template) return [];

  const url = interpolateFixturesUrl(template, params);
  let response: Response;
  try {
    response = await authFetch(url, { signal });
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    if (typeof err === "object" && err !== null && "name" in err && err.name === "AbortError") throw err;

    const hint = formatNetworkHint(url);
    const message = err instanceof Error ? err.message : String(err);
    throw new Error(`Network error fetching fixtures. ${hint} (${message})`);
  }

  if (!response.ok) {
    let details = "";
    try {
      details = await response.text();
    } catch {
      details = "";
    }
    const trimmed = details.trim();
    const suffix = trimmed ? `: ${trimmed.slice(0, 300)}` : "";
    throw new Error(`Failed to fetch fixtures (${response.status})${suffix}`);
  }

  const data: unknown = await parseJsonResponse(response, url, "fixtures endpoint");
  const fixturesRaw = Array.isArray(data)
    ? data
    : isRecord(data) && Array.isArray(data.fixtures)
      ? data.fixtures
      : undefined;

  if (!fixturesRaw) {
    throw new Error("Invalid fixtures response");
  }

  const fixtures: FplTeamFixture[] = fixturesRaw
    .filter(isFplTeamFixtureRecord)
    .map((fixture) => normalizeTeamFixture(fixture));

  return fixtures;
};

export const fetchNextEvent = async (signal?: AbortSignal): Promise<FplNextEventSummary> => {
  const template = getNextEventUrlTemplate();
  // Same reasoning as fetchSquad: a demo gameweek number silently standing in
  // for the real one is worse than an explicit configuration error.
  if (!template) {
    throw new Error(
      "The app is not configured to reach the FPL API (VITE_FPL_API_BASE_URL is unset).",
    );
  }

  let response: Response;
  try {
    response = await authFetch(template, { signal });
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    if (typeof err === "object" && err !== null && "name" in err && err.name === "AbortError") throw err;

    const hint = formatNetworkHint(template);
    const message = err instanceof Error ? err.message : String(err);
    throw new Error(`Network error fetching next event. ${hint} (${message})`);
  }

  if (!response.ok) {
    let details = "";
    try {
      details = await response.text();
    } catch {
      details = "";
    }
    const trimmed = details.trim();
    const suffix = trimmed ? `: ${trimmed.slice(0, 300)}` : "";
    throw new Error(`Failed to fetch next event (${response.status})${suffix}`);
  }

  const data: unknown = await parseJsonResponse(response, template, "next event endpoint");
  if (!isFplNextEventSummary(data)) {
    throw new Error("Invalid next event response");
  }

  return data;
};

export const fetchTeamRecommendation = async (
  params: TeamRecommendationParams,
  signal?: AbortSignal
): Promise<FplTeamRecommendation> => {
  const template = getRecommendationUrlTemplate();
  if (!template) return SAMPLE_TEAM_RECOMMENDATION;

  const url = interpolateTeamRecommendationUrl(template, params);
  let response: Response;
  try {
    response = await authFetch(url, { signal });
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    if (typeof err === "object" && err !== null && "name" in err && err.name === "AbortError") throw err;

    const hint = formatNetworkHint(url);
    const message = err instanceof Error ? err.message : String(err);
    throw new Error(`Network error fetching team recommendation. ${hint} (${message})`);
  }
  if (!response.ok) {
    let details = "";
    try {
      details = await response.text();
    } catch {
      details = "";
    }
    const trimmed = details.trim();
    const suffix = trimmed ? `: ${trimmed.slice(0, 300)}` : "";
    throw new Error(`Failed to fetch team recommendation (${response.status})${suffix}`);
  }

  const data: unknown = await parseJsonResponse(response, url, "team recommendation endpoint");

  if (!isFplTeamRecommendation(data)) {
    throw new Error("Invalid team recommendation response");
  }

  return data;
};

// ============================================================================
// Phase 1 — /explain (LLM rationale for recommendations)
// Phase 2 — /league/list and /league/strategy (mini-league strategy)
// ============================================================================

export type ExplainTransfer = {
  out_id: number | null;
  in_id: number | null;
  rationale: string;
};

export type ExplainResponse = {
  transfers: ExplainTransfer[];
  captain: { player_id: number | null; rationale: string | null };
  chip: { name: string | null; rationale: string | null };
  model?: string;
  cached?: boolean;
  error?: string;
};

export const fetchExplanation = async (
  recommendations: unknown,
  signal?: AbortSignal
): Promise<ExplainResponse> => {
  const apiBase = getEnvString("VITE_FPL_API_BASE_URL") ?? "";
  const url = apiBase ? new URL("/explain", apiBase).toString() : "/explain";
  const response = await authFetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ recommendations }),
    signal,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Failed to fetch explanation (${response.status}): ${body.slice(0, 200)}`);
  }
  return (await response.json()) as ExplainResponse;
};

/* ── Chat (Orchestrator agent) ───────────────────────────────────────────── */

export type ChatRequest = {
  entry_id: number;
  message: string;
  current_gw?: number;
  chips_remaining?: string[];
};

export type ChatResponse = {
  answer: string;
  current_gw: number;
  latency_ms: number;
};

export const fetchChatAnswer = async (
  req: ChatRequest,
  signal?: AbortSignal
): Promise<ChatResponse> => {
  const apiBase = getEnvString("VITE_FPL_API_BASE_URL") ?? "";
  const url = apiBase ? new URL("/chat", apiBase).toString() : "/chat";
  const response = await authFetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
    signal,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Chat request failed (${response.status}): ${body.slice(0, 200)}`);
  }
  return (await response.json()) as ChatResponse;
};

/* ── Fast specialist endpoints (skip orchestrator) ───────────────────────── */

export type SpecialistRequest = {
  entry_id: number;
  current_gw?: number;
  chips_remaining?: string[];
};

export type Specialist = "captain" | "transfer" | "chip";

export const fetchSpecialistAnswer = async (
  specialist: Specialist,
  req: SpecialistRequest,
  signal?: AbortSignal
): Promise<ChatResponse> => {
  const apiBase = getEnvString("VITE_FPL_API_BASE_URL") ?? "";
  const path = `/chat/${specialist}`;
  const url = apiBase ? new URL(path, apiBase).toString() : path;
  const response = await authFetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
    signal,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Specialist request failed (${response.status}): ${body.slice(0, 200)}`);
  }
  return (await response.json()) as ChatResponse;
};

export type LeagueSummary = {
  id: number;
  name: string;
  entry_rank: number | null;
  entry_last_rank: number | null;
  league_type?: string | null;
  scoring?: string | null;
  size?: number | null;
};

export const fetchUserLeagues = async (
  entryId: number,
  signal?: AbortSignal
): Promise<{ entry_id: number; leagues: LeagueSummary[] }> => {
  const apiBase = getEnvString("VITE_FPL_API_BASE_URL") ?? "";
  const path = `/league/list?entry_id=${encodeURIComponent(entryId)}`;
  const url = apiBase ? new URL(path, apiBase).toString() : path;
  const response = await authFetch(url, { signal });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Failed to fetch leagues (${response.status}): ${body.slice(0, 200)}`);
  }
  return (await response.json()) as { entry_id: number; leagues: LeagueSummary[] };
};

/* ── Chip plan (chip timing recommendations) ─────────────────────────────── */

export type ChipName = "wildcard" | "free_hit" | "bench_boost" | "triple_captain";

export const CHIP_LABELS: Record<ChipName, string> = {
  wildcard: "Wildcard",
  free_hit: "Free Hit",
  bench_boost: "Bench Boost",
  triple_captain: "Triple Captain",
};

export type ChipWindow = {
  name: ChipName;
  available: boolean;
  half: 1 | 2;
  expires_gw: number;
};

export type ChipEvPoint = {
  gw: number;
  ev: number;
  p_beats_bar?: number; // TC/BB: P(the chip's extra points clear that GW's bar)
  p_return?: number; // TC/BB: P(captain / bench sum >= the "return" threshold)
  european?: number; // squad players in European weeks around this GW
  post_break?: boolean; // first GW after an international break
};

/** Shape behind a TC/BB EV: the chip's extra-points distribution for its best GW. */
export type ChipDistribution = {
  mean: number;
  modal: number; // single most likely score
  // Per-PLAYER thresholds — triple captain only. A bench-4 sum clears 6 and 10
  // nearly every week, so the backend omits these three for bench boost.
  p_return?: number; // P(>= CHIP_PLAN_DIST_RETURN_AT, 6 by default)
  p_haul?: number; // P(>= 10)
  p_blank?: number; // P(<= 2)
  p80_low: number;
  p80_high: number;
  p80_open?: boolean; // band runs off the pmf axis: read p80_high as "or more"
  bar?: number;
  p_beats_bar?: number; // P(extra points >= bar), measured on the pmf's own axis
};

export type ChipPlanRecommendation = {
  chip: ChipName;
  event_id: number;
  ev_gain: number | null; // null on provisional (structural-zone) recommendations
  provisional: boolean;
  likelihood?: number; // provisional only: 1.0 announced, <1 expected (e.g. FA Cup clash)
  reasons: string[];
  ev_curve: ChipEvPoint[];
  haul_prob?: number; // triple_captain only: P(captain gets 2+ goal involvements)
  distribution?: ChipDistribution; // TC/BB only, when the backend has player priors
  guidance?: string; // plain-language "play it" sentence (older backends omit it)
};

export type ChipNudge = {
  chip: ChipName;
  event_id: number;
  ev_gain: number;
  wait_for_team_news?: boolean;
  p_beats_bar?: number;
};

export type ChipOutlookRow = {
  chip: ChipName;
  event_id: number | null; // null: no candidate window in the model horizon
  ev_gain: number | null;
  bar: number; // the min-EV threshold the window must clear
  status: "play" | "hold";
  reasons: string[];
  distribution?: ChipDistribution;
  guidance?: string; // plain-language "why hold / why play" sentence with a season prior (older backends omit it)
};

export type EuropeanCompetition = "ucl" | "uel" | "uecl";

export const EUROPEAN_LABELS: Record<EuropeanCompetition, string> = {
  ucl: "UCL",
  uel: "UEL",
  uecl: "UECL",
};

export type ChipCalendarRow = {
  gw: number;
  deadline_utc: string | null;
  in_model_zone: boolean;
  post_break: boolean;
  break_gap_days: number | null;
  european: Partial<Record<EuropeanCompetition, string[]>>; // competition -> team labels
  squad_european: { name: string; team: string; competition: EuropeanCompetition; when: "before" | "after" | "both" }[];
  n_teams_playing: number | null; // null: fixtures not known that far out
  dgw_teams: (string | number)[];
  blank_teams: (string | number)[];
  is_blank_heavy: boolean;
  has_dgw: boolean;
  cup_clash: { competition: string; label: string; likely_blank: boolean } | null;
};

export type ChipPlanSignals = {
  breaks: boolean;
  european_calendar: boolean; // false: data/models/european_calendar.json has no teams configured
  cup_calendar: boolean;
  distributions: boolean;
  european_xpts_mult: number | null;
};

export type ChipPlanResponse = {
  entry_id: number;
  current_gw: number;
  chips_remaining: ChipWindow[];
  horizon_model_gws: number;
  recommendations: ChipPlanRecommendation[];
  outlook?: ChipOutlookRow[]; // one row per available chip, hold rows included
  nudge: ChipNudge | null;
  calendar?: ChipCalendarRow[]; // one row per upcoming GW (older backends omit it)
  signals?: ChipPlanSignals;
  transfer_context: {
    planned_transfers_net_gain: number;
    wc_alternative_gw: number | null;
  };
};

export const fetchChipPlan = async (
  entryId: number,
  horizon?: number,
  signal?: AbortSignal
): Promise<ChipPlanResponse> => {
  const apiBase = getEnvString("VITE_FPL_API_BASE_URL") ?? "";
  const params = new URLSearchParams({ entry_id: String(entryId) });
  if (horizon) params.set("horizon", String(horizon));
  const path = `/chips/plan?${params.toString()}`;
  const url = apiBase ? new URL(path, apiBase).toString() : path;
  const response = await authFetch(url, { signal });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Failed to fetch chip plan (${response.status}): ${body.slice(0, 200)}`);
  }
  return (await response.json()) as ChipPlanResponse;
};

export type LeagueStrategyMode = "chase" | "defend" | "differential";

export type LeagueRivalEntry = {
  entry_id: number;
  player_name: string | null;
  entry_name: string | null;
  rank: number | null;
  last_rank: number | null;
  total: number | null;
  event_total: number | null;
};

export type LeagueStrategyCandidate = {
  id: number;
  web_name: string | null;
  team_short: string | null;
  position_id: number | null;
  now_cost: number | null;
  selected_by_percent: string | null;
  ep_next: string | number | null;
  form: string | null;
  model_xpts_horizon: number | null;
  model_xpts_per_gw: Record<string, number> | null;
  league_ownership: number | null;
  differential_ev?: number | null;
  template_xpts?: number | null;
};

export type LeagueCaptainDifferentialPlayer = {
  id: number;
  web_name: string | null;
  team_short: string | null;
  league_ownership: number | null;
  model_xpts_horizon: number | null;
  fixture_run_band?: string | null;
  differential_ev?: number | null;
};

export type LeagueCaptainDifferential = {
  consensus_captain: LeagueCaptainDifferentialPlayer;
  alternative: LeagueCaptainDifferentialPlayer;
  reason: string;
};

export type LeagueStrategyNarrative = {
  headline?: string;
  key_gap?: string;
  recommended_targets?: Array<{ player_id: number; name?: string; rationale: string }>;
  watchouts?: string;
  model?: string;
  error?: string;
};

export type LeagueStrategyResponse = {
  mode: LeagueStrategyMode;
  league: { id: number; name: string };
  user: LeagueRivalEntry;
  rivals_above: LeagueRivalEntry[];
  rivals_below: LeagueRivalEntry[];
  differentials_count: {
    owned_by_me_not_rivals: number;
    owned_by_rivals_not_me: number;
    shared: number;
  };
  candidates: LeagueStrategyCandidate[];
  narrative: LeagueStrategyNarrative;
  captain_differential?: LeagueCaptainDifferential | null;
  projection_horizon_gws?: number;
  projection_error?: string;
  error?: string;
};

export const fetchLeagueStrategy = async (
  params: { entry_id: number; league_id: number; mode: LeagueStrategyMode; event_id?: number; horizon_gws?: number },
  signal?: AbortSignal
): Promise<LeagueStrategyResponse> => {
  const apiBase = getEnvString("VITE_FPL_API_BASE_URL") ?? "";
  const url = apiBase ? new URL("/league/strategy", apiBase).toString() : "/league/strategy";
  const response = await authFetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
    signal,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Failed to fetch league strategy (${response.status}): ${body.slice(0, 200)}`);
  }
  return (await response.json()) as LeagueStrategyResponse;
};

/* ── Fixture difficulty ticker (xG model) ────────────────────────────────── */

export type FixtureDifficultyBand = "very_easy" | "easy" | "medium" | "hard" | "very_hard";

export type FixtureTickerOpponent = {
  opp_id: number;
  opp_short: string;
  home: boolean;
  difficulty: number;
  band: FixtureDifficultyBand;
  color: string;
};

export type FixtureTickerCell = {
  opponents: FixtureTickerOpponent[];
  difficulty: number | null;
  count: number;
  blank: boolean;
};

export type FixtureTickerTeam = {
  team_id: number;
  team_short: string;
  avg_difficulty: number;
  sum_difficulty: number;
  n_fixtures: number;
  band: FixtureDifficultyBand;
  color: string;
  gws: Record<string, FixtureTickerCell>;
};

export type FixtureDifficultyResponse = {
  gw_start: number;
  horizon_gws: number;
  gws: number[];
  teams: FixtureTickerTeam[];
  easiest_runs: string[];
  hardest_runs: string[];
  meta?: {
    model?: string;
    rating_sources?: Record<string, number>;
    league_avg_xg?: number;
    knowledge_as_of?: string | null;
    generated_at_utc?: string;
  };
  error?: string;
};

export const fetchFixtureDifficulty = async (
  params: { gw_start?: number; horizon_gws?: number },
  signal?: AbortSignal
): Promise<FixtureDifficultyResponse> => {
  const apiBase = getEnvString("VITE_FPL_API_BASE_URL") ?? "";
  const search = new URLSearchParams();
  if (params.gw_start) search.set("gw_start", String(params.gw_start));
  if (params.horizon_gws) search.set("horizon_gws", String(params.horizon_gws));
  const path = `/fixtures/difficulty${search.size ? `?${search.toString()}` : ""}`;
  const url = apiBase ? new URL(path, apiBase).toString() : path;
  const response = await authFetch(url, { signal });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Failed to fetch fixture difficulty (${response.status}): ${body.slice(0, 200)}`);
  }
  return (await response.json()) as FixtureDifficultyResponse;
};

/* ── Squad optimizer (pre-first-deadline free swaps) ──────────────────────────
 * POST /squad/optimize — "improve my team" before the first deadline: applies all
 * beneficial FREE swaps (unlimited transfers, no hits). `min_gain` is the
 * aggressiveness dial (higher = fewer, higher-conviction swaps). `apply:false`
 * previews only; `apply:true` persists the optimized squad server-side.
 */

export interface OptimizeSquadRequest {
  entry_id: number;
  horizon_gws?: number;
  min_gain?: number;
  max_swaps?: number | null;
  apply?: boolean;
}

export interface OptimizeSquadPlayer {
  id: number;
  name: string;
  pos: FplPosition;
  team: string;
  price: number;
  xpts_horizon: number;
}

export interface OptimizeSquadSwap {
  position: FplPosition;
  out: OptimizeSquadPlayer;
  in: OptimizeSquadPlayer;
}

export interface OptimizeSquadResponse {
  entry_id: number;
  horizon_gws: number;
  min_gain: number;
  max_swaps: number | null;
  rounds: number;
  num_swaps: number;
  swaps: OptimizeSquadSwap[];
  xpts_before: number;
  xpts_after: number;
  total_gain: number;
  remaining_itb: number;
  optimized_player_ids: number[];
  suggested_captain_id: number;
  suggested_vice_id: number;
  applied: boolean;
}

const isOptimizeSquadResponse = (value: unknown): value is OptimizeSquadResponse => {
  if (!isRecord(value)) return false;
  if (typeof value.entry_id !== "number") return false;
  if (typeof value.num_swaps !== "number") return false;
  if (!Array.isArray(value.swaps)) return false;
  if (typeof value.xpts_before !== "number") return false;
  if (typeof value.xpts_after !== "number") return false;
  if (typeof value.total_gain !== "number") return false;
  if (typeof value.applied !== "boolean") return false;
  return true;
};

export const optimizeSquad = async (
  params: OptimizeSquadRequest,
  signal?: AbortSignal
): Promise<OptimizeSquadResponse> => {
  const url = getOptimizeUrlTemplate() ?? "/squad/optimize";
  const response = await authFetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
    signal,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Failed to optimize squad (${response.status}): ${body.slice(0, 200)}`);
  }

  const data: unknown = await parseJsonResponse(response, url, "optimize endpoint");
  if (!isOptimizeSquadResponse(data)) {
    throw new Error("Invalid optimize squad response");
  }
  return data;
};


export const isFplEntryIdentity = (value: unknown): value is FplEntryIdentity => {
  if (typeof value !== "object" || value === null) return false;
  return typeof (value as FplEntryIdentity).entry_id === "number";
};

/**
 * Look up who an entry id belongs to, before linking it.
 *
 * Proxied through our backend rather than called directly: FPL sends no CORS
 * header for our origin, so a browser fetch to fantasy.premierleague.com is
 * blocked outright.
 */
export const fetchEntryIdentity = async (
  entryId: number,
  signal?: AbortSignal,
): Promise<FplEntryIdentity> => {
  const template = getEntryIdentityUrlTemplate();
  if (!template) {
    throw new Error(
      "The app is not configured to reach the FPL API (VITE_FPL_API_BASE_URL is unset).",
    );
  }
  const url = template.replace("{entry_id}", String(entryId));

  let response: Response;
  try {
    response = await authFetch(url, { signal });
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    if (typeof err === "object" && err !== null && "name" in err && err.name === "AbortError") throw err;
    const message = err instanceof Error ? err.message : String(err);
    throw new Error(`Network error checking that team ID. ${formatNetworkHint(url)} (${message})`);
  }

  if (response.status === 404) {
    throw new Error(`No FPL team found with ID ${entryId}. Check the number and try again.`);
  }
  if (!response.ok) {
    throw new Error(`Could not check that team ID (${response.status}).`);
  }

  const data: unknown = await parseJsonResponse(response, url, "entry identity endpoint");
  if (!isFplEntryIdentity(data)) {
    throw new Error("Invalid entry identity response");
  }
  return data;
};
