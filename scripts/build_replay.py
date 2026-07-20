#!/usr/bin/env python3
"""Precompute per-GW model-vs-reality records for personal GW replay.

Usage:
  python -m scripts.build_replay --season 2025-26 --start 2 --end 38 --entry 588004
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import replay_builder  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2025-26")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=38)
    ap.add_argument("--horizon", type=int, default=3)
    ap.add_argument("--entry", type=int, default=None,
                    help="entry id whose snapshot supplies each GW's squad")
    args = ap.parse_args()

    base = Path("data/replay") / args.season
    snapshot = {"season": args.season, "gws": {}}
    if args.entry:
        snap_path = base / f"entry_{args.entry}.json"
        if snap_path.exists():
            raw = json.loads(snap_path.read_text())
            snapshot = {"season": args.season,
                        "gws": {int(k): v for k, v in raw.get("gws", {}).items()}}
        else:
            print(f"WARN: {snap_path} not found; squads will be empty.", file=sys.stderr)

    base.mkdir(parents=True, exist_ok=True)
    for gw in range(args.start, args.end + 1):
        rec = replay_builder.build_gw_record(gw, args.season, snapshot, horizon=args.horizon)
        out = base / f"gw{gw:02d}.json"
        out.write_text(json.dumps(rec, indent=2))
        print(f"  wrote {out} (players={len(rec['players'])}, setup={rec['setup_gw']})")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
