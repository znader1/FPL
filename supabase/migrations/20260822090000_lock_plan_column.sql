-- Stop users from promoting their own plan tier.
--
-- The original UPDATE policy scopes rows (auth.uid() = id) but not columns, so
-- a signed-in user can run
--   supabase.from('profiles').update({ plan: 'elite' })
-- from the browser console with the public anon key and grant themselves a paid
-- tier. Harmless while BETA_ALL_ACCESS gives everyone full access; a revenue
-- hole the moment billing is switched on.
--
-- Postgres RLS has no column-level WITH CHECK, so the guard compares the
-- submitted plan against the stored one and rejects any change. Writes to plan
-- must come from a trusted context (a Stripe webhook using the service role,
-- which bypasses RLS).

drop policy if exists "Users can update own profile" on public.profiles;

create policy "Users can update own profile"
  on public.profiles for update
  using (auth.uid() = id)
  with check (
    auth.uid() = id
    and plan = (select p.plan from public.profiles p where p.id = auth.uid())
  );

-- Same reasoning on insert: the row is created by the handle_new_user trigger
-- (security definer, so it is exempt), and any client-side insert must take the
-- 'free' default rather than naming its own tier.
drop policy if exists "Users can insert own profile" on public.profiles;

create policy "Users can insert own profile"
  on public.profiles for insert
  with check (auth.uid() = id and plan = 'free');
