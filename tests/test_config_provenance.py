"""Every parameter must declare where its value came from.

config.py holds 200+ numbers. Before this, there was no way to tell which had
been validated against a backtest and which were somebody's first guess — so
nobody could safely change any of them. Each parameter now carries a tag, and
these tests keep that true as parameters are added.
"""
import ast
import re

import pytest

from src import config, rules

CONFIG_PATH = "src/config.py"
VALID_TAGS = {"[tuned]", "[untested]", "[operational]", "[flag]"}
TAG_RE = re.compile(r"#\s*(\[[a-z]+\])")


def _param_lines():
    """{param name: the source line its assignment ends on}."""
    src = open(CONFIG_PATH).read()
    lines = src.split("\n")
    out = {}
    for node in ast.parse(src).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id.isupper()):
            out[node.targets[0].id] = lines[node.end_lineno - 1]
    return out


def test_every_parameter_carries_a_provenance_tag():
    untagged = [name for name, line in _param_lines().items() if not TAG_RE.search(line)]
    assert not untagged, (
        "add a provenance tag ([tuned] / [untested] / [operational] / [flag]) to:\n  "
        + "\n  ".join(untagged))


def test_no_parameter_uses_an_unknown_tag():
    bad = []
    for name, line in _param_lines().items():
        m = TAG_RE.search(line)
        if m and m.group(1) not in VALID_TAGS:
            bad.append(f"{name}: {m.group(1)}")
    assert not bad, f"unknown tags (valid: {sorted(VALID_TAGS)}):\n  " + "\n  ".join(bad)


def test_the_rulebook_is_not_redefined_in_config():
    """rules.py is the definition site; config.py only re-exports. Two
    definitions would let the engine score a goal differently from the game."""
    assigned = set(_param_lines())
    rule_names = {n for n in dir(rules) if n.isupper()}
    clashes = assigned & rule_names
    assert not clashes, f"defined in both rules.py and config.py: {sorted(clashes)}"


@pytest.mark.parametrize("name, expected", [
    ("OUTPUT_GOAL_POINTS", {"GKP": 6, "DEF": 6, "MID": 5, "FWD": 4}),
    ("OUTPUT_ASSIST_POINTS", 3.0),
    ("OUTPUT_CS_POINTS", {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}),
    ("OUTPUT_SAVE_POINTS_PER_SAVE", 1.0 / 3.0),
    ("OUTPUT_DC_POINTS", 2.0),
    ("OUTPUT_DC_THRESHOLD", {"GKP": 10, "DEF": 10, "MID": 12, "FWD": 12}),
    ("TRANSFER_HIT_POINTS_STEP", 4),
    ("FT_MAX", 5),
    ("CHIP_MAX_PER_TEAM", 3),
    ("TRANSFER_MAX_PER_TEAM", 3),
    ("CHIP_PLAN_PHASE_SPLIT_GW", 19),
    ("CHIP_PLAN_SEASON_END_GW", 38),
])
def test_rulebook_values_match_the_fpl_rules(name, expected):
    """These change only when FPL changes the game."""
    assert getattr(rules, name) == expected
    assert getattr(config, name) == expected, "config must re-export the same object"
