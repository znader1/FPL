"""
Chip recommendation engine — Layer 1 (deterministic, no LLM).

Scans candidate gameweeks for each chip type and ranks them by expected value.
Returns structured recommendations with reasoning facts attached.

The LLM explainer (Layer 3) can later wrap this output into natural language.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional
import pandas as pd
import numpy as np
from src import config

ALL_CHIPS = ["wildcard", "free_hit", "bench_boost", "triple_captain"]

# FPL API chip identifiers → canonical names used throughout this repo.
FPL_CHIP_NAME_MAP = {
    "wildcard": "wildcard",
    "freehit": "free_hit",
    "bboost": "bench_boost",
    "3xc": "triple_captain",
}


def effective_min_ev(chip, target_gw, expires_gw):
    """Play/hold threshold for `chip` at `target_gw`, with use-it-or-lose-it decay.

    Outside the ramp the base threshold applies; inside the last
    CHIP_PLAN_EXPIRY_RAMP_GWS gameweeks before expiry it decays linearly to 0,
    so a modest-EV chip gets recommended rather than expiring unused.
    """
    base = float(getattr(config, "CHIP_PLAN_MIN_EV", {}).get(chip, 0.0))
    ramp = int(getattr(config, "CHIP_PLAN_EXPIRY_RAMP_GWS", 5))
    gws_left = max(0, int(expires_gw) - int(target_gw))
    if ramp <= 0 or gws_left >= ramp:
        return base
    return base * gws_left / ramp


def chip_windows(chips_played, current_gw, phase_split_gw=None, season_end_gw=None):
    """Availability + expiry per chip, honoring the two-per-season phase rule.

    chips_played: raw `history["chips"]` list from the FPL entry history API.
    A chip logged in current_gw itself still counts as available — we advise
    FOR current_gw, so only strictly-earlier plays consume the chip.
    """
    split = int(phase_split_gw or getattr(config, "CHIP_PLAN_PHASE_SPLIT_GW", 19))
    end = int(season_end_gw or getattr(config, "CHIP_PLAN_SEASON_END_GW", 38))
    current_gw = int(current_gw)
    in_phase_1 = current_gw <= split
    lo, hi = (1, split) if in_phase_1 else (split + 1, end)

    used = set()
    for c in chips_played or []:
        gw = int(c.get("event", 0) or 0)
        name = FPL_CHIP_NAME_MAP.get(str(c.get("name", "")).lower())
        if name and lo <= gw <= hi and gw < current_gw:
            used.add(name)

    return {
        chip: {
            "available": chip not in used,
            "half": 1 if in_phase_1 else 2,
            "expires_gw": hi,
        }
        for chip in ALL_CHIPS
    }


# Default formation bounds (matches backtest_season.py)
FORMATION_BOUNDS = {"GKP": (1, 1), "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3)}
SQUAD_SHAPE = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}


@dataclass
class ChipRecommendation:
    chip: str               # "wildcard" | "free_hit" | "bench_boost" | "triple_captain"
    gw: int                 # target gameweek
    expected_value: float   # expected points uplift vs not playing this chip
    confidence: float       # 0..1
    reasoning: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "chip": self.chip,
            "gw": self.gw,
            "expected_value": round(float(self.expected_value), 2),
            "confidence": round(float(self.confidence), 2),
            "reasoning": list(self.reasoning),
            "risks": list(self.risks),
        }


# ---------- helpers ----------

def _pick_best_xi(squad_with_xpts: pd.DataFrame) -> pd.DataFrame:
    """Greedy formation-respecting starting XI. squad must have cols: pos, xpts."""
    s = squad_with_xpts.sort_values("xpts", ascending=False).copy()

    starters = []
    for pos, (lo, _) in FORMATION_BOUNDS.items():
        pool = s[s["pos"] == pos].head(lo)
        starters.append(pool)
    starting = pd.concat(starters, ignore_index=False)

    remaining = 11 - len(starting)
    bench_caps = {pos: hi - lo for pos, (lo, hi) in FORMATION_BOUNDS.items()}
    bench_used = {pos: 0 for pos in bench_caps}
    candidates = s[~s.index.isin(starting.index) & (s["pos"] != "GKP")]
    extra = []
    for idx, row in candidates.sort_values("xpts", ascending=False).iterrows():
        if remaining <= 0:
            break
        pos = row["pos"]
        if bench_used[pos] < bench_caps.get(pos, 0):
            extra.append(idx)
            bench_used[pos] += 1
            remaining -= 1

    return pd.concat([starting, s.loc[extra]], ignore_index=False)


def _pick_captain_xpts(starting_xi: pd.DataFrame) -> float:
    """Return xPts of the best captain candidate (favor FWD/MID slightly)."""
    if starting_xi.empty:
        return 0.0
    cap_mult = {"FWD": 1.16, "MID": 1.12, "DEF": 0.92, "GKP": 0.70}
    s = starting_xi.copy()
    s["_score"] = s["xpts"] * s["pos"].map(cap_mult).fillna(1.0)
    return float(s.sort_values("_score", ascending=False).iloc[0]["xpts"])


def team_fixture_counts(fixtures, gw):
    """Team id → fixture count in `gw`. Missing id means a blank GW for that team."""
    if fixtures is None or fixtures.empty or "event" not in fixtures.columns:
        return {}
    f = fixtures[fixtures["event"] == int(gw)]
    counts: dict[int, int] = {}
    for col in ("team_h", "team_a"):
        if col not in f.columns:
            continue
        for t in f[col].dropna().tolist():
            counts[int(t)] = counts.get(int(t), 0) + 1
    return counts


# ---------- chip scorers ----------

def score_triple_captain(
    squad: pd.DataFrame,
    gw_projections: dict[int, pd.DataFrame],
    candidate_gws: list[int],
) -> list[ChipRecommendation]:
    """
    For each candidate GW, find the best captain in the squad and compute the
    TC uplift = captain_xpts × 1 (the EXTRA multiplier beyond normal captaincy).
    """
    recs = []
    for gw in candidate_gws:
        market = gw_projections.get(gw)
        if market is None or market.empty:
            continue
        squad_with_xpts = squad.merge(
            market[["player_id", "xpts", "fixture_count"]], on="player_id", how="left"
        )
        squad_with_xpts["xpts"] = squad_with_xpts["xpts"].fillna(0)
        squad_with_xpts["fixture_count"] = squad_with_xpts["fixture_count"].fillna(0).astype(int)

        xi = _pick_best_xi(squad_with_xpts)
        best_cap_xpts = _pick_captain_xpts(xi)

        # TC value: extra multiplier vs normal capt (captain is already x2, TC makes it x3)
        # So uplift = captain_xpts (the third multiplier on top of normal)
        uplift = best_cap_xpts

        # Detect DGW for the captain — bigger TC value if captain plays twice
        captain_row = xi.sort_values("xpts", ascending=False).iloc[0]
        is_dgw = int(captain_row.get("fixture_count", 1)) >= 2

        reasoning = []
        risks = []
        if is_dgw:
            reasoning.append(f"DGW for captain ({captain_row['name']}) — 2 fixtures")
        else:
            reasoning.append(f"Single fixture for captain ({captain_row['name']})")
        reasoning.append(f"Captain projected xPts: {best_cap_xpts:.1f}")

        if best_cap_xpts < 5.0:
            risks.append("Captain projection below 5 pts — high blank risk")

        recs.append(ChipRecommendation(
            chip="triple_captain",
            gw=gw,
            expected_value=uplift,
            confidence=0.6 + (0.3 if is_dgw else 0) + (0.1 if best_cap_xpts > 8 else 0),
            reasoning=reasoning,
            risks=risks,
        ))
    return recs


def score_bench_boost(
    squad: pd.DataFrame,
    gw_projections: dict[int, pd.DataFrame],
    candidate_gws: list[int],
) -> list[ChipRecommendation]:
    """
    BB value = sum of xPts of bench players (non-starting 4).
    Bigger when many starters double or the bench has decent players.
    """
    recs = []
    for gw in candidate_gws:
        market = gw_projections.get(gw)
        if market is None or market.empty:
            continue
        squad_with_xpts = squad.merge(
            market[["player_id", "xpts", "fixture_count"]], on="player_id", how="left"
        )
        squad_with_xpts["xpts"] = squad_with_xpts["xpts"].fillna(0)
        squad_with_xpts["fixture_count"] = squad_with_xpts["fixture_count"].fillna(0).astype(int)

        xi = _pick_best_xi(squad_with_xpts)
        bench = squad_with_xpts[~squad_with_xpts.index.isin(xi.index)]
        bench_value = float(bench["xpts"].sum())

        # Count how many squad players have a DGW
        n_doubling = int((squad_with_xpts["fixture_count"] >= 2).sum())

        reasoning = [
            f"Bench projected total: {bench_value:.1f} xPts",
            f"{n_doubling}/15 squad players have a fixture this GW",
        ]
        if n_doubling >= 13:
            reasoning.append(f"{n_doubling} squad players doubling — strong BB candidate")

        risks = []
        players_with_no_fixture = int((squad_with_xpts["fixture_count"] == 0).sum())
        if players_with_no_fixture > 0:
            risks.append(f"{players_with_no_fixture} squad players have no fixture (blank)")

        recs.append(ChipRecommendation(
            chip="bench_boost",
            gw=gw,
            expected_value=bench_value,
            confidence=0.5 + (0.3 if n_doubling >= 13 else 0) + (0.2 if bench_value > 15 else 0),
            reasoning=reasoning,
            risks=risks,
        ))
    return recs


def score_free_hit(
    squad: pd.DataFrame,
    gw_projections: dict[int, pd.DataFrame],
    candidate_gws: list[int],
    budget_m: float,
) -> list[ChipRecommendation]:
    """
    FH value = (best possible XI for that GW within budget) - (your normal XI for that GW)
    Bigger when many of your players are blanking (BGW) or you can upgrade significantly.
    """
    recs = []
    for gw in candidate_gws:
        market = gw_projections.get(gw)
        if market is None or market.empty:
            continue

        # Your normal XI value this GW
        squad_with_xpts = squad.merge(
            market[["player_id", "xpts", "fixture_count"]], on="player_id", how="left"
        )
        squad_with_xpts["xpts"] = squad_with_xpts["xpts"].fillna(0)
        normal_xi = _pick_best_xi(squad_with_xpts)
        normal_xi_xpts = float(normal_xi["xpts"].sum())

        # Best possible FH XI (within budget = current squad value + bank)
        # Simple proxy: top players by xPts respecting formation, ignoring real budget
        # constraints since FH is a one-week reset
        market_with_xi = _pick_best_xi(market)
        fh_xi_xpts = float(market_with_xi["xpts"].sum())

        uplift = max(0, fh_xi_xpts - normal_xi_xpts)

        # Detect BGW: many squad players with no fixture
        n_blanking = int((squad_with_xpts["fixture_count"] == 0).sum())

        reasoning = [
            f"Your normal XI projected: {normal_xi_xpts:.1f} xPts",
            f"Best FH XI projected: {fh_xi_xpts:.1f} xPts",
            f"FH uplift: +{uplift:.1f} xPts",
        ]
        if n_blanking >= 3:
            reasoning.append(f"{n_blanking} squad players blanking — strong FH candidate")

        risks = []
        if uplift < 5:
            risks.append("Marginal uplift — consider holding FH for a worse week")

        recs.append(ChipRecommendation(
            chip="free_hit",
            gw=gw,
            expected_value=uplift,
            confidence=0.4 + (0.4 if n_blanking >= 3 else 0) + (0.2 if uplift > 15 else 0),
            reasoning=reasoning,
            risks=risks,
        ))
    return recs


def score_wildcard(
    squad: pd.DataFrame,
    gw_projections: dict[int, pd.DataFrame],
    candidate_gws: list[int],
    horizon: int = 4,
) -> list[ChipRecommendation]:
    """
    WC value = cumulative xPts gain over next `horizon` GWs from replacing the
    current squad with the optimal market squad (no transfer cost).
    """
    recs = []
    for gw in candidate_gws:
        normal_total = 0.0
        wc_total = 0.0
        future_gws = list(range(gw, gw + horizon))
        valid_count = 0

        for fgw in future_gws:
            market = gw_projections.get(fgw)
            if market is None or market.empty:
                continue
            valid_count += 1
            squad_with_xpts = squad.merge(
                market[["player_id", "xpts"]], on="player_id", how="left"
            )
            squad_with_xpts["xpts"] = squad_with_xpts["xpts"].fillna(0)
            normal_xi = _pick_best_xi(squad_with_xpts)
            normal_total += float(normal_xi["xpts"].sum())

            # WC squad: top 15 in market (very rough — ignores budget for now)
            wc_xi = _pick_best_xi(market)
            wc_total += float(wc_xi["xpts"].sum())

        if valid_count == 0:
            continue

        uplift = max(0, wc_total - normal_total)

        reasoning = [
            f"Your squad projected over next {valid_count} GWs: {normal_total:.0f} xPts",
            f"Optimal WC squad over next {valid_count} GWs: {wc_total:.0f} xPts",
            f"WC uplift: +{uplift:.0f} xPts over horizon",
        ]
        if uplift > 30:
            reasoning.append("Large gap to optimal — squad needs reset")

        risks = []
        if uplift < 15:
            risks.append("Small uplift — hold WC for a better moment")

        recs.append(ChipRecommendation(
            chip="wildcard",
            gw=gw,
            expected_value=uplift,
            confidence=0.5 + min(0.4, uplift / 60),
            reasoning=reasoning,
            risks=risks,
        ))
    return recs


# ---------- top-level entry point ----------

def recommend_chips(
    squad: pd.DataFrame,
    current_gw: int,
    gw_projections: dict[int, pd.DataFrame],
    chips_remaining: list[str],
    gws_ahead: int = 10,
    bank_m: float = 0.0,
) -> list[ChipRecommendation]:
    """
    Main entry point. Returns ranked list of (chip, gw, value, reasoning) for
    the chips still available.

    squad: DataFrame with player_id, name, pos, team, price_m
    gw_projections: dict mapping gw -> market DataFrame (player_id, xpts, fixture_count, ...)
    chips_remaining: list of chip names still available
    """
    end_gw = current_gw + gws_ahead
    candidate_gws = [g for g in range(current_gw, end_gw + 1) if g in gw_projections]

    all_recs = []
    if "triple_captain" in chips_remaining:
        all_recs.extend(score_triple_captain(squad, gw_projections, candidate_gws))
    if "bench_boost" in chips_remaining:
        all_recs.extend(score_bench_boost(squad, gw_projections, candidate_gws))
    if "free_hit" in chips_remaining:
        all_recs.extend(score_free_hit(squad, gw_projections, candidate_gws, bank_m))
    if "wildcard" in chips_remaining:
        all_recs.extend(score_wildcard(squad, gw_projections, candidate_gws, horizon=4))

    # Sort by expected value (descending), filter out zero-value
    return sorted(
        [r for r in all_recs if r.expected_value > 0],
        key=lambda r: r.expected_value,
        reverse=True,
    )


def plan_chips_smart(
    squad_at_start: pd.DataFrame,
    start_gw: int,
    end_gw: int,
    gw_projections: dict[int, pd.DataFrame],
    chips_available: Optional[list[str]] = None,
) -> dict[str, int]:
    """
    Pre-plan all chips for the season window. Returns {chip_name: best_gw}.
    Uses one-shot ranking — picks the highest-value GW for each chip independently.
    Real FPL constraints (Phase 1/2, can't double-play same GW) are NOT enforced here.
    """
    if chips_available is None:
        chips_available = ["wildcard", "free_hit", "bench_boost", "triple_captain"]

    plan = {}
    used_gws = set()

    # Rank all chip options across the window
    all_recs = recommend_chips(
        squad=squad_at_start,
        current_gw=start_gw,
        gw_projections=gw_projections,
        chips_remaining=chips_available,
        gws_ahead=end_gw - start_gw,
    )

    # Greedy: assign best GW to each chip, avoiding same-GW conflicts
    for chip in chips_available:
        chip_recs = [r for r in all_recs if r.chip == chip and r.gw not in used_gws]
        if not chip_recs:
            continue
        best = chip_recs[0]
        plan[chip] = best.gw
        used_gws.add(best.gw)

    return plan
