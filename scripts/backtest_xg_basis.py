#!/usr/bin/env python3
"""
Projection-basis DIVERGENCE DIAGNOSTIC: ppg vs xg (Task 8, rescoped).

*** THIS IS NOT AN ACCURACY BACKTEST. ***

A rigorous historical accuracy backtest of the `xg` projection basis would
require reconstructing as-of-each-GW per-90 xG rates + minutes from historical
data -- the cold-start adapters in `src/squad_draft_xg.py` read the
PRE-SEASON bootstrap's retained last-season aggregates, which simply don't
exist mid-season, so there is no drop-in historical replay path today. That
is tracked as its own follow-on sub-project (see
`docs/superpowers/specs/2026-07-23-squad-picker-page-design.md` ##
"Backtest gate").

What this script DOES do, against the real, live current pool: build a full
squad twice via `src/squad_draft.build_squad` -- once with
`projection_basis="ppg"`, once with `projection_basis="xg"` -- and report how
far the two bases diverge:
  - 15-man squad player overlap + the differing picks per position
  - captain agreement
  - `projected_points.horizon_total` for each basis
  - a projection-level divergence over the full shared candidate pool:
    Spearman rank correlation of `xpts_horizon`, and top-15-by-xpts overlap

The default basis is (and stays) `ppg` -- this diagnostic exists to make the
size of the disagreement visible, not to pick a winner.

Local analysis tool only -- not wired into the product, no unit test.

Usage:
  source .venv/bin/activate && PYTHONPATH=. python scripts/backtest_xg_basis.py
  PYTHONPATH=. python scripts/backtest_xg_basis.py --horizon 5 --budget 100.0
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from src import config, fpl_client, projections, squad_draft, squad_draft_xg, transforms  # noqa: E402

try:
    from scipy.stats import spearmanr as _scipy_spearmanr
    _HAVE_SCIPY = True
except ImportError:
    _HAVE_SCIPY = False


def _spearman(a, b):
    """Spearman rank correlation of two equal-length numeric sequences.

    Uses scipy when available; otherwise falls back to pandas `.rank()` +
    Pearson correlation on the ranks, which is mathematically equivalent to
    Spearman's rho (no ties-correction subtlety matters here -- floating-point
    xpts values essentially never tie).
    """
    if _HAVE_SCIPY:
        rho, _p = _scipy_spearmanr(a, b)
        return float(rho)
    ra = pd.Series(a).reset_index(drop=True).rank()
    rb = pd.Series(b).reset_index(drop=True).rank()
    return float(ra.corr(rb))


_XG_BASIS_RAW_COLS = ["expected_goals_per_90", "expected_assists_per_90", "starts"]


def _patch_elements_keep_for_xg_basis():
    """KNOWN BUG, discovered by actually running this diagnostic against live
    data (not fixed here -- out of this task's committed scope, which is
    limited to this script + the spec doc): `config.ELEMENTS_KEEP`
    (`src/config.py`) does not include `expected_goals_per_90` /
    `expected_assists_per_90` / `starts`. Every live call in
    `squad_draft.build_squad` runs `transforms.tables_from_bootstrap`, which
    filters the raw bootstrap element columns down to `ELEMENTS_KEEP` --
    silently dropping those three before `squad_draft_xg.rates_from_bootstrap`
    / `minutes_from_bootstrap` (the "xg"/"blend" basis's cold-start adapters)
    ever see them. Those adapters then do `pd.to_numeric(df.get(<missing
    column>)).fillna(...)`; on a genuinely-absent column this yields a bare
    scalar (not a Series), and `.fillna` on a scalar raises `AttributeError`.
    Net effect: `projection_basis="xg"`/`"blend"` crashes on every real,
    live `build_squad()` call today. None of the existing xg-basis tests
    catch this because they call `build_squad_from_frames` directly with
    synthetic elements that already carry these columns, bypassing
    `transforms.tables_from_bootstrap` (and therefore `ELEMENTS_KEEP`)
    entirely.

    This diagnostic's whole point is to exercise the real live path, so it
    patches `config.ELEMENTS_KEEP` IN THIS PROCESS ONLY -- `src/config.py` on
    disk is untouched -- to unblock the run. The real fix belongs in
    `config.ELEMENTS_KEEP` itself; flagged as a concern in this task's
    report rather than silently patched into the shared config file, since
    this diagnostic's commit is scoped to this script + the spec doc only.
    """
    missing = [c for c in _XG_BASIS_RAW_COLS if c not in config.ELEMENTS_KEEP]
    if missing:
        print(f"[patch] config.ELEMENTS_KEEP missing {missing} (required by the xg basis's "
              f"cold-start adapters) -- patching in-process only, src/config.py is untouched.")
        config.ELEMENTS_KEEP = list(config.ELEMENTS_KEEP) + missing


def _prepare_pool(bootstrap, fixtures_raw, p):
    """Mirror `squad_draft.build_squad_from_frames`'s pool prep EXACTLY (same
    availability filter, same minutes-shrink, same forward-minutes floor) so
    the projection-level diagnostic below runs against the identical
    candidate pool the real squad-building path sees. Reuses the pipeline's
    own private helpers rather than re-implementing them, so this can never
    silently drift from the real path."""
    elements, teams, _etypes = transforms.tables_from_bootstrap(bootstrap)
    fixtures = transforms.fixtures_df(fixtures_raw)
    teams_short = teams.set_index("id")["short_name"].to_dict()
    gw_start = squad_draft._next_gw(bootstrap)

    avail = squad_draft._filter_availability(
        elements, p["include_flagged"], p["min_chance_of_playing"])
    avail = squad_draft._apply_minutes_shrink(avail, p["minutes_prior_k"])
    mins = pd.to_numeric(avail.get("minutes"), errors="coerce").fillna(0.0)
    if float(p["min_fwd_minutes"]) > 0:
        drop = (avail["pos"] == "FWD") & (mins < float(p["min_fwd_minutes"]))
        avail = avail[~drop].copy()
    return avail, fixtures, teams_short, gw_start


def _build_both_projections(avail, fixtures, teams_short, gw_start, horizon):
    """Same two calls `build_squad_from_frames` makes when routing basis
    "ppg" vs "xg" (xg always uses blend_weight=1.0 -- pure xg, no ppg blend)."""
    ppg_proj = projections.project_elements_next_gws(
        elements=avail, fixtures=fixtures, teams_short_map=teams_short,
        gw_start=gw_start, horizon_gws=horizon)
    xg_proj = squad_draft_xg.xg_projection(
        avail, fixtures, teams_short, gw_start, horizon,
        blend_weight=1.0, ppg_proj=ppg_proj)
    return ppg_proj, xg_proj


def _squad_ids(res):
    return {int(r["player_id"]) for r in res.get("squad", [])}


def _ids_by_pos(res):
    out = {}
    for r in res.get("squad", []):
        out.setdefault(r.get("pos"), set()).add(int(r["player_id"]))
    return out


def _names(res):
    return {int(r["player_id"]): r.get("web_name") for r in res.get("squad", [])}


def run(bootstrap, fixtures_raw, horizon, budget):
    _patch_elements_keep_for_xg_basis()

    print("=" * 78)
    print("PROJECTION-BASIS DIVERGENCE DIAGNOSTIC (ppg vs xg)")
    print("*** NOT an accuracy backtest *** -- shows how far the two bases")
    print("disagree on the CURRENT candidate pool. A rigorous walk-forward")
    print("accuracy backtest (MAE / captain hit-rate / top-N precision vs")
    print("actual GW results) is a follow-on sub-project -- see")
    print("docs/superpowers/specs/2026-07-23-squad-picker-page-design.md")
    print("## Backtest gate. `ppg` remains the default projection_basis.")
    print("=" * 78)

    base_params = {"horizon_gws": horizon, "budget_m": budget}
    res_ppg = squad_draft.build_squad(bootstrap, fixtures_raw, {**base_params, "projection_basis": "ppg"})
    res_xg = squad_draft.build_squad(bootstrap, fixtures_raw, {**base_params, "projection_basis": "xg"})

    if not res_ppg["ok"] or not res_xg["ok"]:
        print(f"\nBUILD FAILED: ppg ok={res_ppg['ok']} reason={res_ppg.get('reason')} | "
              f"xg ok={res_xg['ok']} reason={res_xg.get('reason')}")
        return 1

    gw_start = res_ppg["gw_start"]
    horizon = res_ppg["horizon_gws"]
    print(f"\nGW{gw_start}-{gw_start + horizon - 1} (horizon {horizon}), budget £{budget:.1f}m\n")

    ids_ppg, ids_xg = _squad_ids(res_ppg), _squad_ids(res_xg)
    shared = ids_ppg & ids_xg
    print(f"Squad overlap: {len(shared)}/15 players shared between the ppg squad and the xg squad")

    pos_ppg, pos_xg = _ids_by_pos(res_ppg), _ids_by_pos(res_xg)
    names_ppg, names_xg = _names(res_ppg), _names(res_xg)
    print("\nDiffering picks per position:")
    for pos in ["GKP", "DEF", "MID", "FWD"]:
        only_ppg = sorted(pos_ppg.get(pos, set()) - pos_xg.get(pos, set()))
        only_xg = sorted(pos_xg.get(pos, set()) - pos_ppg.get(pos, set()))
        if not only_ppg and not only_xg:
            print(f"  {pos}: identical")
            continue
        ppg_names = ", ".join(names_ppg.get(i, str(i)) for i in only_ppg) or "-"
        xg_names = ", ".join(names_xg.get(i, str(i)) for i in only_xg) or "-"
        print(f"  {pos}: ppg-only=[{ppg_names}]  xg-only=[{xg_names}]")

    cap_ppg, cap_xg = res_ppg["captain_player_id"], res_xg["captain_player_id"]
    agree = cap_ppg == cap_xg
    print(f"\nCaptain agreement: {'YES' if agree else 'NO'} "
          f"(ppg={names_ppg.get(cap_ppg, cap_ppg)!r} id={cap_ppg}, "
          f"xg={names_xg.get(cap_xg, cap_xg)!r} id={cap_xg})")

    print("\nHorizon-total projected points:")
    print(f"  ppg: {res_ppg['projected_points']['horizon_total']:.2f}")
    print(f"  xg:  {res_xg['projected_points']['horizon_total']:.2f}")

    # --- projection-level divergence over the full shared candidate pool ---
    print("\n" + "-" * 78)
    print("Projection-level divergence (full candidate pool, not just the two 15-man squads)")
    p = {**squad_draft.DEFAULT_PARAMS, **base_params}
    avail, fixtures, teams_short, gw_start2 = _prepare_pool(bootstrap, fixtures_raw, p)
    horizon_clamped = max(1, min(8, int(p["horizon_gws"])))
    ppg_proj, xg_proj = _build_both_projections(avail, fixtures, teams_short, gw_start2, horizon_clamped)

    merged = ppg_proj[["id", "web_name", "pos", "xpts_horizon"]].merge(
        xg_proj[["id", "xpts_horizon"]], on="id", suffixes=("_ppg", "_xg"))
    n = len(merged)
    corr = _spearman(merged["xpts_horizon_ppg"], merged["xpts_horizon_xg"])
    method = "scipy.stats.spearmanr" if _HAVE_SCIPY else "pandas .rank() + Pearson-on-ranks (scipy unavailable)"
    print(f"Candidate pool size: {n} players")
    print(f"Spearman rank correlation of xpts_horizon (ppg vs xg): {corr:.3f}  [{method}]")

    top15_ppg = set(merged.sort_values("xpts_horizon_ppg", ascending=False).head(15)["id"])
    top15_xg = set(merged.sort_values("xpts_horizon_xg", ascending=False).head(15)["id"])
    print(f"Top-15-by-xpts overlap: {len(top15_ppg & top15_xg)}/15")

    print("\n" + "=" * 78)
    print("Reminder: this is a divergence snapshot on the CURRENT pool, not a")
    print("validated accuracy comparison. `ppg` remains the default basis;")
    print("`xg`/`blend` stay opt-in until a walk-forward accuracy backtest wins.")
    print("=" * 78)
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Divergence diagnostic: ppg vs xg projection basis on the live pool "
                     "(NOT an accuracy backtest).")
    ap.add_argument("--horizon", type=int, default=5, help="planning horizon in GWs")
    ap.add_argument("--budget", type=float, default=100.0)
    args = ap.parse_args()

    boot = fpl_client.get_bootstrap()
    raw_fx = fpl_client.get_fixtures()
    return run(boot, raw_fx, args.horizon, args.budget)


if __name__ == "__main__":
    raise SystemExit(main())
