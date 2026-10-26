"""Shadow projection for the weekly snapshot (2026-10-26 calibration spec, part 6).

After a projection change ships, ``config.PROJ_SHADOW_OVERRIDES`` holds the
previous model's settings. This job, run on the GitHub runner after the live
snapshot, refreshes FPL data locally and projects the next GW twice on that same
data: once with the current config (``runner_xpts``) and once under the
overrides (``shadow_xpts``). Comparing those two isolates the model change from
data differences between the runner and the Fly volume (status history, runtime
knowledge nudges). It runs in its own process, never inside the API, so the
overrides can't leak into live requests, and the 512 MB Fly machine stays out of
it. Any failure logs and exits 0: the shadow never fails the snapshot job.

    PYTHONPATH=. python scripts/shadow_snapshot.py
Env: SUPABASE_URL, SUPABASE_SERVICE_KEY.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import requests

from scripts.snapshot_to_db import upsert
from src import config
from src.config_overrides import config_overrides

logger = logging.getLogger("shadow_snapshot")


def shadow_rows(runner_proj, shadow_proj, season, gw, shadow_version):
    col = f"xpts_gw{int(gw)}"
    runner = dict(zip(pd.to_numeric(runner_proj["id"], errors="coerce").astype(int),
                      pd.to_numeric(runner_proj[col], errors="coerce")))
    shadow = dict(zip(pd.to_numeric(shadow_proj["id"], errors="coerce").astype(int),
                      pd.to_numeric(shadow_proj[col], errors="coerce")))
    rows = []
    for pid in sorted(set(runner) | set(shadow)):
        r, s = runner.get(pid), shadow.get(pid)
        rows.append({
            "season": str(season), "gw": int(gw), "player_id": int(pid),
            "runner_xpts": None if r is None or pd.isna(r) else round(float(r), 3),
            "shadow_xpts": None if s is None or pd.isna(s) else round(float(s), 3),
            "shadow_model_version": shadow_version,
        })
    return rows


def refresh_local_data():
    """Fetch FPL data into data/processed like the API's refresh → {season, gw, deadline_open}."""
    from api import main as m
    from src import fpl_refresh_next_gw, injury_prior
    from src.season_history import season_label_from_bootstrap

    boot = m.get_bootstrap_cached()
    fx = m.get_fixtures_cached()
    fpl_refresh_next_gw.refresh_next_gw_snapshot(out_base="data/processed")
    m.refresh_match_history(boot, fx)
    nxt = next(e for e in boot["events"] if e.get("is_next"))
    injury_prior.append_status_snapshot(boot, int(nxt["id"]), config.CHIP_WILDCARD_STATUS_HISTORY_PATH)
    deadline = datetime.fromisoformat(str(nxt["deadline_time"]).replace("Z", "+00:00"))
    return {"season": season_label_from_bootstrap(boot), "gw": int(nxt["id"]),
            "deadline_open": datetime.now(timezone.utc) < deadline}


def project_next_gw(gw):
    """The same call get_projections_cached makes, uncached."""
    from api import main as m
    from src import projections, transforms

    boot = m.get_bootstrap_cached()
    elements, teams, _ = transforms.tables_from_bootstrap(boot)
    finished = [int(e["id"]) for e in boot["events"] if e.get("finished")]
    return projections.project_elements_next_gws(
        elements=elements, fixtures=m.get_fixtures_cached(),
        teams_short_map=teams.set_index("id")["short_name"].to_dict(),
        gw_start=int(gw), horizon_gws=1,
        latest_n_matches=config.PROJ_DEFAULT_LATEST_N_MATCHES,
        finished_gw_max=max(finished) if finished else None,
    )


def main():
    logging.basicConfig(level=logging.INFO)
    overrides = dict(config.PROJ_SHADOW_OVERRIDES or {})
    if not overrides:
        logger.info("no shadow model configured — nothing to do")
        return 0
    try:
        ctx = refresh_local_data()
        if not ctx["deadline_open"]:
            logger.info("deadline passed for GW%s — shadow not written", ctx["gw"])
            return 0
        runner = project_next_gw(ctx["gw"])
        with config_overrides(overrides):
            shadow = project_next_gw(ctx["gw"])
        rows = shadow_rows(runner, shadow, ctx["season"], ctx["gw"], config.PROJ_SHADOW_MODEL_VERSION)
        upsert(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"], rows)
        logger.info("shadow: gw=%s rows=%s", ctx["gw"], len(rows))
    except Exception as exc:  # noqa: BLE001 — the shadow never fails the job
        logger.warning("shadow snapshot skipped: %s", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
