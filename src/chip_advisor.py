"""
Chip recommendation engine — Layer 1 (deterministic, no LLM).

Scans candidate gameweeks for each chip type and ranks them by expected value.
Returns structured recommendations with reasoning facts attached.

The LLM explainer (Layer 3) can later wrap this output into natural language.
"""
from __future__ import annotations
import logging
import math
from dataclasses import dataclass, field
from typing import Callable, Optional
import pandas as pd
import numpy as np
from src import config
from src import chip_distribution, european

logger = logging.getLogger(__name__)

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
    base = float(config.CHIP_PLAN_MIN_EV.get(chip, 0.0))
    ramp = int(config.CHIP_PLAN_EXPIRY_RAMP_GWS)
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
    split = int(phase_split_gw or config.CHIP_PLAN_PHASE_SPLIT_GW)
    end = int(season_end_gw or config.CHIP_PLAN_SEASON_END_GW)
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
    haul_prob: float | None = None   # TC only: P(captain gets 2+ goal involvements)
    captain_team: str | None = None  # TC only: captain's team — internal, not emitted by to_dict()
    pmf: np.ndarray | None = None    # TC/BB: distribution of the chip's extra points — internal
    # Share of full xPts `pmf` leaves out (bonus/saves/conceded). A bar quoted
    # in full xPts has to be scaled by (1 - this) to land on the pmf's axis.
    pmf_share: float = 0.0
    # False for a bench-4 sum: RETURN_AT/HAUL_AT/BLANK_AT are per-player.
    pmf_thresholds: bool = True

    def to_dict(self) -> dict:
        out = {
            "chip": self.chip,
            "gw": self.gw,
            "expected_value": round(float(self.expected_value), 2),
            "confidence": round(float(self.confidence), 2),
            "reasoning": list(self.reasoning),
            "risks": list(self.risks),
        }
        if self.haul_prob is not None:
            out["haul_prob"] = round(float(self.haul_prob), 3)
        return out


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


def _pick_captain_row(starting_xi: pd.DataFrame):
    """Row of the best captain candidate (position-weighted, favor FWD/MID)."""
    if starting_xi.empty:
        return None
    cap_mult = {"FWD": 1.16, "MID": 1.12, "DEF": 0.92, "GKP": 0.70}
    s = starting_xi.copy()
    s["_score"] = s["xpts"] * s["pos"].map(cap_mult).fillna(1.0)
    return s.sort_values("_score", ascending=False).iloc[0]


def _pick_captain_xpts(starting_xi: pd.DataFrame) -> float:
    """Return xPts of the best captain candidate (favor FWD/MID slightly)."""
    row = _pick_captain_row(starting_xi)
    return 0.0 if row is None else float(row["xpts"])


def _clip_market_xpts(market: pd.DataFrame, col: str = "xpts") -> pd.DataFrame:
    """Clamp an absurd single-GW xPts outlier before it feeds a dream-squad
    (WC/FH) optimizer build or comparison total.

    Upstream projections have an outlier bug (tracked separately) where a
    handful of cheap players spike into double digits for one GW — a live
    spot-check surfaced a cluster of Hull players like this, including a
    4.5m GKP projecting ~13.5. Left unclamped, a single such row can dominate
    an optimizer's shape/budget search and inflate the whole comparison.

    This is a stopgap on the MARKET side of a chip comparison only — the
    user's own squad valuation (`normal_total` / `normal_xi_xpts`) is never
    clamped, since that's a real read of what the user's squad is worth, not
    a dream-squad search over noisy candidates. Caps are position-aware when
    a `pos` column is present, otherwise falls back to a flat clamp.
    """
    if market is None or col not in market.columns:
        return market
    flat = float(config.CHIP_PLAN_XPTS_CLAMP)
    by_pos = config.CHIP_PLAN_XPTS_CLAMP_BY_POS
    out = market.copy()
    xp = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    if by_pos and "pos" in out.columns:
        caps = out["pos"].map(by_pos).fillna(flat).astype(float)
        out[col] = np.minimum(xp, caps)
    else:
        out[col] = xp.clip(upper=flat)
    return out


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
    xgi_per90: dict[int, float] | None = None,
    team_difficulty_by_gw: dict[int, dict[str, float]] | None = None,
    player_priors: dict[int, dict] | None = None,
    euro_by_gw: dict[int, dict[str, dict]] | None = None,
) -> list[ChipRecommendation]:
    """
    For each candidate GW, find the best captain in the squad and compute the
    TC uplift = captain_xpts × 1 (the EXTRA multiplier beyond normal captaincy).

    With `player_priors` the captain's per-GW points pmf is attached (the TC
    gain distribution); with `euro_by_gw` a captain in a European week gets a
    rotation/fatigue risk line and a confidence haircut.
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
        captain_row = _pick_captain_row(xi)
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

        haul_prob = None
        if xgi_per90:
            per90 = float(xgi_per90.get(int(captain_row["player_id"]), 0.0) or 0.0)
            if per90 > 0:
                dmap = (team_difficulty_by_gw or {}).get(gw) or {}
                d = dmap.get(captain_row.get("team"))
                mult_map = config.CHIP_PLAN_TC_DIFF_MULT
                mult = float(mult_map.get(int(round(d)), 1.0)) if d is not None else 1.0
                n_fix = max(1, int(captain_row.get("fixture_count", 1)))
                lam = per90 * mult * n_fix
                haul_prob = 1.0 - math.exp(-lam) * (1.0 + lam)
                reasoning.append(
                    f"~{haul_prob:.0%} chance of a 2+ goal-involvement haul")

        confidence = 0.6 + (0.3 if is_dgw else 0) + (0.1 if best_cap_xpts > 8 else 0)

        euro = (euro_by_gw or {}).get(gw, {}).get(captain_row.get("team"))
        if euro:
            confidence *= float(config.CHIP_PLAN_EURO_CONFIDENCE_MULT)
            risks.append(_euro_line(captain_row["name"], captain_row.get("team"), euro, gw))

        pmf = None
        pmf_share = 0.0
        if player_priors:
            dmap = (team_difficulty_by_gw or {}).get(gw) or {}
            pmf = chip_distribution.player_gw_pmf(
                pos=captain_row["pos"], xpts=best_cap_xpts,
                prior=player_priors.get(int(captain_row["player_id"])),
                n_fixtures=int(captain_row.get("fixture_count", 1)),
                difficulty=dmap.get(captain_row.get("team")),
            )
            if pmf is not None:
                pmf_share = chip_distribution.continuous_share(
                    [(captain_row["pos"], best_cap_xpts)])
                d = chip_distribution.summarize(pmf)
                reasoning.append(
                    f"{d['p_return']:.0%} chance the captain returns (6+), "
                    f"{d['p_haul']:.0%} of a 10+ haul, {d['p_blank']:.0%} of a blank")

        recs.append(ChipRecommendation(
            chip="triple_captain",
            gw=gw,
            expected_value=uplift,
            confidence=confidence,
            reasoning=reasoning,
            risks=risks,
            haul_prob=haul_prob,
            captain_team=captain_row.get("team"),
            pmf=pmf,
            pmf_share=pmf_share,
        ))
    return recs


def _euro_line(name, team, info, gw):
    comp = european.COMPETITION_LABELS.get(info.get("competition"), "Europe")
    when = info.get("when")
    if when == "before":
        days = info.get("days_before")
        tail = f"{days} days before GW{gw}" if days is not None else f"in the midweek before GW{gw}"
        return f"{name} ({team}) plays in the {comp} {tail} — fatigue / late rotation risk"
    if when == "after":
        return f"{name} ({team}) has a {comp} tie right after GW{gw} — rested-in-the-league risk"
    return f"{name} ({team}) is sandwiched between {comp} ties around GW{gw} — rotation risk"


def score_bench_boost(
    squad: pd.DataFrame,
    gw_projections: dict[int, pd.DataFrame],
    candidate_gws: list[int],
    player_priors: dict[int, dict] | None = None,
    euro_by_gw: dict[int, dict[str, dict]] | None = None,
    team_difficulty_by_gw: dict[int, dict[str, float]] | None = None,
) -> list[ChipRecommendation]:
    """
    BB value = sum of xPts of bench players (non-starting 4).
    Bigger when many starters double or the bench has decent players.

    With `player_priors` the bench-4 sum's pmf (independent convolution) is
    attached; with `euro_by_gw` bench players in European weeks are named
    and, past CHIP_PLAN_EURO_BB_MIN_BENCH of them, BB confidence is cut.
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
            f"{n_doubling}/15 squad players have a double fixture this GW",
        ]
        if n_doubling >= 13:
            reasoning.append(f"{n_doubling} squad players doubling — strong BB candidate")

        risks = []
        players_with_no_fixture = int((squad_with_xpts["fixture_count"] == 0).sum())
        if players_with_no_fixture > 0:
            risks.append(f"{players_with_no_fixture} squad players have no fixture (blank)")

        confidence = 0.5 + (0.3 if n_doubling >= 13 else 0) + (0.2 if bench_value > 15 else 0)

        euro_gw = (euro_by_gw or {}).get(gw) or {}
        exposed = [r for _, r in bench.iterrows() if r["team"] in euro_gw]
        if exposed:
            names = ", ".join(str(r["name"]) for r in exposed[:4])
            risks.append(
                f"{len(exposed)} of your bench 4 are in European weeks around GW{gw} ({names}) — rotation risk")
            if len(exposed) >= int(config.CHIP_PLAN_EURO_BB_MIN_BENCH):
                confidence *= float(config.CHIP_PLAN_EURO_CONFIDENCE_MULT)
        n_squad_euro = int(squad_with_xpts["team"].isin(list(euro_gw)).sum()) if euro_gw else 0
        if n_squad_euro:
            reasoning.append(f"{n_squad_euro}/15 squad players in European weeks around GW{gw}")

        pmf = None
        pmf_share = 0.0
        if player_priors:
            dmap = (team_difficulty_by_gw or {}).get(gw) or {}
            parts = [
                chip_distribution.player_gw_pmf(
                    pos=r["pos"], xpts=float(r["xpts"]),
                    prior=player_priors.get(int(r["player_id"])),
                    n_fixtures=int(r.get("fixture_count", 1)),
                    difficulty=dmap.get(r.get("team")),
                )
                for _, r in bench.iterrows()
            ]
            if parts and all(p is not None for p in parts):
                pmf = chip_distribution.convolve(parts)
                pmf_share = chip_distribution.continuous_share(
                    [(r["pos"], float(r["xpts"])) for _, r in bench.iterrows()])
                d = chip_distribution.summarize(pmf, player_thresholds=False)
                band = f"{d['p80_low']}–{d['p80_high']}{'+' if d.get('p80_open') else ''}"
                reasoning.append(
                    f"Bench most likely {d['modal']} pts (80% band {band})")

        recs.append(ChipRecommendation(
            chip="bench_boost",
            gw=gw,
            expected_value=bench_value,
            confidence=confidence,
            reasoning=reasoning,
            risks=risks,
            pmf=pmf,
            pmf_share=pmf_share,
            pmf_thresholds=False,   # the bench-4 sum is not one player
        ))
    return recs


def score_free_hit(
    squad: pd.DataFrame,
    gw_projections: dict[int, pd.DataFrame],
    candidate_gws: list[int],
    budget_m: float,
    team_difficulty_by_gw: dict[int, dict[str, float]] | None = None,
) -> list[ChipRecommendation]:
    """
    FH value = (best possible XI for that GW within budget) - (your normal XI for that GW)
    Bigger when many of your players are blanking (BGW) or you can upgrade significantly.

    Gated behind CHIP_PLAN_FH_MIN_BLANKING: FH is a blank-GW tool in real play,
    not a weekly "upgrade my squad" button — an ordinary week (few/no blanks)
    is suppressed here even when the raw uplift looks large, since a single-week
    optimal XI will beat almost any real squad built for multi-week value.
    """
    recs = []
    for gw in candidate_gws:
        market = gw_projections.get(gw)
        if market is None or market.empty:
            continue

        # Your normal XI value this GW — never clamped, this is a real read of
        # the user's own squad, not a dream-squad search.
        squad_with_xpts = squad.merge(
            market[["player_id", "xpts", "fixture_count"]], on="player_id", how="left"
        )
        squad_with_xpts["xpts"] = squad_with_xpts["xpts"].fillna(0)
        normal_xi = _pick_best_xi(squad_with_xpts)
        normal_xi_xpts = float(normal_xi["xpts"].sum())

        # Dream-squad side: clamp an absurd single-GW projection outlier before
        # it can feed the optimizer build or the final comparison total.
        clamped_market = _clip_market_xpts(market, "xpts")

        # Best FH squad within budget (squad value + bank). Falls back to the
        # unbudgeted proxy only if the optimizer can't build a legal squad.
        from src import optimizer as _optimizer
        fh_xi_xpts = None
        fallback_reason = None
        try:
            # build_chip_squad expects the raw elements_all schema (id, numeric
            # team) — the gw_projections market uses player_id + team labels.
            # Bridge the two: rename the id column and encode team labels as
            # integers (team caps only need a stable grouping key, not the
            # real FPL team id).
            market_for_optimizer = clamped_market.rename(columns={"player_id": "id"}).copy()
            if "team" in market_for_optimizer.columns:
                market_for_optimizer["team"] = pd.factorize(market_for_optimizer["team"])[0]
            built = _optimizer.build_chip_squad(market_for_optimizer, score_col="xpts", budget_m=budget_m)
            if built.get("ok") and built.get("squad_df") is not None:
                fh_xi = _pick_best_xi(built["squad_df"])
                fh_xi_xpts = float(fh_xi["xpts"].sum())
            else:
                fallback_reason = built.get("reason", "optimizer returned not-ok")
        except Exception as e:  # noqa: BLE001 - degrade to unbudgeted proxy
            fallback_reason = str(e)

        fallback_used = fh_xi_xpts is None
        if fallback_used:
            logger.warning(
                "score_free_hit: budget-aware build failed for GW%s (%s) — "
                "falling back to unbudgeted top-11 proxy", gw, fallback_reason,
            )
            market_with_xi = _pick_best_xi(clamped_market)
            fh_xi_xpts = float(market_with_xi["xpts"].sum())

        uplift = max(0, fh_xi_xpts - normal_xi_xpts)

        # Detect BGW: many squad players with no fixture
        n_blanking = int((squad_with_xpts["fixture_count"] == 0).sum())

        # Tough-pileup OR-path: many squad players facing hard fixtures this GW
        n_tough = 0
        if team_difficulty_by_gw:
            dmap = team_difficulty_by_gw.get(gw) or {}
            tough_at = float(config.CHIP_PLAN_FH_TOUGH_DIFFICULTY)
            n_tough = int(sum(
                1 for t in squad_with_xpts["team"].tolist()
                if dmap.get(t) is not None and float(dmap[t]) >= tough_at))

        min_blanking = int(config.CHIP_PLAN_FH_MIN_BLANKING)
        min_tough = int(config.CHIP_PLAN_FH_MIN_TOUGH)
        blank_trigger = n_blanking >= min_blanking
        tough_trigger = n_tough >= min_tough
        if not blank_trigger and not tough_trigger:
            continue  # ordinary week — hold FH for a blank- or tough-heavy GW

        reasoning = [
            f"Your normal XI projected: {normal_xi_xpts:.1f} xPts",
            f"Best FH XI projected: {fh_xi_xpts:.1f} xPts"
            + (" [unbudgeted proxy — optimizer fallback]" if fallback_used else " (budget-constrained)"),
            f"FH uplift: +{uplift:.1f} xPts",
        ]
        if blank_trigger:
            reasoning.append(f"{n_blanking} squad players blanking — strong FH candidate")
        if tough_trigger:
            tough_at = float(config.CHIP_PLAN_FH_TOUGH_DIFFICULTY)
            reasoning.append(
                f"{n_tough} of your 15 face difficulty ≥{tough_at:.1f} in GW{gw}")

        risks = []
        if uplift < 5:
            risks.append("Marginal uplift — consider holding FH for a worse week")

        recs.append(ChipRecommendation(
            chip="free_hit",
            gw=gw,
            expected_value=uplift,
            confidence=0.4 + (0.4 if (blank_trigger or tough_trigger) else 0)
                       + (0.2 if uplift > 15 else 0),
            reasoning=reasoning,
            risks=risks,
        ))
    return recs


def score_wildcard(
    squad: pd.DataFrame,
    gw_projections: dict[int, pd.DataFrame],
    candidate_gws: list[int],
    horizon: int = 4,
    transfer_plan_net_gain: float = 0.0,
    budget_m: float | None = None,
) -> list[ChipRecommendation]:
    """
    WC value = cumulative xPts gain over next `horizon` GWs from replacing the
    current squad with the optimal squad, respecting budget + team caps.

    Builds one draft squad per candidate GW: an `xpts_horizon` score (each
    future GW's xPts, clamp-protected, summed per player_id) feeds
    `optimizer.build_chip_squad` via the same schema bridge `score_free_hit`
    uses (rename player_id->id, factorize team labels into a stable team-cap
    grouping key). The built 15 is then re-scored week-by-week — best XI
    against each future GW's own market — exactly like the "your squad" side,
    so the two totals are apples-to-apples.

    Falls back to the old unbudgeted top-15-in-market proxy (with a warning
    and a distinguishable reason string in `reasoning`) only if the optimizer
    can't build a legal squad.
    """
    from src import optimizer as _optimizer
    recs = []
    for gw in candidate_gws:
        future_gws = [
            g for g in range(gw, gw + horizon)
            if gw_projections.get(g) is not None and not gw_projections[g].empty
        ]
        if not future_gws:
            continue

        # Your squad's own total across the horizon — never clamped.
        normal_total = 0.0
        for fgw in future_gws:
            market = gw_projections[fgw]
            squad_with_xpts = squad.merge(
                market[["player_id", "xpts"]], on="player_id", how="left"
            )
            squad_with_xpts["xpts"] = squad_with_xpts["xpts"].fillna(0)
            normal_xi = _pick_best_xi(squad_with_xpts)
            normal_total += float(normal_xi["xpts"].sum())

        # Build xpts_horizon: each candidate player's clamp-protected xPts
        # summed across the horizon window, keyed on player_id.
        base_cols = [c for c in ["player_id", "name", "pos", "team", "price_m"]
                     if c in gw_projections[future_gws[0]].columns]
        base_market = gw_projections[future_gws[0]][base_cols].copy().reset_index(drop=True)
        horizon_total = pd.Series(0.0, index=base_market.index)
        for fgw in future_gws:
            clipped = _clip_market_xpts(gw_projections[fgw], "xpts")
            merged = base_market[["player_id"]].merge(
                clipped[["player_id", "xpts"]], on="player_id", how="left"
            )["xpts"].fillna(0.0).reset_index(drop=True)
            horizon_total = horizon_total + merged
        base_market["xpts_horizon"] = horizon_total

        wc_total = None
        fallback_reason = None
        try:
            # Same schema bridge as score_free_hit: rename id, factorize team
            # labels for a stable team-cap grouping key (not the real FPL id).
            market_for_optimizer = base_market.rename(columns={"player_id": "id"}).copy()
            if "team" in market_for_optimizer.columns:
                market_for_optimizer["team"] = pd.factorize(market_for_optimizer["team"])[0]
            built = _optimizer.build_chip_squad(
                market_for_optimizer, score_col="xpts_horizon", budget_m=budget_m
            )
            if built.get("ok") and built.get("squad_df") is not None:
                wc_squad_ids = set(
                    pd.to_numeric(built["squad_df"]["player_id"], errors="coerce")
                    .dropna().astype(int).tolist()
                )
                wc_total = 0.0
                for fgw in future_gws:
                    clipped = _clip_market_xpts(gw_projections[fgw], "xpts")
                    week_squad = clipped[clipped["player_id"].isin(wc_squad_ids)]
                    if week_squad.empty:
                        continue
                    wc_xi = _pick_best_xi(week_squad)
                    wc_total += float(wc_xi["xpts"].sum())
            else:
                fallback_reason = built.get("reason", "optimizer returned not-ok")
        except Exception as e:  # noqa: BLE001 - degrade to unbudgeted proxy
            fallback_reason = str(e)

        fallback_used = wc_total is None
        if fallback_used:
            logger.warning(
                "score_wildcard: budget-aware build failed for GW%s (%s) — "
                "falling back to unbudgeted top-15 proxy", gw, fallback_reason,
            )
            wc_total = 0.0
            for fgw in future_gws:
                clipped = _clip_market_xpts(gw_projections[fgw], "xpts")
                wc_xi = _pick_best_xi(clipped)
                wc_total += float(wc_xi["xpts"].sum())

        valid_count = len(future_gws)
        uplift = max(0, wc_total - normal_total)

        # The no-chip baseline isn't a frozen squad — the horizon transfer plan
        # already improves it. Wildcard EV is net of that improvement.
        plan_gain = max(0.0, float(transfer_plan_net_gain))
        uplift = max(0.0, uplift - plan_gain)

        reasoning = [
            f"Your squad projected over next {valid_count} GWs: {normal_total:.0f} xPts",
            f"Optimal WC squad over next {valid_count} GWs: {wc_total:.0f} xPts"
            + (" [unbudgeted proxy — optimizer fallback]" if fallback_used else " (budget-constrained)"),
            f"WC uplift: +{uplift:.0f} xPts over horizon",
        ]
        if plan_gain > 0:
            reasoning.append(
                f"Net of +{plan_gain:.0f} xPts the normal transfer plan already captures"
            )
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
    transfer_plan_net_gain: float = 0.0,
    breaks: dict[int, dict] | None = None,
    xgi_per90: dict[int, float] | None = None,
    team_difficulty_by_gw: dict[int, dict[str, float]] | None = None,
    player_priors: dict[int, dict] | None = None,
    euro_by_gw: dict[int, dict[str, dict]] | None = None,
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
        all_recs.extend(score_triple_captain(
            squad, gw_projections, candidate_gws,
            xgi_per90=xgi_per90, team_difficulty_by_gw=team_difficulty_by_gw,
            player_priors=player_priors, euro_by_gw=euro_by_gw,
        ))
    if "bench_boost" in chips_remaining:
        all_recs.extend(score_bench_boost(
            squad, gw_projections, candidate_gws,
            player_priors=player_priors, euro_by_gw=euro_by_gw,
            team_difficulty_by_gw=team_difficulty_by_gw,
        ))
    if "free_hit" in chips_remaining:
        all_recs.extend(score_free_hit(
            squad, gw_projections, candidate_gws, bank_m,
            team_difficulty_by_gw=team_difficulty_by_gw,
        ))
    if "wildcard" in chips_remaining:
        all_recs.extend(score_wildcard(
            squad, gw_projections, candidate_gws,
            horizon=int(config.CHIP_WILDCARD_DEFAULT_HORIZON_GWS),
            transfer_plan_net_gain=transfer_plan_net_gain,
            budget_m=bank_m,
        ))

    if breaks:
        mult = float(config.CHIP_PLAN_BREAK_CONFIDENCE_MULT)
        for r in all_recs:
            if r.gw in breaks:
                r.confidence *= mult
                r.reasoning.append(
                    "First GW after international break — elevated injury/rotation uncertainty")
                if r.chip == "triple_captain":
                    r.risks.append(
                        "Late fitness flags after the break hit TC hardest — confirm lineups first")

    # Sort by expected value (descending), filter out zero-value
    return sorted(
        [r for r in all_recs if r.expected_value > 0],
        key=lambda r: r.expected_value,
        reverse=True,
    )


def _fh_structural_cup_clash_gw(cup_clashes, fixtures, model_end, expires_gw, blank_team_threshold):
    """First likely-blank FA Cup clash GW beyond the model horizon, for the
    Free Hit "structural hold" guidance line — mirrors the provisional-FH-rec
    detection below without mutating `recommendations`."""
    if not cup_clashes:
        return None
    for g in sorted(cup_clashes):
        info = cup_clashes[g]
        if g <= model_end or g > expires_gw:
            continue
        if not info.get("likely_blank"):
            continue
        counts = team_fixture_counts(fixtures, g) if fixtures is not None else {}
        if counts and len(counts) <= blank_team_threshold:
            continue  # already announced as a structural blank — handled elsewhere
        return g
    return None


def _fh_structural_guidance(gw):
    """Shared sentence for the Free Hit structural-hold case — used by both
    the outlook row (via `_chip_guidance`) and the provisional cup-clash
    recommendation entry, so the two can never drift apart."""
    return f"Hold for GW{gw}: likely blank gameweek (FA Cup weekend), FPL confirms nearer the time."


def _chip_guidance(chip, status, event_id, ev_gain, bar, distribution, horizon,
                    transfer_plan_net_gain=0.0, structural_gw=None):
    """Plain-language "why is this chip on hold" sentence for one outlook or
    recommendation row. Raises on a missing/unexpected field — callers use
    `_safe_chip_guidance` so a gap never breaks the payload."""
    prior = config.CHIP_PLAN_SEASON_PRIORS[chip]

    if status == "play":
        text = f"Play it in GW{event_id}: +{ev_gain:.1f} pts over the bar of {bar:.0f}."
        if distribution and "p_beats_bar" in distribution:
            text += f" {round(distribution['p_beats_bar'] * 100)}% chance it beats the bar."
        return text

    if event_id is None:
        if chip == "free_hit" and structural_gw is not None:
            return _fh_structural_guidance(structural_gw)
        text = f"Hold. Nothing in the next {horizon} GWs beats keeping it. Best use: {prior}."
        if chip == "wildcard" and transfer_plan_net_gain > 0:
            text += " Your squad plus free transfers already covers this stretch."
        return text

    text = f"Hold for now. GW{event_id} is the best week so far (+{ev_gain:.1f} pts"
    if distribution and "p_beats_bar" in distribution:
        text += f", {round(distribution['p_beats_bar'] * 100)}% chance to beat the {bar:.0f}-pt bar"
    text += f"). Best use: {prior}."
    return text


def _safe_chip_guidance(chip, **kwargs):
    try:
        return _chip_guidance(chip, **kwargs)
    except Exception:
        logger.warning("chip guidance builder failed for %s", chip, exc_info=True)
        prior = config.CHIP_PLAN_SEASON_PRIORS.get(
            chip, "the right structural window for this chip")
        return f"Hold. Best use: {prior}."


def build_chip_plan(
    squad: pd.DataFrame,
    current_gw: int,
    gw_projections: dict[int, pd.DataFrame],
    chips_played: list[dict],
    itb_m: float = 0.0,
    fixtures: pd.DataFrame | None = None,
    transfer_plan: dict | None = None,
    horizon_gws: int | None = None,
    breaks: dict[int, dict] | None = None,
    team_difficulty_by_gw: dict[int, dict[str, float]] | None = None,
    swings: list[dict] | None = None,
    xgi_per90: dict[int, float] | None = None,
    player_priors: dict[int, dict] | None = None,
    euro_by_gw: dict[int, dict[str, dict]] | None = None,
    cup_clashes: dict[int, dict] | None = None,
    events: list[dict] | None = None,
    team_labels: dict[int, str] | None = None,
) -> dict:
    """Assemble the full chip plan payload: model-zone EV recommendations,
    structural provisional windows, next-GW nudge, transfer context, and
    (when the signals are supplied) per-GW points distributions plus a
    fixture-context calendar (breaks, European weeks, DGW/BGW, cup clashes).

    player_priors: {player_id: {pos, xg90, xa90, p_appear, p_60}} — enables
        the TC/BB distributions (`chip_distribution.player_priors_from_elements`).
    euro_by_gw: {gw: {team_label: {competition, when, ...}}} — European
        weeks (`european.european_weeks_by_gw`); applies the
        CHIP_PLAN_EURO_XPTS_MULT haircut to both sides of every comparison.
    cup_clashes: {gw: {competition, label, likely_blank}} — domestic-cup
        weekends that usually blank the GW before FPL announces it.
    events: FPL bootstrap events (deadlines) for the calendar rows.
    team_labels: {team_id: label} so DGW/BGW teams can be named.
    """
    current_gw = int(current_gw)
    horizon = int(horizon_gws or config.CHIP_PLAN_HORIZON_GWS)
    windows = chip_windows(chips_played, current_gw)
    remaining = [c for c, w in windows.items() if w["available"]]
    plan_net_gain = float((transfer_plan or {}).get("total_net_gain", 0.0) or 0.0)

    squad_value = float(pd.to_numeric(squad.get("price_m"), errors="coerce").fillna(0).sum())
    budget_m = squad_value + float(itb_m or 0.0)

    # European midweeks: every player of a team in a European week that GW
    # carries the rotation/fatigue haircut — on the squad AND the market side,
    # so a FH/WC dream squad can't dodge it.
    euro_mult = float(config.CHIP_PLAN_EURO_XPTS_MULT)
    if euro_by_gw:
        gw_projections = european.discount_projections(gw_projections, euro_by_gw, euro_mult)

    all_recs = recommend_chips(
        squad=squad,
        current_gw=current_gw,
        gw_projections=gw_projections,
        chips_remaining=remaining,
        gws_ahead=horizon - 1,
        bank_m=budget_m,
        transfer_plan_net_gain=plan_net_gain,
        breaks=breaks,
        xgi_per90=xgi_per90,
        team_difficulty_by_gw=team_difficulty_by_gw,
        player_priors=player_priors,
        euro_by_gw=euro_by_gw,
    )

    recommendations = []
    nudge = None
    nudge_floor = float(config.CHIP_PLAN_NUDGE_MIN_EV)
    model_end = current_gw + horizon - 1
    fh_structural_gw = (
        _fh_structural_cup_clash_gw(
            cup_clashes, fixtures, model_end, windows["free_hit"]["expires_gw"],
            int(config.CHIP_PLAN_BLANK_TEAM_THRESHOLD))
        if "free_hit" in remaining else None
    )

    # Outlook: one row per available chip, ALWAYS — even when the verdict is
    # hold. "No recommendation" should still show the plan (best window, EV,
    # the bar it failed to clear), not an empty panel.
    outlook = []
    for chip in remaining:
        expires_gw = windows[chip]["expires_gw"]
        chip_recs = [r for r in all_recs if r.chip == chip]
        # Model-zone candidates only run to the chip's expiry.
        in_window = [r for r in chip_recs if r.gw <= expires_gw]
        if not in_window:
            base_bar = float(config.CHIP_PLAN_MIN_EV.get(chip, 0.0))
            no_window_reason = (
                "No blank-heavy or tough-fixture week in the model horizon"
                if chip == "free_hit"
                else "No positive-EV window in the model horizon"
            )
            outlook.append({
                "chip": chip,
                "event_id": None,
                "ev_gain": None,
                "bar": round(base_bar, 2),
                "status": "hold",
                "reasons": [no_window_reason],
                "guidance": _safe_chip_guidance(
                    chip, status="hold", event_id=None, ev_gain=None, bar=base_bar,
                    distribution=None, horizon=horizon,
                    transfer_plan_net_gain=plan_net_gain,
                    structural_gw=fh_structural_gw if chip == "free_hit" else None),
            })
            continue
        best = max(in_window, key=lambda r: r.expected_value)
        curve = []
        for r in sorted(in_window, key=lambda r: r.gw):
            point = {"gw": r.gw, "ev": round(float(r.expected_value), 2)}
            if r.pmf is not None:
                d = chip_distribution.summarize(
                    r.pmf, bar=effective_min_ev(chip, r.gw, expires_gw),
                    continuous_share=r.pmf_share, player_thresholds=r.pmf_thresholds)
                point["p_beats_bar"] = d["p_beats_bar"]
                if "p_return" in d:
                    point["p_return"] = d["p_return"]
            if euro_by_gw and r.gw in euro_by_gw:
                point["european"] = int(squad["team"].isin(list(euro_by_gw[r.gw])).sum())
            if breaks and r.gw in breaks:
                point["post_break"] = True
            curve.append(point)
        bar = effective_min_ev(chip, best.gw, expires_gw)
        distribution = chip_distribution.summarize(
            best.pmf, bar=bar, continuous_share=best.pmf_share,
            player_thresholds=best.pmf_thresholds) if best.pmf is not None else None
        outlook_row = {
            "chip": chip,
            "event_id": int(best.gw),
            "ev_gain": round(float(best.expected_value), 2),
            "bar": round(float(bar), 2),
            "status": "hold",
            "reasons": list(best.reasoning)[:3],
        }
        if distribution is not None:
            outlook_row["distribution"] = distribution
        outlook_row["guidance"] = _safe_chip_guidance(
            chip, status="hold", event_id=outlook_row["event_id"],
            ev_gain=outlook_row["ev_gain"], bar=outlook_row["bar"],
            distribution=distribution, horizon=horizon,
            transfer_plan_net_gain=plan_net_gain)
        outlook.append(outlook_row)
        if best.expected_value < bar:
            continue  # hold — nothing in the model zone clears the bar
        outlook_row["status"] = "play"
        outlook_row["guidance"] = _safe_chip_guidance(
            chip, status="play", event_id=outlook_row["event_id"],
            ev_gain=outlook_row["ev_gain"], bar=outlook_row["bar"],
            distribution=distribution, horizon=horizon)
        rec = {
            "chip": chip,
            "event_id": int(best.gw),
            "ev_gain": round(float(best.expected_value), 2),
            "confidence": round(float(best.confidence), 2),
            "provisional": False,
            "reasons": list(best.reasoning) + [f"Risk: {r}" for r in best.risks],
            "ev_curve": curve,
            "guidance": outlook_row["guidance"],
        }
        if distribution is not None:
            rec["distribution"] = distribution
        if best.haul_prob is not None:
            rec["haul_prob"] = round(float(best.haul_prob), 3)
        if swings and chip in ("wildcard", "triple_captain"):
            near = [s for s in swings
                    if s.get("direction") == "easier"
                    and abs(int(s.get("gw", 0)) - rec["event_id"]) <= 1]
            if chip == "triple_captain":
                # TC only benefits from a swing that involves the recommended
                # captain's own team — a swing elsewhere in the league isn't
                # a reason to triple-captain this player.
                near = [s for s in near
                        if best.captain_team is not None
                        and best.captain_team in (s.get("team"), s.get("team_short"))]
            if near:
                names = ", ".join(sorted(
                    s.get("team_short") or s.get("team", "?") for s in near)[:3])
                rec["reasons"].append(
                    f"Fixture swing: {names} turn easier around GW{rec['event_id']}")
        recommendations.append(rec)
        if rec["event_id"] == current_gw and rec["ev_gain"] >= nudge_floor:
            if nudge is None or rec["ev_gain"] > nudge["ev_gain"]:
                nudge = {"chip": chip, "event_id": current_gw, "ev_gain": rec["ev_gain"],
                         "wait_for_team_news": bool(breaks and current_gw in breaks)}
                if distribution is not None and "p_beats_bar" in distribution:
                    nudge["p_beats_bar"] = distribution["p_beats_bar"]

    # Structural zone: announced DGWs/BGWs beyond the model horizon, up to expiry.
    recommended_chips = {r["chip"] for r in recommendations}
    if fixtures is not None and not fixtures.empty:
        season_end = int(config.CHIP_PLAN_SEASON_END_GW)
        for g in range(model_end + 1, season_end + 1):
            counts = team_fixture_counts(fixtures, g)
            if not counts:
                continue
            n_teams = len(counts)
            has_dgw = any(v >= 2 for v in counts.values())
            blank_team_threshold = int(config.CHIP_PLAN_BLANK_TEAM_THRESHOLD)
            is_blank_heavy = n_teams <= blank_team_threshold  # several teams missing → blank GW
            for chip, wants, label in (
                ("bench_boost", has_dgw, "double gameweek"),
                ("triple_captain", has_dgw, "double gameweek"),
                ("free_hit", is_blank_heavy, "blank-heavy gameweek"),
            ):
                if not wants or chip not in remaining or chip in recommended_chips:
                    continue
                if g > windows[chip]["expires_gw"]:
                    continue
                recommendations.append({
                    "chip": chip,
                    "event_id": g,
                    "ev_gain": None,
                    "provisional": True,
                    "likelihood": 1.0,
                    "reasons": [f"GW{g} is a {label} (from announced fixtures) — "
                                f"candidate window, EV computable once in the model horizon"],
                    "ev_curve": [],
                })
                recommended_chips.add(chip)

    # Expected (not yet announced) blanks: a domestic-cup weekend inside the
    # GW window has historically wiped most of the round. Surface it as a
    # likelihood-tagged provisional FH window so the manager holds the chip
    # for it instead of burning it on an ordinary week.
    if (cup_clashes and "free_hit" in remaining and "free_hit" not in recommended_chips
            and fh_structural_gw is not None):
        blank_prob = float(config.CHIP_PLAN_CUP_CLASH_BLANK_PROB)
        g = fh_structural_gw
        info = cup_clashes[g]
        comp = str(info.get("competition", "cup")).replace("_", " ").upper()
        label = info.get("label") or "round"
        recommendations.append({
            "chip": "free_hit",
            "event_id": g,
            "ev_gain": None,
            "provisional": True,
            "likelihood": round(blank_prob, 2),
            "reasons": [f"GW{g} clashes with the {comp} {label} weekend — "
                        f"~{blank_prob:.0%} likely to become a blank GW once fixtures are "
                        f"confirmed; hold Free Hit for it"],
            "ev_curve": [],
            "guidance": _fh_structural_guidance(g),
        })
        recommended_chips.add("free_hit")

    calendar = build_calendar(
        squad=squad, current_gw=current_gw, horizon=horizon, events=events,
        fixtures=fixtures, breaks=breaks, euro_by_gw=euro_by_gw,
        cup_clashes=cup_clashes, team_labels=team_labels,
    )

    return {
        "current_gw": current_gw,
        "chips_remaining": [
            {"name": c, **windows[c]} for c in ALL_CHIPS
        ],
        "horizon_model_gws": horizon,
        "recommendations": recommendations,
        "outlook": outlook,
        "nudge": nudge,
        "calendar": calendar,
        "signals": {
            "breaks": bool(breaks),
            "european_calendar": bool(euro_by_gw),
            "cup_calendar": bool(cup_clashes),
            "distributions": bool(player_priors),
            "european_xpts_mult": euro_mult if euro_by_gw else None,
        },
        "transfer_context": {
            "planned_transfers_net_gain": round(plan_net_gain, 2),
            "wc_alternative_gw": next(
                (r["event_id"] for r in recommendations if r["chip"] == "wildcard"), None),
        },
    }


def build_calendar(squad, current_gw, horizon, events=None, fixtures=None, breaks=None,
                   euro_by_gw=None, cup_clashes=None, team_labels=None) -> list[dict]:
    """One row per upcoming GW with the fixture context chips care about.

    Rows run from current_gw to CHIP_PLAN_SEASON_END_GW. Model-zone rows are
    flagged `in_model_zone`; the rest is the structural outlook. Every field
    degrades to None/empty when its signal is missing.
    """
    last_gw = int(config.CHIP_PLAN_SEASON_END_GW)
    deadlines = {}
    for e in events or []:
        try:
            deadlines[int(e.get("id"))] = e.get("deadline_time")
        except (TypeError, ValueError):
            continue
    blank_team_threshold = int(config.CHIP_PLAN_BLANK_TEAM_THRESHOLD)
    all_team_ids = set(team_labels or {})

    rows = []
    for g in range(current_gw, last_gw + 1):
        counts = team_fixture_counts(fixtures, g) if fixtures is not None else {}
        n_playing = len(counts)
        dgw_ids = sorted(t for t, v in counts.items() if v >= 2)
        blank_ids = sorted(all_team_ids - set(counts)) if (all_team_ids and counts) else []
        euro_gw = (euro_by_gw or {}).get(g) or {}
        by_comp: dict[str, list[str]] = {}
        for team, info in euro_gw.items():
            by_comp.setdefault(info["competition"], []).append(team)
        exposure = european.squad_exposure(squad, euro_gw)
        row = {
            "gw": g,
            "deadline_utc": deadlines.get(g),
            "in_model_zone": g < current_gw + horizon,
            "post_break": bool(breaks and g in breaks),
            "break_gap_days": (breaks or {}).get(g, {}).get("gap_days") if breaks else None,
            "european": {c: sorted(v) for c, v in sorted(by_comp.items())},
            "squad_european": exposure,
            "n_teams_playing": n_playing if counts else None,
            "dgw_teams": [team_labels.get(t, t) if team_labels else t for t in dgw_ids],
            "blank_teams": [team_labels.get(t, t) for t in blank_ids] if team_labels else [],
            "is_blank_heavy": bool(counts) and n_playing <= blank_team_threshold,
            "has_dgw": bool(dgw_ids),
            "cup_clash": (cup_clashes or {}).get(g),
        }
        rows.append(row)
    return rows


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
