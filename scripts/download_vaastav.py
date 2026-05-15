#!/usr/bin/env python3
"""
Download Vaastav FPL dataset for a given season.

Pulls per-GW merged_gw + fixtures + players_raw from
github.com/vaastav/Fantasy-Premier-League into data/vaastav/<season>/.

Usage:
  python3 scripts/download_vaastav.py --season 2025-26
  python3 scripts/download_vaastav.py --season 2025-26 --gws 1-36
"""
import argparse
import sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

REPO_RAW = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"

# Files to grab once per season (not per GW)
SEASON_FILES = [
    "players_raw.csv",
    "teams.csv",
    "fixtures.csv",
    "cleaned_players.csv",
]


def fetch(url: str, out: Path) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": "fpledge-backtest/1.0"})
    try:
        with urlopen(req, timeout=30) as r:
            data = r.read()
        out.write_bytes(data)
        return True
    except HTTPError as e:
        print(f"  ! {url} -> HTTP {e.code}")
        return False
    except Exception as e:
        print(f"  ! {url} -> {e}")
        return False


def parse_gw_range(spec: str):
    if not spec:
        return list(range(1, 39))
    parts = spec.split("-")
    if len(parts) == 1:
        return [int(parts[0])]
    lo, hi = int(parts[0]), int(parts[1])
    return list(range(lo, hi + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2025-26", help="Season folder name in Vaastav repo (e.g. 2025-26)")
    ap.add_argument("--gws", default="1-38", help="GW range to fetch, e.g. 1-36 or 10")
    ap.add_argument("--out", default="data/vaastav", help="Local output base directory")
    args = ap.parse_args()

    season = args.season
    gw_range = parse_gw_range(args.gws)
    out_base = Path(args.out) / season

    base_url = f"{REPO_RAW}/{season}"
    print(f"Downloading season {season} -> {out_base}")

    # Season-level files
    print("\nSeason files:")
    season_ok = 0
    for fname in SEASON_FILES:
        url = f"{base_url}/{fname}"
        out = out_base / fname
        if fetch(url, out):
            print(f"  ✓ {fname}")
            season_ok += 1

    # Per-GW files (merged_gw is the format Vaastav uses across all seasons)
    print(f"\nPer-GW files (GW {gw_range[0]}–{gw_range[-1]}):")
    gw_ok = 0
    for gw in gw_range:
        url = f"{base_url}/gws/gw{gw}.csv"
        out = out_base / "gws" / f"gw{gw}.csv"
        if fetch(url, out):
            gw_ok += 1
    print(f"  ✓ {gw_ok}/{len(gw_range)} GWs")

    print(f"\nDone. {season_ok}/{len(SEASON_FILES)} season files + {gw_ok} GW files in {out_base}")
    return 0 if (season_ok > 0 and gw_ok > 0) else 1


if __name__ == "__main__":
    sys.exit(main())
