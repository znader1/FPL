import time
from datetime import datetime, timezone

import pandas as pd


def safe_int(x):
    try:
        return int(x)
    except Exception:
        return None


def safe_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default


def round_float(value, ndigits=2, default=0.0):
    parsed = safe_float(value, default=default)
    if parsed is None:
        parsed = default
    return float(round(float(parsed), int(ndigits)))


def safe_player_id(value):
    parsed = safe_int(value)
    if parsed is None:
        return None
    return int(parsed)


def to_iso_utc(value):
    if value is None:
        return None
    try:
        dt = pd.to_datetime(value, errors="coerce", utc=True)
        if pd.isna(dt):
            return None
        return dt.to_pydatetime().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def hours_until_utc(value):
    iso = to_iso_utc(value)
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        delta_h = (dt - datetime.now(timezone.utc)).total_seconds() / 3600.0
        return float(round(delta_h, 2))
    except Exception:
        return None


def parse_bool(x, default=False):
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


def normalize_chip_strategy(value):
    s = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if s in ("", "none", "off", "no_chip"):
        return "none"
    if s in ("wildcard", "wc"):
        return "wildcard"
    if s in ("free_hit", "freehit", "fh"):
        return "free_hit"
    if s in ("bench_boost", "bboost", "bb"):
        return "bench_boost"
    if s in ("triple_captain", "3xc", "tc"):
        return "triple_captain"
    return "none"


def clean_value(v):
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


def df_records(df):
    recs = []
    if df is None or getattr(df, "empty", True):
        return recs
    for _, r in df.iterrows():
        d = {}
        for k, v in r.items():
            d[str(k)] = clean_value(v)
        recs.append(d)
    return recs


def elapsed_ms(start_ts):
    return int(round((time.perf_counter() - float(start_ts)) * 1000.0))
