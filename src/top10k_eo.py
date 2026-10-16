"""Top-10k effective ownership, sampled from the overall league.

The FPL API exposes overall ``selected_by_percent`` only. Rank-aware captaincy
(frontend handoff 1b) wants what the top of the game holds, so we sample
entries from the top ranks of the overall classic league, read their picks for
the current GW and aggregate:

    owned_pct      = entries holding the player / N
    captained_pct  = entries with multiplier >= 2 / N
    eo_pct         = sum(multiplier) / N      (0 bench, 1 start, 2 C, 3 TC)

``eo_pct`` is the sites' "effective ownership". Picks are only readable once
the GW's deadline has passed, so the sample always lags the GW being planned
by one; the file and every record carry ``event_id`` so the UI can say so.

Pure helpers (``aggregate``, ``page_spread``, ``is_current``) have no I/O;
``build_sample`` takes its fetchers as arguments so tests inject fakes.
"""
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from src import config, fpl_client
from src.utils import safe_int

logger = logging.getLogger(__name__)


def aggregate(picks_payloads):
    """Per-player ownership over the readable payloads (``{"picks": [...]}``)."""
    owned = {}
    captained = {}
    weight = {}
    n = 0
    for payload in picks_payloads:
        picks = (payload or {}).get("picks") if isinstance(payload, dict) else None
        if not isinstance(picks, list):
            continue
        n += 1
        for p in picks:
            pid = safe_int(p.get("element"))
            if pid is None:
                continue
            mult = safe_int(p.get("multiplier")) or 0
            owned[pid] = owned.get(pid, 0) + 1
            weight[pid] = weight.get(pid, 0) + mult
            if mult >= 2:
                captained[pid] = captained.get(pid, 0) + 1
    if n == 0:
        return {}
    return {
        pid: {
            "owned_pct": round(100.0 * owned[pid] / n, 1),
            "captained_pct": round(100.0 * captained.get(pid, 0) / n, 1),
            "eo_pct": round(100.0 * weight[pid] / n, 1),
        }
        for pid in owned
    }


def page_spread(pool_ranks, sample_entries, page_size=50):
    """Standings pages to read: ``sample_entries`` worth of pages spread evenly
    across the first ``pool_ranks`` ranks, so the sample is not just ranks 1-1000."""
    total_pages = max(1, int(pool_ranks) // int(page_size))
    want_pages = max(1, min(total_pages, int(sample_entries) // int(page_size)))
    step = total_pages / want_pages
    pages = sorted({min(total_pages, int(i * step) + 1) for i in range(want_pages)})
    return pages


def is_current(data, season, event_id):
    """True when the file already holds this season + GW (the job can skip)."""
    if not isinstance(data, dict):
        return False
    return data.get("season") == season and safe_int(data.get("event_id")) == safe_int(event_id)


def _entries_from_pages(pages, league_id, fetch_standings, session):
    entry_ids = []
    for page in pages:
        try:
            payload = fetch_standings(league_id, page=page, session=session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("top10k standings page %s failed: %s", page, exc)
            continue
        for row in ((payload or {}).get("standings") or {}).get("results") or []:
            eid = safe_int(row.get("entry"))
            if eid:
                entry_ids.append(eid)
    return entry_ids


def build_sample(event_id, season, pages=None, league_id=None, fetch_standings=None, fetch_picks=None, concurrency=None, session=None):
    """Read standings pages, then every entry's picks for ``event_id``; aggregate.

    One failed entry is counted and skipped. If the first batch fails entirely
    the network is blocking us and the run aborts rather than writing an empty
    file over a good one.
    """
    league_id = int(league_id or config.TOP10K_EO_LEAGUE_ID)
    fetch_standings = fetch_standings or fpl_client.get_classic_league_standings
    fetch_picks = fetch_picks or fpl_client.get_entry_picks
    concurrency = int(concurrency or config.TOP10K_EO_CONCURRENCY)
    if pages is None:
        pages = page_spread(config.TOP10K_EO_POOL_RANKS, config.TOP10K_EO_SAMPLE_ENTRIES)

    entry_ids = _entries_from_pages(pages, league_id, fetch_standings, session)
    if not entry_ids:
        raise RuntimeError("top10k sample: no entries read from the standings pages")

    payloads = []
    errors = 0
    last_error = None

    def _one(eid):
        return fetch_picks(eid, int(event_id), session=session)

    first_batch = entry_ids[:concurrency]
    rest = entry_ids[concurrency:]
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        for res in ex.map(lambda e: _safe(_one, e), first_batch):
            if res["ok"]:
                payloads.append(res["value"])
            else:
                errors += 1
                last_error = res["error"]
        if first_batch and not payloads:
            raise RuntimeError(f"top10k sample: every entry in the first batch failed ({last_error})")
        for res in ex.map(lambda e: _safe(_one, e), rest):
            if res["ok"]:
                payloads.append(res["value"])
            else:
                errors += 1

    return {
        "season": season,
        "event_id": int(event_id),
        "league_id": league_id,
        "sample_n": len(payloads),
        "errors": int(errors),
        "sampled_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "players": aggregate(payloads),
    }


def _safe(fn, arg):
    try:
        return {"ok": True, "value": fn(arg)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def save_sample(data, path=None):
    path = Path(path or config.TOP10K_EO_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({**data, "players": {str(k): v for k, v in data["players"].items()}}))
    os.replace(tmp, path)
    return path


def read_file(path=None):
    path = Path(path or config.TOP10K_EO_PATH)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        logger.warning("top10k file unreadable: %s", exc)
        return None


_cache = {"mtime": None, "path": None, "data": None}


def load_eo(path=None, season=None):
    """The sample as ``{event_id, sample_n, players: {int id: {...}}}`` or None.

    Cached on the file's mtime (the job rewrites it once per GW). A file from
    another season is ignored: August must not serve May's ownership.
    """
    path = Path(path or config.TOP10K_EO_PATH)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _cache["data"] is None or _cache["mtime"] != mtime or _cache["path"] != str(path):
        raw = read_file(path)
        data = None
        if isinstance(raw, dict) and isinstance(raw.get("players"), dict):
            data = {
                **raw,
                "players": {int(k): v for k, v in raw["players"].items() if safe_int(k) is not None},
            }
        _cache.update({"mtime": mtime, "path": str(path), "data": data})
    data = _cache["data"]
    if data is None:
        return None
    if season is not None and data.get("season") != season:
        return None
    return data
