"""Synthetic 300-player market (20 teams x 2/5/5/3) for wildcard v2 tests."""
import numpy as np
import pandas as pd

POS_BY_SLOT = ["GKP"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3


def wildcard_market(seed=7):
    rng = np.random.default_rng(seed)
    rows = []
    pid = 1
    for team in range(1, 21):
        for slot, pos in enumerate(POS_BY_SLOT):
            base = {"GKP": 4.3, "DEF": 4.6, "MID": 5.5, "FWD": 6.0}[pos]
            price = round(base + rng.gamma(1.6, 0.9), 1)
            if pos in ("MID", "FWD") and team <= 6 and slot in (7, 12):
                price = round(10.5 + rng.uniform(0.0, 4.5), 1)      # 12 premiums
            if slot in (1, 5, 6, 11, 14):                             # real-market fodder tier
                price = {"GKP": 4.0, "DEF": 4.0 if slot == 5 else 4.5, "MID": 4.5, "FWD": 4.5}[pos]
            score = round(0.55 * price + rng.normal(0.0, 0.8), 2)
            if pos == "GKP":
                score = round(0.9 * price + rng.normal(0.0, 0.4), 2)
            start_share = 0.92 if slot in (0, 2, 3, 4, 7, 8, 9, 12, 13) else rng.choice([0.3, 0.6, 0.95])
            rows.append({
                "id": pid, "web_name": f"T{team}{pos}{slot}", "pos": pos, "team": team,
                "price_m": price, "wildcard_score": max(0.1, score),
                "selected_by_percent": float(round(rng.uniform(0.5, 60.0), 1)),
                "status": "a", "minutes": 900,
                "start_share": float(start_share),
                "p_dc": float(round(rng.uniform(0.0, 0.8), 2)) if pos in ("DEF", "MID") else 0.0,
                "p_clean_sheet": float(round(rng.uniform(0.1, 0.5), 2)) if pos in ("GKP", "DEF") else 0.0,
                "injury_flag": False,
                "team_def_rank": team,
                "team_rated_matches": 4.0 if team >= 19 else 9.0,
                "ep_goals": 0.2, "ep_assists": 0.1, "ep_dc": 0.3, "ep_saves": 0.0,
            })
            pid += 1
    df = pd.DataFrame(rows)
    # one injured star, one flagged
    df.loc[df["id"] == 5, "status"] = "i"
    df.loc[df["id"] == 20, "injury_flag"] = True
    return df
