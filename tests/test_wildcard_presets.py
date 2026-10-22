from src import config

REQUIRED = {
    "premiums_exact", "premiums_max", "bench_mode", "bench_budget_max_m", "gem_min_xi",
    "max_def_per_team", "max_per_team", "captaincy_mult", "trend_mult", "xi_start_share",
    "formation",
}


def test_presets_have_required_keys():
    assert list(config.CHIP_WILDCARD_PRESET_ORDER) == ["aggressive", "balanced", "gems"]
    for name in config.CHIP_WILDCARD_PRESET_ORDER:
        preset = config.CHIP_WILDCARD_PRESETS[name]
        assert REQUIRED <= set(preset), (name, REQUIRED - set(preset))
        assert sum(preset["formation"]) == 10
        assert preset["bench_mode"] in {"enablers", "roles", "enablers_gem"}


def test_preset_structure_differs():
    a, b, g = (config.CHIP_WILDCARD_PRESETS[k] for k in ("aggressive", "balanced", "gems"))
    assert a["premiums_exact"] == 3 and b["premiums_exact"] == 2 and g["premiums_max"] == 1
    assert g["gem_min_xi"] == 6 and g["captaincy_mult"] == 0.0
