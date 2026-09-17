from src.fixture_difficulty import compute_fixture_swings


def _ticker(team_cells):
    """team_cells: {team_short: {gw: difficulty|None}} — None means blank."""
    gws = sorted({gw for cells in team_cells.values() for gw in cells})
    teams = []
    for i, (short, cells) in enumerate(team_cells.items()):
        teams.append({
            "team_id": i + 1,
            "team_short": short,
            "gws": {gw: {"difficulty": d, "blank": d is None, "count": 0 if d is None else 1}
                    for gw, d in cells.items()},
        })
    return {"gw_start": gws[0], "horizon_gws": len(gws), "gws": gws, "teams": teams}


def test_swing_detected_when_run_turns_easier():
    t = _ticker({"ARS": {10: 4.5, 11: 4.2, 12: 4.4, 13: 2.0, 14: 2.2, 15: 2.1}})
    out = compute_fixture_swings(t, window=3, min_delta=0.8)
    assert len(out) == 1
    ev = out[0]
    assert (ev["team_short"], ev["gw"], ev["direction"]) == ("ARS", 13, "easier")
    assert ev["delta"] > 2.0


def test_no_swing_below_min_delta():
    t = _ticker({"CHE": {10: 3.2, 11: 3.0, 12: 3.1, 13: 2.9, 14: 2.8, 15: 3.0}})
    assert compute_fixture_swings(t, window=3, min_delta=0.8) == []


def test_harder_swing_direction():
    t = _ticker({"SUN": {10: 2.0, 11: 2.1, 12: 2.0, 13: 4.4, 14: 4.5, 15: 4.2}})
    out = compute_fixture_swings(t, window=3, min_delta=0.8)
    assert out[0]["direction"] == "harder"


def test_blank_cells_count_as_neutral_three():
    # Blank (None) → 3.0: 3 tough GWs then [3.0, 2.0, 2.0] avg 2.33 → delta ≈ 2.04
    t = _ticker({"MCI": {10: 4.4, 11: 4.3, 12: 4.4, 13: None, 14: 2.0, 15: 2.0}})
    out = compute_fixture_swings(t, window=3, min_delta=0.8)
    assert len(out) == 1 and out[0]["gw"] == 13


def test_partial_windows_at_edges_are_skipped():
    # Only 4 GWs: no gw has 3 before AND 3 after → no events even with huge delta
    t = _ticker({"LIV": {10: 5.0, 11: 5.0, 12: 1.0, 13: 1.0}})
    assert compute_fixture_swings(t, window=3, min_delta=0.5) == []


def test_one_strongest_event_per_team_per_direction():
    # Long easing run would flag several adjacent GWs — keep only the strongest
    t = _ticker({"AVL": {10: 4.8, 11: 4.6, 12: 4.7, 13: 2.0, 14: 2.1, 15: 1.9,
                          16: 2.0, 17: 2.2, 18: 2.1}})
    out = compute_fixture_swings(t, window=3, min_delta=0.8)
    easier = [e for e in out if e["direction"] == "easier"]
    assert len(easier) == 1 and easier[0]["gw"] == 13
