"""Player-level knowledge layer for the squad picker (news/injury-derived).

Mirrors the team-level knowledge rail (fixture_difficulty.apply_knowledge_discount
+ knowledge_discount.json) but at the player axis: availability, injury
return-GW, and a minutes/rotation multiplier. Pure + dependency-injectable;
degrades to empty knowledge when the file is missing or malformed.
"""
import json
import unicodedata

import pandas as pd

from src import config

EMPTY = {"as_of": None, "players": {}}


def load_player_knowledge(path=None):
    """Read player_knowledge.json. Missing/unreadable/malformed -> EMPTY."""
    path = path or getattr(config, "PLAYER_KNOWLEDGE_PATH",
                           "data/models/player_knowledge.json")
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return {"as_of": None, "players": {}}
    if not isinstance(data, dict):
        return {"as_of": None, "players": {}}
    players = data.get("players")
    return {
        "as_of": data.get("as_of"),
        "players": players if isinstance(players, dict) else {},
    }


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip().lower()


def resolve_keys(pk, elements):
    """Map knowledge keys to player ids. Numeric keys pass through; non-numeric
    keys are matched to elements' web_name (accent/case-insensitive). Returns
    (by_id: {int: entry}, notes: [str]) with a note per unresolved key."""
    players = (pk or {}).get("players", {}) or {}
    by_id = {}
    notes = []
    name_to_id = {}
    if elements is not None and "web_name" in elements.columns and "id" in elements.columns:
        for _, r in elements[["id", "web_name"]].iterrows():
            key = _norm(r["web_name"])
            name_to_id.setdefault(key, int(r["id"]))
    for k, entry in players.items():
        ks = str(k).strip()
        if ks.isdigit():
            by_id[int(ks)] = entry
            continue
        pid = name_to_id.get(_norm(ks))
        if pid is not None:
            by_id[pid] = entry
        else:
            notes.append(f"Unknown player in knowledge: '{k}' (not applied).")
    return by_id, notes


def staleness_note(as_of, stale_days, today=None):
    """Return a warning string when as_of is older than stale_days, else None.
    `today` is injectable for deterministic tests."""
    if not as_of:
        return None
    import datetime as _dt
    try:
        d = _dt.date.fromisoformat(str(as_of)[:10])
    except ValueError:
        return None
    today = today or _dt.date.today()
    age = (today - d).days
    if age > int(stale_days):
        return f"Player knowledge is {age} days old (as_of {as_of}); may be stale."
    return None


def merge_request(pk_file, request_pk):
    """Per-request player-knowledge overrides win over the file's entries."""
    file_players = (pk_file or {}).get("players", {}) or {}
    req_players = (request_pk or {}).get("players", {}) if request_pk else {}
    if not isinstance(req_players, dict):
        req_players = {}
    return {
        "as_of": (pk_file or {}).get("as_of"),
        "players": {**file_players, **req_players},
    }


def apply_to_projections(proj, gws, by_id):
    """Per player, per GW: ``xpts_gw{g} *= availability(gw) * minutes_mult``,
    where availability(gw) is 0 before an injury return-GW. Adds
    ``pk_availability`` (min over the horizon) + ``pk_note`` columns and
    recomputes ``xpts_horizon``. Players absent from ``by_id`` are untouched.

    Lifted out of squad_draft so every live recommendation path can share it —
    the squad picker downgraded injured players, the transfer decision card did
    not. Backtests and the replay builder must NOT call this: applying today's
    knowledge to a historical gameweek leaks the future into the result.
    """
    if not by_id:
        return proj
    proj = proj.copy()
    proj["pk_availability"] = pd.NA
    proj["pk_note"] = pd.NA
    for pid, entry in by_id.items():
        mask = proj["id"] == int(pid)
        if not mask.any():
            continue
        av = entry.get("availability")
        availability = 1.0 if av is None else float(av)
        mm = entry.get("minutes_mult")
        minutes_mult = 1.0 if mm is None else float(mm)
        from_gw = entry.get("available_from_gw")
        from_gw = int(from_gw) if from_gw not in (None, "") else None
        min_eff = 1.0
        for g in gws:
            avail_g = 0.0 if (from_gw is not None and int(g) < from_gw) else availability
            eff = avail_g * minutes_mult
            col = f"xpts_gw{g}"
            if col in proj.columns:
                proj.loc[mask, col] = pd.to_numeric(
                    proj.loc[mask, col], errors="coerce").fillna(0.0) * eff
            min_eff = min(min_eff, eff)
        proj.loc[mask, "pk_availability"] = round(min_eff, 3)
        proj.loc[mask, "pk_note"] = entry.get("note")
    xcols = [f"xpts_gw{g}" for g in gws if f"xpts_gw{g}" in proj.columns]
    if xcols:
        proj["xpts_horizon"] = proj[xcols].apply(
            pd.to_numeric, errors="coerce").fillna(0.0).sum(axis=1)
    return proj


def apply(proj, gws, request_pk=None, path=None, stale_days=None, today=None):
    """Load the knowledge file, merge per-request overrides, resolve keys to
    player ids and apply the result to ``proj``. Returns ``(proj, notes)``.

    The one call every live recommendation path needs. Never raises on a
    missing or malformed file — ``load_player_knowledge`` degrades to empty,
    and empty knowledge leaves ``proj`` untouched.
    """
    pk = merge_request(load_player_knowledge(path), request_pk)
    by_id, notes = resolve_keys(pk, proj)
    if stale_days is None:
        stale_days = getattr(config, "PLAYER_KNOWLEDGE_STALE_DAYS", 10)
    stale = staleness_note(pk.get("as_of"), stale_days, today=today)
    if stale:
        notes = notes + [stale]
    return apply_to_projections(proj, gws, by_id), notes
