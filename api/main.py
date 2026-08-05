import os
import time
import logging
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import pandas as pd
from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src import config, explainer, fixture_difficulty, fpl_client, fpl_refresh_next_gw, league as league_mod, league_strategy, manual_squad, optimizer, projections, recommender, transfer_planner, transforms
from src.auth import check_api_key, check_admin_key
from src.insights import (
    build_chip_profile,
    build_scoring_guide,
    build_squad_insights,
    build_strategy_recommendation,
    chip_objective_components,
)
from src.lineup_builder import build_position_panels, pack_lineup_records
from src.media import attach_media
from src.squad_builder import apply_transfer_moves_to_squad, build_transfer_step, estimate_squad_budget_m
from src.utils import (
    df_records,
    elapsed_ms,
    normalize_chip_strategy,
    parse_bool,
    round_float,
    safe_float,
    safe_int,
    safe_player_id,
    to_iso_utc,
    hours_until_utc,
)


app = FastAPI(title="FPL Assistant API", version="0.3.0")
logger = logging.getLogger(__name__)

# --- personal GW replay (local-only; never enabled in production) ---
if os.environ.get("REPLAY_MODE") == "1":
    from api.replay_router import router as replay_router
    app.include_router(replay_router)

# --- dev-only squad picker (never enabled in production) ---
if os.environ.get("SQUAD_PICKER_MODE") == "1":
    from api.squad_router import router as squad_picker_router
    app.include_router(squad_picker_router)

# Mount /chat endpoint (orchestrator agent over HTTP)
try:
    from api.chat import router as chat_router
    app.include_router(chat_router)
except Exception as e:
    logger.warning(f"Chat router not loaded: {e}")


def _csv_env(name):
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


cors_origins = _csv_env("FPL_API_CORS_ORIGINS")
if not cors_origins:
    cors_origins = [
        # Vite dev server hops 8080 -> 8081 -> 8082 -> 8083 as ports get taken,
        # so allow the whole range for both hosts.
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:8081",
        "http://127.0.0.1:8081",
        "http://localhost:8082",
        "http://127.0.0.1:8082",
        "http://localhost:8083",
        "http://127.0.0.1:8083",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
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


_team_ratings_cache = {"ts": 0.0, "data": None}


def get_team_ratings_cached(teams_short_map):
    """
    xG team ratings: current-season xG blended with the prior-season carryover
    seed, plus the manual knowledge discount. Cached on the fixtures TTL.
    """
    ttl = int(getattr(config, "FIXTURES_TTL", 300) or 300)
    hit = _cache_get(_team_ratings_cache, ttl)
    if hit is not None:
        return hit
    match_df = fixture_difficulty.load_match_history()
    team_match_xg = fixture_difficulty.build_team_match_xg(match_df)
    ratings = fixture_difficulty.resolve_team_ratings(team_match_xg, teams_short_map=teams_short_map)
    ratings = fixture_difficulty.apply_knowledge_discount(ratings, teams_short_map=teams_short_map)
    return _cache_set(_team_ratings_cache, ratings)


def build_fixture_difficulty_payload(gw_start=None, horizon_gws=6):
    """Shared builder for /fixtures/difficulty and the league-strategy injection."""
    bootstrap = get_bootstrap_cached()
    fixtures = get_fixtures_cached()
    _, teams_df, _ = transforms.tables_from_bootstrap(bootstrap)
    teams_short = teams_df.set_index("id")["short_name"].to_dict()

    gw_start = safe_int(gw_start) or _default_optimize_event_id(bootstrap)
    horizon_gws = max(1, min(38, safe_int(horizon_gws) or 6))

    ratings = get_team_ratings_cached(teams_short)
    ticker = fixture_difficulty.build_fixture_ticker(
        ratings, fixtures, teams_short, gw_start, horizon_gws=horizon_gws
    )

    sources = {}
    for team_id, r in ratings.items():
        if team_id == "_league" or not isinstance(r, dict):
            continue
        src = r.get("source", "live")
        sources[src] = sources.get(src, 0) + 1

    knowledge = fixture_difficulty.load_knowledge_discount()
    ticker["meta"] = {
        "model": "xg_carryover_v1",
        "rating_sources": sources,
        "league_avg_xg": round_float(ratings.get("_league"), 3),
        "knowledge_as_of": (knowledge or {}).get("as_of"),
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
    }
    ticker["team_ratings"] = df_records(fixture_difficulty.team_ratings_table(ratings))
    return ticker


def build_next_event_summary(bootstrap=None, fixtures=None):
    bootstrap = bootstrap or get_bootstrap_cached()
    fixtures = fixtures if fixtures is not None else get_fixtures_cached()

    events = pd.DataFrame(bootstrap.get("events", []))
    if events.empty or "id" not in events.columns:
        return {
            "event_id": None,
            "deadline_time_utc": None,
            "first_fixture_time_utc": None,
            "hours_to_deadline": None,
            "hours_to_first_fixture": None,
            "fixture_count": 0,
        }

    if "deadline_time" in events.columns:
        events["deadline_time"] = pd.to_datetime(events["deadline_time"], errors="coerce", utc=True)

    event_id = _event_id(bootstrap, "is_next")
    if not event_id:
        now = datetime.now(timezone.utc)
        unfinished = events[events.get("finished") != True].copy()
        if "deadline_time" in unfinished.columns:
            future = unfinished[unfinished["deadline_time"] >= now].sort_values("deadline_time")
            if not future.empty:
                event_id = safe_int(future.iloc[0]["id"])
        if not event_id and not unfinished.empty:
            event_id = safe_int(unfinished["id"].min())
        if not event_id:
            event_id = safe_int(events["id"].max()) or 1

    deadline_value = None
    ev_row = events[events["id"] == int(event_id)]
    if not ev_row.empty and "deadline_time" in ev_row.columns:
        deadline_value = ev_row.iloc[0]["deadline_time"]

    first_fixture = None
    fixture_count = 0
    if fixtures is not None and not fixtures.empty and "event" in fixtures.columns:
        fx = fixtures[fixtures["event"] == int(event_id)].copy()
        fixture_count = int(len(fx))
        if not fx.empty and "kickoff_time" in fx.columns:
            first_fixture = pd.to_datetime(fx["kickoff_time"], errors="coerce", utc=True).min()

    return {
        "event_id": int(event_id),
        "deadline_time_utc": to_iso_utc(deadline_value),
        "first_fixture_time_utc": to_iso_utc(first_fixture),
        "hours_to_deadline": hours_until_utc(deadline_value),
        "hours_to_first_fixture": hours_until_utc(first_fixture),
        "fixture_count": fixture_count,
    }


def _event_id(bootstrap, flag):
    for ev in bootstrap.get("events", []):
        if ev.get(flag):
            try:
                return int(ev.get("id"))
            except Exception:
                return None
    return None


def _default_picks_event_id(bootstrap):
    return _event_id(bootstrap, "is_current") or _event_id(bootstrap, "is_next") or 1


def _default_optimize_event_id(bootstrap):
    return _event_id(bootstrap, "is_next") or _event_id(bootstrap, "is_current") or 1


def _max_event_id(bootstrap):
    try:
        ev_ids = [int(ev.get("id")) for ev in bootstrap.get("events", []) if ev.get("id") is not None]
        return max(ev_ids) if ev_ids else 38
    except Exception:
        return 38


def load_fpl_context(entry_id, squad_event_id, with_fixtures=True):
    notes = []

    entry_id = safe_int(entry_id or os.environ.get("FPL_ENTRY_ID"))
    if not entry_id:
        raise HTTPException(status_code=400, detail="Missing/invalid entry_id.")

    bootstrap = get_bootstrap_cached()
    max_event_id = _max_event_id(bootstrap)

    explicit_squad_event = squad_event_id is not None and str(squad_event_id).strip() != ""
    requested_squad_event_id = safe_int(squad_event_id) if explicit_squad_event else None
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
        cand = safe_int(cand)
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
    my_team_ft = None
    for cand in candidates:
        try:
            myteam = fpl_client.get_entry_picks(entry_id, int(cand))
            used_event_id = int(cand)
            break
        except Exception as e:
            last_err = e
            continue

    # Fallback for pre-first-deadline / pre-season: the public /event/{gw}/picks/
    # endpoint 404s for every GW until picks lock, but the squad is readable via the
    # authenticated /api/my-team/{entry}/ endpoint. If the manager configured browser
    # auth (FPL_COOKIE, optionally FPL_BEARER), fetch the live squad directly.
    if not myteam or not used_event_id:
        cookie = os.environ.get("FPL_COOKIE")
        bearer = os.environ.get("FPL_BEARER")
        if cookie or bearer:
            try:
                raw_my_team = fpl_client.get_entry_my_team(
                    entry_id, cookie_header=cookie, bearer=bearer
                )
                planning_ev = next_event_id or current_event_id or 1
                myteam = fpl_client.normalize_my_team(raw_my_team, int(planning_ev))
                used_event_id = int(planning_ev)
                my_team_ft = myteam.get("_free_transfers")
                notes.append(
                    "Squad loaded from your authenticated FPL account "
                    "(live pre-deadline team)."
                )
            except Exception as e:
                last_err = e

    # Final fallback: a manually-imported squad (no auth). Lets a manager see and
    # work their pre-season XV before any GW locks, without cookies.
    if not myteam or not used_event_id:
        manual = manual_squad.load_manual_squad(entry_id)
        if manual:
            try:
                planning_ev = next_event_id or current_event_id or 1
                myteam = manual_squad.build_manual_myteam(
                    elements,
                    manual.get("player_ids") or [],
                    captain_id=manual.get("captain_id"),
                    vice_id=manual.get("vice_id"),
                    planning_event_id=int(planning_ev),
                )
                used_event_id = int(planning_ev)
                notes.append("Squad loaded from your manual pre-season import.")
            except Exception as e:
                last_err = e

    if not myteam or not used_event_id:
        # Pre-season / pre-first-deadline: FPL publishes no public entry picks until
        # a gameweek locks, so /event/{gw}/picks/ 404s for every GW (and prior-season
        # history is wiped at rollover). Surface a clear message instead of a raw
        # upstream 404 wrapped in a 502.
        current_ev = _event_id(bootstrap, "is_current")
        next_ev = next((e for e in bootstrap.get("events", []) if e.get("is_next")), None)
        if not current_ev and next_ev is not None:
            gw = safe_int(next_ev.get("id")) or 1
            deadline = str(next_ev.get("deadline_time") or "")[:10]
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Your team isn't available yet — FPL publishes squads only after a "
                    f"gameweek locks. It loads automatically after the GW{gw} deadline"
                    f"{f' ({deadline})' if deadline else ''}. Until then, use ZN Pick to predict."
                ),
            )
        raise HTTPException(status_code=502, detail=f"Failed to fetch entry picks. Last error: {last_err}")

    # Free hit picks are temporary — the real permanent squad is from the GW before.
    # If no explicit event was requested and the fetched GW used free hit, step back one GW.
    if not explicit_squad_event and myteam.get("active_chip") == "freehit" and used_event_id > 1:
        try:
            prev_team = fpl_client.get_entry_picks(entry_id, used_event_id - 1)
            notes.append(f"Free hit active in GW{used_event_id}; using permanent squad from GW{used_event_id - 1}.")
            myteam = prev_team
            used_event_id = used_event_id - 1
        except Exception:
            notes.append(f"Free hit active in GW{used_event_id}; could not fetch GW{used_event_id - 1}, using free hit squad.")

    if explicit_squad_event and requested_squad_event_id and int(used_event_id) != int(requested_squad_event_id):
        notes.append(f"squad_event_id {int(requested_squad_event_id)} not available; used {int(used_event_id)}.")

    # Derive ITB and free transfers from real FPL state.
    eh = myteam.get("entry_history") or {}
    bank_tenths = eh.get("bank")
    derived_itb_m = float(bank_tenths) / 10.0 if isinstance(bank_tenths, (int, float)) else None

    # Free transfers for the NEXT planning GW:
    # FPL carries over 1 unused FT (max 2 total). Check the current squad GW's own
    # event_transfers — if the manager used 0 transfers this GW, they banked one → 2 FT next GW.
    # Chip GWs (wildcard/freehit) reset the count to 1.
    derived_free_transfers = 1
    last_active_chip = (myteam.get("active_chip") or "").lower()
    if last_active_chip not in ("wildcard", "freehit"):
        try:
            # eh is already the entry_history for used_event_id (the current squad GW).
            cur_transfers = int(eh.get("event_transfers") or 0)
            if cur_transfers == 0:
                derived_free_transfers = 2
            else:
                derived_free_transfers = 1
        except Exception:
            pass  # keep default of 1

    # Authenticated my-team reports the real free-transfer count directly; it beats
    # the event_transfers heuristic (which wrongly infers a banked FT pre-season).
    if my_team_ft is not None:
        try:
            derived_free_transfers = int(my_team_ft)
        except (TypeError, ValueError):
            pass

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
        "derived_itb_m": derived_itb_m,
        "derived_free_transfers": derived_free_transfers,
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

    records = attach_media(df_records(picks), teams_code)

    starting = []
    bench = []
    for r in records:
        pos = safe_int(r.get("position"))
        if pos is not None and pos > 11:
            bench.append(r)
        else:
            starting.append(r)
    bench.sort(key=lambda r: safe_int(r.get("bench_order")) or 99)

    captain_id = None
    vice_id = None
    for r in records:
        if r.get("is_captain") is True:
            captain_id = safe_int(r.get("player_id"))
        if r.get("is_vice_captain") is True:
            vice_id = safe_int(r.get("player_id"))

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
    total_start = time.perf_counter()
    timings = {}

    entry_id = payload.get("entry_id") or os.environ.get("FPL_ENTRY_ID")
    optimize_event_id_raw = payload.get("event_id")
    squad_event_id_raw = payload.get("squad_event_id")
    horizon_gws_raw = payload.get("horizon_gws", 3)
    chip_horizon_gws_raw = payload.get("chip_horizon_gws")
    chip_play_event_id_raw = payload.get("chip_play_event_id")
    chip_strategy_raw = payload.get("chip_strategy")
    chip_strategy = normalize_chip_strategy(chip_strategy_raw)
    latest_n_matches_raw = payload.get("latest_n_matches", getattr(config, "PROJ_DEFAULT_LATEST_N_MATCHES", 3))
    apply_transfer_count_raw = payload.get("apply_transfer_count")

    include_transfers = parse_bool(payload.get("include_transfers"), default=False)
    itb_m_explicit = payload.get("itb_m") is not None
    free_transfers_explicit = payload.get("free_transfers") is not None
    itb_m = payload.get("itb_m") if itb_m_explicit else 0.5
    free_transfers = payload.get("free_transfers") if free_transfers_explicit else 1
    hit_cap = payload.get("hit_cap", 0)
    panel_limit = safe_int(payload.get("panel_limit"))
    if panel_limit is None:
        panel_limit = 5

    ts = time.perf_counter()
    ctx = load_fpl_context(entry_id, squad_event_id_raw, with_fixtures=True)
    timings["load_context_ms"] = elapsed_ms(ts)
    notes = list(ctx.get("notes") or [])
    if chip_strategy == "none" and chip_strategy_raw not in (None, "", "none", "None"):
        notes.append("Unknown chip_strategy; fallback to none.")

    entry_id = ctx["entry_id"]
    squad_event_id = ctx["squad_event_id"]
    max_event_id = ctx["max_event_id"]
    next_event_id = _event_id(ctx["bootstrap"], "is_next")

    # Use real FPL state if the user didn't override
    if not itb_m_explicit and ctx.get("derived_itb_m") is not None:
        itb_m = ctx["derived_itb_m"]
        notes.append(f"Using bank from FPL: £{itb_m:.1f}m.")
    if not free_transfers_explicit and ctx.get("derived_free_transfers") is not None:
        free_transfers = ctx["derived_free_transfers"]
        notes.append(f"Using free transfers from FPL: {free_transfers}.")

    explicit_optimize_event = optimize_event_id_raw is not None and str(optimize_event_id_raw).strip() != ""
    optimize_event_id = safe_int(optimize_event_id_raw)
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

    # Guard: if the deadline for the requested GW has passed, bump to next GW
    # so projections aren't computed on a partly-played gameweek.
    requested_event_row = next(
        (ev for ev in ctx["bootstrap"].get("events", []) if int(ev.get("id") or 0) == int(optimize_event_id)),
        None,
    )
    if requested_event_row is not None:
        deadline = pd.to_datetime(requested_event_row.get("deadline_time"), errors="coerce", utc=True)
        if pd.notna(deadline) and deadline < datetime.now(timezone.utc):
            new_event_id = int(optimize_event_id) + 1
            if new_event_id <= int(max_event_id):
                notes.append(
                    f"Deadline for GW{int(optimize_event_id)} has passed; "
                    f"recommending for GW{new_event_id} instead."
                )
                optimize_event_id = new_event_id

    display_horizon_gws = safe_int(horizon_gws_raw)
    if display_horizon_gws is None:
        notes.append("Invalid horizon_gws; using 3.")
        display_horizon_gws = 3
    display_horizon_gws = max(1, min(8, int(display_horizon_gws)))
    display_remaining = max(1, int(max_event_id) - int(optimize_event_id) + 1)
    if int(display_horizon_gws) > int(display_remaining):
        notes.append(f"horizon_gws trimmed to {int(display_remaining)} (season end).")
        display_horizon_gws = int(display_remaining)

    wildcard_play_event_id = None
    if chip_strategy == "wildcard":
        wildcard_play_event_id = safe_int(chip_play_event_id_raw)
        if chip_play_event_id_raw is not None and str(chip_play_event_id_raw).strip() != "" and wildcard_play_event_id is None:
            notes.append("Invalid chip_play_event_id; using next playable GW.")
        if wildcard_play_event_id is None:
            wildcard_play_event_id = int(next_event_id or optimize_event_id)
        wildcard_play_event_id = max(1, min(int(max_event_id), int(wildcard_play_event_id)))
        if next_event_id:
            wildcard_play_event_id = max(int(next_event_id), int(wildcard_play_event_id))
        if int(optimize_event_id) > int(wildcard_play_event_id):
            notes.append(
                f"Wildcard squad is anchored at GW{int(wildcard_play_event_id)} and propagated forward to GW{int(optimize_event_id)}."
            )

    if chip_strategy == "wildcard":
        chip_build_horizon_gws = safe_int(chip_horizon_gws_raw)
        if chip_build_horizon_gws is None:
            chip_build_horizon_gws = int(getattr(config, "CHIP_WILDCARD_DEFAULT_HORIZON_GWS", 5) or 5)
            if chip_horizon_gws_raw is None or str(chip_horizon_gws_raw).strip() == "":
                notes.append(f"wildcard build horizon defaulted to {int(chip_build_horizon_gws)} GWs.")
            else:
                notes.append(f"Invalid chip_horizon_gws; using {int(chip_build_horizon_gws)}.")
    elif chip_strategy == "free_hit":
        chip_build_horizon_gws = 1
    else:
        chip_build_horizon_gws = int(display_horizon_gws)

    chip_build_horizon_gws = max(1, min(8, int(chip_build_horizon_gws)))
    chip_build_start_event_id = int(wildcard_play_event_id or optimize_event_id)
    chip_build_remaining = max(1, int(max_event_id) - int(chip_build_start_event_id) + 1)
    if int(chip_build_horizon_gws) > int(chip_build_remaining):
        notes.append(f"chip_horizon_gws trimmed to {int(chip_build_remaining)} (season end).")
        chip_build_horizon_gws = int(chip_build_remaining)

    wildcard_is_active = chip_strategy == "wildcard" and int(optimize_event_id) >= int(wildcard_play_event_id or optimize_event_id)
    chip_is_active = chip_strategy == "free_hit" or wildcard_is_active

    latest_n_matches = safe_int(latest_n_matches_raw)
    if latest_n_matches is None:
        notes.append(f"Invalid latest_n_matches; using {int(getattr(config, 'PROJ_DEFAULT_LATEST_N_MATCHES', 3))}.")
        latest_n_matches = int(getattr(config, "PROJ_DEFAULT_LATEST_N_MATCHES", 3))
    latest_n_matches = max(
        int(getattr(config, "PROJ_LATEST_N_MIN", 1)),
        min(int(getattr(config, "PROJ_LATEST_N_MAX", 8)), int(latest_n_matches)),
    )

    fixtures = ctx["fixtures"]
    elements = ctx["elements"]
    teams_short = ctx["teams_short"]
    teams_code = ctx["teams_code"]
    squad_df = ctx["squad_df"]
    history_context = projections.latest_player_gw_history_info()
    if history_context.get("source") == "csv" and history_context.get("max_gw") is not None:
        notes.append(
            f"Player history source: CSV ({history_context.get('season') or 'season'}), latest GW on file {int(history_context.get('max_gw'))}."
        )
    else:
        notes.append("Player history source: fallback live FPL fields (no player_gw_history CSV available).")

    projection_start_event_id = int(optimize_event_id)
    if wildcard_is_active:
        projection_start_event_id = min(int(optimize_event_id), int(wildcard_play_event_id))
    projection_end_event_id = int(optimize_event_id) + int(display_horizon_gws) - 1
    if wildcard_is_active:
        projection_end_event_id = max(
            int(projection_end_event_id),
            int(wildcard_play_event_id) + int(chip_build_horizon_gws) - 1,
        )
    projection_horizon_gws = max(1, int(projection_end_event_id) - int(projection_start_event_id) + 1)

    ts = time.perf_counter()
    try:
        proj_all = projections.project_elements_next_gws(
            elements=elements,
            fixtures=fixtures,
            teams_short_map=teams_short,
            gw_start=projection_start_event_id,
            horizon_gws=projection_horizon_gws,
            latest_n_matches=latest_n_matches,
        )
        if wildcard_is_active:
            proj_all = projections.add_wildcard_scores(
                projections_df=proj_all,
                gw_start=wildcard_play_event_id,
                horizon_gws=chip_build_horizon_gws,
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Projection failed: {e}")
    timings["projections_ms"] = elapsed_ms(ts)

    recent_history_max_gw = None
    if proj_all is not None and not proj_all.empty and "recent_history_max_gw" in proj_all.columns:
        hist_vals = pd.to_numeric(proj_all["recent_history_max_gw"], errors="coerce").dropna()
        if not hist_vals.empty:
            recent_history_max_gw = int(hist_vals.max())
    if recent_history_max_gw is not None:
        recent_window = int(getattr(config, "PROJ_PLAYER_RECENT_GW_WINDOW", 5) or 5)
        notes.append(
            f"Player baseline blends the last {int(recent_window)} gameweeks on file (latest player-history GW available: {int(recent_history_max_gw)})."
        )

    score_col = f"xpts_gw{int(optimize_event_id)}"
    lineup_squad_df = squad_df
    chip_info = {
        "selected": chip_strategy,
        "is_active": chip_is_active,
        "objective_score_col": None,
        "objective_horizon_gws": int(chip_build_horizon_gws),
        "play_event_id": int(wildcard_play_event_id) if wildcard_play_event_id is not None else None,
        "propagates_to_future_gws": bool(chip_strategy == "wildcard"),
        "budget_m": None,
        "squad_cost_m": None,
        "remaining_budget_m": None,
        "objective_score_total": None,
        "objective_components": chip_objective_components(chip_strategy),
        "explanation": None,
        "profile": None,
        "reason": "No chip strategy applied.",
    }

    if chip_is_active:
        chip_objective_col = "wildcard_score" if chip_strategy == "wildcard" else score_col
        chip_objective_horizon = int(chip_build_horizon_gws) if chip_strategy == "wildcard" else 1
        ts = time.perf_counter()
        budget_m = estimate_squad_budget_m(
            squad_df=squad_df,
            elements=elements,
            itb_m=safe_float(itb_m, default=0.0) or 0.0,
        )
        premium_floor = float(
            getattr(config, "CHIP_WILDCARD_PREMIUM_CAPTAIN_PRICE_FLOOR",
                    getattr(config, "CHIP_WILDCARD_PREMIUM_ATTACKER_FLOOR", 9.0))
            or getattr(config, "CHIP_WILDCARD_PREMIUM_ATTACKER_FLOOR", 9.0)
        )
        premium_positions = list(
            getattr(config, "CHIP_WILDCARD_PREMIUM_CAPTAIN_POSITIONS", ["MID", "FWD"]) or ["MID", "FWD"]
        )
        min_premium_attackers = (
            int(getattr(config, "CHIP_WILDCARD_MIN_PREMIUM_CAPTAINS", 1) or 0)
            if chip_strategy == "wildcard"
            else 0
        )
        if chip_strategy == "free_hit":
            chip_build = optimizer.build_free_hit_squad(
                elements_all=proj_all,
                score_col=chip_objective_col,
                budget_m=budget_m,
                max_per_team=int(getattr(config, "CHIP_MAX_PER_TEAM", 3) or 3),
            )
        else:
            chip_build = optimizer.build_chip_squad(
                elements_all=proj_all,
                score_col=chip_objective_col,
                budget_m=budget_m,
                max_per_team=int(getattr(config, "CHIP_MAX_PER_TEAM", 3) or 3),
                min_premium_attackers=min_premium_attackers,
                premium_floor=premium_floor,
                premium_positions=premium_positions,
            )
        timings["chip_draft_ms"] = elapsed_ms(ts)

        if chip_build.get("ok"):
            lineup_squad_df = chip_build.get("squad_df")
            chip_info = {
                "selected": chip_strategy,
                "is_active": True,
                "objective_score_col": chip_objective_col,
                "objective_horizon_gws": int(chip_objective_horizon),
                "play_event_id": int(wildcard_play_event_id) if wildcard_play_event_id is not None else None,
                "propagates_to_future_gws": bool(chip_strategy == "wildcard"),
                "budget_m": chip_build.get("budget_m"),
                "squad_cost_m": chip_build.get("squad_cost_m"),
                "remaining_budget_m": chip_build.get("remaining_budget_m"),
                "objective_score_total": chip_build.get("objective_score_total"),
                "objective_components": chip_objective_components(chip_strategy),
                "explanation": None,
                "profile": None,
                "reason": chip_build.get("reason"),
            }
            notes.append(
                f"{chip_strategy} draft built on `{chip_objective_col}` "
                f"(budget {chip_build.get('budget_m')}m, left {chip_build.get('remaining_budget_m')}m)."
            )
        else:
            notes.append(f"{chip_strategy} draft fallback to current squad: {chip_build.get('reason')}")
            chip_info = {
                "selected": chip_strategy,
                "is_active": True,
                "objective_score_col": chip_objective_col,
                "objective_horizon_gws": int(chip_objective_horizon),
                "play_event_id": int(wildcard_play_event_id) if wildcard_play_event_id is not None else None,
                "propagates_to_future_gws": bool(chip_strategy == "wildcard"),
                "budget_m": budget_m,
                "squad_cost_m": None,
                "remaining_budget_m": None,
                "objective_score_total": None,
                "objective_components": chip_objective_components(chip_strategy),
                "explanation": None,
                "profile": None,
                "reason": chip_build.get("reason"),
            }
    elif chip_strategy == "wildcard" and wildcard_play_event_id is not None:
        chip_info["reason"] = f"Wildcard is planned from GW{int(wildcard_play_event_id)} and is not yet active for GW{int(optimize_event_id)}."

    ts = time.perf_counter()
    try:
        res = optimizer.optimize_lineup(lineup_squad_df, proj_all, score_col=score_col)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Optimize failed: {e}")
    if not res:
        raise HTTPException(status_code=500, detail="Could not optimize lineup for this squad.")
    timings["optimize_base_ms"] = elapsed_ms(ts)

    gws = [int(optimize_event_id) + i for i in range(int(display_horizon_gws))]
    chip_profile_gws = gws
    if wildcard_is_active:
        chip_profile_gws = [int(wildcard_play_event_id) + i for i in range(int(chip_build_horizon_gws))]

    ts = time.perf_counter()
    starting_records, bench_records = pack_lineup_records(
        starting_df=res["starting_xi"],
        bench_df=res["bench"],
        elements=elements,
        proj_all=proj_all,
        gws=gws,
        teams_code=teams_code,
        chip_strategy=chip_strategy if chip_info.get("is_active") else "none",
        objective_score_col=chip_info.get("objective_score_col"),
        optimize_event_id=optimize_event_id,
    )
    timings["pack_base_lineup_ms"] = elapsed_ms(ts)

    owned_ids = []
    if "player_id" in lineup_squad_df.columns:
        owned_ids = [int(x) for x in pd.to_numeric(lineup_squad_df["player_id"], errors="coerce").dropna().astype(int).tolist()]

    ts = time.perf_counter()
    position_panels = build_position_panels(
        proj_all=proj_all,
        gws=gws,
        teams_code=teams_code,
        owned_ids=owned_ids,
        limit_per_pos=panel_limit,
        ranking_col=chip_info.get("objective_score_col") if chip_info.get("is_active") else "xpts_horizon",
        chip_strategy=chip_strategy if chip_info.get("is_active") else "none",
        objective_score_col=chip_info.get("objective_score_col"),
        optimize_event_id=optimize_event_id,
    )
    timings["position_panels_ms"] = elapsed_ms(ts)

    if chip_info.get("is_active"):
        chip_profile = build_chip_profile(
            chip_strategy=chip_strategy,
            squad_df=lineup_squad_df,
            proj_all=proj_all,
            gws=chip_profile_gws,
        )
        chip_info["profile"] = chip_profile
        chip_info["explanation"] = chip_profile.get("summary") if isinstance(chip_profile, dict) else None

    out = {
        "entry_id": int(entry_id),
        "squad_event_id": int(squad_event_id),
        "event_id": int(optimize_event_id),
        "horizon_gws": int(display_horizon_gws),
        "gws": gws,
        "notes": notes,
        "formation": list(res["formation"]),
        "captain_player_id": int(res["captain_player_id"]),
        "vice_player_id": int(res["vice_player_id"]),
        "projected_points_with_captain": float(res["projected_points_with_captain"]),
        "starting_xi": starting_records,
        "bench": bench_records,
        "position_panels": position_panels,
        "active_chip": ctx.get("myteam", {}).get("active_chip"),
        "squad_source": "chip_draft" if chip_info.get("is_active") else "entry_picks",
        "chip_strategy": chip_info,
        "history_context": history_context,
        "scoring_guide": build_scoring_guide(
            optimize_event_id=optimize_event_id,
            chip_strategy=chip_strategy if chip_info.get("is_active") else "none",
            objective_score_col=chip_info.get("objective_score_col"),
        ),
    }

    free_transfers_value = safe_int(free_transfers)
    if free_transfers_value is None:
        free_transfers_value = 1

    ts = time.perf_counter()
    if chip_info.get("is_active"):
        transfer_preview = {
            "note": f"Transfers planner skipped when chip strategy `{chip_strategy}` is active.",
            "transfer_plan": {
                "free_transfers": int(free_transfers_value),
                "horizon_gws": int(display_horizon_gws),
                "hit_cap": int(safe_int(hit_cap) or 0),
                "transfer_count_target": 0,
                "transfer_count_built": 0,
            },
            "moves_by_position": {},
            "hot_by_position": {"GKP": [], "DEF": [], "MID": [], "FWD": []},
            "moves": [],
            "remaining_itb": chip_info.get("remaining_budget_m"),
        }
    else:
        transfer_preview = recommender.suggest_transfers(
            squad_df=squad_df,
            elements_all=proj_all,
            itb_m=safe_float(itb_m, default=0.0) or 0.0,
            free_transfers=free_transfers_value,
            hit_cap=safe_int(hit_cap) or 0,
            score_col="xpts_horizon",
            horizon_gws=int(display_horizon_gws),
        )
    timings["transfer_preview_ms"] = elapsed_ms(ts)
    if include_transfers:
        out["transfers"] = transfer_preview

    # Additive: a multi-GW roll/bank plan across the horizon (the single-GW
    # `transfers` above never sequences GWs or accounts for the -4 hit). Uses
    # the real squad, bank and free-transfer count. Never breaks the response.
    if include_transfers and not chip_info.get("is_active"):
        try:
            _squad_ids = [int(x) for x in squad_df["player_id"].tolist()]
            out["transfer_plan_horizon"] = transfer_planner.plan_transfers(
                proj_all, _squad_ids, gws,
                itb_m=safe_float(itb_m, default=0.0) or 0.0,
                start_ft=int(free_transfers_value), ft_cap=5, allow_hits=True)
        except Exception as e:  # noqa: BLE001 - planning must never fail the recommendation
            logger.warning("horizon transfer plan failed: %s", e)

    ts = time.perf_counter()
    moves = transfer_preview.get("moves") if isinstance(transfer_preview, dict) else []
    if not isinstance(moves, list):
        moves = []

    apply_transfer_count = safe_int(apply_transfer_count_raw)
    if apply_transfer_count is None:
        effective_apply_count = 0
    else:
        effective_apply_count = max(0, min(int(apply_transfer_count), len(moves)))

    transfer_steps = []
    step_kwargs = dict(
        moves=moves,
        squad_df=lineup_squad_df,
        elements=elements,
        proj_all=proj_all,
        score_col=score_col,
        gws=gws,
        teams_code=teams_code,
        base_res=res,
        base_points=float(res["projected_points_with_captain"]),
        base_starting_records=starting_records,
        base_bench_records=bench_records,
    )
    if moves:
        for idx in range(0, len(moves) + 1):
            transfer_steps.append(build_transfer_step(applied_count=idx, **step_kwargs))
    else:
        transfer_steps.append(build_transfer_step(applied_count=0, **step_kwargs))

    selected_step = transfer_steps[effective_apply_count] if effective_apply_count < len(transfer_steps) else transfer_steps[0]

    out["transfer_application"] = selected_step.get("transfer_application")
    out["squad_with_transfers"] = {
        "formation": selected_step.get("formation"),
        "captain_player_id": selected_step.get("captain_player_id"),
        "vice_player_id": selected_step.get("vice_player_id"),
        "projected_points_with_captain": selected_step.get("projected_points_with_captain"),
        "starting_xi": selected_step.get("starting_xi"),
        "bench": selected_step.get("bench"),
    }
    out["transfer_impact"] = selected_step.get("transfer_impact")
    out["squad_with_transfers_steps"] = transfer_steps
    timings["transfer_apply_and_reoptimize_ms"] = elapsed_ms(ts)

    out["strategy_recommendation"] = build_strategy_recommendation(
        squad_df=lineup_squad_df,
        starting_records=starting_records,
        bench_records=bench_records,
        captain_player_id=res.get("captain_player_id"),
        vice_player_id=res.get("vice_player_id"),
        horizon_gws=display_horizon_gws,
        free_transfers=free_transfers_value,
        transfer_preview=transfer_preview,
        active_chip=ctx.get("myteam", {}).get("active_chip"),
        selected_chip_strategy=chip_strategy if chip_info.get("is_active") else "none",
    )
    out["squad_insights"] = build_squad_insights(
        starting_records=starting_records,
        bench_records=bench_records,
        optimize_event_id=optimize_event_id,
        chip_strategy=chip_strategy if chip_info.get("is_active") else "none",
        chip_profile=chip_info.get("profile"),
    )

    timings["total_ms"] = elapsed_ms(total_start)
    out["timings_ms"] = timings
    logger.info(
        "recommendations entry_id=%s squad_event_id=%s event_id=%s horizon=%s chip=%s timings_ms=%s",
        int(entry_id), int(squad_event_id), int(optimize_event_id), int(display_horizon_gws), chip_strategy, timings,
    )

    return out


def build_xpts_evaluation(payload):
    payload = payload or {}
    history_csv_path = payload.get("history_csv_path")
    base_dir = payload.get("base_dir") or "data/processed/fpl"
    window = safe_int(payload.get("window", 3))
    min_gw = safe_int(payload.get("min_gw", 2))
    topk = safe_int(payload.get("topk", 25))

    if window is None:
        window = 3
    if min_gw is None:
        min_gw = 2
    if topk is None:
        topk = 25

    out = projections.evaluate_xpts_history_file(
        path=history_csv_path,
        base_dir=base_dir,
        window=max(1, int(window)),
        min_gw=max(1, int(min_gw)),
        topk=max(1, int(topk)),
    )
    if not out.get("ok"):
        message = out.get("error") or "xPts evaluation failed."
        status = 404 if "No player_gw_history CSV found" in str(message) else 400
        raise HTTPException(status_code=status, detail=message)
    return out


@app.get("/")
def root():
    return {"ok": True, "docs": "/docs", "health": "/health"}


@app.get("/health")
def health():
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z"}


@app.get("/events/next")
def next_event():
    bootstrap = get_bootstrap_cached()
    fixtures = get_fixtures_cached()
    summary = build_next_event_summary(bootstrap=bootstrap, fixtures=fixtures)
    return JSONResponse(content=jsonable_encoder(summary))


@app.get("/fixtures/difficulty")
def fixtures_difficulty_get(
    gw_start=None, horizon_gws=6,
    api_key=None, x_api_key=Header(None), authorization=Header(None),
):
    err = check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key)
    if err:
        return err
    out = build_fixture_difficulty_payload(gw_start=gw_start, horizon_gws=horizon_gws)
    return JSONResponse(content=jsonable_encoder(out))


@app.post("/admin/refresh")
def admin_refresh(
    payload=Body(None),
    api_key=None,
    x_api_key=Header(None),
    authorization=Header(None),
):
    payload = payload or {}
    err = check_admin_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key or payload.get("api_key"))
    if err:
        return err

    run_snapshot = parse_bool(payload.get("run_snapshot"), default=True)
    out_base = payload.get("out_base") or os.environ.get("FPL_SNAPSHOT_OUT_BASE") or "data/processed"

    _bootstrap_cache["ts"] = 0.0
    _bootstrap_cache["data"] = None
    _fixtures_cache["ts"] = 0.0
    _fixtures_cache["data"] = None
    _team_ratings_cache["ts"] = 0.0
    _team_ratings_cache["data"] = None

    bootstrap = get_bootstrap_cached()
    fixtures = get_fixtures_cached()
    next_ev = build_next_event_summary(bootstrap=bootstrap, fixtures=fixtures)

    snapshot_info = None
    snapshot_error = None
    if run_snapshot:
        try:
            snapshot_info = fpl_refresh_next_gw.refresh_next_gw_snapshot(out_base=out_base)
        except Exception as exc:
            snapshot_error = str(exc)

    return JSONResponse(content=jsonable_encoder({
        "ok": True,
        "next_event": next_ev,
        "cache_refreshed_at_utc": datetime.utcnow().isoformat() + "Z",
        "snapshot_info": snapshot_info,
        "snapshot_error": snapshot_error,
    }))


@app.get("/squad")
def squad_get(
    entry_id=None, event_id=None,
    api_key=None, x_api_key=Header(None), authorization=Header(None),
):
    err = check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key)
    if err:
        return err
    out = build_squad({"entry_id": entry_id, "event_id": event_id})
    return JSONResponse(content=jsonable_encoder(out))


@app.post("/squad")
def squad_post(
    payload=Body(None),
    api_key=None, x_api_key=Header(None), authorization=Header(None),
):
    payload = payload or {}
    err = check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key or payload.get("api_key"))
    if err:
        return err
    out = build_squad(payload)
    return JSONResponse(content=jsonable_encoder(out))


@app.post("/squad/manual")
def squad_manual_post(
    payload=Body(None),
    api_key=None, x_api_key=Header(None), authorization=Header(None),
):
    """
    Import a squad manually (no FPL login) for the pre-first-deadline window.
    Body: {entry_id, player_ids: [15 element ids], captain_id?, vice_id?}.
    Validates composition/budget, persists it, and returns the rendered squad.
    """
    payload = payload or {}
    err = check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key or payload.get("api_key"))
    if err:
        return err

    entry_id = safe_int(payload.get("entry_id") or os.environ.get("FPL_ENTRY_ID"))
    if not entry_id:
        raise HTTPException(status_code=400, detail="Missing/invalid entry_id.")
    player_ids = payload.get("player_ids") or []
    captain_id = payload.get("captain_id")
    vice_id = payload.get("vice_id")

    bootstrap = get_bootstrap_cached()
    elements, _teams, _ = transforms.tables_from_bootstrap(bootstrap)
    planning_ev = _event_id(bootstrap, "is_next") or _event_id(bootstrap, "is_current") or 1

    # Validate by attempting the build; surface a clean 400 on illegal selections.
    try:
        manual_squad.build_manual_myteam(
            elements, player_ids, captain_id=captain_id,
            vice_id=vice_id, planning_event_id=int(planning_ev),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    manual_squad.save_manual_squad(entry_id, player_ids, captain_id=captain_id, vice_id=vice_id)
    out = build_squad({"entry_id": entry_id})
    return JSONResponse(content=jsonable_encoder(out))


@app.delete("/squad/manual")
def squad_manual_delete(
    entry_id=None,
    api_key=None, x_api_key=Header(None), authorization=Header(None),
):
    """Remove a saved manual squad (e.g. once the real public fetch takes over)."""
    err = check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key)
    if err:
        return err
    entry_id = safe_int(entry_id or os.environ.get("FPL_ENTRY_ID"))
    if not entry_id:
        raise HTTPException(status_code=400, detail="Missing/invalid entry_id.")
    removed = manual_squad.clear_manual_squad(entry_id)
    return JSONResponse(content={"entry_id": int(entry_id), "removed": bool(removed)})


@app.get("/recommendations")
def recommendations_get(
    entry_id=None, event_id=None, squad_event_id=None,
    horizon_gws=3, chip_horizon_gws=None, chip_play_event_id=None,
    chip_strategy="none", latest_n_matches=3, include_transfers=False,
    apply_transfer_count=None, itb_m=None, free_transfers=None, hit_cap=0, panel_limit=5,
    api_key=None, x_api_key=Header(None), authorization=Header(None),
):
    err = check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key)
    if err:
        return err
    payload = {
        "entry_id": entry_id, "event_id": event_id, "squad_event_id": squad_event_id,
        "horizon_gws": horizon_gws, "chip_horizon_gws": chip_horizon_gws,
        "chip_play_event_id": chip_play_event_id, "chip_strategy": chip_strategy,
        "latest_n_matches": latest_n_matches, "include_transfers": include_transfers,
        "apply_transfer_count": apply_transfer_count, "itb_m": itb_m,
        "free_transfers": free_transfers, "hit_cap": hit_cap, "panel_limit": panel_limit,
    }
    out = build_recommendations(payload)
    return JSONResponse(content=jsonable_encoder(out))


@app.post("/recommendations")
def recommendations_post(
    payload=Body(None),
    api_key=None, x_api_key=Header(None), authorization=Header(None),
):
    payload = payload or {}
    err = check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key or payload.get("api_key"))
    if err:
        return err
    out = build_recommendations(payload)
    return JSONResponse(content=jsonable_encoder(out))


@app.get("/league/list")
def league_list(
    entry_id=None,
    api_key=None, x_api_key=Header(None), authorization=Header(None),
):
    err = check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key)
    if err:
        return err
    if entry_id is None:
        raise HTTPException(status_code=400, detail="entry_id required")
    leagues = league_mod.list_user_leagues(int(entry_id))
    return JSONResponse(content=jsonable_encoder({"entry_id": int(entry_id), "leagues": leagues}))


@app.post("/league/strategy")
def league_strategy_post(
    payload=Body(None),
    api_key=None, x_api_key=Header(None), authorization=Header(None),
):
    payload = payload or {}
    err = check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key or payload.get("api_key"))
    if err:
        return err

    entry_id = payload.get("entry_id")
    league_id = payload.get("league_id")
    mode = payload.get("mode") or "chase"
    if entry_id is None or league_id is None:
        raise HTTPException(status_code=400, detail="entry_id and league_id required")

    bootstrap = get_bootstrap_cached()
    fixtures = get_fixtures_cached()
    event_id = payload.get("event_id") or _default_picks_event_id(bootstrap)
    horizon_gws = int(payload.get("horizon_gws") or 3)
    latest_n_matches = int(payload.get("latest_n_matches") or 3)

    elements_df, teams_df, _ = transforms.tables_from_bootstrap(bootstrap)
    teams_short = teams_df.set_index("id")["short_name"].to_dict()
    proj_df = None
    proj_error = None
    try:
        proj_df = projections.project_elements_next_gws(
            elements=elements_df,
            fixtures=fixtures,
            teams_short_map=teams_short,
            gw_start=int(event_id),
            horizon_gws=horizon_gws,
            latest_n_matches=latest_n_matches,
        )
    except Exception as e:
        proj_error = str(e)

    fixture_ticker = None
    try:
        fixture_ticker = build_fixture_difficulty_payload(gw_start=event_id, horizon_gws=max(horizon_gws, 6))
    except Exception as e:
        logger.warning(f"fixture ticker unavailable for league strategy: {e}")

    out = league_strategy.build_strategy(
        entry_id=int(entry_id),
        league_id=int(league_id),
        event_id=int(event_id),
        mode=mode,
        bootstrap=bootstrap,
        projections_df=proj_df,
        model=payload.get("model"),
        fixture_ticker=fixture_ticker,
    )
    if proj_error:
        out["projection_error"] = proj_error
    out["projection_horizon_gws"] = horizon_gws
    return JSONResponse(content=jsonable_encoder(out))


@app.post("/explain")
def explain_post(
    payload=Body(None),
    api_key=None, x_api_key=Header(None), authorization=Header(None),
):
    payload = payload or {}
    err = check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key or payload.get("api_key"))
    if err:
        return err

    recs = payload.get("recommendations")
    if not recs:
        entry_id = payload.get("entry_id")
        if entry_id is None:
            raise HTTPException(status_code=400, detail="provide 'recommendations' or 'entry_id'")
        rec_payload = {k: v for k, v in payload.items() if k != "recommendations"}
        recs = build_recommendations(rec_payload)

    out = explainer.explain(recs, model=payload.get("model"))
    return JSONResponse(content=jsonable_encoder(out))


@app.get("/evaluation/xpts")
def evaluation_xpts_get(
    history_csv_path=None, base_dir="data/processed/fpl", window=3, min_gw=2, topk=25,
    api_key=None, x_api_key=Header(None), authorization=Header(None),
):
    err = check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key)
    if err:
        return err
    out = build_xpts_evaluation({"history_csv_path": history_csv_path, "base_dir": base_dir, "window": window, "min_gw": min_gw, "topk": topk})
    return JSONResponse(content=jsonable_encoder(out))


@app.post("/evaluation/xpts")
def evaluation_xpts_post(
    payload=Body(None),
    api_key=None, x_api_key=Header(None), authorization=Header(None),
):
    payload = payload or {}
    err = check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key or payload.get("api_key"))
    if err:
        return err
    out = build_xpts_evaluation(payload)
    return JSONResponse(content=jsonable_encoder(out))
