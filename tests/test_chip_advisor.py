import pandas as pd

from src.chip_advisor import chip_windows, team_fixture_counts


def test_chip_windows_all_available_when_none_played():
    w = chip_windows([], current_gw=5)
    assert set(w) == {"wildcard", "free_hit", "bench_boost", "triple_captain"}
    assert all(v["available"] for v in w.values())
    assert all(v["half"] == 1 and v["expires_gw"] == 19 for v in w.values())


def test_chip_windows_played_chip_unavailable_in_phase():
    played = [{"name": "bboost", "event": 4}]
    w = chip_windows(played, current_gw=6)
    assert w["bench_boost"]["available"] is False
    assert w["wildcard"]["available"] is True


def test_chip_windows_phase1_play_resets_in_phase2():
    played = [{"name": "3xc", "event": 10}]
    w = chip_windows(played, current_gw=25)
    assert w["triple_captain"]["available"] is True
    assert w["triple_captain"]["half"] == 2
    assert w["triple_captain"]["expires_gw"] == 38


def test_chip_windows_current_gw_play_still_counts_as_available():
    # Advising FOR current_gw: a chip logged in current_gw isn't "gone" yet
    # (mirrors the strictly-before rule in the old _derive_chips_remaining).
    played = [{"name": "wildcard", "event": 7}]
    w = chip_windows(played, current_gw=7)
    assert w["wildcard"]["available"] is True


def test_chip_windows_normalizes_fpl_names():
    played = [{"name": "freehit", "event": 3}, {"name": "BBOOST", "event": 4}]
    w = chip_windows(played, current_gw=8)
    assert w["free_hit"]["available"] is False
    assert w["bench_boost"]["available"] is False


def _fixtures(rows):
    return pd.DataFrame(rows, columns=["event", "team_h", "team_a"])


def test_team_fixture_counts_single_and_double():
    fx = _fixtures([
        (12, 1, 2),
        (12, 1, 3),   # team 1 doubles in GW12
        (13, 2, 3),
    ])
    counts = team_fixture_counts(fx, 12)
    assert counts == {1: 2, 2: 1, 3: 1}


def test_team_fixture_counts_blank_gw_team_absent():
    fx = _fixtures([(12, 1, 2)])
    counts = team_fixture_counts(fx, 12)
    assert 3 not in counts
    assert counts.get(3, 0) == 0


def test_team_fixture_counts_empty_fixtures():
    assert team_fixture_counts(pd.DataFrame(columns=["event", "team_h", "team_a"]), 5) == {}


from src.chip_advisor import effective_min_ev


def test_effective_min_ev_full_far_from_expiry():
    # bench_boost base threshold is 5.0; GW5 vs expiry GW19 is outside the ramp
    assert effective_min_ev("bench_boost", target_gw=5, expires_gw=19) == 5.0


def test_effective_min_ev_decays_inside_ramp():
    # ramp is 5 GWs: at 2 GWs left the threshold is base * 2/5
    v = effective_min_ev("bench_boost", target_gw=17, expires_gw=19)
    assert abs(v - 5.0 * 2 / 5) < 1e-9


def test_effective_min_ev_zero_at_expiry_gw():
    assert effective_min_ev("triple_captain", target_gw=19, expires_gw=19) == 0.0


def test_effective_min_ev_monotonic_toward_expiry():
    vals = [effective_min_ev("wildcard", target_gw=g, expires_gw=19) for g in range(13, 20)]
    assert all(a >= b for a, b in zip(vals, vals[1:]))


from src.chip_advisor import score_free_hit, score_wildcard


def _market(players):
    """players: list of (player_id, name, pos, team, price_m, xpts, fixture_count)."""
    return pd.DataFrame(
        players,
        columns=["player_id", "name", "pos", "team", "price_m", "xpts", "fixture_count"],
    )


def _squad_15(prefix="own", xpts=2.0):
    rows, pid = [], 1
    for pos, n in (("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for i in range(n):
            rows.append((pid, f"{prefix}{pid}", pos, f"T{pid % 10}", 5.0, xpts, 1))
            pid += 1
    return _market(rows)


def test_score_wildcard_net_of_transfer_plan_gain():
    squad = _squad_15(xpts=2.0)
    # Market of stars the squad doesn't own: big raw uplift
    stars = _squad_15(prefix="star", xpts=6.0)
    stars["player_id"] = stars["player_id"] + 100
    market = pd.concat([squad[["player_id", "name", "pos", "team", "price_m", "xpts", "fixture_count"]], stars])
    gw_projections = {5: market, 6: market, 7: market, 8: market}

    raw = score_wildcard(squad[["player_id", "name", "pos", "team", "price_m"]],
                         gw_projections, [5], horizon=4)
    net = score_wildcard(squad[["player_id", "name", "pos", "team", "price_m"]],
                         gw_projections, [5], horizon=4, transfer_plan_net_gain=10.0)
    assert raw and net
    assert abs(raw[0].expected_value - net[0].expected_value - 10.0) < 1e-6


def test_score_free_hit_respects_budget():
    squad = _squad_15(xpts=2.0)
    # Unaffordable stars: price 15.0m each, budget only allows the cheap pool
    stars = _squad_15(prefix="star", xpts=9.0)
    stars["player_id"] = stars["player_id"] + 100
    stars["price_m"] = 15.0
    market = pd.concat([squad[["player_id", "name", "pos", "team", "price_m", "xpts", "fixture_count"]], stars])
    gw_projections = {5: market}

    recs = score_free_hit(squad[["player_id", "name", "pos", "team", "price_m"]],
                          gw_projections, [5], budget_m=80.0)
    # With an 80m budget nothing beats the (identical) cheap pool → no uplift
    assert recs == [] or recs[0].expected_value < 1.0
