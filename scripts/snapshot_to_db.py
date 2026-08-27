"""Twice-daily snapshot job: pre-deadline model/FPL state -> Supabase.

Run by .github/workflows/snapshot-db.yml. Pure row-building logic is
separated from I/O so it can be tested without network access.

Env: FPL_API_BASE_URL, FPL_ADMIN_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY.
"""
import os
import sys
from datetime import datetime, timezone

import requests


def season_of(payload):
    return str(payload["season"])


def snapshot_rows(payload, now_utc):
    deadline = datetime.fromisoformat(str(payload["deadline_utc"]).replace("Z", "+00:00"))
    if now_utc >= deadline:
        return []
    season, gw = season_of(payload), int(payload["next_gw"])
    blend = payload.get("blend_weight")
    rows = []
    for p in payload.get("players", []):
        rows.append({
            "season": season, "gw": gw, "player_id": int(p["player_id"]),
            "web_name": p.get("web_name"), "pos": p.get("pos"),
            "team_short": p.get("team_short"), "price_m": p.get("price_m"),
            "ownership_pct": p.get("ownership_pct"), "status": p.get("status"),
            "chance": p.get("chance"), "fpl_ep_next": p.get("fpl_ep_next"),
            "model_xpts": p.get("model_xpts"), "model_blend_weight": blend,
            "captured_at": now_utc.isoformat(),
        })
    return rows


def actuals_rows(live_elements, season, gw, now_iso):
    rows = []
    for e in live_elements or []:
        stats = e.get("stats") or {}
        rows.append({
            "season": season, "gw": int(gw), "player_id": int(e["id"]),
            "actual_points": int(stats.get("total_points") or 0),
            "actual_minutes": int(stats.get("minutes") or 0),
            "actuals_captured_at": now_iso,
        })
    return rows


# ---------------------------------------------------------------- I/O shell

def _supabase_headers(service_key):
    return {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


def upsert(supabase_url, service_key, rows):
    if not rows:
        return
    r = requests.post(
        f"{supabase_url.rstrip('/')}/rest/v1/player_gw_snapshots"
        "?on_conflict=season,gw,player_id",
        headers=_supabase_headers(service_key), json=rows, timeout=60,
    )
    r.raise_for_status()


def gws_missing_actuals(supabase_url, service_key, season):
    r = requests.get(
        f"{supabase_url.rstrip('/')}/rest/v1/player_gw_snapshots"
        # limit lifts PostgREST's default 1000-row cap; a backlog of 3+ GWs
        # (~700 rows each) would otherwise silently drop tail GWs from the set
        f"?select=gw&season=eq.{season}&actual_points=is.null&limit=100000",
        headers=_supabase_headers(service_key), timeout=60,
    )
    r.raise_for_status()
    return sorted({int(row["gw"]) for row in r.json()})


def main():
    api_base = os.environ["FPL_API_BASE_URL"].rstrip("/")
    admin_key = os.environ["FPL_ADMIN_KEY"]
    sb_url = os.environ["SUPABASE_URL"]
    sb_key = os.environ["SUPABASE_SERVICE_KEY"]
    now = datetime.now(timezone.utc)

    snap = requests.get(f"{api_base}/admin/model-snapshot",
                        headers={"X-API-Key": admin_key}, timeout=180)
    snap.raise_for_status()
    payload = snap.json()
    if not any(p.get("model_xpts") is not None for p in payload.get("players", [])):
        raise SystemExit("model-snapshot returned no model_xpts values — aborting, nothing written")
    season = season_of(payload)

    rows = snapshot_rows(payload, now)
    upsert(sb_url, sb_key, rows)
    print(f"snapshot: gw={payload['next_gw']} rows={len(rows)}")

    if "finished_gws" in payload:
        finished_gws = {int(g) for g in payload["finished_gws"] or []}
    else:
        # deployed API predates the finished_gws field — fall back to a raw fetch
        r = requests.get(
            "https://fantasy.premierleague.com/api/bootstrap-static/", timeout=60,
        )
        r.raise_for_status()
        bootstrap = r.json()
        finished_gws = {int(e["id"]) for e in bootstrap.get("events", []) if e.get("finished")}
    for gw in gws_missing_actuals(sb_url, sb_key, season):
        if gw not in finished_gws:
            continue
        r = requests.get(
            f"https://fantasy.premierleague.com/api/event/{gw}/live/", timeout=60,
        )
        r.raise_for_status()
        live = r.json()
        rows = actuals_rows(live.get("elements"), season, gw, now.isoformat())
        upsert(sb_url, sb_key, rows)
        print(f"actuals: gw={gw} rows={len(rows)}")


if __name__ == "__main__":
    sys.exit(main())
