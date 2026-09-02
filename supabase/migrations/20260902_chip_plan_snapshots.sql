-- Chip-plan snapshots: pre-deadline chip timing recommendations + post-GW chip actuals.
-- Applied manually via the Supabase dashboard SQL editor, same procedure as
-- 20260825_player_gw_snapshots.sql. See docs/superpowers/sdd/2026-09-01-chip-planner-backend/.

create table if not exists public.chip_plan_snapshots (
  season text not null,
  gw int not null,
  entry_id bigint not null,
  chips_remaining jsonb,
  recommendations jsonb,
  ev_curves jsonb,
  transfer_context jsonb,
  model_meta jsonb,
  captured_at timestamptz,
  chip_played text,
  actual_points int,
  realized_chip_ev jsonb,
  actuals_captured_at timestamptz,
  primary key (season, gw, entry_id)
);

alter table public.chip_plan_snapshots enable row level security;
-- service-role writes only (no anon policies), same posture as player_gw_snapshots
