import pandas as pd
import pytest

from src import config, optimizer
from tests.wildcard_market_fixture import wildcard_market

# Frozen on master d38b885 (before build_chip_squad learned `preset`):
# build_chip_squad(elements_all=wildcard_market(), score_col="wildcard_score", budget_m=100.0)
LEGACY_IDS = [12, 17, 51, 53, 68, 88, 111, 120, 150, 186, 216, 222, 242, 251, 277]

PREMIUM = config.CHIP_WILDCARD_PREMIUM_CAPTAIN_PRICE_FLOOR


def _legal(df):
    return df["pos"].value_counts().to_dict() == {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3} and len(df) == 15


def _build(preset_name, **kw):
    return optimizer.build_chip_squad(
        elements_all=wildcard_market(), score_col="wildcard_score", budget_m=100.0,
        preset=config.CHIP_WILDCARD_PRESETS[preset_name], **kw,
    )


def _xi(build):
    df = build["squad_df"]
    return df[df["is_xi"].astype(bool)]


def _bench(build):
    df = build["squad_df"]
    return df[~df["is_xi"].astype(bool)]


def _premiums(df):
    return int(((df["price_m"] >= PREMIUM) & df["pos"].isin(["MID", "FWD"])).sum())


def test_no_preset_is_byte_identical_to_legacy():
    build = optimizer.build_chip_squad(
        elements_all=wildcard_market(), score_col="wildcard_score", budget_m=100.0
    )
    assert build["ok"]
    assert sorted(build["squad_df"]["id"].astype(int).tolist()) == LEGACY_IDS


def test_preset_build_is_legal():
    for name in config.CHIP_WILDCARD_PRESET_ORDER:
        b = _build(name)
        assert b["ok"], (name, b["reason"])
        df = b["squad_df"]
        assert len(df) == 15 and len(_xi(b)) == 11
        assert df["pos"].value_counts().to_dict() == {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
        assert float(df["price_m"].sum()) <= 100.0 + 1e-9
        assert df["team"].value_counts().max() <= config.CHIP_WILDCARD_PRESETS[name]["max_per_team"]
        assert b["preset"] == name and len(b["xi_ids"]) == 11


def test_three_presets_share_at_most_eight_xi():
    xis = [set(_xi(_build(n))["id"].astype(int)) for n in config.CHIP_WILDCARD_PRESET_ORDER]
    assert len(xis[0] & xis[1]) <= 8
    assert len(xis[0] & xis[2]) <= 8
    assert len(xis[1] & xis[2]) <= 8


def test_expensive_player_never_on_bench_in_roles_mode():
    b = _build("balanced")
    bench = _bench(b)
    assert float(bench["price_m"].max()) <= 5.5
    assert set(bench["role"]) == {"gk2", "def_cover", "dc_mid", "free"}
    assert float(bench["price_m"].sum()) <= config.CHIP_WILDCARD_PRESETS["balanced"]["bench_budget_max_m"] + 1e-9


def test_balanced_caps_two_defenders_per_non_elite_team():
    b = _build("balanced")
    df = b["squad_df"]
    defensive = df[df["pos"].isin(["GKP", "DEF"])]
    per_team = defensive.groupby("team").size()
    for team, n in per_team.items():
        if int(team) > config.CHIP_WILDCARD_ELITE_DEF_RANK:
            assert n <= config.CHIP_WILDCARD_MAX_DEF_PER_TEAM, (team, n)


def test_elite_defence_may_have_three():
    market = wildcard_market()
    # make team 1's defenders irresistible
    mask = (market["team"] == 1) & market["pos"].isin(["GKP", "DEF"])
    market.loc[mask, "wildcard_score"] = 9.0
    b = optimizer.build_chip_squad(
        elements_all=market, score_col="wildcard_score", budget_m=100.0,
        preset=config.CHIP_WILDCARD_PRESETS["balanced"],
    )
    df = b["squad_df"]
    assert int(((df["team"] == 1) & df["pos"].isin(["GKP", "DEF"])).sum()) == 3


def test_aggressive_has_exactly_three_premiums():
    assert _premiums(_xi(_build("aggressive"))) == 3
    assert _premiums(_xi(_build("balanced"))) == 2


def test_gems_has_six_low_owned_xi_or_notes_relaxation():
    b = _build("gems")
    xi = _xi(b)
    low = int((xi["selected_by_percent"] < config.CHIP_WILDCARD_GEM_OWNERSHIP_MAX).sum())
    assert low >= config.CHIP_WILDCARD_GEM_MIN_XI or any("ownership" in n for n in b["notes"])
    assert _premiums(xi) <= 1


def test_gems_relaxes_when_market_has_too_few_low_owned():
    market = wildcard_market()
    market["selected_by_percent"] = 50.0  # nobody is a gem
    b = optimizer.build_chip_squad(
        elements_all=market, score_col="wildcard_score", budget_m=100.0,
        preset=config.CHIP_WILDCARD_PRESETS["gems"],
    )
    assert b["ok"]
    assert any("ownership" in n for n in b["notes"])


def test_pins_conflict_reported_not_raised():
    market = wildcard_market()
    # four team-2 midfielders pinned: breaks max_per_team=3
    pins = market[(market["team"] == 2) & (market["pos"] == "MID")]["id"].astype(int).tolist()[:4]
    b = optimizer.build_chip_squad(
        elements_all=market, score_col="wildcard_score", budget_m=100.0,
        preset=config.CHIP_WILDCARD_PRESETS["balanced"], pinned_ids=pins,
    )
    assert b["ok"]
    assert _legal(b["squad_df"])
    dropped = set(b["pins_conflict"]) & set(pins)
    assert dropped and all(b["pins_conflict_reasons"][p] == "team_cap" for p in dropped)
    kept = set(pins) - dropped
    assert kept <= set(b["squad_df"]["id"].astype(int))
    assert not dropped & set(b["squad_df"]["id"].astype(int))


def test_pinned_player_is_in_xi_and_excluded_never_selected():
    market = wildcard_market()
    pin = int(market[(market["pos"] == "DEF") & (market["team"] == 15)]["id"].iloc[0])
    excl = int(market[(market["pos"] == "MID") & (market["team"] == 1)]["id"].iloc[0])
    b = optimizer.build_chip_squad(
        elements_all=market, score_col="wildcard_score", budget_m=100.0,
        preset=config.CHIP_WILDCARD_PRESETS["balanced"], pinned_ids=[pin], excluded_ids=[excl],
    )
    assert pin in set(_xi(b)["id"].astype(int))
    assert excl not in set(b["squad_df"]["id"].astype(int))
    assert b["pins_conflict"] == []


def test_small_sample_team_shrinks_toward_price_prior():
    market = wildcard_market()
    # team 20 (4 rated matches) gets an absurd defender score
    idx = market[(market["team"] == 20) & (market["pos"] == "DEF")].index[0]
    market.loc[idx, "wildcard_score"] = 30.0
    out = optimizer.shrink_small_sample_scores(
        optimizer._prepare_chip_market(market, "wildcard_score", {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3})
    )
    row = out[out["id"] == int(market.loc[idx, "id"])].iloc[0]
    assert row["chip_score"] < 30.0 * (4.0 / config.CHIP_WILDCARD_MIN_TEAM_MATCHES) + 5.0
    # fully rated teams untouched
    full = out[out["team_rated_matches"] >= config.CHIP_WILDCARD_MIN_TEAM_MATCHES]
    assert (full["chip_score"] == full["wildcard_score"]).all()


def test_preset_requires_start_share():
    market = wildcard_market().drop(columns=["start_share"])
    with pytest.raises(KeyError, match="start_share"):
        optimizer.build_chip_squad(
            elements_all=market, score_col="wildcard_score", budget_m=100.0,
            preset=config.CHIP_WILDCARD_PRESETS["balanced"],
        )


# ---- final-review fix pass -------------------------------------------------

def test_three_goalkeeper_pins_keep_squad_legal_and_report_shape_conflict():
    market = wildcard_market()
    gks = market[market["pos"] == "GKP"]["id"].astype(int).tolist()[:3]
    b = optimizer.build_chip_squad(
        elements_all=market, score_col="wildcard_score", budget_m=100.0,
        preset=config.CHIP_WILDCARD_PRESETS["balanced"], pinned_ids=gks,
    )
    assert b["ok"], b["reason"]
    assert _legal(b["squad_df"])
    assert gks[2] in b["pins_conflict"]
    assert b["pins_conflict_reasons"][gks[2]] == "shape"


def test_sixteen_pins_capped_to_a_legal_squad():
    market = wildcard_market()
    pins = market[market["team"].isin([1, 2])]["id"].astype(int).tolist()[:16]
    b = optimizer.build_chip_squad(
        elements_all=market, score_col="wildcard_score", budget_m=100.0,
        preset=config.CHIP_WILDCARD_PRESETS["aggressive"], pinned_ids=pins,
    )
    assert b["ok"]
    assert _legal(b["squad_df"])
    assert b["squad_df"]["team"].value_counts().max() <= 3 + len([p for p in b["pins_conflict"] if b["pins_conflict_reasons"].get(p) == "team_cap"])


def test_duplicate_pin_is_deduped():
    market = wildcard_market()
    pin = int(market[market["pos"] == "MID"]["id"].iloc[0])
    b = optimizer.build_chip_squad(
        elements_all=market, score_col="wildcard_score", budget_m=100.0,
        preset=config.CHIP_WILDCARD_PRESETS["balanced"], pinned_ids=[pin, pin],
    )
    assert b["ok"] and _legal(b["squad_df"])
    assert int((b["squad_df"]["id"] == pin).sum()) == 1
    assert b["pins_conflict"] == []


def test_bench_pin_is_not_a_cap_conflict():
    market = wildcard_market()
    # Balanced XI has 3 DEF; a 4th pinned DEF goes to the bench without a conflict.
    defs = [int(market[(market["pos"] == "DEF") & (market["team"] == t)]["id"].iloc[0]) for t in (5, 6, 7, 8)]
    b = optimizer.build_chip_squad(
        elements_all=market, score_col="wildcard_score", budget_m=100.0,
        preset=config.CHIP_WILDCARD_PRESETS["balanced"], pinned_ids=defs,
    )
    assert b["ok"] and _legal(b["squad_df"])
    assert set(defs) <= set(b["squad_df"]["id"].astype(int))
    assert b["pins_conflict"] == []


def test_premium_floor_holds_when_premiums_score_low():
    market = wildcard_market()
    prem = (market["price_m"] >= PREMIUM) & market["pos"].isin(["MID", "FWD"])
    market.loc[prem, "wildcard_score"] = 1.0  # premiums look terrible
    for name, n in (("aggressive", 3), ("balanced", 2)):
        b = optimizer.build_chip_squad(
            elements_all=market, score_col="wildcard_score", budget_m=100.0,
            preset=config.CHIP_WILDCARD_PRESETS[name],
        )
        assert b["ok"]
        assert _premiums(_xi(b)) == n, (name, b["notes"])
