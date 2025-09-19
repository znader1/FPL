# src/fpl_client.py
from __future__ import annotations
import os, time
from typing import Optional, Tuple, Dict, Any, List
import requests
from requests.exceptions import RequestException
from urllib.parse import urlparse, parse_qs

# ---- Read CA *dynamically* every call (so setting env before import isn't required)
def _verify():
    return os.environ.get("REQUESTS_CA_BUNDLE") or True

# Try a couple of UAs. FPL's community wrapper uses a Dalvik (Android) UA & /a/login redirect. :contentReference[oaicite:0]{index=0}
UA_PC = os.getenv("FPL_HTTP_UA",
                  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
UA_ANDROID = "Dalvik/2.1.0 (Linux; U; Android 5.1; Nexus 5 Build/LMY47D)"

def new_session(ua: str = UA_PC) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    })
    return s

def _is_holding(resp: requests.Response) -> bool:
    try:
        if "holding.html" in (resp.url or "").lower(): return True
        if b"holding" in (resp.content or b"").lower(): return True
    except Exception:
        pass
    return False

def _json_dict(resp: requests.Response) -> Optional[dict]:
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "application/json" not in ctype:
        return None
    try:
        data = resp.json()
        return data if isinstance(data, dict) else None
    except ValueError:
        return None

def _do_login_once(s: requests.Session, email: str, password: str, redirect_uri: str) -> requests.Response:
    payload = {
        "login": email,
        "password": password,
        "app": "plfpl-web",
        "redirect_uri": redirect_uri,  # e.g. https://fantasy.premierleague.com/a/login
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://fantasy.premierleague.com",
        "Referer": "https://fantasy.premierleague.com/",
        "User-Agent": s.headers.get("User-Agent", UA_PC),
    }
    return s.post("https://users.premierleague.com/accounts/login/",
                  data=payload, headers=headers, allow_redirects=True,
                  verify=_verify(), timeout=20)

def login(email: str, password: str) -> Tuple[Optional[requests.Session], Optional[int], str]:
    """
    Returns (session, entry_id, msg). Robust against holding page, non-JSON /api/me/,
    and missing cookies. Tries a desktop UA, then Android UA + /a/login redirect.
    """
    for attempt in (("PC", UA_PC, "https://fantasy.premierleague.com/"),
                    ("Android", UA_ANDROID, "https://fantasy.premierleague.com/a/login")):
        label, ua, redirect = attempt
        s = new_session(ua=ua)
        try:
            # Warm-ups
            s.get("https://fantasy.premierleague.com/", verify=_verify(), timeout=20)
            s.get(redirect, verify=_verify(), timeout=20)
            time.sleep(1.0)

            r = _do_login_once(s, email, password, redirect)
            if _is_holding(r):
                time.sleep(2.5)
                r = _do_login_once(s, email, password, redirect)

            # If redirect carried a state=fail, expose reason (pattern borrowed from community lib). :contentReference[oaicite:1]{index=1}
            try:
                q = parse_qs(urlparse(r.url).query)
                if q.get("state", [""])[0] == "fail":
                    reason = q.get("reason", ["unknown"])[0]
                    return None, None, f"Login ({label}) failed: {reason}"
            except Exception:
                pass

            # Confirm via /api/me
            rme = s.get("https://fantasy.premierleague.com/api/me/",
                        headers={"Accept": "application/json"},
                        verify=_verify(), timeout=20)

            data = _json_dict(rme)
            cookie_names = [c.name for c in s.cookies]

            if rme.status_code != 200:
                return None, None, f"/api/me HTTP {rme.status_code}; cookies={cookie_names}"

            if not data:
                snip = (rme.text or "")[:160].replace("\n", " ")
                return None, None, f"/api/me non-JSON (likely holding/proxy). cookies={cookie_names} snippet='{snip}…'"

            entry = (data.get("player") or {}).get("entry")
            if not entry:
                # No entry → auth not sticking for this attempt; try next UA combo.
                continue

            return s, int(entry), f"OK via {label} UA"

        except RequestException as e:
            # Try the next attempt combo
            last_err = str(e)
            continue

    # If we got here, both attempts produced no entry/cookies
    return None, None, "Login produced no cookies/entry (holding/proxy/CA). Try cookie login."

def get_bootstrap() -> Dict[str, Any]:
    r = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/",
                     verify=_verify(), timeout=20)
    r.raise_for_status()
    return r.json()

def get_fixtures() -> List[dict]:
    r = requests.get("https://fantasy.premierleague.com/api/fixtures/",
                     verify=_verify(), timeout=20)
    r.raise_for_status()
    return r.json()

def get_my_team(session: requests.Session, entry_id: int) -> Dict[str, Any]:
    r = session.get(f"https://fantasy.premierleague.com/api/entry/{entry_id}/event/4/picks/",
                    verify=_verify(), timeout=20)
    if r.status_code == 403:
        raise RuntimeError("403 /api/my-team (cookies expired or blocked).")
    r.raise_for_status()
    return r.json()

# -------- Optional: allow logging in with an existing browser cookie ----------
def session_from_browser_cookie(pl_profile_value: str) -> requests.Session:
    """
    Build a session using a pl_profile cookie copied from your browser.
    Use when POST login is blocked by corp proxy/holding page.
    """
    s = new_session()
    # Set cookie for both potential scopes
    for domain in [".premierleague.com", "fantasy.premierleague.com"]:
        s.cookies.set("pl_profile", pl_profile_value, domain=domain, path="/")
    return s
