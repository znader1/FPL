import pytest

from src import config, projections


def _load_real_inputs():
    """Assemble (elements_df, fixtures, teams_short, gw) from the live FPL API.
    Returns None if anything is unavailable (offline / rate-limited)."""
    try:
        from src import fpl_client, transforms
        bootstrap = fpl_client.get_bootstrap()
        fixtures = transforms.fixtures_df(fpl_client.get_fixtures())
        elements_df, teams_df, _ = transforms.tables_from_bootstrap(bootstrap)
        teams_short = teams_df.set_index("id")["short_name"].to_dict()
        events = bootstrap.get("events", []) or []
        gw = next((e["id"] for e in events if e.get("is_next")), None)
        if gw is None:
            gw = next((e["id"] for e in events if not e.get("finished")), 1)
        return elements_df, fixtures, teams_short, int(gw)
    except Exception:
        return None


def test_flag_off_adds_no_columns_flag_on_discounts(monkeypatch):
    data = _load_real_inputs()
    if data is None:
        pytest.skip("no live FPL data available")
    elements_df, fixtures, teams_short, gw = data

    monkeypatch.setattr(config, "PROJ_APPLY_MINUTES_MODEL", False, raising=False)
    off = projections.project_elements_next_gws(
        elements_df, fixtures, teams_short, gw_start=gw, horizon_gws=3
    )
    assert not any(c.startswith("minutes_mult_gw") for c in off.columns)
    assert "prob_start" not in off.columns

    monkeypatch.setattr(config, "PROJ_APPLY_MINUTES_MODEL", True, raising=False)
    on = projections.project_elements_next_gws(
        elements_df, fixtures, teams_short, gw_start=gw, horizon_gws=3
    )
    assert any(c.startswith("minutes_mult_gw") for c in on.columns)
    assert "prob_start" in on.columns
    # Relative discount only lowers totals — never raises them.
    assert on["xpts_horizon"].sum() <= off["xpts_horizon"].sum() + 1e-6
    # At least one player is genuinely discounted.
    mult_cols = [c for c in on.columns if c.startswith("minutes_mult_gw")]
    assert (on[mult_cols].min().min()) < 1.0
