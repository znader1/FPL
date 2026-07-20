#!/usr/bin/env python3
"""Write a clean per-GW entry snapshot from frozen raw FPL JSON.

Raw files must already exist under data/replay/<season>/raw/
(entry.json, history.json, picks_gwNN.json). Capture them with the raw fetch
first; this script only parses local files (no network).

Usage:
  python -m scripts.snapshot_entry --entry 588004 --season 2025-26
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import replay_snapshot  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", type=int, required=True)
    ap.add_argument("--season", default="2025-26")
    args = ap.parse_args()
    base = Path("data/replay") / args.season
    raw = base / "raw"
    if not raw.exists():
        print(f"ERROR: raw dir missing: {raw}. Capture raw FPL JSON first.", file=sys.stderr)
        return 1
    snap = replay_snapshot.build_entry_snapshot(str(raw), season=args.season)
    out = base / f"entry_{args.entry}.json"
    out.write_text(json.dumps(snap, indent=2))
    print(f"Wrote {out} ({len(snap['gws'])} GWs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
