# src/fpl_client.py
import os, time
import requests
from requests.exceptions import RequestException
from urllib.parse import urlparse, parse_qs

# ---- Read CA *dynamically* every call (so setting env before import isn't required)
def _verify():
    return os.environ.get("REQUESTS_CA_BUNDLE") or True

# Try a couple of UAs. Some setups work better with an Android UA + /a/login redirect.
UA_PC = os.getenv("FPL_HTTP_UA",
                  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
UA_ANDROID = "Dalvik/2.1.0 (Linux; U; Android 5.1; Nexus 5 Build/LMY47D)"

def new_session(ua=UA_PC):
    s = requests.Session()
    s.headers.update({
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    })
    return s

def _is_holding(resp):
    try:
        if "holding.html" in (resp.url or "").lower(): return True
        if b"holding" in (resp.content or b"").lower(): return True
    except Exception:
        pass
    return False

def _json_dict(resp):
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "application/json" not in ctype:
        return None
    try:
        data = resp.json()
        return data if isinstance(data, dict) else None
    except ValueError:
        return None

def _do_login_once(s, email, password, redirect_uri):
    payload = {
        "login": email,
        "password": password,
        "app": "plfpl-web",
        "redirect_uri": redirect_uri,  # e.g. https://fantasy.premierleague.com/a/login
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://users.premierleague.com",
        "Referer": "https://users.premierleague.com/accounts/login/",
        "User-Agent": s.headers.get("User-Agent", UA_PC),
    }
    return s.post("https://users.premierleague.com/accounts/login/",
                  data=payload, headers=headers, allow_redirects=True,
                  verify=_verify(), timeout=20)

def login(email, password):
    """
    Returns (session, entry_id, msg). Robust against holding page, non-JSON /api/me/,
    and missing cookies. Tries a desktop UA, then Android UA + /a/login redirect.
    """
    last_err = None
    for attempt in (("PC", UA_PC, "https://fantasy.premierleague.com/"),
                    ("Android", UA_ANDROID, "https://fantasy.premierleague.com/a/login")):
        label, ua, redirect = attempt
        s = new_session(ua=ua)
        try:
            # Warm-ups
            s.get("https://fantasy.premierleague.com/", verify=_verify(), timeout=20)
            s.get(redirect, verify=_verify(), timeout=20)
            # Warm up the users domain too (helps with CSRF/cookies if the flow changed)
            s.get("https://users.premierleague.com/accounts/login/", verify=_verify(), timeout=20)
            time.sleep(1.0)
            r = _do_login_once(s, email, password, redirect)
            if _is_holding(r):
                time.sleep(2.5)
                r = _do_login_once(s, email, password, redirect)

            # If redirect carried a state=fail, expose reason
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
            last_err = f"{type(e).__name__}: {e}"
            continue

    # If we got here, both attempts produced no entry/cookies
    if last_err:
        return None, None, f"Login produced no cookies/entry. Last error: {last_err}"
    return None, None, "Login produced no cookies/entry (holding/proxy/CA). Try cookie login."


def get_me(session=None):
    """
    Returns JSON from /api/me (requires auth cookies).
    Useful for cookie-based login flows.
    """
    s = session or new_session()
    r = s.get(
        "https://fantasy.premierleague.com/api/me/",
        headers={"Accept": "application/json"},
        verify=_verify(),
        timeout=20,
    )
    if r.status_code == 403:
        raise RuntimeError("403 /api/me (cookies missing/expired or blocked).")
    r.raise_for_status()
    data = _json_dict(r)
    if not data:
        snip = (r.text or "")[:160].replace("\n", " ")
        raise RuntimeError(f"/api/me non-JSON. snippet='{snip}…'")
    return data

def get_bootstrap():
    r = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/",
                     verify=_verify(), timeout=20)
    r.raise_for_status()
    return r.json()

def get_fixtures():
    r = requests.get("https://fantasy.premierleague.com/api/fixtures/",
                     verify=_verify(), timeout=20)
    r.raise_for_status()
    return r.json()

def get_entry_picks(
    entry_id,
    event_id,
    session=None,
):
    """
    Fetch an entry's picks for a specific GW (event).

    Notes:
    - This endpoint is generally public for any `entry_id`.
    - Some networks / bot protections may still require a warmed session and
      realistic User-Agent, hence the optional `session`.
    """
    s = session or new_session()
    r = s.get(
        f"https://fantasy.premierleague.com/api/entry/{int(entry_id)}/event/{int(event_id)}/picks/",
        verify=_verify(),
        timeout=20,
    )
    if r.status_code == 403:
        raise RuntimeError("403 /api/entry/.../picks (blocked by network/bot protection).")
    r.raise_for_status()
    return r.json()


def get_my_team(session, entry_id, event_id):
    """
    Backwards-compatible wrapper (older code called this 'my team').
    Prefer `get_entry_picks(entry_id, event_id, session=...)`.
    """
    return get_entry_picks(entry_id=entry_id, event_id=event_id, session=session)

# -------- Optional: allow logging in with an existing browser cookie ----------
def session_from_browser_cookie(pl_profile_value):
    """
    Build a session using a pl_profile cookie copied from your browser.
    Use when POST login is blocked by corp proxy/holding page.
    """
    s = new_session()
    # Set cookie for both potential scopes
    for domain in [".premierleague.com", "fantasy.premierleague.com"]:
        s.cookies.set("pl_profile", pl_profile_value, domain=domain, path="/")
    return s
