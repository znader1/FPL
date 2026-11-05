-- Monitoring dashboard tables (spec docs/superpowers/specs/2026-11-05-monitoring-dashboard-design.md, 7.2).
-- Apply in the Supabase dashboard SQL editor (project tetvymwgpaordnmsnneo) BEFORE running
-- scripts/monitor_backfill.py against the database: PostgREST rejects unknown tables.
--
-- Then make yourself the owner, once, by hand (your id is under Authentication > Users):
--   insert into public.monitor_owners (user_id) values ('<your auth.users id>');
--
-- Access model: the service role writes (it bypasses row-level security). A signed-in user can
-- read a row only when their user id is in monitor_owners. No one else gets a policy, so every
-- other user reads nothing.

create table if not exists public.monitor_owners (
  user_id uuid primary key
);

create table if not exists public.expert_picks (
  season text not null,
  gw int not null,
  source text not null,
  series text not null,
  article_id bigint,
  url text,
  title text,
  published_at timestamptz,
  fetched_at timestamptz,
  captain_player_id int,
  vice_player_id int,
  captain_stated boolean,
  captain_inferred_player_id int,
  players jsonb,
  unmatched jsonb,
  needs_review boolean,
  review_reason text,
  primary key (season, gw, source, series)
);

create table if not exists public.advice_snapshots (
  season text not null,
  gw int not null,
  entry_id bigint not null,
  kind text not null,
  origin text not null,
  model_version text,
  payload jsonb,
  captured_at timestamptz,
  primary key (season, gw, entry_id, kind, origin)
);

create table if not exists public.entry_gw_actuals (
  season text not null,
  gw int not null,
  entry_id bigint not null,
  picks jsonb,
  transfers jsonb,
  chip text,
  points int,
  points_on_bench int,
  transfer_cost int,
  bank_m numeric(6,1),
  value_m numeric(6,1),
  captured_at timestamptz,
  primary key (season, gw, entry_id)
);

create table if not exists public.monitor_reports (
  season text not null,
  gw int not null,
  entry_id bigint not null,
  report jsonb,
  built_at timestamptz,
  code_version text,
  primary key (season, gw, entry_id)
);

alter table public.monitor_owners enable row level security;
alter table public.expert_picks enable row level security;
alter table public.advice_snapshots enable row level security;
alter table public.entry_gw_actuals enable row level security;
alter table public.monitor_reports enable row level security;

create policy monitor_owners_read_self on public.monitor_owners
  for select to authenticated using (user_id = auth.uid());

create policy expert_picks_owner_read on public.expert_picks
  for select to authenticated using (auth.uid() in (select user_id from public.monitor_owners));

create policy advice_snapshots_owner_read on public.advice_snapshots
  for select to authenticated using (auth.uid() in (select user_id from public.monitor_owners));

create policy entry_gw_actuals_owner_read on public.entry_gw_actuals
  for select to authenticated using (auth.uid() in (select user_id from public.monitor_owners));

create policy monitor_reports_owner_read on public.monitor_reports
  for select to authenticated using (auth.uid() in (select user_id from public.monitor_owners));
