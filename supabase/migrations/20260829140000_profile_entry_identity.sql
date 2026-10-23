-- FPL reissues entry ids each season, so a stored entry_id silently resolves to
-- a different manager after the August rollover and the app renders a stranger's
-- squad with no error. Snapshot who the id belonged to at link time so the
-- rollover can be detected on load.
alter table public.profiles
  add column if not exists manager_name text,
  add column if not exists team_name text,
  -- The strongest signal: joined_time changes when FPL hands the id to a new
  -- manager, where renaming a team does not.
  add column if not exists entry_joined_time timestamptz,
  add column if not exists entry_linked_at timestamptz;

comment on column public.profiles.entry_joined_time is
  'FPL entry joined_time captured at link time; a change means the id was reissued.';

-- RLS is unchanged: these are user-writable exactly like entry_id. `plan` stays
-- server-only and must not be widened here.
