"""Captain Lab fields on lineup player records (frontend handoff 1b, 2026-10).

The 80% band from the points distribution already is the 10th-90th percentile
pair, so xpts_p10/xpts_p90 alias it under the names the frontend asked for.
Ownership is FPL's overall selected_by_percent — honest, not top-10k EO.
"""
from src import lineup_builder


def _record(**over):
    rec = {
        "player_id": 1, "web_name": "Saka", "xpts": 7.4, "xpts_horizon": 20.1,
        "p80_low": 2, "p80_high": 16, "selected_by_percent": 38.4,
        "fixtures_gw29": "H-BHA(D1)", "fixture_count_gw29": 1, "diff_avg_gw29": 1.0, "xpts_gw29": 7.4,
    }
    rec.update(over)
    return rec


def test_record_carries_percentiles_and_ownership():
    rec = lineup_builder.decorate_projection_record(_record(), gws=[29])
    assert rec["xpts_p10"] == 2
    assert rec["xpts_p90"] == 16
    assert rec["ownership_pct"] == 38.4


def test_fields_are_null_when_the_inputs_are_missing():
    rec = lineup_builder.decorate_projection_record(
        _record(p80_low=None, p80_high=None, selected_by_percent=None), gws=[29],
    )
    assert rec["xpts_p10"] is None
    assert rec["xpts_p90"] is None
    assert rec["ownership_pct"] is None


def test_projection_columns_include_ownership():
    import pandas as pd
    proj = pd.DataFrame({"id": [1], "xpts_horizon": [1.0], "selected_by_percent": [12.0], "p80_low": [1], "p80_high": [9]})
    cols = lineup_builder._lineup_projection_cols(proj, gws=[])
    assert "selected_by_percent" in cols
    assert "p80_low" in cols and "p80_high" in cols
