"""Parse frozen raw FPL entry JSON (data/replay/<season>/raw/) into a clean,
per-GW entry snapshot. Pure: no network, no FastAPI."""
import json
from pathlib import Path


def derive_transfers(prev_picks, picks):
    if not prev_picks:
        return {"in": [], "out": []}
    prev, cur = set(prev_picks), set(picks)
    return {"in": sorted(cur - prev), "out": sorted(prev - cur)}


def _load(path):
    return json.loads(Path(path).read_text())


def build_entry_snapshot(raw_dir, season="2025-26"):
    raw = Path(raw_dir)
    entry = _load(raw / "entry.json")
    gws = {}
    prev_picks = []
    for pick_file in sorted(raw.glob("picks_gw*.json")):
        gw = int(pick_file.stem.replace("picks_gw", ""))
        d = _load(pick_file)
        picks_rows = d.get("picks", [])
        pick_ids = [int(p["element"]) for p in picks_rows]
        eh = d.get("entry_history", {}) or {}
        cap = next((int(p["element"]) for p in picks_rows if p.get("is_captain")), None)
        vice = next((int(p["element"]) for p in picks_rows if p.get("is_vice_captain")), None)
        bank = eh.get("bank")
        gws[gw] = {
            "picks": pick_ids,
            "captain": cap,
            "vice": vice,
            "transfers": derive_transfers(prev_picks, pick_ids),
            "chip": d.get("active_chip"),
            "points": eh.get("points"),
            "bank": (bank / 10.0) if isinstance(bank, (int, float)) else None,
        }
        prev_picks = pick_ids
    return {"entry_id": int(entry.get("id")), "season": season, "gws": gws}
