"""Mounted ONLY when SQUAD_PICKER_MODE=1 (see api/main.py). Dev-only squad picker."""
import json

from fastapi import APIRouter, HTTPException

from src import config, fpl_client, squad_draft
from src.utils import clean_value

router = APIRouter(prefix="/squad-picker", tags=["squad-picker"])

KNOWLEDGE_PATH = getattr(config, "FDR_KNOWLEDGE_DISCOUNT_PATH",
                         "data/models/knowledge_discount.json")
PLAYER_KNOWLEDGE_PATH = getattr(config, "PLAYER_KNOWLEDGE_PATH",
                                "data/models/player_knowledge.json")


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


@router.post("/gk-pairs")
def gk_pairs(params: dict):
    try:
        bootstrap = fpl_client.get_bootstrap()
        fixtures_raw = fpl_client.get_fixtures()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Live FPL fetch failed: {e}")
    try:
        result = squad_draft.gk_rotation_pairs(bootstrap, fixtures_raw, params or {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GK pairs failed: {e}")
    return _sanitize(result)


@router.post("/digest-news")
def digest_news(params: dict):
    try:
        bootstrap = fpl_client.get_bootstrap()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Live FPL fetch failed: {e}")
    from src import news_digest, transforms
    try:
        elements, _teams, _ = transforms.tables_from_bootstrap(bootstrap)
        current_gw = squad_draft._next_gw(bootstrap)
        # A: live first-party injury/availability signal (no LLM, always runs)
        boot = news_digest.digest_bootstrap_news(
            elements, bootstrap.get("events", []), current_gw=current_gw)
        # B: narrative/rotation from the digested news corpus (LLM per match)
        articles = news_digest.load_news_articles((params or {}).get("kb_dir"))
        idx = news_digest.index_by_player(articles, elements)
        article_props = news_digest.propose_player_knowledge(
            idx, elements, current_gw=current_gw)
        # bootstrap wins on conflict; articles add players it doesn't flag
        proposals = news_digest.merge_proposals(article_props, boot)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"News digest failed: {e}")
    return _sanitize({
        "proposals": proposals,
        "article_count": len(articles),
        "matched_players": len(idx),
        "bootstrap_flags": len(boot["players"]),
    })


@router.get("/knowledge")
def get_knowledge():
    try:
        with open(KNOWLEDGE_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"as_of": None, "teams": {}}


@router.get("/player-knowledge")
def get_player_knowledge():
    try:
        with open(PLAYER_KNOWLEDGE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {"as_of": None, "players": {}}


@router.post("/player-knowledge")
def save_player_knowledge(payload: dict):
    import os
    data = {"as_of": payload.get("as_of"), "players": payload.get("players", {})}
    os.makedirs(os.path.dirname(PLAYER_KNOWLEDGE_PATH) or ".", exist_ok=True)
    with open(PLAYER_KNOWLEDGE_PATH, "w") as f:
        json.dump(data, f, indent=2)
    return data


@router.post("/knowledge")
def save_knowledge(payload: dict):
    data = {"as_of": payload.get("as_of"), "teams": payload.get("teams", {})}
    with open(KNOWLEDGE_PATH, "w") as f:
        json.dump(data, f, indent=2)
    return data
