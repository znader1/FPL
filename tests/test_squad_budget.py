import pandas as pd

from src.squad_builder import squad_budget_breakdown


def _elements():
    return pd.DataFrame({"id": list(range(1, 16)), "price_m": [6.0] * 15})


def _squad_no_sell():
    return pd.DataFrame({"player_id": list(range(1, 16))})


def test_entry_value_is_selling_value_plus_bank():
    bb = squad_budget_breakdown(
        {"value": 1018, "bank": 1}, squad_df=_squad_no_sell(), elements=_elements(), itb_m=None
    )
    assert bb == {
        "source": "entry_value",
        "squad_sell_value_m": 101.7,
        "bank_m": 0.1,
        "budget_m": 101.8,
    }


def test_my_team_selling_price_wins_over_entry_value():
    sq = _squad_no_sell().assign(selling_price=[50] * 15)  # tenths
    bb = squad_budget_breakdown({"value": 1018, "bank": 1}, sq, _elements(), itb_m=0.1)
    assert bb["source"] == "my_team"
    assert bb["budget_m"] == 75.1


def test_missing_value_falls_back_to_market_not_zero():
    bb = squad_budget_breakdown({}, _squad_no_sell(), _elements(), itb_m=0.5)
    assert bb["source"] == "market"
    assert bb["budget_m"] == 90.5
