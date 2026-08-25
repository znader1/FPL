import pandas as pd
import pytest

from src import config, minutes_model, projections


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


def test_flag_wiring_offline_deterministic(monkeypatch):
    """
    Offline, deterministic counterpart to the live-API test above.

    Fabricates a minimal (elements, fixtures) pair that
    ``transforms.annotate_elements_with_gw_fixtures`` accepts directly, and
    monkeypatches ``minutes_model.load_minutes_history`` /
    ``minutes_model.minutes_projection`` so the rotation multiplier is fully
    controlled — no network call, no dependency on real history CSVs.

    Real fabricated fixtures (not a monkeypatched ``annotate_elements_with_gw_fixtures``)
    turned out to work cleanly: two players on the same team, with one home
    fixture per GW at neutral (D3) difficulty, keeps every context multiplier
    (difficulty/home-away/opp-form/team-form) at an easily-reasoned-about
    constant (home_away_mult=1.06, everything else 1.0) across all 3 GWs.

    Both fabricated players are fully "fit" (``chance_of_playing_next_round`` is
    NaN, mocked ``availability`` is 1.0), so the flag-off legacy ``play_prob`` /
    ``future_play_prob`` is exactly 1.0 for every GW in the horizon. That makes
    flag-off ``xpts`` equal the undiscounted base xpts, so
    ``xpts_on == xpts_off * minutes_mult`` must hold EXACTLY (within float
    tolerance) if the multiplier is applied exactly once. A double-discount bug
    would instead produce ``xpts_off * minutes_mult ** 2``, which this assertion
    would catch.
    """
    gw_start = 10
    nailed_id, rotation_id = 900001, 900002
    fit_team, opp_team = 1, 2

    elements = pd.DataFrame(
        [
            {
                "id": nailed_id,
                "team": fit_team,
                "web_name": "Nailed",
                "status": "a",
                "chance_of_playing_next_round": float("nan"),
                "form": 5.0,
                "points_per_game": 5.0,
            },
            {
                "id": rotation_id,
                "team": fit_team,
                "web_name": "Rotation",
                "status": "a",
                "chance_of_playing_next_round": float("nan"),
                "form": 4.0,
                "points_per_game": 4.0,
            },
        ]
    )

    # One home fixture per GW at neutral (D3) difficulty for the whole horizon.
    fixtures = pd.DataFrame(
        [
            {
                "event": gw,
                "team_h": fit_team,
                "team_a": opp_team,
                "team_h_difficulty": 3,
                "team_a_difficulty": 3,
            }
            for gw in range(gw_start, gw_start + 3)
        ]
    )
    teams_short_map = {fit_team: "AAA", opp_team: "BBB"}

    # Fixed, controlled minutes-model output: a nailed starter and a rotation
    # risk, both fully available. Values chosen to match the fixtures already
    # exercised in tests/test_minutes_model.py::test_rotation_minutes_multiplier_values.
    mock_mins = pd.DataFrame(
        {
            "prob_start": [0.95, 0.55],
            "prob_appear": [0.99, 0.80],
            "prob_60": [0.90, 0.45],
            "exp_minutes": [88.0, 55.0],
            "rotation_prob_start": [0.95, 0.55],
            "availability": [1.0, 1.0],
        },
        index=[nailed_id, rotation_id],
    )

    monkeypatch.setattr(minutes_model, "load_minutes_history", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(
        minutes_model, "minutes_projection", lambda elements, hist, gw: mock_mins.copy()
    )

    # Isolate from the unrelated xG-blend feature (PROJ_MODEL_BLEND_WEIGHT): this test
    # is specifically about the minutes-mult exact-once-application invariant, and the
    # blend term doesn't scale with minutes_mult, so a nonzero weight breaks the
    # `xpts_on == xpts_off * minutes_mult` assertion for reasons orthogonal to what's
    # under test here.
    monkeypatch.setattr(config, "PROJ_MODEL_BLEND_WEIGHT", 0.0, raising=False)

    monkeypatch.setattr(config, "PROJ_APPLY_MINUTES_MODEL", False, raising=False)
    off = projections.project_elements_next_gws(
        elements, fixtures, teams_short_map, gw_start=gw_start, horizon_gws=3
    )
    assert not any(c.startswith("minutes_mult_gw") for c in off.columns)
    assert "prob_start" not in off.columns

    monkeypatch.setattr(config, "PROJ_APPLY_MINUTES_MODEL", True, raising=False)
    on = projections.project_elements_next_gws(
        elements, fixtures, teams_short_map, gw_start=gw_start, horizon_gws=3
    )
    assert any(c.startswith("minutes_mult_gw") for c in on.columns)
    assert "prob_start" in on.columns

    off_by_id = off.set_index("id")
    on_by_id = on.set_index("id")

    gw1_xpts_col = f"xpts_gw{gw_start}"
    gw1_mult_col = f"minutes_mult_gw{gw_start}"

    for pid in (nailed_id, rotation_id):
        base_off = float(off_by_id.loc[pid, gw1_xpts_col])
        mult = float(on_by_id.loc[pid, gw1_mult_col])
        actual_on = float(on_by_id.loc[pid, gw1_xpts_col])
        # Exact-once application: base * mult, not base * mult**2.
        assert abs(actual_on - base_off * mult) < 1e-9

    assert abs(float(on_by_id.loc[nailed_id, gw1_mult_col]) - 1.0) < 1e-9
    assert float(on_by_id.loc[rotation_id, gw1_mult_col]) < 1.0
