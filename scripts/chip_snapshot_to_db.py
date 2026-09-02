"""Chip-plan snapshot job: pre-deadline plan + post-GW chip actuals -> Supabase.

Run alongside snapshot_to_db.py by .github/workflows/snapshot-db.yml.
Env: FPL_API_BASE_URL, FPL_ADMIN_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY,
     CHIP_SNAPSHOT_ENTRY_IDS (comma-separated FPL entry ids).
"""
import os
import sys
from datetime import datetime, timezone

import requests

FPL_CHIP_NAME_MAP = {
    "wildcard": "wildcard", "freehit": "free_hit",
    "bboost": "bench_boost", "3xc": "triple_captain",
}


def chip_plan_rows(payload, now_utc):
    deadline = datetime.fromisoformat(str(payload["deadline_utc"]).replace("Z", "+00:00"))
    if now_utc >= deadline:
        return []
    plan = payload["plan"]
    curves = {r["chip"]: r.get("ev_curve") or [] for r in plan.get("recommendations", [])}
    return [{
        "season": str(payload["season"]),
        "gw": int(payload["next_gw"]),
        "entry_id": int(payload["entry_id"]),
        "chips_remaining": plan.get("chips_remaining"),
        "recommendations": plan.get("recommendations"),
        "ev_curves": curves,
        "transfer_context": plan.get("transfer_context"),
        "model_meta": payload.get("model_meta"),
        "captured_at": now_utc.isoformat(),
    }]


def chip_actuals_rows(entry_id, season, gw, chips_played, picks, live_points_by_id, now_iso):
    chip_raw = next(
        (c.get("name") for c in chips_played or [] if int(c.get("event", 0) or 0) == int(gw)),
        None,
    )
    chip = FPL_CHIP_NAME_MAP.get(str(chip_raw).lower()) if chip_raw else None

    bench = [p for p in picks or [] if int(p.get("position", 0)) >= 12]
    bench_pts = sum(int(live_points_by_id.get(int(p["element"]), 0)) for p in bench)
    cap = next((p for p in picks or [] if p.get("is_captain")), None)
    cap_pts = int(live_points_by_id.get(int(cap["element"]), 0)) if cap else 0
    total = sum(int(live_points_by_id.get(int(p["element"]), 0)) for p in picks or [])

    return [{
        "season": season, "gw": int(gw), "entry_id": int(entry_id),
        "chip_played": chip,
        "actual_points": total,
        # Counterfactual realized EVs computable from actuals alone; FH/WC need
        # counterfactual squads and stay out of the labels.
        "realized_chip_ev": {"bench_boost": bench_pts, "triple_captain": cap_pts},
        "actuals_captured_at": now_iso,
    }]


# ---------------------------------------------------------------- I/O shell

def _headers(service_key):
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
        f"{supabase_url.rstrip('/')}/rest/v1/chip_plan_snapshots"
        "?on_conflict=season,gw,entry_id",
        headers=_headers(service_key), json=rows, timeout=60,
    )
    r.raise_for_status()


def gws_missing_actuals(supabase_url, service_key, season, entry_id):
    r = requests.get(
        f"{supabase_url.rstrip('/')}/rest/v1/chip_plan_snapshots"
        f"?select=gw&season=eq.{season}&entry_id=eq.{entry_id}"
        f"&actuals_captured_at=is.null&limit=100000",
        headers=_headers(service_key), timeout=60,
    )
    r.raise_for_status()
    return sorted({int(row["gw"]) for row in r.json()})


def main():
    api_base = os.environ["FPL_API_BASE_URL"].rstrip("/")
    admin_key = os.environ["FPL_ADMIN_KEY"]
    sb_url = os.environ["SUPABASE_URL"]
    sb_key = os.environ["SUPABASE_SERVICE_KEY"]
    entry_ids = [int(x) for x in os.environ.get("CHIP_SNAPSHOT_ENTRY_IDS", "").split(",") if x.strip()]
    if not entry_ids:
        print("CHIP_SNAPSHOT_ENTRY_IDS empty — nothing to do")
        return
    now = datetime.now(timezone.utc)

    finished_gws = set()
    rboot = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/", timeout=60)
    rboot.raise_for_status()
    for e in rboot.json().get("events", []):
        if e.get("finished"):
            finished_gws.add(int(e["id"]))

    for entry_id in entry_ids:
        snap = requests.get(
            f"{api_base}/admin/chip-plan?entry_id={entry_id}",
            headers={"X-API-Key": admin_key}, timeout=180,
        )
        snap.raise_for_status()
        payload = snap.json()
        season = str(payload["season"])

        rows = chip_plan_rows(payload, now)
        upsert(sb_url, sb_key, rows)
        print(f"chip plan: entry={entry_id} gw={payload['next_gw']} rows={len(rows)}")

        rh = requests.get(
            f"https://fantasy.premierleague.com/api/entry/{entry_id}/history/", timeout=60)
        rh.raise_for_status()
        chips_played = rh.json().get("chips") or []

        for gw in gws_missing_actuals(sb_url, sb_key, season, entry_id):
            if gw not in finished_gws:
                continue
            rp = requests.get(
                f"https://fantasy.premierleague.com/api/entry/{entry_id}/event/{gw}/picks/",
                timeout=60)
            rp.raise_for_status()
            picks = rp.json().get("picks") or []
            rl = requests.get(
                f"https://fantasy.premierleague.com/api/event/{gw}/live/", timeout=60)
            rl.raise_for_status()
            live_points = {
                int(e["id"]): int((e.get("stats") or {}).get("total_points") or 0)
                for e in rl.json().get("elements") or []
            }
            rows = chip_actuals_rows(entry_id, season, gw, chips_played, picks, live_points, now.isoformat())
            upsert(sb_url, sb_key, rows)
            print(f"chip actuals: entry={entry_id} gw={gw}")


if __name__ == "__main__":
    sys.exit(main())
