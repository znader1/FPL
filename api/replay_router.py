"""Personal GW-replay API. Serves precomputed static JSON from data/replay/.
Mounted ONLY when REPLAY_MODE=1 (see api/main.py). Never falls back to the live
FPL API — a missing file is a 404, by design."""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/replay", tags=["replay"])

_BASE = Path("data/replay")


def _season_dir(season):
    return _BASE / season


@router.get("/seasons")
def seasons():
    if not _BASE.exists():
        return {"seasons": []}
    return {"seasons": sorted(p.name for p in _BASE.iterdir()
                              if p.is_dir() and any(p.glob("gw*.json")))}


def _load_entry(season, entry_id):
    if not entry_id:
        return None
    p = _season_dir(season) / f"entry_{entry_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


@router.get("/{season}/gw/{gw}")
def gw(season: str, gw: int, entry_id: int = Query(None)):
    p = _season_dir(season) / f"gw{gw:02d}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"No replay record for season {season} GW {gw}")
    record = json.loads(p.read_text())
    entry = _load_entry(season, entry_id)
    record["your"] = (entry.get("gws", {}) or {}).get(str(gw)) if entry else None
    return record


@router.get("/{season}/summary")
def summary(season: str, entry_id: int = Query(None)):
    entry = _load_entry(season, entry_id)
    gws = (entry.get("gws", {}) if entry else {}) or {}
    rows = [{"gw": int(k), "your_points": v.get("points")} for k, v in sorted(gws.items(), key=lambda x: int(x[0]))]
    total = sum(r["your_points"] or 0 for r in rows)
    return {"season": season, "gws": rows, "your_total": total}
