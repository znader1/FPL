"""
Manual squad import for the pre-season / pre-first-deadline window.

Before GW1 locks, FPL exposes no public picks (the /event/{gw}/picks/ endpoint
404s) and reading the live team needs authentication. Manual import sidesteps
auth entirely: the manager enters their 15 once, we persist it, and it feeds the
same pipeline as a fetched squad until the first gameweek locks and the public
endpoint takes over.

The stored squad is normalized into the public /event/{gw}/picks/ shape so every
downstream consumer (picks_to_df, build_recommendations, ...) treats it uniformly.
"""
import json
import os
from pathlib import Path

import pandas as pd

# Valid FPL squad composition, keyed by element_type id.
# 1=GKP, 2=DEF, 3=MID, 4=FWD.
SQUAD_COMPOSITION = {1: 2, 2: 5, 3: 5, 4: 3}
SQUAD_SIZE = 15
BUDGET_TENTHS = 1000  # £100.0m, FPL stores money ×10

# Default legal starting XI when the manager doesn't specify one: 3-4-3.
# Always legal for a 2/5/5/3 squad; the recommendations pipeline re-optimizes
# the XI afterwards, so this is only a sensible starting point.
_START_BY_TYPE = {1: 1, 2: 3, 3: 4, 4: 3}


def _data_dir():
    """Directory for persisted manual squads (under the Fly data volume in prod)."""
    base = os.environ.get("FPL_MANUAL_SQUAD_DIR") or os.environ.get("FPL_DATA_DIR") or "data"
    return Path(base) / "manual_squads"


def _path_for(entry_id):
    return _data_dir() / f"entry_{int(entry_id)}.json"


def save_manual_squad(entry_id, player_ids, captain_id=None, vice_id=None):
    """Persist the raw manual selection. Validation happens at build time."""
    payload = {
        "entry_id": int(entry_id),
        "player_ids": [int(p) for p in player_ids],
        "captain_id": int(captain_id) if captain_id is not None else None,
        "vice_id": int(vice_id) if vice_id is not None else None,
    }
    d = _data_dir()
    d.mkdir(parents=True, exist_ok=True)
    _path_for(entry_id).write_text(json.dumps(payload))
    return payload


def load_manual_squad(entry_id):
    """Return the persisted selection dict, or None if none saved."""
    p = _path_for(entry_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return None


def clear_manual_squad(entry_id):
    """Remove a persisted manual squad (e.g. once the real fetch takes over)."""
    p = _path_for(entry_id)
    if p.exists():
        p.unlink()
        return True
    return False


def _validate(elements, player_ids):
    """Raise ValueError with a human-readable reason if the selection is illegal."""
    ids = [int(p) for p in player_ids]
    if len(ids) != SQUAD_SIZE:
        raise ValueError(f"Need exactly {SQUAD_SIZE} players, got {len(ids)}.")
    if len(set(ids)) != SQUAD_SIZE:
        raise ValueError("Duplicate players in selection.")

    by_id = elements.set_index("id")
    unknown = [pid for pid in ids if pid not in by_id.index]
    if unknown:
        raise ValueError(f"Unknown player id(s): {unknown}.")

    rows = by_id.loc[ids]
    counts = rows["element_type"].value_counts().to_dict()
    for etype, need in SQUAD_COMPOSITION.items():
        have = int(counts.get(etype, 0))
        if have != need:
            names = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
            raise ValueError(f"Need {need} {names[etype]}, got {have}.")

    total = int(rows["now_cost"].sum())
    if total > BUDGET_TENTHS:
        raise ValueError(
            f"Squad costs £{total / 10:.1f}m, over the £{BUDGET_TENTHS / 10:.0f}m budget."
        )
    return rows, total


def build_manual_myteam(bootstrap_elements, player_ids, captain_id=None,
                        vice_id=None, planning_event_id=1):
    """
    Turn a validated manual selection into a payload shaped like the public
    /event/{gw}/picks/ response, so downstream code consumes it unchanged.

    `bootstrap_elements` is the elements DataFrame from
    transforms.tables_from_bootstrap (needs id, element_type, now_cost).

    Positions 1-11 are a legal default XI (3-4-3); 12-15 the bench. The
    recommendations pipeline re-optimizes the XI, so exact ordering is only a
    starting point. Raises ValueError on an illegal selection.
    """
    rows, total_cost = _validate(bootstrap_elements, player_ids)

    # Order players within each position, cheapest last so pricier picks tend to
    # start — a reasonable default before the pipeline re-optimizes.
    by_type = {etype: [] for etype in SQUAD_COMPOSITION}
    ordered = rows.sort_values("now_cost", ascending=False)
    for pid, row in ordered.iterrows():
        by_type[int(row["element_type"])].append(int(pid))

    starters, bench = [], []
    for etype in (1, 2, 3, 4):
        n_start = _START_BY_TYPE[etype]
        starters.extend(by_type[etype][:n_start])
        bench.extend(by_type[etype][n_start:])

    # Default captain/vice = two priciest starters, unless specified.
    starter_set = set(starters)
    if captain_id is None or int(captain_id) not in starter_set:
        captain_id = starters[0] if starters else None
    if vice_id is None or int(vice_id) not in starter_set or int(vice_id) == int(captain_id):
        vice_id = next((p for p in starters if p != int(captain_id)), None)

    picks = []
    for pos, pid in enumerate(starters, start=1):
        is_cap = captain_id is not None and pid == int(captain_id)
        is_vice = vice_id is not None and pid == int(vice_id)
        picks.append({
            "element": pid,
            "position": pos,
            "multiplier": 2 if is_cap else 1,
            "is_captain": bool(is_cap),
            "is_vice_captain": bool(is_vice),
        })
    for offset, pid in enumerate(bench):
        picks.append({
            "element": pid,
            "position": 12 + offset,
            "multiplier": 0,
            "is_captain": False,
            "is_vice_captain": False,
        })

    return {
        "picks": picks,
        "entry_history": {
            "event": int(planning_event_id),
            "bank": BUDGET_TENTHS - total_cost,
            "value": total_cost,
            "event_transfers": 0,
        },
        "active_chip": None,
        "_source": "manual",
        "_pre_deadline": True,
        # Pre-first-deadline you have unlimited free transfers; the recommendations
        # layer reads this to switch off the FT/hit framing.
        "_free_transfers": None,
    }
