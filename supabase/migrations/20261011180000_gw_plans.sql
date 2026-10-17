-- The GW plan (XI, bench order, transfer/captain/chip choices, saved flag)
-- lived only in localStorage, so it was per browser: a plan saved in one
-- in-app browser was gone in Safari, and gone again on a laptop. One row per
-- user + FPL entry + deadline GW makes it follow the login; localStorage
-- stays as the offline cache and the newer updated_at wins on merge.
create table public.gw_plans (
  user_id uuid not null references auth.users (id) on delete cascade,
  entry_id bigint not null,
  gw integer not null,
  plan jsonb not null,
  base jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (user_id, entry_id, gw)
);

comment on table public.gw_plans is
  'Client-authored GW plan per user/entry/deadline GW; plan and base are GwPlan JSON (src/lib/gwPlan.ts).';

alter table public.gw_plans enable row level security;

create policy "Users can read own gw plans"
  on public.gw_plans for select
  using (auth.uid() = user_id);

create policy "Users can insert own gw plans"
  on public.gw_plans for insert
  with check (auth.uid() = user_id);

create policy "Users can update own gw plans"
  on public.gw_plans for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "Users can delete own gw plans"
  on public.gw_plans for delete
  using (auth.uid() = user_id);
