"""The monitoring tables are owner-only: RLS on, one select policy each, nothing else."""
import pathlib
import re

SQL = pathlib.Path("supabase/migrations/20261106_monitoring_tables.sql")
TABLES = ["monitor_owners", "expert_picks", "advice_snapshots", "entry_gw_actuals", "monitor_reports"]


def _sql():
    # Comments explain the manual steps; policies are asserted on statements only.
    return "\n".join(
        line for line in SQL.read_text().lower().splitlines() if not line.strip().startswith("--")
    )


def test_every_table_has_rls_and_an_owner_only_select_policy():
    sql = _sql()
    for t in TABLES:
        assert f"create table if not exists public.{t}" in sql
        assert f"alter table public.{t} enable row level security" in sql
        assert re.search(rf"create policy [^;]+ on public\.{t}\s+for select[^;]+auth\.uid\(\)", sql)
    assert "for insert" not in sql and "for update" not in sql and "for delete" not in sql
    assert "for all" not in sql
    assert " anon" not in sql


def test_data_tables_are_readable_only_through_the_owner_list():
    sql = _sql()
    for t in TABLES[1:]:
        policy = re.search(rf"create policy [^;]+ on public\.{t}\s+for select[^;]+;", sql).group(0)
        assert "public.monitor_owners" in policy


def test_config_headline_preset_is_a_real_preset():
    from src import config
    assert config.MONITOR_WILDCARD_HEADLINE_PRESET in config.CHIP_WILDCARD_PRESET_ORDER
    assert config.MONITOR_TRANSFER_VERDICT_WINDOW_GWS in config.MONITOR_WINDOWS_GWS
    assert config.MONITOR_WILDCARD_WINDOW_GWS in config.MONITOR_WINDOWS_GWS


def test_the_migration_can_be_run_twice():
    # Applied by hand in the dashboard: a second run after a half-finished first one
    # must not stop on "policy already exists".
    sql = _sql()
    for name, table in re.findall(r"create policy (\w+) on public\.(\w+)", sql):
        assert f"drop policy if exists {name} on public.{table};" in sql
    assert len(re.findall(r"create policy", sql)) == len(TABLES)
