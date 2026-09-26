"""Guard the shipped knowledge_discount.json seed.

fixture_difficulty.apply_knowledge_discount silently skips a key it can't
resolve, so a wrong short name (e.g. "SPURS" for TOT) or a leftover template
entry applies nothing and nobody notices. These checks fail CI instead.
"""
import json
from pathlib import Path

import pytest

SEED = Path(__file__).resolve().parent.parent / "data" / "models" / "knowledge_discount.json"

# Live FPL short_name list, 2026-27 season (bootstrap-static, checked 2026-09-26).
# Update at season rollover when the promoted/relegated teams change.
SHORT_NAMES_2026_27 = {
    "ARS", "AVL", "BHA", "BOU", "BRE", "CHE", "COV", "CRY", "EVE", "FUL",
    "HUL", "IPS", "LEE", "LIV", "MCI", "MUN", "NEW", "NFO", "SUN", "TOT",
}

# The file's own _workflow: "keep nudges in 0.85-1.15".
NUDGE_MIN, NUDGE_MAX = 0.85, 1.15


@pytest.fixture(scope="module")
def teams():
    return json.loads(SEED.read_text())["teams"]


def test_every_team_key_is_a_live_short_name(teams):
    unknown = sorted(k for k in teams if k not in SHORT_NAMES_2026_27)
    assert not unknown, f"keys that resolve to no team (applied as nothing): {unknown}"


def test_multipliers_stay_within_workflow_band(teams):
    out_of_band = {
        key: {side: adj[side]}
        for key, adj in teams.items()
        for side in ("attack", "defense")
        if side in adj and not NUDGE_MIN <= float(adj[side]) <= NUDGE_MAX
    }
    assert not out_of_band, f"multipliers outside {NUDGE_MIN}-{NUDGE_MAX}: {out_of_band}"


def test_every_entry_has_a_note(teams):
    missing = sorted(k for k, adj in teams.items() if not str(adj.get("note", "")).strip())
    assert not missing, f"entries without a sourcing note: {missing}"
