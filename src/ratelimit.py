"""Shared rate-limiting primitives and the request-size ceiling.

Lives outside api/main.py so the chat router can share the same limiter instance
without importing api.main at module scope (which would be circular).

Two keys, deliberately:

* ``_client_ip`` — the default per-IP bucket. Trusts only proxy-set headers; see
  ``docs/prelaunch_audit_2026-09-12.md`` (C2) for why the left-most
  X-Forwarded-For entry is attacker-controlled on Fly.
* ``_user_key`` — the per-account bucket used on LLM-spending routes, so
  rotating IPs does not hand the same account a fresh budget (C2 + H5).
"""
import os

from slowapi import Limiter
from slowapi.util import get_remote_address

from src import auth
from src import llm_usage

# Starlette buffers the whole body before deserialization and the production VM
# has 512MB, so an unbounded POST is an OOM kill. 2MB comfortably fits the
# largest legitimate payload (a 15-player squad plus recommendations).
MAX_REQUEST_BYTES = int(os.environ.get("FPL_MAX_REQUEST_BYTES") or 2 * 1024 * 1024)

# LLM-spending routes get their own, much tighter ceiling on top of the default.
LLM_LIMIT = os.environ.get("FPL_LLM_RATE_LIMIT") or "20/hour"


def _csv_env(name):
    raw = (os.environ.get(name) or "").strip()
    return [p.strip() for p in raw.split(",") if p.strip()] if raw else None


def _client_ip(request):
    """The rate-limit bucket key. Must not be attacker-controlled.

    Fly *appends* the real client address to any inbound X-Forwarded-For rather
    than replacing it, so the left-most entry is whatever the caller sent —
    rotating it defeated every limit in the app. ``Fly-Client-IP`` is written by
    the proxy and cannot be set from outside; off Fly, the right-most XFF hop is
    the one our own proxy appended.
    """
    fly_ip = (request.headers.get("fly-client-ip") or "").strip()
    if fly_ip:
        return fly_ip
    xff = request.headers.get("x-forwarded-for")
    if xff:
        hops = [h.strip() for h in xff.split(",") if h.strip()]
        if hops:
            return hops[-1]
    return get_remote_address(request)


def _user_key(request):
    """Per-account bucket for LLM routes; falls back to the IP when anonymous."""
    token = auth._bearer(request.headers.get("authorization"))
    if token:
        claims = auth.verify_supabase_jwt(token)
        sub = (claims or {}).get("sub")
        if sub:
            llm_usage.bind_user(sub)  # tag this request's LLM usage records
            return f"user:{sub}"
    return _client_ip(request)


_rl_default = _csv_env("FPL_RATE_LIMITS") or ["90/minute", "1500/hour"]
limiter = Limiter(key_func=_client_ip, default_limits=_rl_default, headers_enabled=True)
