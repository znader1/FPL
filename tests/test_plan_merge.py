from src import plan_merge


def _p(pid, name="X", team="TTT", price=5.0):
    return {"id": pid, "name": name, "team": team, "price": price}


def _beam(*pairs):
    return {
        "moves": [
            {"position": "MID", "sell": _p(s), "buy": _p(b), "score_gain": 3.0,
             "buy_hot_score": 1.5, "buy_set_piece_score": 0.2}
            for s, b in pairs
        ],
        "moves_by_position": {"MID": len(pairs)},
        "transfer_plan": {"free_transfers": 1, "horizon_gws": 3, "hit_cap": 0,
                          "transfer_count_target": 1, "transfer_count_built": len(pairs)},
        "remaining_itb": 0.3,
    }


def _plan(action, moves, bank_after=1.2):
    return {
        "verdict": action,
        "plan": [{"gw": 5, "action": "transfer" if moves else "roll", "moves": [],
                  "bank_after": bank_after}],
        "verdict_detail": {
            "action": action,
            "moves": [
                {"position": "DEF", "sell": _p(s, "S"), "buy": _p(b, "B"),
                 "this_gw_gain": 0.9, "horizon_gain": 2.8, "forced_injury": False,
                 "h2h_conflicts": []}
                for s, b in moves
            ],
        },
    }


def test_spend_plan_moves_lead_and_beam_survivors_follow():
    preview = plan_merge.merge_plan_moves_into_preview(_beam((1, 2), (3, 4)), _plan("spend", [(7, 8)]))
    ids = [(m["sell"]["id"], m["buy"]["id"]) for m in preview["moves"]]
    assert ids == [(7, 8), (1, 2), (3, 4)]
    assert [m["in_plan"] for m in preview["moves"]] == [True, False, False]
    assert preview["moves"][0]["score_gain"] == 2.8
    assert preview["moves"][0]["this_gw_gain"] == 0.9
    assert preview["moves"][0]["position"] == "DEF"
    assert preview["moves_by_position"] == {"DEF": 1, "MID": 2}
    assert preview["transfer_plan"]["transfer_count_built"] == 2   # beam diagnostic, untouched
    assert preview["remaining_itb"] == 0.3                         # beam diagnostic, untouched


def test_duplicate_pair_reuses_the_beam_record():
    preview = plan_merge.merge_plan_moves_into_preview(_beam((1, 2), (3, 4)), _plan("spend", [(3, 4)]))
    ids = [(m["sell"]["id"], m["buy"]["id"]) for m in preview["moves"]]
    assert ids == [(3, 4), (1, 2)]
    lead = preview["moves"][0]
    assert lead["in_plan"] is True
    assert lead["buy_hot_score"] == 1.5          # beam enrichment kept
    assert lead["this_gw_gain"] == 0.9           # plan slice added
    assert preview["transfer_plan"]["transfer_count_built"] == 2


def test_forced_injury_counts_as_spend():
    preview = plan_merge.merge_plan_moves_into_preview(_beam((1, 2)), _plan("spend_forced_injury", [(7, 8)]))
    assert preview["moves"][0]["sell"]["id"] == 7


def test_roll_leaves_beam_order_and_flags_false():
    preview = plan_merge.merge_plan_moves_into_preview(_beam((1, 2), (3, 4)), _plan("roll", []))
    ids = [(m["sell"]["id"], m["buy"]["id"]) for m in preview["moves"]]
    assert ids == [(1, 2), (3, 4)]
    assert all(m["in_plan"] is False for m in preview["moves"])
    assert preview["remaining_itb"] == 0.3


def test_missing_plan_or_detail_is_a_noop_with_flags():
    preview = plan_merge.merge_plan_moves_into_preview(_beam((1, 2)), None)
    assert preview["moves"][0]["in_plan"] is False
    preview = plan_merge.merge_plan_moves_into_preview(_beam((1, 2)), {"verdict": "spend"})
    assert preview["moves"][0]["in_plan"] is False


def test_non_dict_preview_returned_untouched():
    assert plan_merge.merge_plan_moves_into_preview(None, _plan("spend", [(7, 8)])) is None
