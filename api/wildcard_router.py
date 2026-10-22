"""POST /wildcard/drafts — three preset wildcard squads + core (require_user)."""
from fastapi import APIRouter, Body, Depends, HTTPException

from api.wildcard import build_wildcard_drafts
from src.auth import require_user

router = APIRouter(prefix="/wildcard", tags=["wildcard"])


@router.post("/drafts", dependencies=[Depends(require_user)])
def drafts(payload: dict = Body(None)):
    try:
        return build_wildcard_drafts(payload or {})
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Wildcard drafts failed: {e}")
