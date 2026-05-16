"""
Transfer recommendation engine — Layer 1 (deterministic).

Improvements over the simple 1-for-1 swap:
- Multi-GW horizon: scores transfers over next 3 GWs, not just this week
- Captain-aware: penalizes selling a likely captain
- Premium-aware: bonus for buying expensive attackers
- Returns ranked list with reasoning so the LLM layer can explain it
"""
from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class TransferRecommendation:
    sell_id: int
    sell_name: str
    sell_pos: str
    buy_id: int
    buy_name: str
    buy_pos: str
    expected_gain: float          # cumulative xPts gain over horizon
    sell_price: float
    buy_price: float
    confidence: float
    reasoning: list[str] = field(default_factory=list)


POSITION_ATTACK_BONUS = {
    "FWD": 0.30,
    "MID": 0.20,
    "DEF": 0.05,
    "GKP": 0.0,
}
PREMIUM_FLOOR = 8.5
PREMIUM_BONUS = 0.15


def _multi_gw_xpts(player_id: int, gw_projections: dict[int, pd.DataFrame], horizon_gws: list[int]) -> float:
    total = 0.0
    for gw in horizon_gws:
        market = gw_projections.get(gw)
        if market is None or market.empty:
            continue
        row = market[market["player_id"] == player_id]
        if row.empty:
            continue
        total += float(row.iloc[0].get("xpts", 0) or 0)
    return total


def recommend_transfer(
    squad: pd.DataFrame,
    market: pd.DataFrame,
    gw_projections: dict[int, pd.DataFrame],
    current_gw: int,
    bank_m: float,
    horizon: int = 3,
    captain_id: int | None = None,
    top_n: int = 5,
    min_gain: float = 0.8,
) -> list[TransferRecommendation]:
    """
    Rank 1-for-1 transfer options by multi-GW expected gain.
    """
    if squad.empty or market.empty:
        return []

    horizon_gws = list(range(current_gw, current_gw + horizon))
    owned_ids = set(squad["player_id"].astype(int).tolist())

    # Precompute multi-GW xPts for all market players (and for squad)
    market = market.copy()
    market["horizon_xpts"] = market["player_id"].apply(
        lambda pid: _multi_gw_xpts(int(pid), gw_projections, horizon_gws)
    )

    squad = squad.copy()
    squad["horizon_xpts"] = squad["player_id"].apply(
        lambda pid: _multi_gw_xpts(int(pid), gw_projections, horizon_gws)
    )

    candidates = []
    for _, sell in squad.iterrows():
        pos = sell["pos"]
        sell_value = float(sell["price_m"])
        budget_for_buy = bank_m + sell_value
        pool = market[
            (market["pos"] == pos)
            & (~market["player_id"].isin(owned_ids))
            & (market["price_m"] <= budget_for_buy)
        ]
        if pool.empty:
            continue

        # Top 3 buy candidates by horizon xPts
        best_buys = pool.sort_values("horizon_xpts", ascending=False).head(3)
        for _, buy in best_buys.iterrows():
            raw_gain = float(buy["horizon_xpts"]) - float(sell["horizon_xpts"])

            # Adjustments
            pos_bonus = POSITION_ATTACK_BONUS.get(pos, 0)
            premium_bonus = max(0, float(buy["price_m"]) - PREMIUM_FLOOR) * PREMIUM_BONUS
            captain_penalty = 0.0
            if captain_id is not None and int(sell["player_id"]) == int(captain_id):
                captain_penalty = 2.5  # don't sell our captain easily

            adj_gain = raw_gain + pos_bonus + premium_bonus - captain_penalty
            if adj_gain < min_gain:
                continue

            reasoning = [
                f"Horizon xPts: sell {float(sell['horizon_xpts']):.1f} → buy {float(buy['horizon_xpts']):.1f}",
                f"Raw gain over {horizon} GWs: +{raw_gain:.1f}",
            ]
            if premium_bonus > 0:
                reasoning.append(f"Premium attacker bonus: +{premium_bonus:.2f}")
            if captain_penalty > 0:
                reasoning.append(f"Captain penalty: -{captain_penalty}")

            candidates.append(TransferRecommendation(
                sell_id=int(sell["player_id"]),
                sell_name=sell["name"],
                sell_pos=pos,
                buy_id=int(buy["player_id"]),
                buy_name=buy["name"],
                buy_pos=buy["pos"],
                expected_gain=adj_gain,
                sell_price=sell_value,
                buy_price=float(buy["price_m"]),
                confidence=min(1.0, 0.5 + adj_gain / 10.0),
                reasoning=reasoning,
            ))

    candidates.sort(key=lambda r: r.expected_gain, reverse=True)
    return candidates[:top_n]


def top_transfer(
    squad: pd.DataFrame,
    market: pd.DataFrame,
    gw_projections: dict[int, pd.DataFrame],
    current_gw: int,
    bank_m: float,
    horizon: int = 3,
    captain_id: int | None = None,
    min_gain: float = 0.8,
) -> TransferRecommendation | None:
    recs = recommend_transfer(
        squad, market, gw_projections, current_gw, bank_m,
        horizon=horizon, captain_id=captain_id, min_gain=min_gain, top_n=1,
    )
    return recs[0] if recs else None
