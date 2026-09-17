import math

from src.odds_model import (
    devig,
    implied_total_lambda,
    split_supremacy,
    implied_fixture_lambdas,
)


def test_devig_normalizes_overround():
    # Bookmaker 1X2 at 5% overround
    probs = devig([2.0, 3.5, 4.0])
    assert abs(sum(probs) - 1.0) < 1e-9
    assert probs[0] > probs[1] > probs[2]


def test_implied_total_lambda_inverts_poisson_tail():
    # If P(N >= 3) = 0.5768, lambda should be ~2.675 (known Poisson value)
    lam = implied_total_lambda(p_over=0.5768, line=2.5)
    p_check = 1.0 - sum(math.exp(-lam) * lam ** k / math.factorial(k) for k in range(3))
    assert abs(p_check - 0.5768) < 1e-3
    assert 2.0 < lam < 3.5


def test_implied_total_lambda_monotonic():
    assert implied_total_lambda(0.7, 2.5) > implied_total_lambda(0.4, 2.5)


def test_split_supremacy_symmetric():
    # Equal home/away win probs → near-equal lambdas
    lh, la = split_supremacy(total_lam=2.6, p_home=0.37, p_away=0.37)
    assert abs(lh - la) < 0.05
    assert abs((lh + la) - 2.6) < 1e-6


def test_split_supremacy_favourite_gets_bigger_lambda():
    lh, la = split_supremacy(total_lam=3.0, p_home=0.70, p_away=0.12)
    assert lh > la
    assert lh > 1.9  # heavy favourite carries most of the goals


def test_implied_fixture_lambdas_end_to_end():
    fixture_odds = {
        "home_team": "Manchester City",
        "away_team": "Hull City",
        "h2h": [1.25, 6.5, 12.0],   # home/draw/away decimal odds
        "totals": {"line": 3.5, "over": 1.95, "under": 1.87},
    }
    out = implied_fixture_lambdas(fixture_odds)
    assert out is not None
    assert out["lam_home"] > out["lam_away"]
    assert out["lam_home"] + out["lam_away"] == out["total_lam"]
    assert 0.0 < out["p_home"] < 1.0


def test_implied_fixture_lambdas_missing_market_returns_none():
    assert implied_fixture_lambdas({"home_team": "A", "away_team": "B", "h2h": [2, 3, 4]}) is None
    assert implied_fixture_lambdas({"home_team": "A", "away_team": "B",
                                    "totals": {"line": 2.5, "over": 2.0, "under": 1.8}}) is None
