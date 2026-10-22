"""POST /wildcard/drafts — three preset wildcard squads + core (require_user)."""
from fastapi import APIRouter, Body, Depends, HTTPException

from api.wildcard import build_wildcard_drafts
from src.auth import require_user

router = APIRouter(prefix="/wildcard", tags=["wildcard"])


MAX_ID_LIST = 15


def parse_id_list(payload, key):
    """A list of at most MAX_ID_LIST ints (deduped, order kept); anything else is a 422."""
    raw = (payload or {}).get(key)
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise HTTPException(status_code=422, detail=f"{key} must be a list of player ids")
    out = []
    for v in raw:
        if isinstance(v, bool) or not isinstance(v, (int, str)):
            raise HTTPException(status_code=422, detail=f"{key} must contain integer player ids")
        try:
            n = int(v)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"{key} must contain integer player ids")
        if n not in out:
            out.append(n)
    if len(out) > MAX_ID_LIST:
        raise HTTPException(status_code=422, detail=f"{key} holds at most {MAX_ID_LIST} ids")
    return out


@router.post("/drafts", dependencies=[Depends(require_user)])
def drafts(payload: dict = Body(None)):
    payload = dict(payload or {})
    if not isinstance(payload.get("entry_id"), (int, str)) or isinstance(payload.get("entry_id"), bool):
        raise HTTPException(status_code=422, detail="entry_id is required")
    try:
        int(payload["entry_id"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="entry_id must be an integer")
    payload["pinned_ids"] = parse_id_list(payload, "pinned_ids")
    payload["excluded_ids"] = parse_id_list(payload, "excluded_ids")
    try:
        return build_wildcard_drafts(payload)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Wildcard drafts failed: {e}")
