# Supabase (one project for the app and the backend jobs)

Project `tetvymwgpaordnmsnneo`. The frontend's tables (`profiles`, `gw_plans`) and the backend's (`player_gw_snapshots`, `chip_plan_snapshots`) live in the same database.

Migrations here are applied **by hand** in the dashboard SQL editor. The remote migration history only records `gw_plans` (as `20261011172539`). Never run `supabase db push` without first reconciling `supabase_migrations.schema_migrations`, or it will try to re-apply tables that already exist.
