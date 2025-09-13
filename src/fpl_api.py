import json, time
from pathlib import Path
import requests, certifi

CACHE_DIR = Path("data"); CACHE_DIR.mkdir(exist_ok=True)
CACHE_TTL = 6 * 3600  # 6h

def _session():
    s = requests.Session()
    s.verify = certifi.where()  # change to False ONLY if you're stuck on corp PC
    s.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://fantasy.premierleague.com/",
    })
    return s

S = _session()

def _cached_get(name, url, ttl=CACHE_TTL, timeout=15):
    fp = CACHE_DIR / f"{name}.json"
    # return fresh cache if recent
    if fp.exists() and (time.time() - fp.stat().st_mtime) < ttl:
        return json.loads(fp.read_text())

    r = S.get(url, timeout=timeout)
    if r.ok:
        fp.write_text(r.text)
        return r.json()

    # fallback to cache if any
    if fp.exists():
        return json.loads(fp.read_text())
    r.raise_for_status()

def bootstrap():
    return _cached_get("bootstrap", "https://fantasy.premierleague.com/api/bootstrap-static/")

def fixtures():
    return _cached_get("fixtures", "https://fantasy.premierleague.com/api/fixtures/")