"""Admin endpoints for news auto-apply: run, inspect, revert.

All routes require the admin key. Paths always come from config, never from
the client. Error bodies are generic (no stack traces / internals).
"""
import logging
import re
import threading
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse

from src import config, news_auto, news_auto_run
from src.auth import require_admin
from src.player_knowledge import load_auto_knowledge
from src.squad_draft import _next_gw

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_admin)])

_DIGITS = re.compile(r"[0-9]{1,9}")  # always .fullmatch
_RUN_ID = re.compile(r"[A-Za-z0-9_.:-]{1,64}")  # always .fullmatch


def _bootstrap():
    from api import main as _main  # lazy: avoids a circular import
    return _main.get_bootstrap_cached()


@router.post("/admin/refresh-news", status_code=202)
def refresh_news():
    out_dir = config.NEWS_AUTO_DIR
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    if not news_auto_run.acquire_lock(out_dir, run_id):
        return JSONResponse(status_code=409,
                            content={"detail": "news run already in progress"})
    try:
        bootstrap = _bootstrap()
        # run() releases the lock itself in its finally (lock_held=True).
        threading.Thread(
            target=news_auto_run.run, args=(bootstrap,),
            kwargs={"run_id": run_id, "lock_held": True}, daemon=True,
        ).start()
    except Exception:  # noqa: BLE001
        logger.exception("news run failed to start")
        news_auto_run.release_lock(out_dir, run_id)
        raise HTTPException(status_code=500, detail="failed to start news run")
    return {"run_id": run_id, "started": now.strftime("%Y-%m-%dT%H:%M:%SZ")}


@router.get("/admin/news-status")
def news_status():
    return news_auto_run.read_status()


def _parse_selector(body):
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="body must be an object")
    has_ids, has_run = "player_ids" in body, "run_id" in body
    if has_ids == has_run:
        raise HTTPException(status_code=422,
                            detail="provide exactly one of player_ids or run_id")
    if has_run:
        rid = body["run_id"]
        if not isinstance(rid, str) or not _RUN_ID.fullmatch(rid):
            raise HTTPException(status_code=422, detail="invalid run_id")
        return None, rid
    ids = body["player_ids"]
    if not isinstance(ids, list) or not ids or len(ids) > 500:
        raise HTTPException(status_code=422, detail="player_ids must be a non-empty list")
    out = []
    for v in ids:
        if isinstance(v, bool) or not isinstance(v, (int, str)) or not _DIGITS.fullmatch(str(v)):
            raise HTTPException(status_code=422, detail="player_ids must be digits only")
        out.append(str(int(v)))
    return out, None


@router.post("/admin/news-knowledge/revert")
def revert_news_knowledge(body=Body(...)):
    player_ids, run_id = _parse_selector(body)
    out_dir = config.NEWS_AUTO_DIR
    auto_path = config.PLAYER_KNOWLEDGE_AUTO_PATH
    token = f"revert-{uuid.uuid4().hex}"
    if not news_auto_run.acquire_lock(out_dir, token):
        return JSONResponse(status_code=409,
                            content={"detail": "news run already in progress"})
    try:
        gw = _next_gw(_bootstrap())
        auto, events = news_auto.revert(load_auto_knowledge(auto_path),
                                        player_ids, run_id, gw)
        if events:
            news_auto_run.write_auto(auto_path, auto)
            news_auto_run.append_log(out_dir, events, token)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("news revert failed")
        raise HTTPException(status_code=500, detail="revert failed")
    finally:
        news_auto_run.release_lock(out_dir, token)
    return {"reverted": [e["player_id"] for e in events]}
