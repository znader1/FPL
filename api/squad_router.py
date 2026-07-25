"""Mounted ONLY when SQUAD_PICKER_MODE=1 (see api/main.py). Dev-only squad picker."""
import json

from fastapi import APIRouter, HTTPException

from src import config, fpl_client, squad_draft
from src.utils import clean_value

router = APIRouter(prefix="/squad-picker", tags=["squad-picker"])

KNOWLEDGE_PATH = getattr(config, "FDR_KNOWLEDGE_DISCOUNT_PATH",
                         "data/models/knowledge_discount.json")


def _sanitize(obj):
    """Recursively replace NaN/NaT/Inf (and numpy scalar types) with JSON-safe
    values. squad_draft builds records via DataFrame.to_dict(), which leaves
    raw NaN floats in place; Starlette's default JSONResponse serializes with
    allow_nan=False and would otherwise 500 on any missing optional stat
    (e.g. penalties_order for a player with no penalty duty)."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return clean_value(obj)


@router.post("/build")
def build(params: dict):
    try:
        bootstrap = fpl_client.get_bootstrap()
        fixtures_raw = fpl_client.get_fixtures()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Live FPL fetch failed: {e}")
    try:
        result = squad_draft.build_squad(bootstrap, fixtures_raw, params or {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Squad build failed: {e}")
    return _sanitize(result)


@router.post("/players")
def players(params: dict):
    try:
        bootstrap = fpl_client.get_bootstrap()
        fixtures_raw = fpl_client.get_fixtures()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Live FPL fetch failed: {e}")
    try:
        result = squad_draft.player_pool(bootstrap, fixtures_raw, params or {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Player pool failed: {e}")
    return _sanitize(result)


@router.post("/lineup")
def lineup(payload: dict):
    try:
        bootstrap = fpl_client.get_bootstrap()
        fixtures_raw = fpl_client.get_fixtures()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Live FPL fetch failed: {e}")
    try:
        result = squad_draft.build_lineup(
            bootstrap, fixtures_raw,
            payload.get("player_ids", []), payload.get("params", {}))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lineup failed: {e}")
    return _sanitize(result)


@router.get("/knowledge")
def get_knowledge():
    try:
        with open(KNOWLEDGE_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"as_of": None, "teams": {}}


@router.post("/knowledge")
def save_knowledge(payload: dict):
    data = {"as_of": payload.get("as_of"), "teams": payload.get("teams", {})}
    with open(KNOWLEDGE_PATH, "w") as f:
        json.dump(data, f, indent=2)
    return data
