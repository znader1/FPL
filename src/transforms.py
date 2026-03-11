# transforms.py
import pandas as pd

# Support both package and flat script usage
try:
    from . import config
except Exception:  # pragma: no cover
    import config  # type: ignore


# -----------------------------
# Bootstrap / elements wrangling
# -----------------------------
def tables_from_bootstrap(bootstrap):
    """
    Returns (elements, teams, element_types) with handy derived columns on elements:
    - team_name, team_short, pos
    - coerced numerics for common metrics
    """
    elements_raw = pd.DataFrame(bootstrap["elements"])
    keep_cols = [c for c in config.ELEMENTS_KEEP if c in elements_raw.columns]
    el = elements_raw[keep_cols].copy()

    teams = pd.DataFrame(bootstrap["teams"])
    etypes = pd.DataFrame(bootstrap["element_types"])

    teams_map = teams.set_index("id")["name"].to_dict()
    short_map = teams.set_index("id")["short_name"].to_dict()
    pos_map = etypes.set_index("id")["singular_name_short"].to_dict()

    el["team_name"] = el["team"].map(teams_map)
    el["team_short"] = el["team"].map(short_map)
    el["pos"] = el["element_type"].map(pos_map)

    # Coerce common numeric fields
    for c in [
        "total_points",
        "form",
        "points_per_game",
        "now_cost",
        "selected_by_percent",
        "ep_next",
        "minutes",
        "transfers_in_event",
        "transfers_out_event",
        "penalties_order",
        "direct_freekicks_order",
        "corners_and_indirect_freekicks_order",
    ]:
        if c in el.columns:
            el[c] = pd.to_numeric(el[c], errors="coerce")

    # Convenience price in millions
    if "now_cost" in el.columns:
        el["price_m"] = el["now_cost"] / 10.0

    return el, teams, etypes


def current_event(bootstrap):
    """
    Returns the current event id if available, otherwise the next event id, else None.
    """
    for ev in bootstrap.get("events", []):
        if ev.get("is_current"):
            return int(ev.get("id"))
    for ev in bootstrap.get("events", []):
        if ev.get("is_next"):
            return int(ev.get("id"))
    return None


# -----------------------------
# My team → DataFrame
# -----------------------------
def picks_to_df(myteam, elements):
    """
    Convert /api/my-team/{entry}/ JSON into a tidy squad DataFrame joined to element info.
    """
    picks = pd.DataFrame(myteam.get("picks", []))
    if picks.empty:
        return picks

    out = picks.merge(
        elements[["id", "web_name", "team", "team_name", "team_short", "pos"]],
        left_on="element",
        right_on="id",
        how="left",
    )
    out["is_captain"] = out["is_captain"].astype(bool)
    out["is_vice_captain"] = out["is_vice_captain"].astype(bool)
    out.rename(columns={"element": "player_id"}, inplace=True)

    cols = [c for c in config.SQUAD_COLUMNS if c in out.columns]
    return out[cols]


# -----------------------------
# Fixtures helpers
# -----------------------------
def fixtures_df(raw_fixtures):
    """
    Normalize fixtures list into a DataFrame; keep only rows with an event (scheduled).
    """
    fx = pd.DataFrame(raw_fixtures)
    if "event" in fx.columns:
        fx = fx[fx["event"].notna()].copy()
        fx["event"] = fx["event"].astype(int)
    return fx


def fixtures_string(
    fx,
    team_id,
    teams_short_map,
    gw_from,
    n,
):
    """
    Compact string of the next n fixtures for a team starting at gw_from.
    Example: 'GW6 H-AVL(D2) | GW7 A-MCI(D5)'
    """
    if fx.empty or gw_from is None:
        return ""
    view = fx[(fx["team_h"] == team_id) | (fx["team_a"] == team_id)].copy()
    view = view[view["event"] >= gw_from].sort_values("event").head(n)
    labels = []
    for _, r in view.iterrows():
        home = int(r["team_h"]) == int(team_id)
        opp = int(r["team_a"] if home else r["team_h"])
        opps = teams_short_map.get(opp, "?")
        diff_col = "team_h_difficulty" if home else "team_a_difficulty"
        diff = int(r.get(diff_col, 0) or 0)
        labels.append(f"GW{int(r['event'])} {'H' if home else 'A'}-{opps}(D{diff})")
    return " | ".join(labels)


def top_performers(
    elements,
    pos_filter,
    metric_label,
    topn,
    fx,
    teams_short_map,
    gw_from,
    nfx,
):
    """
    Rank players by a chosen metric and append a compact next-fixtures string.
    metric_label must exist in config.METRIC_MAP; falls back safely.
    """
    df = elements.copy()
    if pos_filter:
        df = df[df["pos"].isin(pos_filter)]

    col = config.METRIC_MAP.get(metric_label, "total_points")
    if col not in df.columns:
        # graceful fallback
        col = "total_points" if "total_points" in df.columns else None

    if col:
        df = df.sort_values(col, ascending=False)

    df = df.head(int(topn)).copy()
    df["next_fixtures"] = df.apply(
        lambda r: fixtures_string(fx, int(r["team"]), teams_short_map, gw_from, nfx), axis=1
    )

    keep = ["web_name", "pos", "team_short", "next_fixtures"]
    if col:
        keep.insert(3, col)  # after team_short
    keep = [c for c in keep if c in df.columns]
    out = df[keep].copy()
    if col and metric_label != col:
        out = out.rename(columns={col: metric_label})
    return out


# -----------------------------
# Next-GW players utilities
# -----------------------------
def fixtures_by_team_for_gw(fx, gw):
    """
    Returns {team_id: [ {opp,is_home,diff,event}, ... ]} for the given GW.
    Handles doubles by returning multiple entries per team.
    """
    out = {}
    if fx.empty:
        return out
    g = fx[fx["event"] == int(gw)]
    for _, r in g.iterrows():
        # home
        out.setdefault(int(r["team_h"]), []).append(
            {
                "opp": int(r["team_a"]),
                "is_home": True,
                "diff": int(r.get("team_h_difficulty", 0) or 0),
                "event": int(r["event"]),
            }
        )
        # away
        out.setdefault(int(r["team_a"]), []).append(
            {
                "opp": int(r["team_h"]),
                "is_home": False,
                "diff": int(r.get("team_a_difficulty", 0) or 0),
                "event": int(r["event"]),
            }
        )
    return out


def annotate_elements_with_gw_fixtures(
    elements,
    fx,
    gw,
    teams_short_map,
):
    """
    Adds per-player, team-based GW annotations:
      - gw_fixtures (e.g., 'H-AVL(D2) & A-MCI(D5)')
      - gw_fixture_count (int)
      - gw_diff_sum, gw_diff_avg
      - price_m (if available)
    """
    by_team = fixtures_by_team_for_gw(fx, int(gw))
    df = elements.copy()

    def label(team_id):
        lst = by_team.get(int(team_id), [])
        if not lst:
            return ""
        parts = []
        for it in lst:
            opp = teams_short_map.get(int(it["opp"]), "?")
            parts.append(f"{'H' if it['is_home'] else 'A'}-{opp}(D{int(it['diff'])})")
        return " & ".join(parts)

    def dsum(team_id):
        return int(sum(int(it["diff"]) for it in by_team.get(int(team_id), [])))

    def dcnt(team_id):
        return int(len(by_team.get(int(team_id), [])))

    df["gw_fixtures"] = df["team"].map(label)
    df["gw_fixture_count"] = df["team"].map(dcnt).fillna(0).astype(int)
    df["gw_diff_sum"] = df["team"].map(dsum).fillna(0).astype(int)
    # avoid division by zero
    df["gw_diff_avg"] = df.apply(
        lambda r: (r["gw_diff_sum"] / r["gw_fixture_count"]) if r["gw_fixture_count"] else 0, axis=1
    )

    # Normalize useful numeric cols
    for c in [
        "now_cost",
        "form",
        "points_per_game",
        "total_points",
        "selected_by_percent",
        "ep_next",
        "minutes",
        "transfers_in_event",
        "transfers_out_event",
        "penalties_order",
        "direct_freekicks_order",
        "corners_and_indirect_freekicks_order",
    ]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # price in millions
    if "now_cost" in df.columns:
        df["price_m"] = df["now_cost"] / 10.0

    return df


def players_for_gw(
    elements,
    fx,
    gw,
    teams_short_map,
    pos_filter=None,
    only_with_fixture=True,
    sort_by="ep_next",
    topn=None,
):
    """
    Build a player table for the requested GW with fixture annotations.
    - Filters to players whose team has a fixture (or doubles) if only_with_fixture=True.
    - Sorts by sort_by (falls back to total_points if missing/empty).
    - Returns a tidy subset of columns, optionally head(topn).
    """
    df = annotate_elements_with_gw_fixtures(elements, fx, int(gw), teams_short_map)

    if pos_filter:
        df = df[df["pos"].isin(pos_filter)]

    if only_with_fixture:
        df = df[df["gw_fixture_count"] > 0]

    # Choose sort column safely
    if sort_by not in df.columns or df[sort_by].isna().all():
        sort_by = "total_points" if "total_points" in df.columns else None

    if sort_by:
        df = df.sort_values(sort_by, ascending=False)

    keep = [
        "web_name",
        "pos",
        "team_short",
        "price_m",
        "form",
        "points_per_game",
        "total_points",
        "selected_by_percent",
        "ep_next",
        "gw_fixtures",
        "gw_fixture_count",
        "gw_diff_sum",
        "gw_diff_avg",
    ]
    keep = [c for c in keep if c in df.columns]
    out = df[keep].copy()

    if topn:
        out = out.head(int(topn))

    return out
