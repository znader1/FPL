"""
Vaastav-based backtest data loader.

Loads cached Vaastav CSVs (downloaded via scripts/download_vaastav.py) and
exposes time-capped slices: never returns data from GWs > max_gw, so projection
code can be reused without leaking the future into past predictions.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd


POSITION_MAP = {"GKP": "GKP", "GK": "GKP", "DEF": "DEF", "MID": "MID", "FWD": "FWD"}


def _data_dir(season: str, base: str | Path = "data/vaastav") -> Path:
    return Path(base) / season


def load_players_raw(season: str = "2025-26", base: str | Path = "data/vaastav") -> pd.DataFrame:
    df = pd.read_csv(_data_dir(season, base) / "players_raw.csv")
    df["price_m"] = pd.to_numeric(df.get("now_cost"), errors="coerce") / 10.0
    return df


def load_teams(season: str = "2025-26", base: str | Path = "data/vaastav") -> pd.DataFrame:
    return pd.read_csv(_data_dir(season, base) / "teams.csv")


def load_fixtures(season: str = "2025-26", base: str | Path = "data/vaastav") -> pd.DataFrame:
    return pd.read_csv(_data_dir(season, base) / "fixtures.csv")


def available_gws(season: str = "2025-26", base: str | Path = "data/vaastav") -> list[int]:
    gws_dir = _data_dir(season, base) / "gws"
    if not gws_dir.exists():
        return []
    out = []
    for p in gws_dir.glob("gw*.csv"):
        try:
            out.append(int(p.stem.replace("gw", "")))
        except Exception:
            continue
    return sorted(out)


def load_gw(gw: int, season: str = "2025-26", base: str | Path = "data/vaastav") -> pd.DataFrame:
    """Load one GW's per-player actuals."""
    path = _data_dir(season, base) / "gws" / f"gw{gw}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing Vaastav GW file: {path}")
    df = pd.read_csv(path)
    df["gw"] = int(gw)
    df["player_id"] = pd.to_numeric(df["element"], errors="coerce").astype("Int64")
    df["pos"] = df["position"].map(POSITION_MAP).fillna(df["position"])
    df["price_m"] = pd.to_numeric(df.get("value"), errors="coerce") / 10.0
    return df


def load_history(season: str = "2025-26", base: str | Path = "data/vaastav", max_gw: int | None = None) -> pd.DataFrame:
    """Concatenate all GW files up to max_gw (inclusive). Returns long-format actuals."""
    gws = available_gws(season, base)
    if max_gw is not None:
        gws = [g for g in gws if g <= int(max_gw)]
    if not gws:
        return pd.DataFrame()
    frames = [load_gw(g, season, base) for g in gws]
    out = pd.concat(frames, ignore_index=True, sort=False)
    return out


def player_actuals_through(gw: int, season: str = "2025-26", base: str | Path = "data/vaastav") -> pd.DataFrame:
    """Long-format actuals up to and including `gw`. Use for computing form/baseline at a given point in time."""
    return load_history(season, base, max_gw=gw)


def player_actuals_at(gw: int, season: str = "2025-26", base: str | Path = "data/vaastav") -> pd.DataFrame:
    """Just GW `gw` actuals (for scoring squad performance)."""
    return load_gw(gw, season, base)


def fixtures_through(gw: int, season: str = "2025-26", base: str | Path = "data/vaastav") -> pd.DataFrame:
    """Fixtures with event <= gw (results known)."""
    fx = load_fixtures(season, base)
    fx = fx[pd.to_numeric(fx.get("event"), errors="coerce").fillna(0).astype(int) <= int(gw)]
    return fx


def fixtures_for(gw: int, season: str = "2025-26", base: str | Path = "data/vaastav") -> pd.DataFrame:
    """Just GW `gw` fixtures (for projecting that GW)."""
    fx = load_fixtures(season, base)
    return fx[pd.to_numeric(fx.get("event"), errors="coerce").fillna(0).astype(int) == int(gw)]
