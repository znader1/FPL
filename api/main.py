import os
import time
from datetime import datetime

import pandas as pd
from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src import config, fpl_client, optimizer, projections, recommender, transforms


app = FastAPI(title="FPL Assistant API", version="0.2.0")


def _csv_env(name):
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


cors_origins = _csv_env("FPL_API_CORS_ORIGINS")
if not cors_origins:
    cors_origins = [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8082",
    ]

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
    # "Squad GW": use the currently active GW first (more likely to have picks),
    # then fallback to next.
    return _event_id(bootstrap, "is_current") or _event_id(bootstrap, "is_next") or 1


def _default_optimize_event_id(bootstrap):
    # "Optimize GW": usually the next GW you want to plan for.
    return _event_id(bootstrap, "is_next") or _event_id(bootstrap, "is_current") or 1


def _max_event_id(bootstrap):
    try:
        ev_ids = [int(ev.get("id")) for ev in bootstrap.get("events", []) if ev.get("id") is not None]
        return max(ev_ids) if ev_ids else 38
    except Exception:
        return 38


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
    team_code = _safe_int(team_code)
    if not team_code:
        return None
    return f"https://resources.premierleague.com/premierleague/badges/{int(size)}/t{team_code}.png"


def player_photo_url(player_code=None, photo=None, size="110x140"):
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


def load_fpl_context(entry_id, squad_event_id, with_fixtures=True):
    notes = []

    entry_id = _safe_int(entry_id or os.environ.get("FPL_ENTRY_ID"))
    if not entry_id:
        raise HTTPException(status_code=400, detail="Missing/invalid entry_id.")

    bootstrap = get_bootstrap_cached()
    max_event_id = _max_event_id(bootstrap)

    explicit_squad_event = squad_event_id is not None and str(squad_event_id).strip() != ""
    requested_squad_event_id = _safe_int(squad_event_id) if explicit_squad_event else None
    if explicit_squad_event and not requested_squad_event_id:
        notes.append("Invalid squad_event_id; using defaults.")

    current_event_id = _event_id(bootstrap, "is_current")
    next_event_id = _event_id(bootstrap, "is_next")
    default_squad_event_id = _default_picks_event_id(bootstrap)

    candidates = []
    for cand in [
        requested_squad_event_id,
        default_squad_event_id,
        current_event_id,
        (int(current_event_id) - 1) if current_event_id and int(current_event_id) > 1 else None,
        next_event_id,
    ]:
        if cand is None:
            continue
        cand = _safe_int(cand)
        if not cand:
            continue
        if int(cand) < 1:
            cand = 1
        if int(cand) > int(max_event_id):
            cand = int(max_event_id)
        if cand not in candidates:
            candidates.append(int(cand))

    fixtures = get_fixtures_cached() if with_fixtures else None
    elements, teams, _ = transforms.tables_from_bootstrap(bootstrap)
    teams_short = teams.set_index("id")["short_name"].to_dict()
    teams_code = teams.set_index("id")["code"].to_dict() if "code" in teams.columns else {}

    myteam = None
    used_event_id = None
    last_err = None
    for cand in candidates:
        try:
            myteam = fpl_client.get_entry_picks(entry_id, int(cand))
            used_event_id = int(cand)
            break
        except Exception as e:
            last_err = e
            continue

    if not myteam or not used_event_id:
        raise HTTPException(status_code=502, detail=f"Failed to fetch entry picks. Last error: {last_err}")

    if explicit_squad_event and requested_squad_event_id and int(used_event_id) != int(requested_squad_event_id):
        notes.append(f"squad_event_id {int(requested_squad_event_id)} not available; used {int(used_event_id)}.")

    squad_df = transforms.picks_to_df(myteam, elements)
    if squad_df is None or squad_df.empty:
        raise HTTPException(status_code=404, detail="No picks returned for that entry/event.")

    return {
        "entry_id": int(entry_id),
        "squad_event_id": int(used_event_id),
        "max_event_id": int(max_event_id),
        "bootstrap": bootstrap,
        "fixtures": fixtures,
        "elements": elements,
        "teams": teams,
        "teams_short": teams_short,
        "teams_code": teams_code,
        "myteam": myteam,
        "squad_df": squad_df,
        "notes": notes,
    }


def build_squad(payload):
    ctx = load_fpl_context(payload.get("entry_id"), payload.get("event_id"), with_fixtures=False)

    elements = ctx["elements"]
    teams_code = ctx["teams_code"]
    myteam = ctx["myteam"]

    picks = pd.DataFrame(myteam.get("picks", []))
    if picks.empty:
        raise HTTPException(status_code=404, detail="No picks in response.")

    picks = picks.rename(columns={"element": "player_id"})
    for c in ["player_id", "position", "multiplier"]:
        if c in picks.columns:
            picks[c] = pd.to_numeric(picks[c], errors="coerce")

    el_cols = [c for c in ["id", "web_name", "team", "team_short", "team_name", "pos", "code", "photo"] if c in elements.columns]
    el_small = elements[el_cols].rename(columns={"id": "player_id"})
    picks = picks.merge(el_small, on="player_id", how="left")

    if "position" in picks.columns:
        picks["bench_order"] = picks["position"].apply(lambda p: int(p) - 11 if pd.notna(p) and int(p) > 11 else None)
        picks = picks.sort_values("position")

    records = _attach_media(_df_records(picks), teams_code)

    starting = []
    bench = []
    for r in records:
        pos = _safe_int(r.get("position"))
        if pos is not None and pos > 11:
            bench.append(r)
        else:
            starting.append(r)
    bench.sort(key=lambda r: _safe_int(r.get("bench_order")) or 99)

    captain_id = None
    vice_id = None
    for r in records:
        if r.get("is_captain") is True:
            captain_id = _safe_int(r.get("player_id"))
        if r.get("is_vice_captain") is True:
            vice_id = _safe_int(r.get("player_id"))

    return {
        "entry_id": ctx["entry_id"],
        "event_id": ctx["squad_event_id"],
        "notes": ctx.get("notes") or [],
        "captain_player_id": captain_id,
        "vice_player_id": vice_id,
        "starting_xi": starting,
        "bench": bench,
        "entry_history": myteam.get("entry_history"),
        "active_chip": myteam.get("active_chip"),
    }


def build_recommendations(payload):
    entry_id = payload.get("entry_id") or os.environ.get("FPL_ENTRY_ID")
    optimize_event_id_raw = payload.get("event_id")
    squad_event_id_raw = payload.get("squad_event_id")
    horizon_gws_raw = payload.get("horizon_gws", 3)

    include_transfers = _parse_bool(payload.get("include_transfers"), default=False)
    itb_m = payload.get("itb_m", 0.5)
    free_transfers = payload.get("free_transfers", 1)
    hit_cap = payload.get("hit_cap", 0)

    ctx = load_fpl_context(entry_id, squad_event_id_raw, with_fixtures=True)
    notes = list(ctx.get("notes") or [])

    entry_id = ctx["entry_id"]
    squad_event_id = ctx["squad_event_id"]
    max_event_id = ctx["max_event_id"]

    explicit_optimize_event = optimize_event_id_raw is not None and str(optimize_event_id_raw).strip() != ""
    optimize_event_id = _safe_int(optimize_event_id_raw)
    if explicit_optimize_event and not optimize_event_id:
        notes.append("Invalid event_id; using default optimize GW.")
        optimize_event_id = None
    if optimize_event_id is None:
        optimize_event_id = _default_optimize_event_id(ctx["bootstrap"])
        if not optimize_event_id:
            optimize_event_id = int(squad_event_id)

    if int(optimize_event_id) < 1:
        notes.append("event_id < 1; clamped to 1.")
        optimize_event_id = 1
    if int(optimize_event_id) > int(max_event_id):
        notes.append(f"event_id > {int(max_event_id)}; clamped to {int(max_event_id)}.")
        optimize_event_id = int(max_event_id)

    horizon_gws = _safe_int(horizon_gws_raw)
    if horizon_gws is None:
        notes.append("Invalid horizon_gws; using 3.")
        horizon_gws = 3
    horizon_gws = max(1, min(8, int(horizon_gws)))
    remaining = int(max_event_id) - int(optimize_event_id) + 1
    if remaining < 1:
        remaining = 1
    if int(horizon_gws) > int(remaining):
        notes.append(f"horizon_gws trimmed to {int(remaining)} (season end).")
        horizon_gws = int(remaining)

    fixtures = ctx["fixtures"]
    elements = ctx["elements"]
    teams_short = ctx["teams_short"]
    teams_code = ctx["teams_code"]
    squad_df = ctx["squad_df"]

    try:
        proj_all = projections.project_elements_next_gws(
            elements=elements,
            fixtures=fixtures,
            teams_short_map=teams_short,
            gw_start=optimize_event_id,
            horizon_gws=horizon_gws,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Projection failed: {e}")

    score_col = f"xpts_gw{int(optimize_event_id)}"
    try:
        res = optimizer.optimize_lineup(squad_df, proj_all, score_col=score_col)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Optimize failed: {e}")
    if not res:
        raise HTTPException(status_code=500, detail="Could not optimize lineup for this squad.")

    gws = [int(optimize_event_id) + i for i in range(int(horizon_gws))]

    el_img = elements.copy()
    cols = [c for c in ["id", "team", "code", "photo"] if c in el_img.columns]
    el_img = el_img[cols].rename(columns={"id": "player_id"})

    proj_cols = ["id"]
    if "xpts_horizon" in proj_all.columns:
        proj_cols.append("xpts_horizon")
    for gw in gws:
        for c in [f"xpts_gw{gw}", f"fixtures_gw{gw}", f"fixture_count_gw{gw}", f"diff_avg_gw{gw}"]:
            if c in proj_all.columns:
                proj_cols.append(c)
    proj_small = proj_all[list(dict.fromkeys(proj_cols))].copy().rename(columns={"id": "player_id"})

    starting = res["starting_xi"].merge(el_img, on="player_id", how="left").merge(proj_small, on="player_id", how="left")
    bench = res["bench"].merge(el_img, on="player_id", how="left").merge(proj_small, on="player_id", how="left")
    starting_records = _attach_media(_df_records(starting), teams_code)
    bench_records = _attach_media(_df_records(bench), teams_code)

    drop_keys = []
    for gw in gws:
        drop_keys.extend([f"xpts_gw{gw}", f"fixtures_gw{gw}", f"fixture_count_gw{gw}", f"diff_avg_gw{gw}"])
    for rec in starting_records + bench_records:
        fixtures_h = []
        for gw in gws:
            fixtures_h.append(
                {
                    "event_id": int(gw),
                    "fixtures": (rec.get(f"fixtures_gw{gw}") or ""),
                    "fixture_count": int(_safe_int(rec.get(f"fixture_count_gw{gw}")) or 0),
                    "diff_avg": float(_safe_float(rec.get(f"diff_avg_gw{gw}"), default=0.0) or 0.0),
                    "xpts": float(_safe_float(rec.get(f"xpts_gw{gw}"), default=0.0) or 0.0),
                }
            )
        rec["fixtures_horizon"] = fixtures_h
        rec["next_fixtures"] = fixtures_h[0]["fixtures"] if fixtures_h else ""
        for k in drop_keys:
            if k in rec:
                rec.pop(k, None)

    out = {
        "entry_id": int(entry_id),
        "squad_event_id": int(squad_event_id),
        "event_id": int(optimize_event_id),
        "horizon_gws": int(horizon_gws),
        "gws": gws,
        "notes": notes,
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


@app.get("/")
def root():
    return {"ok": True, "docs": "/docs", "health": "/health"}


@app.get("/health")
def health():
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z"}


@app.get("/squad")
def squad_get(
    entry_id=None,
    event_id=None,
    api_key=None,
    x_api_key=Header(None),
    authorization=Header(None),
):
    err = _check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key)
    if err:
        return err
    out = build_squad({"entry_id": entry_id, "event_id": event_id})
    return JSONResponse(content=jsonable_encoder(out))


@app.post("/squad")
def squad_post(
    payload=Body(None),
    api_key=None,
    x_api_key=Header(None),
    authorization=Header(None),
):
    payload = payload or {}
    err = _check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key or payload.get("api_key"))
    if err:
        return err
    out = build_squad(payload)
    return JSONResponse(content=jsonable_encoder(out))


@app.get("/recommendations")
def recommendations_get(
    entry_id=None,
    event_id=None,
    squad_event_id=None,
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
        "squad_event_id": squad_event_id,
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
    payload = payload or {}
    err = _check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key or payload.get("api_key"))
    if err:
        return err
    out = build_recommendations(payload)
    return JSONResponse(content=jsonable_encoder(out))
