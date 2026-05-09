import os
import json
from datetime import datetime, timezone

import pandas as pd
import requests
from tenacity import retry, wait_exponential, stop_after_attempt

import certifi


BASE = "https://fantasy.premierleague.com/api"

# ---------- HTTP helpers ----------
@retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(5), reraise=True)
def _get_json(url):
    r = requests.get(url, timeout=30, verify=certifi.where())
    r.raise_for_status()
    return r.json()

def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def _stamp_folder(base="data/processed"):
    d = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(base, d)
    _ensure_dir(path)
    return path

def _save_table(df, path_no_ext):
    df.to_csv(path_no_ext + ".csv", index=False)
    try:
        df.to_parquet(path_no_ext + ".parquet", index=False)
    except Exception:
        pass

def _save_json(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# ---------- FPL endpoints ----------
def fetch_bootstrap():
    return _get_json(f"{BASE}/bootstrap-static/")

def fetch_fixtures():
    return _get_json(f"{BASE}/fixtures/")

def fetch_element_summary(element_id):
    return _get_json(f"{BASE}/element-summary/{int(element_id)}/")

# ---------- Builders ----------
def normalize_bootstrap(boot):
    players = pd.DataFrame(boot.get("elements", []))
    teams   = pd.DataFrame(boot.get("teams", []))
    types   = pd.DataFrame(boot.get("element_types", []))
    events  = pd.DataFrame(boot.get("events", []))
    # Coerce datetimes that we will display/use
    if "news_added" in players.columns:
        players["news_added"] = pd.to_datetime(players["news_added"], errors="coerce", utc=True)
    if "deadline_time" in events.columns:
        events["deadline_time"] = pd.to_datetime(events["deadline_time"], errors="coerce", utc=True)
    return players, teams, types, events

def get_next_event_id(events):
    # Prefer 'is_next' if present, else choose first with is_current==False and finished==False and deadline in future
    if "is_next" in events.columns and events["is_next"].any():
        return int(events.loc[events["is_next"] == True, "id"].iloc[0])
    # fallback
    now = datetime.now(timezone.utc)
    cand = events[(events.get("finished", False) == False) & (events["deadline_time"] > now)]
    return int(cand["id"].iloc[0]) if not cand.empty else None

def build_next_gw_fixtures(fixtures_json, next_event_id):
    fx = pd.DataFrame(fixtures_json)
    if "kickoff_time" in fx.columns:
        fx["kickoff_time"] = pd.to_datetime(fx["kickoff_time"], errors="coerce", utc=True)
    fx_next = fx[fx["event"] == next_event_id].copy()
    # Keep a small, useful subset + readable team ids
    keep = ["id","event","kickoff_time","team_h","team_a","team_h_difficulty","team_a_difficulty","finished","started"]
    cols = [c for c in keep if c in fx_next.columns]
    return fx_next[cols].sort_values("kickoff_time")

def build_players_table(players, teams, types):
    out_cols = [
        "id","web_name","first_name","second_name","team","now_cost","status",
        "chance_of_playing_this_round","chance_of_playing_next_round","news","news_added","element_type"
    ]
    p = players[[c for c in out_cols if c in players.columns]].copy()
    # Attach readable team and position names
    team_map = dict(zip(teams["id"], teams["name"])) if not teams.empty else {}
    type_map = dict(zip(types["id"], types["singular_name_short"])) if not types.empty else {}
    p["team_name"] = p["team"].map(team_map)
    p["pos"] = p["element_type"].map(type_map)
    # Price in £m for readability (FPL stores in tenths)
    if "now_cost" in p.columns:
        p["price_m"] = p["now_cost"].astype(float) / 10.0
    return p.sort_values(["pos","team_name","web_name"])

def build_player_gw_history(player_ids, max_workers=8):
    """Fetch per-GW history for every player and stack into one DataFrame.

    Schema matches what src/projections.py expects:
      player_id, gw, gw_total_points, gw_fixture_count, gw_minutes, gw_starts
    Multiple fixtures in one GW (DGW) are aggregated.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    rows = []

    def _one(pid):
        try:
            data = fetch_element_summary(pid)
        except Exception:
            return pid, None
        return pid, data.get("history") or []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_one, pid) for pid in player_ids]
        for fut in as_completed(futures):
            pid, history = fut.result()
            if not history:
                continue
            for h in history:
                rows.append({
                    "player_id": pid,
                    "gw": h.get("round"),
                    "gw_total_points": h.get("total_points"),
                    "gw_minutes": h.get("minutes"),
                    "gw_starts": h.get("starts"),
                })

    if not rows:
        return pd.DataFrame(columns=["player_id", "gw", "gw_total_points", "gw_fixture_count", "gw_minutes", "gw_starts"])

    df = pd.DataFrame(rows)
    df["player_id"] = pd.to_numeric(df["player_id"], errors="coerce")
    df["gw"] = pd.to_numeric(df["gw"], errors="coerce")
    df["gw_total_points"] = pd.to_numeric(df["gw_total_points"], errors="coerce")
    df["gw_minutes"] = pd.to_numeric(df["gw_minutes"], errors="coerce")
    df["gw_starts"] = pd.to_numeric(df["gw_starts"], errors="coerce")
    df = df.dropna(subset=["player_id", "gw"]).copy()
    df["player_id"] = df["player_id"].astype(int)
    df["gw"] = df["gw"].astype(int)

    # Aggregate DGWs into one row per (player, gw); fixture_count = number of rows merged
    grouped = df.groupby(["player_id", "gw"], as_index=False).agg(
        gw_total_points=("gw_total_points", "sum"),
        gw_minutes=("gw_minutes", "sum"),
        gw_starts=("gw_starts", "sum"),
        gw_fixture_count=("gw_total_points", "size"),
    )
    return grouped.sort_values(["player_id", "gw"]).reset_index(drop=True)


# ---------- Main task ----------
def refresh_next_gw_snapshot(out_base="data/processed"):
    out_dir = _stamp_folder(out_base)

    boot = fetch_bootstrap()
    fixtures_json = fetch_fixtures()

    players, teams, types, events = normalize_bootstrap(boot)
    next_event_id = get_next_event_id(events)
    if next_event_id is None:
        raise RuntimeError("Could not determine next gameweek (event id).")

    # Build tables
    next_fx = build_next_gw_fixtures(fixtures_json, next_event_id)
    players_small = build_players_table(players, teams, types)

    # Save
    _save_table(events, os.path.join(out_dir, "events"))
    _save_table(next_fx, os.path.join(out_dir, f"fixtures_gw{next_event_id}"))
    _save_table(players_small, os.path.join(out_dir, "players_current"))

    # raw JSON for debugging
    _save_json(boot, os.path.join(out_dir, "bootstrap_static.json"))
    _save_json(fixtures_json, os.path.join(out_dir, "fixtures_raw.json"))

    # Build per-GW history table that the projection layer expects.
    # Lives under <out_base>/fpl/<DATE>/player_gw_history_<MAXGW>.csv
    history_dir_base = os.path.join(out_base, "fpl")
    history_dir = os.path.join(history_dir_base, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    _ensure_dir(history_dir)
    player_ids = players["id"].dropna().astype(int).tolist()
    history_df = build_player_gw_history(player_ids)
    history_path = None
    history_max_gw = None
    if not history_df.empty and "gw" in history_df.columns:
        history_max_gw = int(pd.to_numeric(history_df["gw"], errors="coerce").max())
        history_path = os.path.join(history_dir, f"player_gw_history_{history_max_gw}")
        _save_table(history_df, history_path)

    return {
        "out_dir": out_dir,
        "next_event_id": str(next_event_id),
        "fixtures_path": os.path.join(out_dir, f"fixtures_gw{next_event_id}.csv"),
        "players_path": os.path.join(out_dir, "players_current.csv"),
        "history_path": (history_path + ".csv") if history_path else None,
        "history_max_gw": history_max_gw,
        "history_rows": int(len(history_df)),
    }

if __name__ == "__main__":
    info = refresh_next_gw_snapshot()
    print(f"Saved next-GW snapshot to: {info['out_dir']}")
    print(f"Next GW = {info['next_event_id']}")
    print(f"Fixtures CSV: {info['fixtures_path']}")
    print(f"Players  CSV: {info['players_path']}")
