import os
import time
from datetime import datetime

import pandas as pd
from fastapi import Body, FastAPI, HTTPException, Header
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src import config, fpl_client, optimizer, projections, recommender, transforms


app = FastAPI(title="FPL Assistant API", version="0.1.0")


def _csv_env(name):
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


cors_origins = _csv_env("FPL_API_CORS_ORIGINS")
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


_bootstrap_cache = {"ts": 0.0, "data": None}
_fixtures_cache = {"ts": 0.0, "data": None}


def _cache_get(cache, ttl_s):
    now = time.time()
    if cache.get("data") is not None and (now - float(cache.get("ts") or 0.0)) < float(ttl_s):
        return cache["data"]
    return None


def _cache_set(cache, data):
    cache["data"] = data
    cache["ts"] = time.time()
    return data


def get_bootstrap_cached():
    ttl = int(getattr(config, "BOOTSTRAP_TTL", 300) or 300)
    hit = _cache_get(_bootstrap_cache, ttl)
    if hit is not None:
        return hit
    return _cache_set(_bootstrap_cache, fpl_client.get_bootstrap())


def get_fixtures_cached():
    ttl = int(getattr(config, "FIXTURES_TTL", 300) or 300)
    hit = _cache_get(_fixtures_cache, ttl)
    if hit is not None:
        return hit
    fx = transforms.fixtures_df(fpl_client.get_fixtures())
    return _cache_set(_fixtures_cache, fx)


def _event_id(bootstrap, flag):
    for ev in bootstrap.get("events", []):
        if ev.get(flag):
            try:
                return int(ev.get("id"))
            except Exception:
                return None
    return None


def _default_picks_event_id(bootstrap):
    return _event_id(bootstrap, "is_next") or _event_id(bootstrap, "is_current") or 1


def _safe_int(x):
    try:
        return int(x)
    except Exception:
        return None


def _safe_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default


def _parse_bool(x, default=False):
    if isinstance(x, bool):
        return x
    if x is None:
        return default
    s = str(x).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off", ""):
        return False
    return default


def _extract_api_key(x_api_key, authorization, api_key):
    if api_key is not None and str(api_key).strip() != "":
        return str(api_key).strip()
    if x_api_key is not None and str(x_api_key).strip() != "":
        return str(x_api_key).strip()
    auth = (authorization or "").strip()
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def _check_api_key(x_api_key=None, authorization=None, api_key=None):
    required = (os.environ.get("FPL_API_KEY") or "").strip()
    if not required:
        return None

    got = _extract_api_key(x_api_key, authorization, api_key)
    if got == required:
        return None

    return JSONResponse(status_code=401, content={"error": "Unauthorized"})


def team_badge_url(team_code, size=50):
    """
    Best-effort PL badge URL. Not official API; may change.
    """
    team_code = _safe_int(team_code)
    if not team_code:
        return None
    return f"https://resources.premierleague.com/premierleague/badges/{int(size)}/t{team_code}.png"


def player_photo_url(player_code=None, photo=None, size="110x140"):
    """
    Best-effort player photo URL. Not official API; may change.
    """
    pid = _safe_int(player_code)
    if not pid and photo:
        try:
            raw = str(photo).split(".")[0]
            digits = "".join(ch for ch in raw if ch.isdigit())
            pid = int(digits) if digits else None
        except Exception:
            pid = None
    if not pid:
        return None
    return f"https://resources.premierleague.com/premierleague/photos/players/{size}/p{pid}.png"


def _clean_value(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            pass
    if isinstance(v, (datetime, pd.Timestamp)):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    return v


def _df_records(df):
    recs = []
    if df is None or getattr(df, "empty", True):
        return recs
    for _, r in df.iterrows():
        d = {}
        for k, v in r.items():
            d[str(k)] = _clean_value(v)
        recs.append(d)
    return recs


def _attach_media(records, teams_code_map):
    for d in records:
        team_id = _safe_int(d.get("team"))
        team_code = teams_code_map.get(team_id) if team_id is not None else None
        d["badge_url"] = team_badge_url(team_code, size=50)
        d["photo_url"] = player_photo_url(d.get("code"), d.get("photo"), size="110x140")
    return records


def build_recommendations(payload):
    entry_id = payload.get("entry_id") or os.environ.get("FPL_ENTRY_ID")
    event_id = payload.get("event_id")
    horizon_gws = payload.get("horizon_gws", 3)
    include_transfers = _parse_bool(payload.get("include_transfers"), default=False)
    itb_m = payload.get("itb_m", 0.5)
    free_transfers = payload.get("free_transfers", 1)
    hit_cap = payload.get("hit_cap", 0)

    entry_id = _safe_int(entry_id)
    if not entry_id:
        raise HTTPException(status_code=400, detail="Missing/invalid entry_id.")

    bootstrap = get_bootstrap_cached()
    if event_id is None or str(event_id).strip() == "":
        event_id = _default_picks_event_id(bootstrap)
    event_id = _safe_int(event_id)
    if not event_id:
        raise HTTPException(status_code=400, detail="Missing/invalid event_id.")

    horizon_gws = _safe_int(horizon_gws) or 3
    horizon_gws = max(1, min(8, int(horizon_gws)))

    fixtures = get_fixtures_cached()
    elements, teams, _ = transforms.tables_from_bootstrap(bootstrap)
    teams_short = teams.set_index("id")["short_name"].to_dict()
    teams_code = teams.set_index("id")["code"].to_dict() if "code" in teams.columns else {}

    try:
        myteam = fpl_client.get_entry_picks(entry_id, event_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch entry picks: {e}")

    squad_df = transforms.picks_to_df(myteam, elements)
    if squad_df is None or squad_df.empty:
        raise HTTPException(status_code=404, detail="No picks returned for that entry/event.")

    try:
        proj_all = projections.project_elements_next_gws(
            elements=elements,
            fixtures=fixtures,
            teams_short_map=teams_short,
            gw_start=event_id,
            horizon_gws=horizon_gws,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Projection failed: {e}")

    score_col = f"xpts_gw{int(event_id)}"
    try:
        res = optimizer.optimize_lineup(squad_df, proj_all, score_col=score_col)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Optimize failed: {e}")
    if not res:
        raise HTTPException(status_code=500, detail="Could not optimize lineup for this squad.")

    el_img = elements.copy()
    cols = [c for c in ["id", "team", "code", "photo"] if c in el_img.columns]
    el_img = el_img[cols].rename(columns={"id": "player_id"})

    starting = res["starting_xi"].merge(el_img, on="player_id", how="left")
    bench = res["bench"].merge(el_img, on="player_id", how="left")
    starting_records = _attach_media(_df_records(starting), teams_code)
    bench_records = _attach_media(_df_records(bench), teams_code)

    out = {
        "entry_id": int(entry_id),
        "event_id": int(event_id),
        "horizon_gws": int(horizon_gws),
        "formation": list(res["formation"]),
        "captain_player_id": int(res["captain_player_id"]),
        "vice_player_id": int(res["vice_player_id"]),
        "projected_points_with_captain": float(res["projected_points_with_captain"]),
        "starting_xi": starting_records,
        "bench": bench_records,
    }

    if include_transfers:
        rec = recommender.suggest_transfers(
            squad_df=squad_df,
            elements_all=proj_all,
            itb_m=_safe_float(itb_m, default=0.0) or 0.0,
            free_transfers=_safe_int(free_transfers) or 1,
            hit_cap=_safe_int(hit_cap) or 0,
            score_col="xpts_horizon",
        )
        out["transfers"] = rec

    return out


@app.get("/health")
def health():
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z"}


@app.get("/recommendations")
def recommendations_get(
    entry_id=None,
    event_id=None,
    horizon_gws=3,
    include_transfers=False,
    itb_m=0.5,
    free_transfers=1,
    hit_cap=0,
    api_key=None,
    x_api_key=Header(None),
    authorization=Header(None),
):
    err = _check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key)
    if err:
        return err
    payload = {
        "entry_id": entry_id,
        "event_id": event_id,
        "horizon_gws": horizon_gws,
        "include_transfers": include_transfers,
        "itb_m": itb_m,
        "free_transfers": free_transfers,
        "hit_cap": hit_cap,
    }
    out = build_recommendations(payload)
    return JSONResponse(content=jsonable_encoder(out))


@app.post("/recommendations")
def recommendations_post(
    payload=Body(None),
    api_key=None,
    x_api_key=Header(None),
    authorization=Header(None),
):
    err = _check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key or (payload or {}).get("api_key"))
    if err:
        return err
    out = build_recommendations(payload or {})
    return JSONResponse(content=jsonable_encoder(out))
