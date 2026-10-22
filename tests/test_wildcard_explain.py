from src import explainer, lineup_builder


def _record():
    return {
        "player_id": 10, "web_name": "Striker", "pos": "FWD", "price_m": 8.0,
        "wildcard_score": 20.5, "wildcard_weighted_xpts": 18.0, "wildcard_future_dgw_bonus": 0.0,
        "wildcard_captaincy_bonus": 1.0, "wildcard_trend": 0.2, "wildcard_trend_term": 0.2,
        "wildcard_upside": 0.9, "wildcard_injury_mult": 0.95, "role": "xi",
        "fixtures_horizon": [],
    }


def test_breakdown_lists_new_components():
    bd = lineup_builder._build_score_breakdown(_record(), chip_strategy="wildcard", objective_score_col="wildcard_score")
    wc = bd["wildcard"]
    assert set(wc) >= {"score", "weighted_xpts", "dgw", "captaincy", "trend", "upside", "injury_mult", "ownership_term", "role"}
    assert "form_bonus" not in wc and "ownership_bonus" not in wc
    assert wc["trend"] == 0.2 and wc["injury_mult"] == 0.95 and wc["role"] == "xi"


def test_breakdown_carries_facts_when_given():
    rec = _record()
    rec["facts"] = {"vs_opponent": {"games": 3, "goals": 3, "assists": 0, "points": 22}, "milestone": None, "streak": 2}
    bd = lineup_builder._build_score_breakdown(rec, chip_strategy="wildcard", objective_score_col="wildcard_score")
    assert bd["wildcard"]["facts"]["streak"] == 2


def test_explainer_wildcard_prompt_contains_only_provided_facts():
    rec = _record()
    rec["score_breakdown"] = lineup_builder._build_score_breakdown(
        dict(rec, facts={"vs_opponent": None, "milestone": {"stat": "goals", "current": 48, "target": 50}, "streak": 2}),
        chip_strategy="wildcard", objective_score_col="wildcard_score",
    )
    recs = {
        "squad": {"starting_xi": [rec], "bench": []},
        "strategy_recommendation": {"chip_strategy": "wildcard"},
    }
    ctx = explainer._compact_context(recs)
    picks = ctx["wildcard_picks"]
    assert picks[0]["id"] == 10
    assert picks[0]["facts"]["milestone"]["target"] == 50
    assert set(picks[0]["breakdown"]) <= {"score", "weighted_xpts", "dgw", "captaincy", "trend", "trend_term", "upside", "injury_mult", "ownership_term", "role"}
    assert "score_breakdown and facts" in explainer.SYSTEM_PROMPT


def test_explainer_context_has_no_wildcard_picks_without_wildcard():
    rec = {"player_id": 1, "web_name": "x", "score_breakdown": {}}
    ctx = explainer._compact_context({"squad": {"starting_xi": [rec], "bench": []}, "strategy_recommendation": {}})
    assert "wildcard_picks" not in ctx
