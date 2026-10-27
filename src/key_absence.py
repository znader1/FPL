"""
Key-player absence analysis: does a team's attacking output (and its
teammates' xG/xA rates) move when one of its key players is missing?

Pure pandas, frame-in / frame-out, no I/O. The CLI in
``scripts/analyze_key_absence.py`` does loading and reporting. Design:
``docs/superpowers/specs/2026-10-27-key-absence-analysis-design.md``.
"""
from __future__ import annotations

import pandas as pd

COLUMNS = [
    "element", "element_type", "team_id", "fixture", "event", "was_home",
    "kickoff_time", "minutes", "starts", "expected_goals", "expected_assists",
]

MIN_ROWS_PER_TEAM_FIXTURE = 11


def normalize_history(match_df, fixtures):
    """
    Coerce either season's match-history schema to ``COLUMNS`` and drop rows
    whose ``team_id`` is not one of the fixture's two sides (the live-history
    producer assigns the current bootstrap team, so a transferred player's
    early rows sit under the wrong club).
    """
    if match_df is None or match_df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df = match_df.copy()
    if "kickoff_time" not in df.columns and "kickoff_time_x" in df.columns:
        df = df.rename(columns={"kickoff_time_x": "kickoff_time"})
    df = df.drop(columns=[c for c in ("kickoff_time_x", "kickoff_time_y") if c in df.columns])

    for col in ("element", "element_type", "team_id", "fixture", "event",
                "minutes", "starts", "expected_goals", "expected_assists"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["minutes"] = df["minutes"].fillna(0.0)
    if "expected_goals" not in df.columns:
        df["expected_goals"] = 0.0
    if "expected_assists" not in df.columns:
        df["expected_assists"] = 0.0
    df["expected_goals"] = df["expected_goals"].fillna(0.0)
    df["expected_assists"] = df["expected_assists"].fillna(0.0)
    if "starts" not in df.columns:
        df["starts"] = (df["minutes"] >= 60).astype(int)
    df["starts"] = df["starts"].fillna((df["minutes"] >= 60).astype(int))
    if "was_home" not in df.columns:
        df["was_home"] = False
    if "kickoff_time" not in df.columns:
        df["kickoff_time"] = pd.NaT

    df = df[df["element"].notna() & df["team_id"].notna() & df["fixture"].notna()].copy()
    for col in ("element", "team_id", "fixture"):
        df[col] = df[col].astype(int)

    pair = {}
    for fx in fixtures or []:
        fid = pd.to_numeric(fx.get("id"), errors="coerce")
        if pd.isna(fid):
            continue
        pair[int(fid)] = {
            int(t) for t in (fx.get("team_h"), fx.get("team_a"))
            if t is not None and pd.notna(pd.to_numeric(t, errors="coerce"))
        }
    if pair:
        keep = [tid in pair.get(fid, set()) for fid, tid in zip(df["fixture"], df["team_id"])]
        df = df[keep].copy()

    return df[COLUMNS].reset_index(drop=True)


def team_fixture_sets(df, min_rows=MIN_ROWS_PER_TEAM_FIXTURE):
    """
    One row per (team_id, fixture) the team actually played: at least
    ``min_rows`` players with minutes. Guards against partially scraped
    gameweeks (one-sided fixtures, zero-minute-only rows).

    Columns: team_id, fixture, event, was_home, team_xg_for.
    """
    cols = ["team_id", "fixture", "event", "was_home", "team_xg_for"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    played = df[df["minutes"] > 0]
    agg = (
        played.groupby(["team_id", "fixture"])
        .agg(
            n=("element", "size"),
            event=("event", "first"),
            was_home=("was_home", "first"),
            team_xg_for=("expected_goals", "sum"),
        )
        .reset_index()
    )
    agg = agg[agg["n"] >= int(min_rows)]
    return agg[cols].sort_values(["team_id", "fixture"]).reset_index(drop=True)


def presence_buckets(df, team_fx, team_id, player_id):
    """
    The team's played fixtures (from ``team_fixture_sets``) tagged by the key
    player's status: ``present`` (started), ``benched`` (played, no start),
    ``absent`` (zero minutes or no row at all -- the live-history producer
    omits non-players). Only fixtures between the player's first and last
    appearance for this club are kept, so a mid-season signing or sale is
    not read as an injury absence. Adds ``bucket`` and ``key_xg``.
    """
    cols = ["team_id", "fixture", "event", "was_home", "team_xg_for", "bucket", "key_xg"]
    team_id = int(team_id)
    player_id = int(player_id)
    fx = team_fx[team_fx["team_id"] == team_id].copy()
    if fx.empty:
        return pd.DataFrame(columns=cols)

    mine = df[(df["element"] == player_id) & (df["team_id"] == team_id)]
    played = mine[mine["minutes"] > 0]
    if played.empty:
        return pd.DataFrame(columns=cols)
    order = fx.sort_values(["event", "fixture"])[["fixture"]].reset_index(drop=True)
    order["pos"] = range(len(order))
    pos_of = dict(zip(order["fixture"], order["pos"]))
    appear = [pos_of[f] for f in played["fixture"] if f in pos_of]
    if not appear:
        return pd.DataFrame(columns=cols)
    lo, hi = min(appear), max(appear)
    fx = fx[fx["fixture"].map(pos_of).between(lo, hi)].copy()

    by_fixture = mine.set_index("fixture")
    buckets, key_xg = [], []
    for f in fx["fixture"]:
        if f in by_fixture.index:
            r = by_fixture.loc[f]
            mins = float(r["minutes"])
            if mins <= 0:
                buckets.append("absent"); key_xg.append(0.0)
            elif float(r["starts"]) >= 1:
                buckets.append("present"); key_xg.append(float(r["expected_goals"]))
            else:
                buckets.append("benched"); key_xg.append(float(r["expected_goals"]))
        else:
            buckets.append("absent"); key_xg.append(0.0)
    fx["bucket"] = buckets
    fx["key_xg"] = key_xg
    return fx[cols].sort_values(["event", "fixture"]).reset_index(drop=True)
