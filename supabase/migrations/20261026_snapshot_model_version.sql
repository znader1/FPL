-- Model version + shadow projection on the weekly snapshot (2026-10-26 calibration spec, part 6).
-- Apply in the Supabase dashboard SQL editor (project tetvymwgpaordnmsnneo) BEFORE merging the
-- code that writes these columns: PostgREST rejects unknown columns, which would fail the
-- live snapshot job.
alter table public.player_gw_snapshots
  add column if not exists model_version text,
  add column if not exists shadow_model_version text,
  add column if not exists shadow_xpts numeric(7,3),
  add column if not exists runner_xpts numeric(7,3);
