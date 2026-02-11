import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import certifi
import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential


BASE = "https://fantasy.premierleague.com/api"


def _session():
    s = requests.Session()
    s.verify = certifi.where()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://fantasy.premierleague.com/",
        }
    )
    return s


@retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(5), reraise=True)
def _get_json(url, session=None):
    s = session or _session()
    r = s.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_bootstrap(session=None):
    return _get_json(f"{BASE}/bootstrap-static/", session=session)


def fetch_fixtures(session=None):
    return _get_json(f"{BASE}/fixtures/", session=session)


def fetch_element_summary(element_id, session=None):
    return _get_json(f"{BASE}/element-summary/{int(element_id)}/", session=session)


def season_label_from_bootstrap(bootstrap):
    """
    Best-effort label based on the earliest event deadline year.
    Example: 2025-26
    """
    events = pd.DataFrame(bootstrap.get("events", []))
    if events.empty or "deadline_time" not in events.columns:
        return "unknown-season"

    deadlines = pd.to_datetime(events["deadline_time"], errors="coerce", utc=True)
    start_year = int(deadlines.min().year) if deadlines.notna().any() else 0
    if not start_year:
        return "unknown-season"
    end_yy = str((start_year + 1) % 100).zfill(2)
    return f"{start_year}-{end_yy}"


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_element_ids(bootstrap):
    return [int(e["id"]) for e in bootstrap.get("elements", []) if "id" in e]


def scrape_element_summaries(
    element_ids,
    out_dir,
    *,
    max_workers=8,
    resume=True,
    throttle_s=0.0,
):
    """
    Download /element-summary/{id}/ for each element_id into out_dir/{id}.json.
    Returns (downloaded, skipped).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    ids = [int(i) for i in element_ids]

    def job(eid):
        fp = out_dir / f"{eid}.json"
        if resume and fp.exists():
            return eid, "skipped"
        data = fetch_element_summary(eid)
        _write_json(fp, data)
        if throttle_s:
            time.sleep(float(throttle_s))
        return eid, "downloaded"

    downloaded = 0
    skipped = 0
    with ThreadPoolExecutor(max_workers=int(max_workers)) as ex:
        futs = {ex.submit(job, eid): eid for eid in ids}
        for fut in as_completed(futs):
            _, status = fut.result()
            if status == "downloaded":
                downloaded += 1
            else:
                skipped += 1
    return downloaded, skipped


def build_player_match_history(
    bootstrap,
    fixtures_json,
    element_summary_dir,
):
    """
    Aggregate per-player match history (one row per fixture) for the current season.
    Joins fixture metadata and derives the player's team id for that fixture.
    """
    # Fixtures lookup (fixture id is "id" in fixtures endpoint; "fixture" in element-summary history)
    fx = pd.DataFrame(fixtures_json)
    if not fx.empty:
        fx["kickoff_time"] = pd.to_datetime(fx.get("kickoff_time"), errors="coerce", utc=True)
    fx_keep = [
        "id",
        "event",
        "kickoff_time",
        "team_h",
        "team_a",
        "team_h_difficulty",
        "team_a_difficulty",
    ]
    fx = fx[[c for c in fx_keep if c in fx.columns]].copy()
    fx = fx.rename(columns={"id": "fixture"})

    # Player meta
    elements = pd.DataFrame(bootstrap.get("elements", []))
    meta_keep = ["id", "web_name", "first_name", "second_name", "element_type"]
    meta = elements[[c for c in meta_keep if c in elements.columns]].copy()
    meta = meta.rename(columns={"id": "player_id"})

    rows = []
    for fp in sorted(element_summary_dir.glob("*.json")):
        try:
            eid = int(fp.stem)
        except Exception:
            continue
        payload = _read_json(fp)
        for r in payload.get("history", []) or []:
            rr = dict(r)
            rr["player_id"] = eid
            rows.append(rr)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Normalize types
    if "kickoff_time" in df.columns:
        df["kickoff_time"] = pd.to_datetime(df["kickoff_time"], errors="coerce", utc=True)
    if "round" in df.columns:
        df["round"] = pd.to_numeric(df["round"], errors="coerce").astype("Int64")

    # Join fixtures
    if "fixture" in df.columns and not fx.empty:
        df = df.merge(fx, on="fixture", how="left")

        home = df["was_home"].astype(bool) if "was_home" in df.columns else pd.Series(False, index=df.index)
        df["team_id"] = df["team_h"].where(home, df["team_a"])
        df["team_difficulty"] = df["team_h_difficulty"].where(home, df["team_a_difficulty"])
        df["opp_difficulty"] = df["team_a_difficulty"].where(home, df["team_h_difficulty"])

    # Join player meta
    df = df.merge(meta, on="player_id", how="left")
    return df


def build_player_gw_history(match_df):
    """
    Convert player×fixture rows into player×GW rows.
    Handles doubles by summing stats within the GW.
    """
    if match_df is None or match_df.empty:
        return pd.DataFrame()

    df = match_df.copy()

    # Decide which column represents GW
    if "round" in df.columns:
        df["gw"] = pd.to_numeric(df["round"], errors="coerce")
    elif "event" in df.columns:
        df["gw"] = pd.to_numeric(df["event"], errors="coerce")
    else:
        raise ValueError("No GW column found (expected 'round' or 'event').")

    df = df[df["gw"].notna()].copy()
    df["gw"] = df["gw"].astype(int)

    if "kickoff_time" in df.columns:
        df["kickoff_time"] = pd.to_datetime(df["kickoff_time"], errors="coerce", utc=True)

    keys = ["player_id", "gw"]
    if "season" in df.columns:
        keys = ["season"] + keys

    grp = df.groupby(keys, dropna=False)

    out = grp.size().rename("gw_fixture_count").reset_index()

    # Sum common per-fixture stats into GW totals
    sum_candidates = [
        "total_points",
        "minutes",
        "starts",
        "goals_scored",
        "assists",
        "clean_sheets",
        "goals_conceded",
        "own_goals",
        "penalties_saved",
        "penalties_missed",
        "yellow_cards",
        "red_cards",
        "saves",
        "bonus",
        "bps",
        "influence",
        "creativity",
        "threat",
        "ict_index",
        # expected stats (available in recent seasons)
        "expected_goals",
        "expected_assists",
        "expected_goal_involvements",
        "expected_goals_conceded",
    ]
    sum_cols = [c for c in sum_candidates if c in df.columns]
    if sum_cols:
        sums = grp[sum_cols].sum(min_count=1).reset_index()
        rename = {c: f"gw_{c}" for c in sum_cols}
        sums = sums.rename(columns=rename)
        out = out.merge(sums, on=keys, how="left")

    # GW kickoff window
    if "kickoff_time" in df.columns:
        kt = grp["kickoff_time"].agg(["min", "max"]).reset_index()
        kt = kt.rename(columns={"min": "gw_kickoff_time_first", "max": "gw_kickoff_time_last"})
        out = out.merge(kt, on=keys, how="left")

    # Fixture difficulty aggregates (from fixtures join)
    for col in ["team_difficulty", "opp_difficulty"]:
        if col in df.columns:
            tmp = grp[col].agg(["sum", "mean"]).reset_index()
            tmp = tmp.rename(columns={"sum": f"gw_{col}_sum", "mean": f"gw_{col}_avg"})
            out = out.merge(tmp, on=keys, how="left")

    # End-of-GW values (use last played fixture in that GW)
    order_cols = []
    if "kickoff_time" in df.columns:
        order_cols.append("kickoff_time")
    if "fixture" in df.columns:
        order_cols.append("fixture")
    sort_cols = keys + order_cols if order_cols else keys
    last = df.sort_values(sort_cols).groupby(keys, as_index=False).tail(1)

    # Meta columns (stable identifiers)
    meta_cols = [c for c in ["web_name", "first_name", "second_name", "element_type"] if c in last.columns]
    if meta_cols:
        meta = last[keys + meta_cols].copy()
        out = out.merge(meta, on=keys, how="left")

    # Snapshot-ish columns (these exist in element-summary history for many seasons)
    end_cols = []
    for c in ["value", "selected", "transfers_balance", "transfers_in", "transfers_out", "team_id"]:
        if c in last.columns:
            end_cols.append(c)
    if end_cols:
        end = last[keys + end_cols].copy()
        end = end.rename(columns={c: f"gw_{c}_end" for c in end_cols})
        out = out.merge(end, on=keys, how="left")

    out = out.sort_values(keys)
    return out


def save_table(df, out_dir, base_name):
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / base_name

    csv_path = str(base.with_suffix(".csv"))
    df.to_csv(csv_path, index=False)
    paths = {"csv": csv_path}

    try:
        parquet_path = str(base.with_suffix(".parquet"))
        df.to_parquet(parquet_path, index=False)
        paths["parquet"] = parquet_path
    except Exception:
        pass

    return paths


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scrape FPL current-season player match history (element-summary).")
    ap.add_argument("--raw-dir", default="data/raw/fpl", help="Where to store raw JSON snapshots.")
    ap.add_argument("--out-dir", default="data/processed/fpl", help="Where to store aggregated tables.")
    ap.add_argument("--max-workers", type=int, default=8, help="Concurrent downloads for element summaries.")
    ap.add_argument("--resume", action="store_true", help="Skip already-downloaded element summaries.")
    ap.add_argument("--throttle-s", type=float, default=0.0, help="Sleep after each download (per worker).")
    ap.add_argument("--limit", type=int, default=0, help="Only scrape the first N players (debug). 0 = all.")
    args = ap.parse_args(argv)

    s = _session()
    boot = fetch_bootstrap(session=s)
    fixtures_json = fetch_fixtures(session=s)
    season = season_label_from_bootstrap(boot)

    raw_root = Path(args.raw_dir) / season
    element_dir = raw_root / "element_summary"
    _write_json(raw_root / "bootstrap_static.json", boot)
    _write_json(raw_root / "fixtures.json", fixtures_json)

    element_ids = _iter_element_ids(boot)
    if args.limit and int(args.limit) > 0:
        element_ids = element_ids[: int(args.limit)]

    dl, sk = scrape_element_summaries(
        element_ids,
        element_dir,
        max_workers=int(args.max_workers),
        resume=bool(args.resume),
        throttle_s=float(args.throttle_s),
    )

    match_df = build_player_match_history(boot, fixtures_json, element_dir)
    match_df["season"] = season
    gw_df = build_player_gw_history(match_df)

    # Add GW metadata (deadline, finished, etc) from bootstrap events
    events = pd.DataFrame(boot.get("events", []))
    if not events.empty and "id" in events.columns:
        if "deadline_time" in events.columns:
            events["deadline_time"] = pd.to_datetime(events["deadline_time"], errors="coerce", utc=True)
        keep = ["id", "name", "deadline_time", "finished", "is_current", "is_next"]
        ev = events[[c for c in keep if c in events.columns]].copy()
        ev = ev.rename(
            columns={
                "id": "gw",
                "name": "gw_name",
                "deadline_time": "gw_deadline_time",
                "finished": "gw_finished",
                "is_current": "gw_is_current",
                "is_next": "gw_is_next",
            }
        )
        if not gw_df.empty and "gw" in gw_df.columns:
            gw_df = gw_df.merge(ev, on="gw", how="left")

    out_root = Path(args.out_dir) / season
    match_paths = save_table(match_df, out_root, f"player_match_history_{season}")
    gw_paths = save_table(gw_df, out_root, f"player_gw_history_{season}")

    print(f"Season: {season}")
    print(f"Element summaries: downloaded={dl} skipped={sk} dir={element_dir}")
    print(f"Match rows: {len(match_df):,} players: {match_df['player_id'].nunique() if 'player_id' in match_df.columns else 0}")
    print(f"GW rows: {len(gw_df):,} players: {gw_df['player_id'].nunique() if 'player_id' in gw_df.columns else 0}")
    for k, v in match_paths.items():
        print(f"Wrote match {k}: {v}")
    for k, v in gw_paths.items():
        print(f"Wrote gw {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
