"""
Player match history built from the live gameweek endpoint.

The xG stack (``fixture_difficulty`` -> ``output_model`` -> ``expected_points``)
reads ``data/processed/fpl/*/player_match_history_*.csv``. Until now the only
producer was ``season_history.main()``, a CLI that pulls ``/element-summary/{id}/``
once per player -- ~620 upstream calls -- and was never run on a server. So every
deployment started with an empty volume and the whole model silently disabled.

``/api/event/{gw}/live/`` carries the same expected-goals figures for every
player in a single request, which makes keeping the file current cheap enough to
do inside ``/admin/refresh``: one call per finished gameweek that isn't on disk
yet, and none at all once it has caught up.

Attribution: ``explain`` names the fixture a player's return came from, so a
normal gameweek maps exactly. A double gameweek aggregates both fixtures into one
``stats`` block, so the totals are split across fixtures in proportion to minutes
played -- approximate, but only for the minority of players in a DGW, and far
better than dropping them.
"""

import pandas as pd

try:
    from . import fpl_client
except Exception:  # pragma: no cover - flat script usage
    import fpl_client  # type: ignore


# Columns the model reads. `expected_goals` and `expected_assists` drive the
# player rates; `defensive_contribution` drives the DC term.
NUMERIC_STATS = [
    "minutes",
    "expected_goals",
    "expected_assists",
    "expected_goals_conceded",
    "defensive_contribution",
    "saves",
    "total_points",
    "bps",
    "starts",
]

COLUMNS = ["element", "element_type", "team_id", "fixture", "event", "was_home",
           "kickoff_time"] + NUMERIC_STATS


def _fixture_ids(explain):
    out = []
    for entry in explain or []:
        fid = (entry or {}).get("fixture")
        if fid is not None:
            out.append(int(fid))
    return out


def _minutes_by_fixture(explain):
    """Minutes per fixture from the explain block, used to split a DGW."""
    out = {}
    for entry in explain or []:
        fid = (entry or {}).get("fixture")
        if fid is None:
            continue
        for stat in (entry or {}).get("stats") or []:
            if (stat or {}).get("identifier") == "minutes":
                try:
                    out[int(fid)] = float(stat.get("value") or 0.0)
                except (TypeError, ValueError):
                    out[int(fid)] = 0.0
    return out


def _fixture_lookup(fixtures):
    """{fixture_id: {"event", "team_h", "team_a", "kickoff_time"}}"""
    lookup = {}
    if fixtures is None or getattr(fixtures, "empty", True):
        return lookup
    for _, r in fixtures.iterrows():
        fid = pd.to_numeric(r.get("id"), errors="coerce")
        if pd.isna(fid):
            continue
        lookup[int(fid)] = {
            "event": pd.to_numeric(r.get("event"), errors="coerce"),
            "team_h": pd.to_numeric(r.get("team_h"), errors="coerce"),
            "team_a": pd.to_numeric(r.get("team_a"), errors="coerce"),
            "kickoff_time": r.get("kickoff_time"),
        }
    return lookup


def build_event_rows(live_elements, bootstrap, fixtures, event_id):
    """
    One row per (player, fixture) for a single gameweek.

    Returns an empty frame -- never raises -- when the gameweek has no usable
    data, so a refresh can skip it and carry on.
    """
    if not live_elements:
        return pd.DataFrame(columns=COLUMNS)

    meta = {}
    for e in (bootstrap or {}).get("elements", []) or []:
        pid = pd.to_numeric(e.get("id"), errors="coerce")
        if pd.isna(pid):
            continue
        meta[int(pid)] = (
            pd.to_numeric(e.get("team"), errors="coerce"),
            pd.to_numeric(e.get("element_type"), errors="coerce"),
        )

    fixtures_by_id = _fixture_lookup(fixtures)
    rows = []

    for el in live_elements:
        pid = pd.to_numeric((el or {}).get("id"), errors="coerce")
        if pd.isna(pid):
            continue
        pid = int(pid)
        stats = (el or {}).get("stats") or {}
        if not float(pd.to_numeric(stats.get("minutes"), errors="coerce") or 0.0):
            continue  # didn't play: contributes nothing to a rate

        team_id, element_type = meta.get(pid, (None, None))
        if team_id is None or pd.isna(team_id):
            continue
        team_id = int(team_id)

        fids = [f for f in _fixture_ids(el.get("explain")) if f in fixtures_by_id]
        if not fids:
            continue

        # Split a double gameweek by minutes; a single fixture takes everything.
        mins = _minutes_by_fixture(el.get("explain"))
        total_mins = sum(mins.get(f, 0.0) for f in fids)
        for fid in fids:
            share = 1.0 if len(fids) == 1 else (
                (mins.get(fid, 0.0) / total_mins) if total_mins > 0 else 1.0 / len(fids)
            )
            fx = fixtures_by_id[fid]
            row = {
                "element": pid,
                "element_type": int(element_type) if pd.notna(element_type) else None,
                "team_id": team_id,
                "fixture": fid,
                "event": int(event_id),
                "was_home": bool(pd.notna(fx["team_h"]) and int(fx["team_h"]) == team_id),
                "kickoff_time": fx["kickoff_time"],
            }
            for col in NUMERIC_STATS:
                value = pd.to_numeric(stats.get(col), errors="coerce")
                row[col] = float(value) * share if pd.notna(value) else 0.0
            rows.append(row)

    return pd.DataFrame(rows, columns=COLUMNS)


def finished_event_ids(bootstrap):
    """Gameweeks safe to append. In-progress GWs report zeroed ICT columns and
    can still change, so only finished ones are recorded."""
    out = []
    for e in (bootstrap or {}).get("events", []) or []:
        if not e.get("finished"):
            continue
        eid = pd.to_numeric(e.get("id"), errors="coerce")
        if pd.notna(eid):
            out.append(int(eid))
    return sorted(out)


def missing_event_ids(existing, bootstrap):
    """Finished gameweeks not already present in the history frame."""
    finished = finished_event_ids(bootstrap)
    if existing is None or getattr(existing, "empty", True) or "event" not in getattr(existing, "columns", []):
        return finished
    have = set(pd.to_numeric(existing["event"], errors="coerce").dropna().astype(int).tolist())
    return [gw for gw in finished if gw not in have]


def append_events(existing, bootstrap, fixtures, event_ids, fetch=None):
    """
    Fetch each gameweek and append it to ``existing``.

    A gameweek that fails upstream is skipped rather than aborting the rest --
    partial history is worth more than none.
    """
    fetch = fetch or fpl_client.get_event_live_elements
    frames = []
    if existing is not None and not getattr(existing, "empty", True):
        frames.append(existing)
    added = []
    for gw in event_ids:
        try:
            rows = build_event_rows(fetch(gw), bootstrap, fixtures, gw)
        except Exception:
            continue
        if not rows.empty:
            frames.append(rows)
            added.append(int(gw))
    if not frames:
        return pd.DataFrame(columns=COLUMNS), added
    out = pd.concat(frames, ignore_index=True)
    if {"element", "fixture"}.issubset(out.columns):
        out = out.drop_duplicates(subset=["element", "fixture"], keep="last")
    return out.reset_index(drop=True), added
