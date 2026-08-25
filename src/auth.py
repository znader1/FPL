"""Request authentication.

Two mechanisms:

* **User routes** — a valid Supabase user access token (JWT) presented as
  ``Authorization: Bearer <token>``. The signature is verified against the
  project's public JWKS (asymmetric ES256), so no shared secret is needed on
  the server. Optionally, a static ``FPL_API_KEY`` presented via the
  ``X-API-Key`` header is also accepted (for server-to-server scripts / tests).
* **Admin routes** — a static ``FPL_ADMIN_KEY`` via ``X-API-Key`` (or bearer).

Both checks **fail closed**: if the required credential can't be validated the
request is rejected. Keys are compared with ``hmac.compare_digest`` to avoid
timing leaks, and API keys are never read from the query string / body.
"""
import os
import hmac
import logging

from fastapi import Header, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# The production Supabase project. Public info (URL only) — override per-env
# with FPL_SUPABASE_URL / FPL_SUPABASE_JWKS_URL. Kept as a default so a deploy
# that forgets the env var still verifies tokens instead of locking everyone out.
_DEFAULT_SUPABASE_URL = "https://tetvymwgpaordnmsnneo.supabase.co"

_JWKS_CLIENT = None


def _supabase_url():
    return (
        os.environ.get("FPL_SUPABASE_URL")
        or os.environ.get("SUPABASE_URL")
        or _DEFAULT_SUPABASE_URL
    ).strip().rstrip("/")


def _jwks_url():
    explicit = (os.environ.get("FPL_SUPABASE_JWKS_URL") or "").strip()
    if explicit:
        return explicit
    base = _supabase_url()
    return f"{base}/auth/v1/.well-known/jwks.json" if base else ""


def _get_jwks_client():
    """Lazily build (and cache) the PyJWKClient. Returns None if unavailable."""
    global _JWKS_CLIENT
    if _JWKS_CLIENT is not None:
        return _JWKS_CLIENT
    url = _jwks_url()
    if not url:
        return None
    try:
        from jwt import PyJWKClient
        _JWKS_CLIENT = PyJWKClient(url, cache_keys=True, lifespan=3600)
    except Exception as e:  # pragma: no cover - import/network edge
        logger.warning("Could not init Supabase JWKS client: %s", e)
        return None
    return _JWKS_CLIENT


def verify_supabase_jwt(token):
    """Return decoded claims for a valid Supabase access token, else None."""
    if not token:
        return None
    client = _get_jwks_client()
    if client is None:
        return None
    try:
        import jwt
        signing_key = client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
    except Exception:
        return None


def _bearer(authorization):
    auth = (authorization or "").strip()
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def _static_key_ok(x_api_key):
    required = (os.environ.get("FPL_API_KEY") or "").strip()
    if not required:
        return False
    got = str(x_api_key).strip() if x_api_key is not None else ""
    return bool(got) and hmac.compare_digest(got, required)


def check_api_key(x_api_key=None, authorization=None, api_key=None):
    """Allow a valid Supabase user JWT, or the optional static service key.

    ``api_key`` (query/body) is intentionally ignored — keys must not travel in
    URLs or request bodies. Returns None on success, a 401 JSONResponse on failure.
    """
    token = _bearer(authorization)
    if token and verify_supabase_jwt(token) is not None:
        return None
    if _static_key_ok(x_api_key):
        return None
    return JSONResponse(status_code=401, content={"error": "Unauthorized"})


def check_admin_key(x_api_key=None, authorization=None, api_key=None):
    """Require the static admin key. Fails closed if none is configured."""
    required = (os.environ.get("FPL_ADMIN_KEY") or os.environ.get("FPL_API_KEY") or "").strip()
    if not required:
        return JSONResponse(status_code=503, content={"error": "Admin key not configured"})
    for candidate in (str(x_api_key).strip() if x_api_key is not None else "", _bearer(authorization) or ""):
        if candidate and hmac.compare_digest(candidate, required):
            return None
    return JSONResponse(status_code=401, content={"error": "Unauthorized (admin key required)"})


# --- FastAPI dependencies (raise instead of returning a response) ---------

def require_user(authorization: str = Header(None), x_api_key: str = Header(None)):
    if check_api_key(x_api_key=x_api_key, authorization=authorization) is not None:
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_admin(authorization: str = Header(None), x_api_key: str = Header(None)):
    if check_admin_key(x_api_key=x_api_key, authorization=authorization) is not None:
        raise HTTPException(status_code=401, detail="Unauthorized (admin key required)")
