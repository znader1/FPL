"""
Injury prior from a status-history CSV the refresh appends (spec 4.6).

`append_status_snapshot` upserts one row per (event, element) with the
bootstrap's current status — last write for a GW wins, so a Friday flag
replaces Monday's 'a'. `player_injury_prior` turns that history into
p_miss = (#GWs with status i/d) / (#GWs on file + SHRINK) and an
injury_flag (current status i/d/s, or p_miss above 0.25). A missing file
is an empty frame; `attach` fills 0 / False so sums never see NaN.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import config

COLUMNS = ["event", "element", "status", "chance"]
MISS_STATUS = {"i", "d"}
FLAG_STATUS = {"i", "d", "s"}
FLAG_P_MISS = 0.25


def append_status_snapshot(bootstrap, event_id, path):
    """Upsert the bootstrap's player statuses for `event_id`. Returns rows written."""
    elements = (bootstrap or {}).get("elements") or []
    new = pd.DataFrame([
        {
            "event": int(event_id),
            "element": int(e["id"]),
            "status": str(e.get("status") or "a").lower(),
            "chance": e.get("chance_of_playing_next_round"),
        }
        for e in elements if e.get("id") is not None
    ], columns=COLUMNS)
    p = Path(path)
    if p.exists():
        try:
            old = pd.read_csv(p)
        except Exception:
            old = pd.DataFrame(columns=COLUMNS)
        old = old[[c for c in COLUMNS if c in old.columns]]
        old = old[~(pd.to_numeric(old["event"], errors="coerce") == int(event_id))]
        out = pd.concat([old, new], ignore_index=True)
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        out = new
    out = out.sort_values(["event", "element"]).reset_index(drop=True)
    out.to_csv(p, index=False)
    return int(len(new))


def player_injury_prior(path):
    """→ DataFrame[element, p_miss, injury_flag]; empty when the file is missing."""
    p = Path(path) if path else None
    if p is None or not p.exists():
        return pd.DataFrame(columns=["element", "p_miss", "injury_flag"])
    try:
        df = pd.read_csv(p)
    except Exception:
        return pd.DataFrame(columns=["element", "p_miss", "injury_flag"])
    if df.empty or "element" not in df.columns or "status" not in df.columns:
        return pd.DataFrame(columns=["element", "p_miss", "injury_flag"])
    df["status"] = df["status"].astype(str).str.lower()
    df["event"] = pd.to_numeric(df["event"], errors="coerce")
    df = df.sort_values(["element", "event"])
    shrink = float(config.CHIP_WILDCARD_INJURY_PRIOR_SHRINK_GWS)
    g = df.groupby("element")
    n = g.size()
    k = g["status"].apply(lambda s: int(s.isin(MISS_STATUS).sum()))
    last = g["status"].last()
    out = pd.DataFrame({"element": n.index.astype(int)})
    out["p_miss"] = (k.values / (n.values + shrink)).astype(float)
    out["injury_flag"] = (last.isin(FLAG_STATUS).values) | (out["p_miss"].values > FLAG_P_MISS)
    return out.reset_index(drop=True)


def attach(df, prior, id_col="id"):
    """Left-join the prior onto `df` by player id with 0 / False defaults."""
    out = df.copy()
    if prior is None or prior.empty:
        out["p_miss"] = 0.0
        out["injury_flag"] = False
        return out
    m = prior.rename(columns={"element": id_col})
    out = out.merge(m[[id_col, "p_miss", "injury_flag"]], on=id_col, how="left")
    out["p_miss"] = pd.to_numeric(out["p_miss"], errors="coerce").fillna(0.0)
    out["injury_flag"] = out["injury_flag"].fillna(False).astype(bool)
    return out
