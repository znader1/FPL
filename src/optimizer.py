import pandas as pd

from . import config


VALID_FORMATIONS = [
    (3, 4, 3),
    (3, 5, 2),
    (4, 3, 3),
    (4, 4, 2),
    (4, 5, 1),
    (5, 3, 2),
    (5, 4, 1),
]


CAPTAIN_POSITION_MULTIPLIER = dict(config.CAPTAIN_POSITION_MULTIPLIER)


def merge_scores(squad_df, projections_df, score_col):
    """
    Attach `xpts` to a squad DataFrame using a projections table.
    - squad_df: expects `player_id`
    - projections_df: expects `id` and `score_col`
    """
    df = squad_df.copy()
    proj = projections_df[["id", score_col]].copy()
    proj = proj.rename(columns={"id": "player_id", score_col: "xpts"})
    df = df.merge(proj, on="player_id", how="left")
    df["xpts"] = pd.to_numeric(df["xpts"], errors="coerce").fillna(0.0)
    return df


def optimize_lineup(squad_df, projections_df, score_col, formations=None):
    """
    Pick best XI + bench order + captain/vice from an existing 15-man squad.

    Returns a dict:
      - formation: (DEF, MID, FWD)
      - starting_xi: DataFrame (includes xpts + suggested captain/vice flags)
      - bench: DataFrame (includes bench_order + xpts)
      - captain_player_id / vice_player_id
      - projected_points_with_captain
    """
    if squad_df is None or squad_df.empty:
        return None

    df = merge_scores(squad_df, projections_df, score_col)
    formations = formations or VALID_FORMATIONS

    gk = df[df["pos"] == "GKP"].sort_values("xpts", ascending=False)
    de = df[df["pos"] == "DEF"].sort_values("xpts", ascending=False)
    mi = df[df["pos"] == "MID"].sort_values("xpts", ascending=False)
    fw = df[df["pos"] == "FWD"].sort_values("xpts", ascending=False)

    if gk.empty:
        return None

    best = None

    for d, m, f in formations:
        if len(de) < d or len(mi) < m or len(fw) < f:
            continue

        starting = pd.concat(
            [
                gk.head(1),
                de.head(int(d)),
                mi.head(int(m)),
                fw.head(int(f)),
            ],
            ignore_index=True,
        )
        remaining = df[~df["player_id"].isin(starting["player_id"])].copy()

        start_sorted = starting.sort_values("xpts", ascending=False).reset_index(drop=True)
        start_sorted["captain_score"] = start_sorted.apply(
            lambda r: float(r["xpts"]) * float(CAPTAIN_POSITION_MULTIPLIER.get(r["pos"], 1.0)),
            axis=1,
        )
        captain_rank = start_sorted.sort_values(["captain_score", "xpts"], ascending=[False, False]).reset_index(drop=True)
        captain_id = int(captain_rank.loc[0, "player_id"])
        vice_pool = captain_rank[captain_rank["player_id"] != captain_id].copy()
        vice_id = int(vice_pool.iloc[0]["player_id"]) if not vice_pool.empty else captain_id

        # Score includes captain doubling (add captain again)
        captain_xpts = float(starting[starting["player_id"] == captain_id]["xpts"].iloc[0])
        score = float(starting["xpts"].sum() + captain_xpts)

        starting_out = starting.copy()
        starting_out["is_captain_suggested"] = starting_out["player_id"] == captain_id
        starting_out["is_vice_suggested"] = starting_out["player_id"] == vice_id
        starting_out = starting_out.sort_values(["pos", "xpts"], ascending=[True, False])

        # Bench: outfield by xpts, GK last
        bench_gk = remaining[remaining["pos"] == "GKP"].sort_values("xpts", ascending=False).head(1).copy()
        bench_outfield = remaining[remaining["pos"] != "GKP"].sort_values("xpts", ascending=False).reset_index(drop=True)
        bench_outfield["bench_order"] = bench_outfield.index + 1

        if not bench_gk.empty:
            last = int(bench_outfield["bench_order"].max()) if not bench_outfield.empty else 0
            bench_gk["bench_order"] = last + 1
            bench = pd.concat([bench_outfield, bench_gk], ignore_index=True)
        else:
            bench = bench_outfield

        bench = bench.sort_values("bench_order")

        res = {
            "formation": (int(d), int(m), int(f)),
            "captain_player_id": captain_id,
            "vice_player_id": vice_id,
            "starting_xi": starting_out,
            "bench": bench,
            "projected_points_with_captain": score,
        }

        if best is None or res["projected_points_with_captain"] > best["projected_points_with_captain"]:
            best = res

    return best
