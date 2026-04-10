import os
import time
import logging
from datetime import datetime, timezone
#need to refactor
import pandas as pd
from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src import config, fpl_client, fpl_refresh_next_gw, optimizer, projections, recommender, transforms


app = FastAPI(title="FPL Assistant API", version="0.3.0")
logger = logging.getLogger(__name__)


def _csv_env(name):
    """Read a comma-separated env var into a trimmed list."""
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
    """Return cached payload when entry is still within TTL seconds."""
    now = time.time()
    if cache.get("data") is not None and (now - float(cache.get("ts") or 0.0)) < float(ttl_s):
        return cache["data"]
    return None


def _cache_set(cache, data):
    """Store payload in cache dict with current timestamp."""
    cache["data"] = data
    cache["ts"] = time.time()
    return data


def get_bootstrap_cached():
    """Fetch bootstrap data with in-memory TTL caching."""
    ttl = int(getattr(config, "BOOTSTRAP_TTL", 300) or 300)
    hit = _cache_get(_bootstrap_cache, ttl)
    if hit is not None:
        return hit
    return _cache_set(_bootstrap_cache, fpl_client.get_bootstrap())


def get_fixtures_cached():
    """Fetch and normalize fixtures with in-memory TTL caching."""
    ttl = int(getattr(config, "FIXTURES_TTL", 300) or 300)
    hit = _cache_get(_fixtures_cache, ttl)
    if hit is not None:
        return hit
    fx = transforms.fixtures_df(fpl_client.get_fixtures())
    return _cache_set(_fixtures_cache, fx)


def build_next_event_summary(bootstrap=None, fixtures=None):
    """Build deadline/first-fixture metadata for the next active event."""
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
                event_id = _safe_int(future.iloc[0]["id"])
        if not event_id and not unfinished.empty:
            event_id = _safe_int(unfinished["id"].min())
        if not event_id:
            event_id = _safe_int(events["id"].max()) or 1

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
        "deadline_time_utc": _to_iso_utc(deadline_value),
        "first_fixture_time_utc": _to_iso_utc(first_fixture),
        "hours_to_deadline": _hours_until_utc(deadline_value),
        "hours_to_first_fixture": _hours_until_utc(first_fixture),
        "fixture_count": fixture_count,
    }


def _event_id(bootstrap, flag):
    """Return event id where a boolean event flag is true."""
    for ev in bootstrap.get("events", []):
        if ev.get(flag):
            try:
                return int(ev.get("id"))
            except Exception:
                return None
    return None


def _default_picks_event_id(bootstrap):
    """Pick default event id for squad retrieval."""
    # "Squad GW": use the currently active GW first (more likely to have picks),
    # then fallback to next.
    return _event_id(bootstrap, "is_current") or _event_id(bootstrap, "is_next") or 1


def _default_optimize_event_id(bootstrap):
    """Pick default event id for optimization."""
    # "Optimize GW": usually the next GW you want to plan for.
    return _event_id(bootstrap, "is_next") or _event_id(bootstrap, "is_current") or 1


def _max_event_id(bootstrap):
    """Return maximum available event id from bootstrap, fallback 38."""
    try:
        ev_ids = [int(ev.get("id")) for ev in bootstrap.get("events", []) if ev.get("id") is not None]
        return max(ev_ids) if ev_ids else 38
    except Exception:
        return 38


def _safe_int(x):
    """Safely parse integer, returning None on failure."""
    try:
        return int(x)
    except Exception:
        return None


def _safe_float(x, default=None):
    """Safely parse float, returning default on failure."""
    try:
        return float(x)
    except Exception:
        return default


def _to_iso_utc(value):
    """Convert datetime-like input to ISO UTC string."""
    if value is None:
        return None
    try:
        dt = pd.to_datetime(value, errors="coerce", utc=True)
        if pd.isna(dt):
            return None
        return dt.to_pydatetime().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _hours_until_utc(value):
    """Return remaining hours from now until datetime-like input."""
    iso = _to_iso_utc(value)
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        delta_h = (dt - datetime.now(timezone.utc)).total_seconds() / 3600.0
        return float(round(delta_h, 2))
    except Exception:
        return None


def _parse_bool(x, default=False):
    """Parse common truthy/falsy string values into bool."""
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


def _normalize_chip_strategy(value):
    """Normalize chip strategy to one of: none, wildcard, free_hit."""
    s = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if s in ("", "none", "off", "no_chip"):
        return "none"
    if s in ("wildcard", "wc"):
        return "wildcard"
    if s in ("free_hit", "freehit", "fh"):
        return "free_hit"
    return "none"


def _extract_api_key(x_api_key, authorization, api_key):
    """Extract API key from query param, header, or Bearer token."""
    if api_key is not None and str(api_key).strip() != "":
        return str(api_key).strip()
    if x_api_key is not None and str(x_api_key).strip() != "":
        return str(x_api_key).strip()
    auth = (authorization or "").strip()
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def _check_api_key(x_api_key=None, authorization=None, api_key=None):
    """Validate request API key against `FPL_API_KEY`."""
    required = (os.environ.get("FPL_API_KEY") or "").strip()
    if not required:
        return None

    got = _extract_api_key(x_api_key, authorization, api_key)
    if got == required:
        return None

    return JSONResponse(status_code=401, content={"error": "Unauthorized"})


def _check_admin_key(x_api_key=None, authorization=None, api_key=None):
    """Validate admin key against `FPL_ADMIN_KEY` (or `FPL_API_KEY`)."""
    required = (os.environ.get("FPL_ADMIN_KEY") or os.environ.get("FPL_API_KEY") or "").strip()
    if not required:
        return None

    got = _extract_api_key(x_api_key, authorization, api_key)
    if got == required:
        return None

    return JSONResponse(status_code=401, content={"error": "Unauthorized (admin key required)"})


def team_badge_url(team_code, size=50):
    """Build Premier League team badge URL from team code."""
    team_code = _safe_int(team_code)
    if not team_code:
        return None
    return f"https://resources.premierleague.com/premierleague/badges/{int(size)}/t{team_code}.png"


def player_photo_url(player_code=None, photo=None, size="110x140"):
    """Build Premier League player photo URL from code or photo string."""
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
    """Normalize DataFrame/scalar values so they are JSON serializable."""
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
    """Convert a DataFrame to list of cleaned dict records."""
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
    """Append badge/photo URLs to player records."""
    for d in records:
        team_id = _safe_int(d.get("team"))
        team_code = teams_code_map.get(team_id) if team_id is not None else None
        d["badge_url"] = team_badge_url(team_code, size=50)
        d["photo_url"] = player_photo_url(d.get("code"), d.get("photo"), size="110x140")
    return records


def _estimate_squad_budget_m(squad_df, elements, itb_m=0.0):
    """Estimate total available squad budget from current squad value + ITB."""
    if squad_df is None or squad_df.empty:
        return float(max(0.0, _safe_float(itb_m, default=0.0) or 0.0))
    if elements is None or elements.empty or "id" not in elements.columns:
        return float(max(0.0, _safe_float(itb_m, default=0.0) or 0.0))

    prices = elements.copy()
    prices["id"] = pd.to_numeric(prices["id"], errors="coerce")
    if "price_m" in prices.columns:
        prices["price_m"] = pd.to_numeric(prices["price_m"], errors="coerce")
    elif "now_cost" in prices.columns:
        prices["price_m"] = pd.to_numeric(prices["now_cost"], errors="coerce") / 10.0
    else:
        return float(max(0.0, _safe_float(itb_m, default=0.0) or 0.0))
    prices = prices[prices["id"].notna() & prices["price_m"].notna()][["id", "price_m"]].copy()
    if prices.empty:
        return float(max(0.0, _safe_float(itb_m, default=0.0) or 0.0))
    prices["id"] = prices["id"].astype(int)

    sq = squad_df.copy()
    if "player_id" not in sq.columns:
        return float(max(0.0, _safe_float(itb_m, default=0.0) or 0.0))
    sq["player_id"] = pd.to_numeric(sq["player_id"], errors="coerce")
    sq = sq[sq["player_id"].notna()].copy()
    if sq.empty:
        return float(max(0.0, _safe_float(itb_m, default=0.0) or 0.0))
    sq["player_id"] = sq["player_id"].astype(int)

    merged = sq.merge(prices.rename(columns={"id": "player_id"}), on="player_id", how="left")
    squad_value = float(pd.to_numeric(merged.get("price_m"), errors="coerce").fillna(0.0).sum())
    itb_val = float(max(0.0, _safe_float(itb_m, default=0.0) or 0.0))
    budget = squad_value + itb_val
    return float(round(max(0.0, budget), 2))


def _chip_objective_components(chip_strategy):
    """Return a short list of scoring components for each chip mode."""
    chip_strategy = _normalize_chip_strategy(chip_strategy)
    if chip_strategy == "wildcard":
        return [
            "weighted next-fixture xPts",
            "future double-gameweek bonus",
            "premium captaincy bonus",
        ]
    if chip_strategy == "free_hit":
        return [
            "current gameweek xPts",
            "immediate doubles and blanks only",
        ]
    return []


def _build_chip_profile(chip_strategy, squad_df, proj_all, gws):
    """Summarize what the active chip build is trying to do."""
    chip_strategy = _normalize_chip_strategy(chip_strategy)
    if chip_strategy == "none" or squad_df is None or squad_df.empty or proj_all is None or proj_all.empty:
        return None

    if "player_id" not in squad_df.columns or "id" not in proj_all.columns:
        return None

    def merged_series(df, col, default=None):
        for cand in [col, f"{col}_x", f"{col}_y"]:
            if cand in df.columns:
                return df[cand]
        return pd.Series(default, index=df.index)

    join_cols = ["id", "pos", "price_m"]
    for extra in ["wildcard_score", "wildcard_weighted_xpts", "wildcard_future_dgw_bonus", "wildcard_captaincy_bonus"]:
        if extra in proj_all.columns:
            join_cols.append(extra)
    for gw in gws:
        for col in [f"fixture_count_gw{gw}", f"xpts_gw{gw}"]:
            if col in proj_all.columns:
                join_cols.append(col)

    sq = squad_df.copy()
    sq["player_id"] = pd.to_numeric(sq.get("player_id"), errors="coerce")
    sq = sq[sq["player_id"].notna()].copy()
    if sq.empty:
        return None
    sq["player_id"] = sq["player_id"].astype(int)

    merged = sq.merge(
        proj_all[list(dict.fromkeys(join_cols))].rename(columns={"id": "player_id"}),
        on="player_id",
        how="left",
    )
    if merged.empty:
        return None

    if chip_strategy == "free_hit":
        current_gw = int(gws[0]) if gws else None
        double_count = 0
        if current_gw is not None and f"fixture_count_gw{current_gw}" in merged.columns:
            double_count = int((pd.to_numeric(merged[f"fixture_count_gw{current_gw}"], errors="coerce").fillna(0.0) > 1).sum())
        return {
            "summary": "Free Hit is treated as a one-week attack: maximize the current gameweek score and ignore longer-term setup.",
            "focus": ["current gameweek", "immediate doubles", "short-term ceiling"],
            "current_double_players": int(double_count),
        }

    premium_floor = float(
        getattr(
            config,
            "CHIP_WILDCARD_PREMIUM_ATTACKER_FLOOR",
            getattr(config, "CAPTAIN_PREMIUM_PRICE_FLOOR", 9.0),
        )
        or getattr(config, "CAPTAIN_PREMIUM_PRICE_FLOOR", 9.0)
    )
    pos_series = merged_series(merged, "pos", default="")
    price_series = pd.to_numeric(merged_series(merged, "price_m", default=0.0), errors="coerce").fillna(0.0)
    attackers = pos_series.astype(str).isin(["MID", "FWD"])
    premium_attackers = int((attackers & (price_series >= premium_floor)).sum())

    future_double_gameweeks = []
    future_double_players = pd.Series(False, index=merged.index)
    for gw in list(gws)[1:]:
        fixture_col = f"fixture_count_gw{gw}"
        if fixture_col not in merged.columns:
            continue
        fixture_count = pd.to_numeric(merged[fixture_col], errors="coerce").fillna(0.0)
        doubled = fixture_count > 1.0
        if int(doubled.sum()) > 0:
            future_double_gameweeks.append(
                {
                    "event_id": int(gw),
                    "player_count": int(doubled.sum()),
                }
            )
        future_double_players = future_double_players | doubled

    return {
        "summary": (
            "Wildcard is being developed as a setup chip: it looks across the next fixtures, "
            "keeps captaincy-grade premiums in play, and boosts later doubles inside the planning horizon so the squad can move toward a bench boost."
        ),
        "focus": ["next fixtures", "future double gameweeks", "captaincy premiums", "bench boost setup"],
        "premium_attackers": int(premium_attackers),
        "future_double_gameweeks": future_double_gameweeks,
        "future_double_players": int(future_double_players.sum()),
    }


def _build_player_alerts(record, optimize_event_id=None):
    """Build lightweight per-player alerts for UI badges/tooltips."""
    alerts = []
    status = str(record.get("status") or "").strip().lower()
    chance = _safe_float(record.get("chance_of_playing_next_round"), default=None)

    if status and status != "a":
        severity = "high" if status in ("i", "u") else "medium"
        alerts.append(
            {
                "severity": severity,
                "category": "availability",
                "text": f"Availability risk ({status}).",
            }
        )
    elif chance is not None and float(chance) < 100.0:
        severity = "high" if float(chance) < 50.0 else "medium"
        alerts.append(
            {
                "severity": severity,
                "category": "availability",
                "text": f"Chance of playing next round is {int(round(float(chance)))}%.",
            }
        )

    fixtures_horizon = list(record.get("fixtures_horizon") or [])
    blank_alert = None
    double_alert = None
    for item in fixtures_horizon:
        event_id = _safe_int(item.get("event_id"))
        fixture_count = int(_safe_int(item.get("fixture_count")) or 0)
        if blank_alert is None and fixture_count == 0:
            severity = "high" if event_id == _safe_int(optimize_event_id) else "medium"
            blank_alert = {
                "severity": severity,
                "category": "blank",
                "event_id": event_id,
                "text": f"Blank gameweek in GW{int(event_id)}." if event_id else "Blank gameweek ahead.",
            }
        if double_alert is None and fixture_count > 1:
            double_alert = {
                "severity": "info",
                "category": "double",
                "event_id": event_id,
                "text": f"Double gameweek in GW{int(event_id)}." if event_id else "Double gameweek ahead.",
            }
        if blank_alert and double_alert:
            break

    if blank_alert:
        alerts.append(blank_alert)
    if double_alert:
        alerts.append(double_alert)
    return alerts


def _build_score_breakdown(record, chip_strategy="none", objective_score_col=None):
    """Build player-facing score explanation payload."""
    breakdown = {
        "note": "xPts are projected points, not actual FPL points.",
        "current_gw_xpts": _round_float(record.get("xpts"), 2, 0.0) if record.get("xpts") is not None else None,
        "horizon_xpts": _round_float(record.get("xpts_horizon"), 2, 0.0) if record.get("xpts_horizon") is not None else None,
        "objective_score_col": objective_score_col,
        "objective_score": None,
    }

    if objective_score_col and record.get(objective_score_col) is not None:
        breakdown["objective_score"] = _round_float(record.get(objective_score_col), 3, 0.0)

    if chip_strategy == "wildcard" or record.get("wildcard_score") is not None:
        breakdown["objective_explanation"] = (
            "Wildcard score is a planning score: weighted future xPts plus bonuses for future doubles and premium captaincy coverage."
        )
        breakdown["wildcard"] = {
            "score": _round_float(record.get("wildcard_score"), 3, 0.0) if record.get("wildcard_score") is not None else None,
            "weighted_xpts": _round_float(record.get("wildcard_weighted_xpts"), 3, 0.0)
            if record.get("wildcard_weighted_xpts") is not None
            else None,
            "future_dgw_bonus": _round_float(record.get("wildcard_future_dgw_bonus"), 3, 0.0)
            if record.get("wildcard_future_dgw_bonus") is not None
            else None,
            "captaincy_bonus": _round_float(record.get("wildcard_captaincy_bonus"), 3, 0.0)
            if record.get("wildcard_captaincy_bonus") is not None
            else None,
        }
    else:
        breakdown["objective_explanation"] = "Single-gameweek xPts estimate for the selected lineup week."

    breakdown["fixtures_horizon"] = list(record.get("fixtures_horizon") or [])
    return breakdown


def _decorate_projection_record(record, gws, chip_strategy="none", objective_score_col=None, optimize_event_id=None):
    """Normalize raw projection columns into frontend-friendly record fields."""
    fixtures_h = []
    for gw in gws:
        fixtures_h.append(
            {
                "event_id": int(gw),
                "fixtures": (record.get(f"fixtures_gw{gw}") or ""),
                "fixture_count": int(_safe_int(record.get(f"fixture_count_gw{gw}")) or 0),
                "diff_avg": float(_safe_float(record.get(f"diff_avg_gw{gw}"), default=0.0) or 0.0),
                "xpts": float(_safe_float(record.get(f"xpts_gw{gw}"), default=0.0) or 0.0),
            }
        )
        record.pop(f"fixtures_gw{gw}", None)
        record.pop(f"fixture_count_gw{gw}", None)
        record.pop(f"diff_avg_gw{gw}", None)
        record.pop(f"xpts_gw{gw}", None)

    record["fixtures_horizon"] = fixtures_h
    record["next_fixtures"] = fixtures_h[0]["fixtures"] if fixtures_h else ""
    record["alerts"] = _build_player_alerts(record, optimize_event_id=optimize_event_id)
    record["score_breakdown"] = _build_score_breakdown(
        record,
        chip_strategy=chip_strategy,
        objective_score_col=objective_score_col,
    )
    return record


def _build_position_panels(
    proj_all,
    gws,
    teams_code,
    owned_ids=None,
    limit_per_pos=5,
    ranking_col="xpts_horizon",
    chip_strategy="none",
    objective_score_col=None,
    optimize_event_id=None,
):
    """Build per-position top-player panels for all and not-owned pools."""
    if proj_all is None or proj_all.empty:
        return {"all": {}, "not_owned": {}}

    owned_ids = set([int(x) for x in (owned_ids or []) if _safe_int(x) is not None])
    limit_per_pos = max(1, int(limit_per_pos))
    ranking_col = str(ranking_col or "xpts_horizon")
    if ranking_col not in proj_all.columns:
        ranking_col = "xpts_horizon" if "xpts_horizon" in proj_all.columns else ranking_col

    base_cols = [
        "id",
        "web_name",
        "pos",
        "team",
        "team_short",
        "team_name",
        "price_m",
        "code",
        "photo",
        "status",
        "chance_of_playing_next_round",
        "xpts_horizon",
        "wildcard_score",
        "wildcard_weighted_xpts",
        "wildcard_future_dgw_bonus",
        "wildcard_captaincy_bonus",
    ]
    if ranking_col not in base_cols and ranking_col in proj_all.columns:
        base_cols.append(ranking_col)
    gw_cols = []
    for gw in gws:
        for c in [f"xpts_gw{gw}", f"fixtures_gw{gw}", f"fixture_count_gw{gw}", f"diff_avg_gw{gw}"]:
            if c in proj_all.columns:
                gw_cols.append(c)
    keep_cols = [c for c in base_cols + gw_cols if c in proj_all.columns]

    pool = proj_all[keep_cols].copy().rename(columns={"id": "player_id"})
    pool = pool.sort_values(ranking_col, ascending=False)

    def pack(df):
        out = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
        for pos in out.keys():
            chunk = df[df["pos"] == pos].head(limit_per_pos)
            recs = _attach_media(_df_records(chunk), teams_code)
            for rec in recs:
                _decorate_projection_record(
                    rec,
                    gws=gws,
                    chip_strategy=chip_strategy,
                    objective_score_col=objective_score_col or ranking_col,
                    optimize_event_id=optimize_event_id,
                )
            out[pos] = recs
        return out

    not_owned_df = pool[~pool["player_id"].astype(int).isin(owned_ids)] if owned_ids else pool.copy()
    return {
        "all": pack(pool),
        "not_owned": pack(not_owned_df),
    }


def _elapsed_ms(start_ts):
    """Return elapsed milliseconds since a perf-counter timestamp."""
    return int(round((time.perf_counter() - float(start_ts)) * 1000.0))


def _lineup_projection_cols(proj_all, gws):
    """List projection columns required to enrich lineup records."""
    proj_cols = ["id"]
    for c in [
        "xpts_horizon",
        "status",
        "chance_of_playing_next_round",
        "wildcard_score",
        "wildcard_weighted_xpts",
        "wildcard_future_dgw_bonus",
        "wildcard_captaincy_bonus",
    ]:
        if c in proj_all.columns:
            proj_cols.append(c)
    for gw in gws:
        for c in [f"xpts_gw{gw}", f"fixtures_gw{gw}", f"fixture_count_gw{gw}", f"diff_avg_gw{gw}"]:
            if c in proj_all.columns:
                proj_cols.append(c)
    return list(dict.fromkeys(proj_cols))


def _pack_lineup_records(
    starting_df,
    bench_df,
    elements,
    proj_all,
    gws,
    teams_code,
    chip_strategy="none",
    objective_score_col=None,
    optimize_event_id=None,
):
    """Merge lineup with media/projection fields and return JSON-safe records."""
    el_img = elements.copy()
    cols = [c for c in ["id", "team", "code", "photo"] if c in el_img.columns]
    el_img = el_img[cols].rename(columns={"id": "player_id"})

    proj_small = proj_all[_lineup_projection_cols(proj_all, gws)].copy().rename(columns={"id": "player_id"})
    starting = starting_df.merge(el_img, on="player_id", how="left").merge(proj_small, on="player_id", how="left")
    bench = bench_df.merge(el_img, on="player_id", how="left").merge(proj_small, on="player_id", how="left")
    starting_records = _attach_media(_df_records(starting), teams_code)
    bench_records = _attach_media(_df_records(bench), teams_code)

    for rec in starting_records + bench_records:
        _decorate_projection_record(
            rec,
            gws=gws,
            chip_strategy=chip_strategy,
            objective_score_col=objective_score_col,
            optimize_event_id=optimize_event_id,
        )

    return starting_records, bench_records


def _apply_transfer_moves_to_squad(squad_df, transfer_moves, elements):
    """Apply sell/buy transfer moves to a squad DataFrame."""
    if squad_df is None or squad_df.empty:
        return squad_df, {"requested": 0, "applied": 0, "skipped": 0}

    moves = transfer_moves if isinstance(transfer_moves, list) else []
    if not moves:
        return squad_df.copy(), {"requested": 0, "applied": 0, "skipped": 0}

    out = squad_df.copy()
    if "player_id" not in out.columns:
        return out, {"requested": len(moves), "applied": 0, "skipped": len(moves)}
    out["player_id"] = pd.to_numeric(out["player_id"], errors="coerce")
    out = out[out["player_id"].notna()].copy()
    out["player_id"] = out["player_id"].astype(int)

    el_cols = [c for c in ["id", "web_name", "team", "team_short", "team_name", "pos"] if c in elements.columns]
    el_map = elements[el_cols].drop_duplicates("id").set_index("id") if "id" in elements.columns else pd.DataFrame()

    applied = 0
    skipped = 0
    for move in moves:
        if not isinstance(move, dict):
            skipped += 1
            continue
        sell = move.get("sell") or {}
        buy = move.get("buy") or {}
        sell_id = _safe_int(sell.get("id"))
        buy_id = _safe_int(buy.get("id"))
        if not sell_id or not buy_id or int(sell_id) == int(buy_id):
            skipped += 1
            continue

        idxs = out.index[out["player_id"] == int(sell_id)].tolist()
        if not idxs:
            skipped += 1
            continue
        if int(buy_id) in set(out["player_id"].astype(int).tolist()):
            skipped += 1
            continue

        idx = idxs[0]
        out.at[idx, "player_id"] = int(buy_id)
        if "is_captain" in out.columns:
            out.at[idx, "is_captain"] = False
        if "is_vice_captain" in out.columns:
            out.at[idx, "is_vice_captain"] = False

        if not el_map.empty and int(buy_id) in el_map.index:
            row = el_map.loc[int(buy_id)]
            for col in ["web_name", "team", "team_short", "team_name", "pos"]:
                if col in out.columns and col in row.index:
                    out.at[idx, col] = row[col]
        else:
            if "web_name" in out.columns:
                out.at[idx, "web_name"] = buy.get("name")
            if "team_short" in out.columns:
                out.at[idx, "team_short"] = buy.get("team")

        applied += 1

    return out, {"requested": len(moves), "applied": applied, "skipped": skipped}


def _build_transfer_step(
    applied_count,
    moves,
    squad_df,
    elements,
    proj_all,
    score_col,
    gws,
    teams_code,
    base_res,
    base_points,
    base_starting_records,
    base_bench_records,
):
    """Build a lineup snapshot after applying N planned transfers."""
    applied_count = max(0, int(applied_count or 0))
    moves = list(moves or [])
    selected_moves = moves[:applied_count]

    if applied_count <= 0 or not selected_moves:
        apply_info = {"requested": 0, "applied": 0, "skipped": 0}
        return {
            "applied_count": 0,
            "transfer_application": {
                **apply_info,
                "available_moves": int(len(moves)),
                "requested_apply_count": 0,
            },
            "transfer_impact": {
                "base_projected_points_with_captain": float(base_points),
                "with_transfers_projected_points_with_captain": float(base_points),
                "delta_projected_points_with_captain": _round_float(0.0, 2, 0.0),
            },
            "formation": list(base_res["formation"]),
            "captain_player_id": int(base_res["captain_player_id"]),
            "vice_player_id": int(base_res["vice_player_id"]),
            "projected_points_with_captain": float(base_points),
            "starting_xi": base_starting_records,
            "bench": base_bench_records,
        }

    squad_after_df, apply_info = _apply_transfer_moves_to_squad(
        squad_df=squad_df,
        transfer_moves=selected_moves,
        elements=elements,
    )

    res_after = None
    if apply_info.get("applied", 0) > 0:
        try:
            res_after = optimizer.optimize_lineup(squad_after_df, proj_all, score_col=score_col)
        except Exception:
            res_after = None

    if not res_after:
        step_points = float(base_points)
        step_starting_records = base_starting_records
        step_bench_records = base_bench_records
        step_formation = list(base_res["formation"])
        step_captain = int(base_res["captain_player_id"])
        step_vice = int(base_res["vice_player_id"])
    else:
        step_points = float(res_after["projected_points_with_captain"])
        step_formation = list(res_after["formation"])
        step_captain = int(res_after["captain_player_id"])
        step_vice = int(res_after["vice_player_id"])
        step_starting_records, step_bench_records = _pack_lineup_records(
            starting_df=res_after["starting_xi"],
            bench_df=res_after["bench"],
            elements=elements,
            proj_all=proj_all,
            gws=gws,
            teams_code=teams_code,
        )

    return {
        "applied_count": int(applied_count),
        "transfer_application": {
            **apply_info,
            "available_moves": int(len(moves)),
            "requested_apply_count": int(applied_count),
        },
        "transfer_impact": {
            "base_projected_points_with_captain": float(base_points),
            "with_transfers_projected_points_with_captain": float(step_points),
            "delta_projected_points_with_captain": _round_float(step_points - float(base_points), 2, 0.0),
        },
        "formation": step_formation,
        "captain_player_id": step_captain,
        "vice_player_id": step_vice,
        "projected_points_with_captain": float(step_points),
        "starting_xi": step_starting_records,
        "bench": step_bench_records,
    }


def _round_float(value, ndigits=2, default=0.0):
    """Round numeric input safely to `ndigits` decimals."""
    parsed = _safe_float(value, default=default)
    if parsed is None:
        parsed = default
    return float(round(float(parsed), int(ndigits)))


def _safe_player_id(value):
    """Parse player id as int, returning None on invalid input."""
    parsed = _safe_int(value)
    if parsed is None:
        return None
    return int(parsed)


def _player_map_from_records(starting_records, bench_records):
    """Index starting/bench records by player id."""
    by_id = {}
    for rec in list(starting_records or []) + list(bench_records or []):
        pid = _safe_player_id(rec.get("player_id"))
        if pid is None:
            continue
        by_id[pid] = rec
    return by_id


def _build_bench_moves(squad_df, starting_records, bench_records):
    """Suggest start/bench swaps based on recommended XI and bench order."""
    if squad_df is None or squad_df.empty:
        return []

    cur = squad_df.copy()
    if "player_id" not in cur.columns:
        return []
    cur["player_id"] = pd.to_numeric(cur["player_id"], errors="coerce")
    cur = cur[cur["player_id"].notna()].copy()
    cur["player_id"] = cur["player_id"].astype(int)
    if cur.empty:
        return []

    if "multiplier" in cur.columns:
        cur["multiplier"] = pd.to_numeric(cur["multiplier"], errors="coerce").fillna(0.0)
    else:
        cur["multiplier"] = 0.0

    current_starting_ids = set(cur[cur["multiplier"] > 0]["player_id"].astype(int).tolist())
    current_bench_ids = set(cur[cur["multiplier"] <= 0]["player_id"].astype(int).tolist())

    rec_starting_ids = set()
    for rec in starting_records or []:
        pid = _safe_player_id(rec.get("player_id"))
        if pid is not None:
            rec_starting_ids.add(pid)

    rec_bench_order = {}
    for rec in bench_records or []:
        pid = _safe_player_id(rec.get("player_id"))
        if pid is None:
            continue
        rec_bench_order[pid] = _safe_int(rec.get("bench_order"))

    by_id = _player_map_from_records(starting_records, bench_records)

    start_candidates = []
    for pid in rec_starting_ids:
        rec = by_id.get(pid) or {}
        start_candidates.append((pid, _safe_float(rec.get("xpts"), default=0.0) or 0.0))
    start_candidates.sort(key=lambda row: row[1], reverse=True)

    moves = []
    for pid, _ in start_candidates:
        if pid not in current_bench_ids:
            continue
        rec = by_id.get(pid) or {}
        moves.append(
            {
                "player_id": int(pid),
                "web_name": rec.get("web_name"),
                "team_short": rec.get("team_short"),
                "move": "start",
                "recommended_bench_order": None,
                "xpts": _round_float(rec.get("xpts"), 2, 0.0),
            }
        )

    bench_candidates = []
    for pid, bench_order in rec_bench_order.items():
        rec = by_id.get(pid) or {}
        xpts = _safe_float(rec.get("xpts"), default=0.0) or 0.0
        bench_candidates.append((pid, bench_order if bench_order is not None else 99, xpts))
    bench_candidates.sort(key=lambda row: (row[1], row[2]))

    for pid, bench_order, _ in bench_candidates:
        if pid not in current_starting_ids:
            continue
        rec = by_id.get(pid) or {}
        moves.append(
            {
                "player_id": int(pid),
                "web_name": rec.get("web_name"),
                "team_short": rec.get("team_short"),
                "move": "bench",
                "recommended_bench_order": int(bench_order) if bench_order is not None else None,
                "xpts": _round_float(rec.get("xpts"), 2, 0.0),
            }
        )

    limit = int(getattr(config, "STRATEGY_MAX_BENCH_MOVES", 6) or 6)
    return moves[: max(1, limit)]


def _build_strategy_recommendation(
    squad_df,
    starting_records,
    bench_records,
    captain_player_id,
    vice_player_id,
    horizon_gws,
    free_transfers,
    transfer_preview,
    active_chip=None,
    selected_chip_strategy="none",
):
    """Create high-level action recommendation: roll, transfer, or chip."""
    horizon_gws = max(1, int(_safe_int(horizon_gws) or 1))
    free_transfers = max(0, int(_safe_int(free_transfers) or 0))

    transfer_preview = transfer_preview or {}
    preview_moves = transfer_preview.get("moves")
    if not isinstance(preview_moves, list):
        preview_moves = []

    total_gain = 0.0
    for move in preview_moves:
        if isinstance(move, dict):
            total_gain += float(_safe_float(move.get("score_gain"), default=0.0) or 0.0)
    planned_moves = len(preview_moves)
    avg_gain = float(total_gain / planned_moves) if planned_moves > 0 else 0.0

    if horizon_gws == 1:
        min_gain_per_transfer = float(getattr(config, "STRATEGY_MIN_GAIN_PER_TRANSFER_GW1", 1.4))
    else:
        min_gain_per_transfer = float(getattr(config, "STRATEGY_MIN_GAIN_PER_TRANSFER_MULTI", 1.1))

    suggested_transfers_count = planned_moves if avg_gain >= min_gain_per_transfer and total_gain > 0 else 0
    action = "make_transfers" if suggested_transfers_count > 0 else "roll"

    by_id = _player_map_from_records(starting_records, bench_records)
    captain_rec = by_id.get(_safe_player_id(captain_player_id) or -1) or {}
    vice_rec = by_id.get(_safe_player_id(vice_player_id) or -1) or {}
    captain_xpts = float(_safe_float(captain_rec.get("xpts"), default=0.0) or 0.0)
    bench_xpts = sum(float(_safe_float(r.get("xpts"), default=0.0) or 0.0) for r in (bench_records or []))

    chip_name = "none"
    chip_should_use = False
    chip_confidence = 0.35
    chip_reason = "No strong chip signal for this setup."

    selected_chip_strategy = _normalize_chip_strategy(selected_chip_strategy)

    if selected_chip_strategy in ("wildcard", "free_hit"):
        chip_name = selected_chip_strategy
        chip_should_use = True
        chip_confidence = 0.86 if selected_chip_strategy == "wildcard" else 0.84
        chip_reason = f"Scenario explicitly optimized for `{selected_chip_strategy}`."
    elif active_chip:
        chip_reason = f"Chip already active this GW ({active_chip})."
    elif horizon_gws == 1:
        bb_min = float(getattr(config, "STRATEGY_CHIP_BENCH_BOOST_MIN_XPTS", 15.0))
        tc_min = float(getattr(config, "STRATEGY_CHIP_TRIPLE_CAPTAIN_MIN_XPTS", 10.0))
        bench_boost_margin = bench_xpts - bb_min
        triple_captain_margin = captain_xpts - tc_min
        if bench_boost_margin >= 0 or triple_captain_margin >= 0:
            chip_should_use = True
            if bench_boost_margin >= triple_captain_margin:
                chip_name = "bench_boost"
                chip_confidence = min(0.92, 0.72 + max(0.0, bench_boost_margin) * 0.03)
                chip_reason = f"Bench projection is high ({_round_float(bench_xpts, 1, 0.0)} xPts)."
            else:
                chip_name = "triple_captain"
                chip_confidence = min(0.92, 0.72 + max(0.0, triple_captain_margin) * 0.04)
                chip_reason = f"Captain projection is very high ({_round_float(captain_xpts, 1, 0.0)} xPts)."

    reasons = []
    if action == "make_transfers":
        reasons.append(
            f"Transfer planner projects {_round_float(total_gain, 2, 0.0)} points total gain "
            f"({_round_float(avg_gain, 2, 0.0)} per move)."
        )
    else:
        reasons.append(
            f"Average transfer gain ({_round_float(avg_gain, 2, 0.0)}) is below threshold "
            f"({_round_float(min_gain_per_transfer, 2, 0.0)}), so rolling is safer."
        )

    if chip_should_use:
        reasons.append(chip_reason)
        action = "use_chip"

    if free_transfers > 0:
        reasons.append(f"Free transfers available: {int(free_transfers)}.")
    if horizon_gws > 1:
        reasons.append(f"Decision is optimized across the next {int(horizon_gws)} GWs.")

    if action == "use_chip":
        confidence = min(0.95, max(0.65, float(chip_confidence)))
    elif action == "make_transfers":
        confidence = min(0.9, 0.58 + max(0.0, min(0.28, avg_gain * 0.08)))
    else:
        confidence = min(0.88, 0.58 + max(0.0, min(0.24, (min_gain_per_transfer - avg_gain) * 0.1)))

    bench_moves = _build_bench_moves(squad_df, starting_records, bench_records)

    return {
        "action": action,
        "confidence": _round_float(confidence, 3, 0.6),
        "reasons": reasons,
        "captain_suggestion": {
            "captain_player_id": _safe_player_id(captain_player_id),
            "vice_player_id": _safe_player_id(vice_player_id),
            "captain_web_name": captain_rec.get("web_name"),
            "vice_web_name": vice_rec.get("web_name"),
            "captain_xpts": _round_float(captain_xpts, 2, 0.0),
        },
        "transfer_suggestion": {
            "free_transfers": int(free_transfers),
            "horizon_gws": int(horizon_gws),
            "suggested_transfers_count": int(suggested_transfers_count),
            "considered_transfers_count": int(planned_moves),
            "estimated_total_gain": _round_float(total_gain, 2, 0.0),
            "estimated_avg_gain": _round_float(avg_gain, 2, 0.0),
            "min_gain_per_transfer_threshold": _round_float(min_gain_per_transfer, 2, 0.0),
        },
        "chip_suggestion": {
            "chip": chip_name,
            "should_use": bool(chip_should_use),
            "confidence": _round_float(chip_confidence, 3, 0.35),
            "active_chip": active_chip,
            "reason": chip_reason,
        },
        "bench_recommendation": {
            "moves": bench_moves,
        },
    }


def _build_scoring_guide(optimize_event_id, chip_strategy="none", objective_score_col=None):
    """Explain the main scoring fields in plain language."""
    optimize_event_id = _safe_int(optimize_event_id)
    guide = {
        "headline": "Scores in this app are projected points, not actual FPL points already earned.",
        "bullets": [],
        "objective_score_col": objective_score_col,
    }
    if optimize_event_id:
        guide["bullets"].append(f"`xpts_gw{int(optimize_event_id)}` estimates points for GW{int(optimize_event_id)}.")
    guide["bullets"].append("`xpts_horizon` is the sum of projected xPts across the selected planning window.")
    if chip_strategy == "wildcard":
        guide["bullets"].append(
            "`wildcard_score` is a planning score for squad building: weighted future xPts plus bonuses for future doubles and premium captaincy cover."
        )
    else:
        guide["bullets"].append("Lineup selection still uses the selected gameweek xPts for the XI, captain, and bench order.")
    return guide


def _build_squad_insights(starting_records, bench_records, optimize_event_id, chip_strategy="none", chip_profile=None):
    """Build quick bullet-point squad insights and player flags."""
    optimize_event_id = _safe_int(optimize_event_id)
    records = list(starting_records or []) + list(bench_records or [])
    summary_points = []
    player_flags = []

    availability_names = []
    blank_now_names = []
    future_blanks = {}
    future_doubles = {}

    for rec in records:
        name = rec.get("web_name") or "Player"
        for alert in list(rec.get("alerts") or []):
            item = {
                "severity": alert.get("severity") or "info",
                "category": alert.get("category"),
                "text": f"{name}: {alert.get('text')}",
                "player_id": _safe_player_id(rec.get("player_id")),
                "player_name": name,
                "event_id": _safe_int(alert.get("event_id")),
            }
            player_flags.append(item)

            category = str(alert.get("category") or "")
            event_id = _safe_int(alert.get("event_id"))
            if category == "availability":
                availability_names.append(name)
            elif category == "blank":
                if event_id == optimize_event_id:
                    blank_now_names.append(name)
                elif event_id:
                    future_blanks.setdefault(int(event_id), []).append(name)
            elif category == "double" and event_id:
                future_doubles.setdefault(int(event_id), []).append(name)

    if availability_names:
        unique_names = list(dict.fromkeys(availability_names))
        summary_points.append(
            {
                "severity": "high",
                "category": "availability",
                "text": f"Availability risk to review: {', '.join(unique_names[:3])}" + ("." if len(unique_names) <= 3 else ", ..."),
            }
        )

    if blank_now_names:
        unique_names = list(dict.fromkeys(blank_now_names))
        summary_points.append(
            {
                "severity": "high",
                "category": "blank",
                "event_id": optimize_event_id,
                "text": f"Blank in GW{int(optimize_event_id)} for {', '.join(unique_names[:3])}" + ("." if len(unique_names) <= 3 else ", ..."),
            }
        )

    for event_id in sorted(future_blanks.keys())[:2]:
        names = list(dict.fromkeys(future_blanks[event_id]))
        summary_points.append(
            {
                "severity": "medium",
                "category": "blank",
                "event_id": int(event_id),
                "text": f"Blank risk ahead in GW{int(event_id)} for {len(names)} squad players.",
            }
        )

    for event_id in sorted(future_doubles.keys())[:2]:
        names = list(dict.fromkeys(future_doubles[event_id]))
        summary_points.append(
            {
                "severity": "info",
                "category": "double",
                "event_id": int(event_id),
                "text": f"Double gameweek upside in GW{int(event_id)} for {len(names)} squad players.",
            }
        )

    bench_xpts = sum(float(_safe_float(r.get("xpts"), default=0.0) or 0.0) for r in (bench_records or []))
    if chip_strategy == "wildcard":
        summary_points.append(
            {
                "severity": "info",
                "category": "chip",
                "text": f"Wildcard bench projects {_round_float(bench_xpts, 1, 0.0)} xPts for the selected week.",
            }
        )
        if isinstance(chip_profile, dict) and chip_profile.get("future_double_players"):
            summary_points.append(
                {
                    "severity": "info",
                    "category": "chip",
                    "text": f"Wildcard draft already carries {int(chip_profile.get('future_double_players') or 0)} players with later doubles in the planning window.",
                }
            )

    if not summary_points:
        summary_points.append(
            {
                "severity": "info",
                "category": "stable",
                "text": "No major squad warning flags detected in the selected planning window.",
            }
        )

    severity_rank = {"high": 0, "medium": 1, "info": 2, "low": 3}
    summary_points = sorted(summary_points, key=lambda item: severity_rank.get(str(item.get("severity")), 9))[:6]
    player_flags = sorted(player_flags, key=lambda item: severity_rank.get(str(item.get("severity")), 9))[:12]
    return {
        "summary_points": summary_points,
        "player_flags": player_flags,
    }


def load_fpl_context(entry_id, squad_event_id, with_fixtures=True):
    """Load and normalize bootstrap, fixtures, elements, and squad for an entry."""
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
    """Build squad payload with captain/vice and split starting XI vs bench."""
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
    """Build optimized lineup, transfers preview, and strategy recommendation."""
    total_start = time.perf_counter()
    timings = {}

    entry_id = payload.get("entry_id") or os.environ.get("FPL_ENTRY_ID")
    optimize_event_id_raw = payload.get("event_id")
    squad_event_id_raw = payload.get("squad_event_id")
    horizon_gws_raw = payload.get("horizon_gws", 3)
    chip_horizon_gws_raw = payload.get("chip_horizon_gws")
    chip_play_event_id_raw = payload.get("chip_play_event_id")
    chip_strategy_raw = payload.get("chip_strategy")
    chip_strategy = _normalize_chip_strategy(chip_strategy_raw)
    latest_n_matches_raw = payload.get("latest_n_matches", getattr(config, "PROJ_DEFAULT_LATEST_N_MATCHES", 3))
    apply_transfer_count_raw = payload.get("apply_transfer_count")

    include_transfers = _parse_bool(payload.get("include_transfers"), default=False)
    itb_m = payload.get("itb_m", 0.5)
    free_transfers = payload.get("free_transfers", 1)
    hit_cap = payload.get("hit_cap", 0)
    panel_limit = _safe_int(payload.get("panel_limit"))
    if panel_limit is None:
        panel_limit = 5

    ts = time.perf_counter()
    ctx = load_fpl_context(entry_id, squad_event_id_raw, with_fixtures=True)
    timings["load_context_ms"] = _elapsed_ms(ts)
    notes = list(ctx.get("notes") or [])
    if chip_strategy == "none" and chip_strategy_raw not in (None, "", "none", "None"):
        notes.append("Unknown chip_strategy; fallback to none.")

    entry_id = ctx["entry_id"]
    squad_event_id = ctx["squad_event_id"]
    max_event_id = ctx["max_event_id"]
    next_event_id = _event_id(ctx["bootstrap"], "is_next")

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

    display_horizon_gws = _safe_int(horizon_gws_raw)
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
        wildcard_play_event_id = _safe_int(chip_play_event_id_raw)
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
        chip_build_horizon_gws = _safe_int(chip_horizon_gws_raw)
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

    latest_n_matches = _safe_int(latest_n_matches_raw)
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
    timings["projections_ms"] = _elapsed_ms(ts)

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
        "objective_components": _chip_objective_components(chip_strategy),
        "explanation": None,
        "profile": None,
        "reason": "No chip strategy applied.",
    }

    if chip_is_active:
        chip_objective_col = "wildcard_score" if chip_strategy == "wildcard" else score_col
        chip_objective_horizon = int(chip_build_horizon_gws) if chip_strategy == "wildcard" else 1
        ts = time.perf_counter()
        budget_m = _estimate_squad_budget_m(
            squad_df=squad_df,
            elements=elements,
            itb_m=_safe_float(itb_m, default=0.0) or 0.0,
        )
        chip_build = optimizer.build_chip_squad(
            elements_all=proj_all,
            score_col=chip_objective_col,
            budget_m=budget_m,
            max_per_team=int(getattr(config, "CHIP_MAX_PER_TEAM", 3) or 3),
        )
        timings["chip_draft_ms"] = _elapsed_ms(ts)

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
                "objective_components": _chip_objective_components(chip_strategy),
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
                "objective_components": _chip_objective_components(chip_strategy),
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
    timings["optimize_base_ms"] = _elapsed_ms(ts)

    gws = [int(optimize_event_id) + i for i in range(int(display_horizon_gws))]
    chip_profile_gws = gws
    if wildcard_is_active:
        chip_profile_gws = [int(wildcard_play_event_id) + i for i in range(int(chip_build_horizon_gws))]
    ts = time.perf_counter()
    starting_records, bench_records = _pack_lineup_records(
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
    timings["pack_base_lineup_ms"] = _elapsed_ms(ts)

    owned_ids = []
    if "player_id" in lineup_squad_df.columns:
        owned_ids = [int(x) for x in pd.to_numeric(lineup_squad_df["player_id"], errors="coerce").dropna().astype(int).tolist()]
    ts = time.perf_counter()
    position_panels = _build_position_panels(
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
    timings["position_panels_ms"] = _elapsed_ms(ts)

    if chip_info.get("is_active"):
        chip_profile = _build_chip_profile(
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
        "scoring_guide": _build_scoring_guide(
            optimize_event_id=optimize_event_id,
            chip_strategy=chip_strategy if chip_info.get("is_active") else "none",
            objective_score_col=chip_info.get("objective_score_col"),
        ),
    }

    free_transfers_value = _safe_int(free_transfers)
    if free_transfers_value is None:
        free_transfers_value = 1
    ts = time.perf_counter()
    if chip_info.get("is_active"):
        transfer_preview = {
            "note": f"Transfers planner skipped when chip strategy `{chip_strategy}` is active.",
            "transfer_plan": {
                "free_transfers": int(free_transfers_value),
                "horizon_gws": int(display_horizon_gws),
                "hit_cap": int(_safe_int(hit_cap) or 0),
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
            itb_m=_safe_float(itb_m, default=0.0) or 0.0,
            free_transfers=free_transfers_value,
            hit_cap=_safe_int(hit_cap) or 0,
            score_col="xpts_horizon",
            horizon_gws=int(display_horizon_gws),
        )
    timings["transfer_preview_ms"] = _elapsed_ms(ts)
    if include_transfers:
        out["transfers"] = transfer_preview

    ts = time.perf_counter()
    moves = transfer_preview.get("moves") if isinstance(transfer_preview, dict) else []
    if not isinstance(moves, list):
        moves = []

    apply_transfer_count = _safe_int(apply_transfer_count_raw)
    if apply_transfer_count is None:
        effective_apply_count = 0
    else:
        effective_apply_count = max(0, min(int(apply_transfer_count), len(moves)))

    transfer_steps = []
    if moves:
        for idx in range(0, len(moves) + 1):
            step = _build_transfer_step(
                applied_count=idx,
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
            transfer_steps.append(step)
    else:
        transfer_steps.append(
            _build_transfer_step(
                applied_count=0,
                moves=[],
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
        )

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
    timings["transfer_apply_and_reoptimize_ms"] = _elapsed_ms(ts)

    out["strategy_recommendation"] = _build_strategy_recommendation(
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
    out["squad_insights"] = _build_squad_insights(
        starting_records=starting_records,
        bench_records=bench_records,
        optimize_event_id=optimize_event_id,
        chip_strategy=chip_strategy if chip_info.get("is_active") else "none",
        chip_profile=chip_info.get("profile"),
    )

    timings["total_ms"] = _elapsed_ms(total_start)
    out["timings_ms"] = timings
    logger.info(
        "recommendations entry_id=%s squad_event_id=%s event_id=%s horizon=%s chip=%s timings_ms=%s",
        int(entry_id),
        int(squad_event_id),
        int(optimize_event_id),
        int(display_horizon_gws),
        chip_strategy,
        timings,
    )

    return out


def build_xpts_evaluation(payload):
    """Evaluate baseline xPts quality against actual GW points history."""
    payload = payload or {}
    history_csv_path = payload.get("history_csv_path")
    base_dir = payload.get("base_dir") or "data/processed/fpl"
    window = _safe_int(payload.get("window", 3))
    min_gw = _safe_int(payload.get("min_gw", 2))
    topk = _safe_int(payload.get("topk", 25))

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
    """API root endpoint with health/docs pointers."""
    return {"ok": True, "docs": "/docs", "health": "/health"}


@app.get("/health")
def health():
    """Simple health endpoint used by probes."""
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z"}


@app.get("/events/next")
def next_event():
    """Return computed metadata for the next event/deadline."""
    bootstrap = get_bootstrap_cached()
    fixtures = get_fixtures_cached()
    summary = build_next_event_summary(bootstrap=bootstrap, fixtures=fixtures)
    return JSONResponse(content=jsonable_encoder(summary))


@app.post("/admin/refresh")
def admin_refresh(
    payload=Body(None),
    api_key=None,
    x_api_key=Header(None),
    authorization=Header(None),
):
    """Admin endpoint to refresh caches and optional next-GW snapshot."""
    payload = payload or {}
    err = _check_admin_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key or payload.get("api_key"))
    if err:
        return err

    run_snapshot = _parse_bool(payload.get("run_snapshot"), default=True)
    out_base = payload.get("out_base") or os.environ.get("FPL_SNAPSHOT_OUT_BASE") or "data/processed"

    _bootstrap_cache["ts"] = 0.0
    _bootstrap_cache["data"] = None
    _fixtures_cache["ts"] = 0.0
    _fixtures_cache["data"] = None

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

    return JSONResponse(
        content=jsonable_encoder(
            {
                "ok": True,
                "next_event": next_ev,
                "cache_refreshed_at_utc": datetime.utcnow().isoformat() + "Z",
                "snapshot_info": snapshot_info,
                "snapshot_error": snapshot_error,
            }
        )
    )


@app.get("/squad")
def squad_get(
    entry_id=None,
    event_id=None,
    api_key=None,
    x_api_key=Header(None),
    authorization=Header(None),
):
    """GET squad endpoint."""
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
    """POST squad endpoint."""
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
    chip_horizon_gws=None,
    chip_play_event_id=None,
    chip_strategy="none",
    latest_n_matches=3,
    include_transfers=False,
    apply_transfer_count=None,
    itb_m=0.5,
    free_transfers=1,
    hit_cap=0,
    panel_limit=5,
    api_key=None,
    x_api_key=Header(None),
    authorization=Header(None),
):
    """GET recommendations endpoint."""
    err = _check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key)
    if err:
        return err
    payload = {
        "entry_id": entry_id,
        "event_id": event_id,
        "squad_event_id": squad_event_id,
        "horizon_gws": horizon_gws,
        "chip_horizon_gws": chip_horizon_gws,
        "chip_play_event_id": chip_play_event_id,
        "chip_strategy": chip_strategy,
        "latest_n_matches": latest_n_matches,
        "include_transfers": include_transfers,
        "apply_transfer_count": apply_transfer_count,
        "itb_m": itb_m,
        "free_transfers": free_transfers,
        "hit_cap": hit_cap,
        "panel_limit": panel_limit,
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
    """POST recommendations endpoint."""
    payload = payload or {}
    err = _check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key or payload.get("api_key"))
    if err:
        return err
    out = build_recommendations(payload)
    return JSONResponse(content=jsonable_encoder(out))


@app.get("/evaluation/xpts")
def evaluation_xpts_get(
    history_csv_path=None,
    base_dir="data/processed/fpl",
    window=3,
    min_gw=2,
    topk=25,
    api_key=None,
    x_api_key=Header(None),
    authorization=Header(None),
):
    """GET xPts evaluation endpoint."""
    err = _check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key)
    if err:
        return err
    out = build_xpts_evaluation(
        {
            "history_csv_path": history_csv_path,
            "base_dir": base_dir,
            "window": window,
            "min_gw": min_gw,
            "topk": topk,
        }
    )
    return JSONResponse(content=jsonable_encoder(out))


@app.post("/evaluation/xpts")
def evaluation_xpts_post(
    payload=Body(None),
    api_key=None,
    x_api_key=Header(None),
    authorization=Header(None),
):
    """POST xPts evaluation endpoint."""
    payload = payload or {}
    err = _check_api_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key or payload.get("api_key"))
    if err:
        return err
    out = build_xpts_evaluation(payload)
    return JSONResponse(content=jsonable_encoder(out))
