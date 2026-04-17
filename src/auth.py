import os

from fastapi.responses import JSONResponse


def _extract_api_key(x_api_key, authorization, api_key):
    if api_key is not None and str(api_key).strip() != "":
        return str(api_key).strip()
    if x_api_key is not None and str(x_api_key).strip() != "":
        return str(x_api_key).strip()
    auth = (authorization or "").strip()
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def check_api_key(x_api_key=None, authorization=None, api_key=None):
    required = (os.environ.get("FPL_API_KEY") or "").strip()
    if not required:
        return None
    got = _extract_api_key(x_api_key, authorization, api_key)
    if got == required:
        return None
    return JSONResponse(status_code=401, content={"error": "Unauthorized"})


def check_admin_key(x_api_key=None, authorization=None, api_key=None):
    required = (os.environ.get("FPL_ADMIN_KEY") or os.environ.get("FPL_API_KEY") or "").strip()
    if not required:
        return None
    got = _extract_api_key(x_api_key, authorization, api_key)
    if got == required:
        return None
    return JSONResponse(status_code=401, content={"error": "Unauthorized (admin key required)"})
