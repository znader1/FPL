"""Beam-search discipline: bench sellers ignore buyer bonuses; DEF/GKP swaps
need a higher bar; injury urgency bypasses it — mirroring the horizon planner."""
import pandas as pd

from src import recommender


def _market(rows):
    """rows: (id, pos, base, penalties_order or None, status, chance)."""
    recs = []
    for pid, pos, base, pens, status, chance in rows:
        recs.append({
            "id": pid,
            "web_name": f"P{pid}",
            "team": pid,          # distinct team per player: no 3-per-club issues
            "team_short": f"T{pid}",
            "pos": pos,
            "price_m": 5.0,
            "form": 0.0,
            "points_per_game": 0.0,
            "selected_by_percent": 0.0,
            "status": status,
            "chance_of_playing_next_round": chance,
            "penalties_order": pens,
            "xh": base,           # score_col -> base_score
            "xpts_horizon": base,  # hot_by_position reads this unconditionally
        })
    return pd.DataFrame(recs)


def _squad(pid, multiplier=1):
    return pd.DataFrame([{
        "player_id": pid,
        "multiplier": multiplier,
        "is_captain": False,
        "is_vice_captain": False,
    }])


def _moves(squad_df, market_df):
    out = recommender.suggest_transfers(
        squad_df, market_df, itb_m=1.0, free_transfers=1, hit_cap=0,
        score_col="xh", horizon_gws=1,
    )
    return out.get("moves") or []


def test_bench_seller_ignores_buyer_set_piece_bonus():
    # Buyer's raw upgrade is +0.3 (< bench threshold); his penalty-taker bonus
    # would clear it, but set pieces are worthless to a bench slot.
    market = _market([
        (1, "MID", 2.0, None, "a", 100),
        (2, "MID", 2.3, 1, "a", 100),
    ])
    assert _moves(_squad(1, multiplier=0), market) == []


def test_starter_seller_still_credits_buyer_bonuses():
    market = _market([
        (1, "MID", 2.0, None, "a", 100),
        (2, "MID", 2.3, 1, "a", 100),
    ])
    moves = _moves(_squad(1, multiplier=1), market)
    assert len(moves) == 1
    assert moves[0]["buy"]["name"] == "P2"


def test_defender_swap_needs_higher_bar_than_midfielder():
    # Gain of 1.0 clears the MID bar (0.60) but not the DEF bar (0.60 x 1.75).
    def_market = _market([
        (1, "DEF", 2.0, None, "a", 100),
        (2, "DEF", 3.0, None, "a", 100),
    ])
    mid_market = _market([
        (1, "MID", 2.0, None, "a", 100),
        (2, "MID", 3.0, None, "a", 100),
    ])
    assert _moves(_squad(1), def_market) == []
    assert len(_moves(_squad(1), mid_market)) == 1


def test_injured_defender_bypasses_positional_bar():
    market = _market([
        (1, "DEF", 2.0, None, "i", 0),
        (2, "DEF", 3.0, None, "a", 100),
    ])
    moves = _moves(_squad(1), market)
    assert len(moves) == 1
    assert moves[0]["sell"]["name"] == "P1"
