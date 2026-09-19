"""config.py is the only place a parameter value may live.

Every parameter used to be read as ``getattr(config, "NAME", <fallback>)`` — 264
sites, each carrying its own hardcoded default. That gave every parameter two
values: the one in config.py and the one at the call site. 50 of them disagreed,
13 numerically (e.g. PROJ_MODEL_BLEND_WEIGHT was 0.5 in config and 0.0 at the
call site), so deleting a config.py line would have silently changed behaviour
instead of failing. These tests keep the second value from coming back.
"""
import ast
import glob

import pytest

from src import config

SOURCE_GLOBS = ("src/*.py", "api/*.py", "agents/*.py", "scripts/*.py")


def _source_files():
    files = []
    for pattern in SOURCE_GLOBS:
        files.extend(sorted(glob.glob(pattern)))
    assert files, "no source files found - are the tests running from the repo root?"
    return files


def _trees():
    for path in _source_files():
        yield path, ast.parse(open(path).read(), path)


def test_no_module_reintroduces_a_getattr_fallback_for_config():
    offenders = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "getattr"
                    and node.args):
                continue
            target = node.args[0]
            is_config = ((isinstance(target, ast.Name) and target.id == "config")
                         or (isinstance(target, ast.Attribute) and target.attr == "config"))
            if is_config:
                offenders.append(f"{path}:{node.lineno}: {ast.unparse(node)[:80]}")
    assert not offenders, (
        "read parameters as config.NAME, not getattr(config, ...) — a fallback is a "
        "second source of truth:\n  " + "\n  ".join(offenders))


def test_every_config_reference_exists_so_deleting_a_param_fails_loudly():
    """The point of dropping the fallbacks: a removed parameter is now an
    AttributeError at import, not a silent switch to a different value."""
    missing = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "config"
                    and node.attr.isupper()
                    and not hasattr(config, node.attr)):
                missing.append(f"{path}:{node.lineno}: config.{node.attr}")
    assert not missing, "referenced but absent from config.py:\n  " + "\n  ".join(missing)


@pytest.mark.parametrize("name, expected", [
    # The 13 parameters whose old call-site fallback differed numerically from
    # config.py. Each previously resolved to the config value; pin that so a
    # future edit can't quietly restore the fallback number instead.
    ("PROJ_MODEL_BLEND_WEIGHT", 0.5),          # fallback was 0.0 - would disable the xG blend
    ("PROJ_SHRINKAGE_GAMES", 5.0),             # fallback was 0.0 - would disable early-season shrinkage
    ("PROJ_PENALTY_TAKER_UPLIFT", 0.45),       # fallback was 0.0
    ("PROJ_GK_FIXTURE_DAMP", 0.5),             # fallback was 1.0
    ("PROJ_EP_NEXT_BLEND_WEIGHT", 0.5),        # fallback was 0.45
    ("TRANSFER_H2H_CONFLICT_PENALTY", 3.0),    # fallback was 0.0
    ("TRANSFER_PLAN_MIN_HORIZON_GWS", 1),      # fallback was 3
    ("TRANSFER_PLAN_MAX_MOVES_PER_GW", 2),     # fallback was 1
    ("CHIP_WILDCARD_DEFAULT_HORIZON_GWS", 5),  # fallback was 4
    ("CHIP_WILDCARD_PREMIUM_ATTACKER_FLOOR", 8.5),  # fallback was 9.0
    ("CHIP_PLAN_EURO_XPTS_MULT", 0.95),        # fallback was 1.0
    ("PROJ_DIFFICULTY_SOURCE", "xg_ratings"),  # fallback was "fpl"
    # Hoisted: these existed only as a call-site fallback, never in config.py.
    ("PROJ_DEFAULT_HORIZON_GWS", 3),
    ("TRANSFER_MAX_PER_TEAM", 3),
])
def test_parameters_whose_old_fallback_disagreed_keep_the_config_value(name, expected):
    assert getattr(config, name) == expected
