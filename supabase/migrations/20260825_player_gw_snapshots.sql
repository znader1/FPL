-- Weekly FPL database: per-player pre-deadline snapshots + post-GW actuals.
-- Applied manually via the Supabase dashboard SQL editor (project tetvymwgpaordnmsnneo);
-- kept here as the record. See docs/superpowers/specs/2026-08-25-weekly-db-design.md.

create table public.player_gw_snapshots (
  season text not null,
  gw smallint not null,
  player_id integer not null,
  web_name text,
  pos text,
  team_short text,
  price_m numeric(5,1),
  ownership_pct numeric(5,2),
  status text,
  chance smallint,
  fpl_ep_next numeric(6,2),
  model_xpts numeric(7,3),
  model_blend_weight numeric(4,2),
  captured_at timestamptz not null default now(),
  actual_points smallint,
  actual_minutes smallint,
  actuals_captured_at timestamptz,
  primary key (season, gw, player_id)
);

-- Service-role writes only; a read policy ships with gems v2.
alter table public.player_gw_snapshots enable row level security;
