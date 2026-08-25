"""
Captain recommendation engine — Layer 1 (deterministic).

Picks the best captain from a starting XI considering:
- xPts projection
- Position ceiling (FWD > MID > DEF > GKP)
- Premium price floor (cheaper players have lower ceilings)
- Fixture difficulty
- DGW status (player playing twice)
"""
from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class CaptainRecommendation:
    player_id: int
    name: str
    pos: str
    team: str
    xpts: float
    expected_captain_value: float  # xpts × 2 (or × 3 with TC)
    confidence: float
    reasoning: list[str] = field(default_factory=list)


# Position ceiling multipliers — favor attackers
POSITION_CEILING_MULT = {
    "FWD": 1.16,
    "MID": 1.12,
    "DEF": 0.92,
    "GKP": 0.65,
}

# Premium price bonus per £m above floor
PREMIUM_PRICE_FLOOR = 9.0
PREMIUM_BONUS_PER_M = 0.10


def score_captain_candidate(row: dict, is_dgw: bool = False) -> tuple[float, list[str]]:
    """
    Return (captaincy_score, reasoning) for a single player.
    Score is the proxy used to rank — higher means better captain.
    """
    xpts = float(row.get("xpts", 0))
    pos = row.get("pos", "")
    price = float(row.get("price_m", 0))

    reasoning = [f"Projected xPts: {xpts:.1f}"]

    # Position multiplier
    pos_mult = POSITION_CEILING_MULT.get(pos, 1.0)
    score = xpts * pos_mult
    if pos in ("FWD", "MID"):
        reasoning.append(f"Position bonus: ×{pos_mult:.2f}")
    elif pos in ("DEF", "GKP"):
        reasoning.append(f"Position penalty (low ceiling): ×{pos_mult:.2f}")

    # Premium price bonus
    if price >= PREMIUM_PRICE_FLOOR:
        bonus = (price - PREMIUM_PRICE_FLOOR) * PREMIUM_BONUS_PER_M
        score += bonus
        reasoning.append(f"Premium price (£{price:.1f}m): +{bonus:.2f}")

    # DGW bonus
    if is_dgw:
        score += xpts * 0.5  # half a second fixture worth
        reasoning.append("DGW: +50% xPts uplift")

    return score, reasoning


def recommend_captain(
    starting_xi: pd.DataFrame,
    top_n: int = 3,
) -> list[CaptainRecommendation]:
    """
    starting_xi: DataFrame with player_id, name, pos, team, price_m, xpts, [fixture_count]
    Returns ranked list of captain candidates with reasoning.
    """
    if starting_xi.empty:
        return []

    df = starting_xi.copy()
    df["fixture_count"] = df.get("fixture_count", 1).fillna(1).astype(int) if "fixture_count" in df.columns else 1
    if not hasattr(df["fixture_count"], "fillna"):
        df["fixture_count"] = 1

    scored = []
    for _, row in df.iterrows():
        is_dgw = int(row.get("fixture_count", 1)) >= 2
        score, reasoning = score_captain_candidate(row.to_dict(), is_dgw=is_dgw)
        scored.append({
            "player_id": int(row["player_id"]),
            "name": row["name"],
            "pos": row["pos"],
            "team": row.get("team", ""),
            "xpts": float(row["xpts"]),
            "price_m": float(row.get("price_m", 0)),
            "score": score,
            "reasoning": reasoning,
            "is_dgw": is_dgw,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    # Confidence: gap between top and 2nd. Bigger gap = more confident.
    if len(scored) >= 2:
        gap = scored[0]["score"] - scored[1]["score"]
        confidence = min(1.0, 0.5 + gap / 10.0)
    else:
        confidence = 0.7

    recs = []
    for entry in scored[:top_n]:
        recs.append(CaptainRecommendation(
            player_id=entry["player_id"],
            name=entry["name"],
            pos=entry["pos"],
            team=entry["team"],
            xpts=entry["xpts"],
            expected_captain_value=entry["xpts"] * 2,
            confidence=confidence,
            reasoning=entry["reasoning"],
        ))

    return recs


def pick_captain_id(starting_xi: pd.DataFrame) -> int:
    """Convenience: return just the player_id of the top captain."""
    recs = recommend_captain(starting_xi, top_n=1)
    if not recs:
        return int(starting_xi.iloc[0]["player_id"])
    return recs[0].player_id
