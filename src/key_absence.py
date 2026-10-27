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
    appearance for this club are kept (the upper bound only when he later
    plays for another club), so a mid-season signing or sale is not read as
    an injury absence while a season-ending injury still is. Adds ``bucket``
    and ``key_xg``.
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
    lo = min(appear)
    # Upper bound only when the player later turns out for another club:
    # a sale ends his window, a season-ending injury does not.
    later_elsewhere = df[(df["element"] == player_id) & (df["team_id"] != team_id)
                         & (df["minutes"] > 0)]
    last_here = played["event"].max()
    if not later_elsewhere.empty and later_elsewhere["event"].max() > last_here:
        hi = max(appear)
        fx = fx[fx["fixture"].map(pos_of).between(lo, hi)].copy()
    else:
        fx = fx[fx["fixture"].map(pos_of) >= lo].copy()

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


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

SELECTION_MIN_MINUTES = 270.0
GOALKEEPER = 1


def select_key_players(signals, top=3, min_minutes=SELECTION_MIN_MINUTES, overrides=None):
    """
    Top ``top`` outfield players per team by rank-sum of threat/90,
    creativity/90, price, last-season ppg and this-season ppg (equal weights,
    higher is better, NaN ranks last). Rates, not totals, so a player's own
    absences cannot push him off the list; under ``min_minutes`` the two
    rates are NaN and he competes on the other three. Ties break by minutes.
    ``overrides[team_id]`` replaces that team's list verbatim.
    """
    out = {}
    if signals is None or signals.empty:
        return dict(overrides or {})
    s = signals.copy()
    for c in ("minutes", "threat", "creativity", "now_cost", "last_ppg", "this_ppg"):
        s[c] = pd.to_numeric(s.get(c), errors="coerce")
    s = s[pd.to_numeric(s["element_type"], errors="coerce") != GOALKEEPER]
    mins = s["minutes"].fillna(0.0)
    enough = mins >= float(min_minutes)
    s["threat90"] = (s["threat"] / mins * 90.0).where(enough)
    s["creativity90"] = (s["creativity"] / mins * 90.0).where(enough)
    rank_cols = ["threat90", "creativity90", "now_cost", "last_ppg", "this_ppg"]
    for team_id, g in s.groupby("team_id"):
        score = sum(g[c].rank(ascending=False, na_option="bottom") for c in rank_cols)
        g = g.assign(_score=score, _mins=mins.loc[g.index])
        g = g.sort_values(["_score", "_mins"], ascending=[True, False])
        out[int(team_id)] = [int(p) for p in g["player_id"].head(int(top))]
    for team_id, players in (overrides or {}).items():
        out[int(team_id)] = [int(p) for p in players]
    return out


PLACEBO_MIN_START_SHARE = 0.5


def select_placebo(df, key, team_fx, min_start_share=PLACEBO_MIN_START_SHARE):
    """
    Per team: every outfield non-key player who started at least
    ``min_start_share`` of the team's played fixtures. Pooled together they
    give the placebo enough absences to compare against (one ever-present
    centre-back per team did not).
    """
    out = {}
    if df is None or df.empty or team_fx is None or team_fx.empty:
        return out
    played_n = team_fx.groupby("team_id")["fixture"].nunique()
    outfield = df[(df["element_type"] != GOALKEEPER) & (df["starts"] >= 1) & (df["minutes"] > 0)]
    starts = outfield.groupby(["team_id", "element"])["fixture"].nunique().reset_index(name="n_starts")
    for team_id, g in starts.groupby("team_id"):
        n = played_n.get(int(team_id), 0)
        if not n:
            continue
        banned = set(key.get(int(team_id), []))
        g = g[(~g["element"].isin(banned)) & (g["n_starts"] >= float(min_start_share) * n)]
        if not g.empty:
            out[int(team_id)] = sorted(int(p) for p in g["element"])
    return out


# ---------------------------------------------------------------------------
# Team effect with fixture expectation
# ---------------------------------------------------------------------------

def attach_expected(buckets, ratings, fixtures):
    """
    Add ``opp_id``, ``expected_for`` (opponent-defence and venue controlled,
    via ``fixture_difficulty.expected_xg_for_fixture``), ``team_ratio`` and
    ``teammates_ratio`` (team xG minus the key player's own, over expected).
    """
    from src import fixture_difficulty as fd

    out = buckets.copy()
    if out.empty:
        for c in ("opp_id", "expected_for", "team_ratio", "teammates_ratio"):
            out[c] = pd.Series(dtype="float64")
        return out
    pair = {}
    for fx in fixtures or []:
        fid = pd.to_numeric(fx.get("id"), errors="coerce")
        if pd.notna(fid):
            pair[int(fid)] = (fx.get("team_h"), fx.get("team_a"))
    opp, exp = [], []
    for tid, fid, home in zip(out["team_id"], out["fixture"], out["was_home"]):
        h, a = pair.get(int(fid), (None, None))
        o = a if (h is not None and int(h) == int(tid)) else h
        o = int(o) if o is not None else None
        opp.append(o)
        e, _ = fd.expected_xg_for_fixture(ratings, int(tid), o, bool(home))
        exp.append(e)
    out["opp_id"] = opp
    out["expected_for"] = exp
    denom = out["expected_for"].where(out["expected_for"] > 0)
    out["team_ratio"] = out["team_xg_for"] / denom
    out["teammates_ratio"] = (out["team_xg_for"] - out["key_xg"]) / denom
    return out


def team_effect(buckets):
    """Bucket means and absent/present effects; NaN effect when a bucket is empty."""
    def _mean(col, bucket):
        s = buckets.loc[buckets["bucket"] == bucket, col]
        return float(s.mean()) if len(s) else float("nan")

    def _ratio(a, b):
        return a / b if (b == b and a == a and b != 0) else float("nan")

    n = buckets["bucket"].value_counts() if not buckets.empty else {}
    tr_p, tr_a = _mean("team_ratio", "present"), _mean("team_ratio", "absent")
    tm_p, tm_a = _mean("teammates_ratio", "present"), _mean("teammates_ratio", "absent")
    return {
        "n_present": int(n.get("present", 0)),
        "n_absent": int(n.get("absent", 0)),
        "n_benched": int(n.get("benched", 0)),
        "team_ratio_present": tr_p, "team_ratio_absent": tr_a,
        "teammates_ratio_present": tm_p, "teammates_ratio_absent": tm_a,
        "team_effect": _ratio(tr_a, tr_p),
        "teammates_effect": _ratio(tm_a, tm_p),
        "xg_for_present": _mean("team_xg_for", "present"),
        "xg_for_absent": _mean("team_xg_for", "absent"),
    }


# ---------------------------------------------------------------------------
# Teammate rates, pooling, shrinkage, decision
# ---------------------------------------------------------------------------

TEAMMATE_MIN_MINUTES = 180.0
SHRINK_K = 4.0
BOOTSTRAP_DRAWS = 2000
DECISION_BAR = 0.95


def teammate_rates(df, buckets, team_id, player_id, min_minutes=TEAMMATE_MIN_MINUTES):
    """
    Minutes-weighted xG90 / xA90 of every other player on the team in the
    key player's present vs absent fixtures; only teammates with at least
    ``min_minutes`` in both buckets.
    """
    cols = ["teammate_id", "element_type", "min_present", "min_absent",
            "xg90_present", "xg90_absent", "xa90_present", "xa90_absent",
            "xg90_ratio", "xa90_ratio"]
    if buckets is None or buckets.empty:
        return pd.DataFrame(columns=cols)
    bucket_of = dict(zip(buckets["fixture"], buckets["bucket"]))
    mates = df[(df["team_id"] == int(team_id)) & (df["element"] != int(player_id))].copy()
    mates["bucket"] = mates["fixture"].map(bucket_of)
    mates = mates[mates["bucket"].isin(["present", "absent"])]
    if mates.empty:
        return pd.DataFrame(columns=cols)
    agg = (mates.groupby(["element", "bucket"])
           .agg(minutes=("minutes", "sum"), xg=("expected_goals", "sum"),
                xa=("expected_assists", "sum"), element_type=("element_type", "first"))
           .reset_index())
    rows = []
    for pid, g in agg.groupby("element"):
        g = g.set_index("bucket")
        if not {"present", "absent"}.issubset(g.index):
            continue
        p, a = g.loc["present"], g.loc["absent"]
        if p["minutes"] < min_minutes or a["minutes"] < min_minutes:
            continue
        xg90_p, xg90_a = p["xg"] / p["minutes"] * 90.0, a["xg"] / a["minutes"] * 90.0
        xa90_p, xa90_a = p["xa"] / p["minutes"] * 90.0, a["xa"] / a["minutes"] * 90.0
        rows.append({
            "teammate_id": int(pid), "element_type": int(p["element_type"]),
            "min_present": float(p["minutes"]), "min_absent": float(a["minutes"]),
            "xg90_present": xg90_p, "xg90_absent": xg90_a,
            "xa90_present": xa90_p, "xa90_absent": xa90_a,
            "xg90_ratio": xg90_a / xg90_p if xg90_p > 0 else float("nan"),
            "xa90_ratio": xa90_a / xa90_p if xa90_p > 0 else float("nan"),
        })
    return pd.DataFrame(rows, columns=cols)


def pool_effects(rows, key="teammates_effect", weight_key="n_absent",
                 draws=BOOTSTRAP_DRAWS, seed=0):
    """Weighted mean of ``key`` across (team, player) rows with a bootstrap 90% interval."""
    import numpy as np

    vals, wts = [], []
    for r in rows:
        v, w = r.get(key), r.get(weight_key, 0)
        if v is None or v != v or not w or w <= 0:
            continue
        vals.append(float(v)); wts.append(float(w))
    if not vals:
        return {"effect": float("nan"), "n": 0.0, "lo": float("nan"), "hi": float("nan"), "pairs": 0}
    v, w = np.asarray(vals), np.asarray(wts)
    effect = float((v * w).sum() / w.sum())
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(v), size=(int(draws), len(v)))
    boots = (v[idx] * w[idx]).sum(axis=1) / w[idx].sum(axis=1)
    lo, hi = np.percentile(boots, [5, 95])
    return {"effect": effect, "n": float(w.sum()), "lo": float(lo), "hi": float(hi), "pairs": len(v)}


def shrink(raw, n, pooled, k=SHRINK_K):
    """``(n*raw + k*pooled) / (n+k)``; a NaN raw counts as n = 0."""
    if raw is None or raw != raw:
        n = 0.0
        raw = 0.0
    return (float(n) * float(raw) + float(k) * float(pooled)) / (float(n) + float(k))


def decision(key_pool, placebo_pool, bar=DECISION_BAR):
    """Signal is real iff the placebo mean sits outside the key 90% interval and key effect < bar."""
    eff, lo, hi = key_pool.get("effect"), key_pool.get("lo"), key_pool.get("hi")
    plc = placebo_pool.get("effect")
    if any(x is None or x != x for x in (eff, lo, hi, plc)):
        return False, "insufficient data (NaN pooled effect)"
    outside = not (lo <= plc <= hi)
    below = eff < bar
    ok = outside and below
    why = (f"key pooled {eff:.3f} [{lo:.3f}, {hi:.3f}] vs placebo {plc:.3f}: "
           f"{'placebo outside interval' if outside else 'placebo inside interval'}, "
           f"{'below' if below else 'not below'} bar {bar:.2f}")
    return ok, why


# ---------------------------------------------------------------------------
# Selection signals, overrides, orchestration
# ---------------------------------------------------------------------------

LAST_SEASON_MIN_APPS = 10


def _appearances(df):
    """Appearances with minutes per player (element -> count)."""
    if df is None or df.empty:
        return {}
    return df[df["minutes"] > 0].groupby("element").size().to_dict()


def build_signals(df, bootstrap, last_season_df=None, last_bootstrap=None):
    """
    One row per player for ``select_key_players``: bootstrap rates/price,
    this-season ppg from the history frame, last-season ppg joined on the
    stable bootstrap ``code`` (element ids are reissued each season).
    """
    apps = _appearances(df)
    last_ppg_by_code = {}
    if last_season_df is not None and not last_season_df.empty and last_bootstrap:
        code_of = {int(e["id"]): e.get("code") for e in last_bootstrap.get("elements", [])}
        played = last_season_df[last_season_df["minutes"] > 0]
        pts = pd.to_numeric(played.get("total_points"), errors="coerce").fillna(0.0)
        g = played.assign(_pts=pts).groupby("element")["_pts"].agg(["sum", "size"])
        for eid, r in g.iterrows():
            if r["size"] >= LAST_SEASON_MIN_APPS and code_of.get(int(eid)) is not None:
                last_ppg_by_code[code_of[int(eid)]] = float(r["sum"] / r["size"])
    rows = []
    for e in bootstrap.get("elements", []):
        pid = int(e["id"])
        n = apps.get(pid, 0)
        tp = float(pd.to_numeric(e.get("total_points"), errors="coerce") or 0.0)
        rows.append({
            "player_id": pid, "team_id": int(e["team"]), "element_type": int(e["element_type"]),
            "minutes": float(pd.to_numeric(e.get("minutes"), errors="coerce") or 0.0),
            "threat": float(pd.to_numeric(e.get("threat"), errors="coerce") or 0.0),
            "creativity": float(pd.to_numeric(e.get("creativity"), errors="coerce") or 0.0),
            "now_cost": float(pd.to_numeric(e.get("now_cost"), errors="coerce") or 0.0),
            "last_ppg": last_ppg_by_code.get(e.get("code"), float("nan")),
            "this_ppg": tp / n if n else float("nan"),
        })
    return pd.DataFrame(rows)


def build_signals_from_history(df_raw):
    """
    Signals for a season with no bootstrap on hand (the 2025-26 file carries
    ``threat``, ``creativity``, ``value`` and ``total_points`` per match).
    Season totals, identical treatment for every player; ``last_ppg`` NaN.
    """
    d = df_raw.copy()
    for c in ("minutes", "threat", "creativity", "value", "total_points"):
        d[c] = pd.to_numeric(d.get(c), errors="coerce").fillna(0.0)
    ko = "kickoff_time" if "kickoff_time" in d.columns else "kickoff_time_x"
    d = d.sort_values(ko) if ko in d.columns else d
    played = d[d["minutes"] > 0]
    g = d.groupby("element").agg(
        team_id=("team_id", "last"), element_type=("element_type", "first"),
        minutes=("minutes", "sum"), threat=("threat", "sum"), creativity=("creativity", "sum"),
        now_cost=("value", "last"), total_points=("total_points", "sum"),
    )
    apps = played.groupby("element").size()
    g["this_ppg"] = g["total_points"] / apps.reindex(g.index)
    g["last_ppg"] = float("nan")
    g = g.reset_index().rename(columns={"element": "player_id"})
    g["team_id"] = g["team_id"].astype(int)
    g["element_type"] = g["element_type"].astype(int)
    return g[["player_id", "team_id", "element_type", "minutes", "threat", "creativity",
              "now_cost", "last_ppg", "this_ppg"]]


def _norm(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).strip().lower()


def parse_overrides(spec, bootstrap, teams_short_map):
    """``"CHE:João Pedro,Palmer;ARS:Saka"`` -> {team_id: [player ids]}; accent-insensitive."""
    if not spec:
        return {}
    short_to_id = {str(v).upper(): int(k) for k, v in teams_short_map.items()}
    by_team = {}
    for e in bootstrap.get("elements", []):
        by_team.setdefault(int(e["team"]), {})[_norm(e.get("web_name"))] = int(e["id"])
    out = {}
    for chunk in spec.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        short, _, names = chunk.partition(":")
        tid = short_to_id.get(short.strip().upper())
        if tid is None:
            raise ValueError(f"{short.strip()}: unknown team")
        ids = []
        for name in names.split(","):
            pid = by_team.get(tid, {}).get(_norm(name))
            if pid is None:
                raise ValueError(f"{short.strip()}: no player named {name.strip()}")
            ids.append(pid)
        out[tid] = ids
    return out


def run_analysis(df, fixtures, ratings, key, placebo, teams_short_map, names):
    """Everything per (team, key player) plus placebo, pools, shrinkage, decision."""
    team_fx = team_fixture_sets(df)

    def _one(team_id, pid):
        b = attach_expected(presence_buckets(df, team_fx, team_id, pid), ratings, fixtures)
        eff = team_effect(b)
        eff.update({"team_id": int(team_id), "team_short": teams_short_map.get(int(team_id), str(team_id)),
                    "player_id": int(pid), "player_name": names.get(int(pid), str(pid))})
        return b, eff

    team_rows, teammate_rows = [], []
    for team_id, pids in key.items():
        for pid in pids:
            b, eff = _one(team_id, pid)
            team_rows.append(eff)
            tm = teammate_rates(df, b, team_id, pid)
            for r in tm.to_dict("records"):
                r.update({"team_id": int(team_id), "team_short": eff["team_short"],
                          "key_player_id": int(pid), "key_player_name": eff["player_name"],
                          "teammate_name": names.get(int(r["teammate_id"]), str(r["teammate_id"]))})
                teammate_rows.append(r)
    placebo_rows = [_one(t, p)[1] for t, pids in placebo.items() for p in pids]

    key_pool = pool_effects(team_rows)
    placebo_pool = pool_effects(placebo_rows)
    for r in team_rows:
        r["shrunk_teammates_effect"] = shrink(r["teammates_effect"], r["n_absent"], key_pool["effect"])
    return {
        "team_rows": team_rows, "teammate_rows": teammate_rows, "placebo_rows": placebo_rows,
        "key_pool": key_pool, "placebo_pool": placebo_pool,
        "decision": decision(key_pool, placebo_pool),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _f(x, nd=3):
    return "n/a" if x is None or x != x else f"{float(x):.{nd}f}"


def render_report(result, season, key, names, teams_short_map, caveats):
    """Markdown report in spec order: selection, pooled decision, per-team table, movers, caveats."""
    kp, pp = result["key_pool"], result["placebo_pool"]
    ok, why = result["decision"]
    lines = [f"# Key-player absence analysis — {season}", ""]

    lines += ["## Key players (top per team)", ""]
    for tid in sorted(key, key=lambda t: teams_short_map.get(t, str(t))):
        lines.append(f"- **{teams_short_map.get(tid, tid)}**: "
                     + ", ".join(names.get(p, str(p)) for p in key[tid]))
    lines.append("")

    lines += ["## League pool: key players vs placebo", "",
              "| | effect (teammates xG / expected) | 90% interval | n absent matches | pairs |",
              "|---|---|---|---|---|",
              f"| key players | {_f(kp['effect'])} | [{_f(kp['lo'])}, {_f(kp['hi'])}] | {kp['n']:.0f} | {kp['pairs']} |",
              f"| placebo | {_f(pp['effect'])} | [{_f(pp['lo'])}, {_f(pp['hi'])}] | {pp['n']:.0f} | {pp['pairs']} |",
              "", f"**Decision: {'PASS' if ok else 'FAIL'}** — {why}", "",
              "Effect < 1 means teammates produce less xG (per expected, opponent/venue controlled) "
              "when the key player is out. Phase 2 requires PASS on 2025-26.", ""]

    lines += ["## Per team, per key player (sorted by shrunk effect)", "",
              "| team | key player | present | absent | benched | teammates effect | shrunk | whole-team effect | xG/match present | xG/match absent |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    rows = sorted(result["team_rows"], key=lambda r: (r["shrunk_teammates_effect"] != r["shrunk_teammates_effect"],
                                                       r["shrunk_teammates_effect"]))
    for r in rows:
        lines.append(f"| {r['team_short']} | {r['player_name']} | {r['n_present']} | {r['n_absent']} | {r['n_benched']} | "
                     f"{_f(r['teammates_effect'])} | {_f(r['shrunk_teammates_effect'])} | {_f(r['team_effect'])} | "
                     f"{_f(r['xg_for_present'], 2)} | {_f(r['xg_for_absent'], 2)} |")
    lines.append("")

    lines += ["## Teammate movers (xG90+xA90 absent / present; ≥180 min both buckets)", ""]
    by_key = {}
    for t in result["teammate_rows"]:
        by_key.setdefault((t["team_short"], t["key_player_name"]), []).append(t)
    for (short, kname), ts in sorted(by_key.items()):
        def _xgi_ratio(t):
            p = t["xg90_present"] + t["xa90_present"]
            a = t["xg90_absent"] + t["xa90_absent"]
            return a / p if p > 0 else float("nan")
        scored = [(t, _xgi_ratio(t)) for t in ts]
        scored = [s for s in scored if s[1] == s[1]]
        scored.sort(key=lambda s: s[1])
        down = scored[:5]
        up = list(reversed(scored[-5:]))
        lines.append(f"### {short} without {kname}")
        lines.append("")
        lines.append("| teammate | min present | min absent | xGI90 present | xGI90 absent | ratio |")
        lines.append("|---|---|---|---|---|---|")
        seen = set()
        for t, ratio in down + up:
            if t["teammate_id"] in seen:
                continue
            seen.add(t["teammate_id"])
            lines.append(f"| {t['teammate_name']} | {t['min_present']:.0f} | {t['min_absent']:.0f} | "
                         f"{_f(t['xg90_present'] + t['xa90_present'], 2)} | "
                         f"{_f(t['xg90_absent'] + t['xa90_absent'], 2)} | {_f(ratio, 2)} |")
        lines.append("")

    lines += ["## Caveats", ""] + [f"- {c}" for c in caveats] + [""]
    return "\n".join(lines)
