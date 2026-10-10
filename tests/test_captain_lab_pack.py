"""pack_lineup_records must not lose columns the lineup frame already carries
(pandas suffixes _x/_y on an overlapping merge and record.get() then sees nothing)."""
import pandas as pd
from src import lineup_builder


def test_overlapping_columns_survive_the_projection_merge():
    starting = pd.DataFrame({
        "player_id": [1], "web_name": ["Saka"], "pos": ["MID"], "team": [1], "team_short": ["ARS"],
        "xpts": [7.4], "selected_by_percent": [38.4], "p80_low": [2], "p80_high": [16], "status": ["a"],
    })
    bench = starting.iloc[0:0].copy()
    elements = pd.DataFrame({"id": [1], "team": [1], "code": [1], "photo": ["x.png"]})
    proj = pd.DataFrame({
        "id": [1], "xpts_horizon": [20.1], "status": ["a"], "selected_by_percent": [38.4],
        "p80_low": [2], "p80_high": [16], "modal_points": [3],
        "xpts_gw29": [7.4], "fixtures_gw29": ["H-BHA(D1)"], "fixture_count_gw29": [1], "diff_avg_gw29": [1.0],
    })
    recs, _ = lineup_builder.pack_lineup_records(starting, bench, elements, proj, gws=[29], teams_code={})
    rec = recs[0]
    assert rec["xpts_p10"] == 2
    assert rec["xpts_p90"] == 16
    assert rec["ownership_pct"] == 38.4
    assert rec["score_breakdown"]["distribution"]["p80_low"] == 2
    assert rec["status"] == "a"
    assert not [k for k in rec if k.endswith("_x") or k.endswith("_y")]
