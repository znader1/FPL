"""Availability-adjusted team strength (2026-10-26 calibration spec, part 2).

Pure functions. FPL status / chance gives each player a play probability; his
share of his team's recent output says how much the team loses without him.

* attack share  = his (xG + xA) / the team's, over the team's last
  AVAIL_SHARE_WINDOW_MATCHES matches before the GW being projected;
* defence share = for keepers and defenders, his minutes / the team's keeper +
  defender minutes over the same window.

Missing share per team and GW = Σ share × (1 − play probability), where a doubt
counts only in the first GW (see ``_missing_rows``).
"""
from __future__ import annotations

import pandas as pd

from src import config

OUT_STATUSES = {"i", "s", "u", "n"}


def play_probability(elements):
    """Series indexed by element id: P(plays) from FPL status + chance."""
    status = elements["status"].astype(str).str.lower()
    chance = pd.to_numeric(elements["chance_of_playing_next_round"], errors="coerce") / 100.0
    p = chance.fillna(1.0)
    p = p.where(status != "d", chance.fillna(float(config.AVAIL_DOUBT_DEFAULT_CHANCE)))
    p = p.where(~status.isin(OUT_STATUSES), 0.0)
    return pd.Series(p.clip(0.0, 1.0).values, index=pd.to_numeric(elements["id"], errors="coerce").astype(int))


def team_shares(match_df, gw_start):
    cols = ["element", "team_id", "attack_share", "defence_share"]
    if match_df is None or match_df.empty:
        return pd.DataFrame(columns=cols)
    m = match_df.copy()
    m = m[pd.to_numeric(m["event"], errors="coerce") < int(gw_start)]
    if m.empty:
        return pd.DataFrame(columns=cols)
    for c in ("minutes", "expected_goals", "expected_assists"):
        m[c] = pd.to_numeric(m[c], errors="coerce").fillna(0.0)
    m["xgi"] = m["expected_goals"] + m["expected_assists"]
    m["back"] = pd.to_numeric(m["element_type"], errors="coerce").isin([1, 2])
    out = []
    window = int(config.AVAIL_SHARE_WINDOW_MATCHES)
    for team, g in m.groupby("team_id"):
        events = sorted(pd.to_numeric(g["event"], errors="coerce").dropna().unique())[-window:]
        g = g[pd.to_numeric(g["event"], errors="coerce").isin(events)]
        xgi_total = float(g["xgi"].sum())
        back_minutes = float(g.loc[g["back"], "minutes"].sum())
        per = g.groupby("element").agg(xgi=("xgi", "sum"), minutes=("minutes", "sum"), back=("back", "max"))
        for el, r in per.iterrows():
            out.append({
                "element": int(el), "team_id": int(team),
                "attack_share": float(r["xgi"]) / xgi_total if xgi_total > 0 else 0.0,
                "defence_share": float(r["minutes"]) / back_minutes if (bool(r["back"]) and back_minutes > 0) else 0.0,
            })
    return pd.DataFrame(out, columns=cols)


DOUBT_STATUSES = {"d"}
GONE_STATUSES = {"u"}   # left the club / not registered: his old club's xG already lacks him


def _missing_rows(shares, elements, first_gw):
    """shares joined to each player's missing fraction for one GW.

    A doubt (``d``, or ``a`` with a published chance below 100) is a next-GW
    question: it counts (1 − p) in the first GW and nothing after. Injured /
    suspended / unavailable (``i``/``s``/``n``) count in every GW. A departed
    player (``u``) and a share earned at another club count nothing.
    """
    cols = ["element", "team_id", "attack_share", "defence_share", "missing"]
    if shares is None or shares.empty:
        return pd.DataFrame(columns=cols)
    ids = pd.to_numeric(elements["id"], errors="coerce").astype(int)
    p = play_probability(elements)
    status = pd.Series(elements["status"].astype(str).str.lower().values, index=ids.values)
    team = pd.Series(pd.to_numeric(elements["team"], errors="coerce").values, index=ids.values)
    chance = pd.Series(pd.to_numeric(elements["chance_of_playing_next_round"], errors="coerce").values,
                       index=ids.values)
    d = shares[shares["element"].isin(p.index)].copy()
    d = d[d["element"].map(team) == d["team_id"]]
    st = d["element"].map(status)
    d = d[~st.isin(GONE_STATUSES)]
    st = d["element"].map(status)
    doubt = st.isin(DOUBT_STATUSES) | ((st == "a") & (d["element"].map(chance) < 100))
    gone = 1.0 - d["element"].map(p)
    d["missing"] = (gone.where(~doubt, gone if first_gw else 0.0)).fillna(0.0)
    return d[cols]


def team_missing(shares, elements, first_gw=True):
    d = _missing_rows(shares, elements, first_gw)
    out = {}
    for team, g in d.groupby("team_id"):
        attack = float((g["attack_share"] * g["missing"]).sum())
        defence = float((g["defence_share"] * g["missing"]).sum())
        if attack > 0 or defence > 0:
            out[int(team)] = {"attack": attack, "defence": defence}
    return out


def missing_by_gw(shares, elements, gws):
    """{gw: team_missing} — the first GW carries the doubts, later GWs don't."""
    gws = [int(g) for g in gws]
    first = team_missing(shares, elements, first_gw=True)
    rest = team_missing(shares, elements, first_gw=False) if len(gws) > 1 else {}
    return {g: (first if i == 0 else rest) for i, g in enumerate(gws)}


def apply_to_ratings(ratings, missing):
    lo, hi = float(config.FDR_RATING_MIN), float(config.FDR_RATING_MAX)
    out = {}
    for team, r in (ratings or {}).items():
        if not isinstance(r, dict):
            out[team] = r          # league-level entries (averages, meta) pass through
            continue
        r = dict(r)
        try:
            miss = (missing or {}).get(int(team))
        except (TypeError, ValueError):
            miss = None
        if miss:
            r["attack"] = min(hi, max(lo, float(r.get("attack", 1.0)) * (1 - float(config.AVAIL_ATTACK_IMPACT) * miss["attack"])))
            r["defense"] = min(hi, max(lo, float(r.get("defense", 1.0)) * (1 + float(config.AVAIL_DEF_IMPACT) * miss["defence"])))
        out[team] = r
    return out


def teammate_multiplier(shares, elements, missing, first_gw=True):
    ids = pd.to_numeric(elements["id"], errors="coerce").astype(int)
    mult = pd.Series(1.0, index=ids.values)
    d = _missing_rows(shares, elements, first_gw)
    own = dict(zip(d["element"], d["attack_share"] * d["missing"])) if not d.empty else {}
    teams = pd.to_numeric(elements["team"], errors="coerce").values
    etype = pd.to_numeric(elements["element_type"], errors="coerce").values
    floor = float(config.AVAIL_TEAMMATE_FLOOR)
    impact = float(config.AVAIL_TEAMMATE_IMPACT)
    for pid, team, et in zip(ids.values, teams, etype):
        if et not in (3, 4) or pd.isna(team):
            continue
        team_attack = float(((missing or {}).get(int(team)) or {}).get("attack", 0.0))
        others = max(0.0, team_attack - float(own.get(int(pid), 0.0)))
        if others > 0:
            mult.loc[pid] = max(floor, 1.0 - impact * others)
    return mult
