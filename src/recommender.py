# recommender.py
import pandas as pd

def naive_score(row):
    form = float(pd.to_numeric(row.get("form",0), errors="coerce") or 0)
    ppg  = float(pd.to_numeric(row.get("points_per_game",0), errors="coerce") or 0)
    return 0.6*ppg + 0.4*form

def suggest_transfers(squad_df, elements_all,
                      itb_m, free_transfers, hit_cap=0,
                      score_col=None):
    if squad_df.empty:
        return {"note":"No squad loaded.","moves":[],"remaining_itb":itb_m}

    el = elements_all.copy()
    for c in ["now_cost","form","points_per_game"]:
        el[c] = pd.to_numeric(el[c], errors="coerce")
    el["price_m"] = el["now_cost"]/10.0
    if score_col and score_col in el.columns:
        el["score"] = pd.to_numeric(el[score_col], errors="coerce").fillna(0.0)
    else:
        el["score"] = el.apply(naive_score, axis=1)

    starters = squad_df.sort_values("multiplier", ascending=False).head(11).copy()
    starters = starters.merge(el[["id","price_m","score","pos","web_name","team_short"]],
                              left_on="player_id", right_on="id", how="left")
    weakest = starters.sort_values("score").head(max(1, min(2, int(free_transfers or 1))))

    moves=[]; remain=itb_m
    for _,w in weakest.iterrows():
        sell=w["price_m"]; pos=w["pos"]
        cand = el[(el["pos"]==pos) & (el["price_m"]<=sell+remain)].sort_values("score", ascending=False).head(1)
        if not cand.empty and int(cand.iloc[0]["id"])!=int(w["player_id"]):
            t=cand.iloc[0]; delta=float(t["price_m"]-sell); remain-=max(delta,0)
            moves.append({
                "sell":{"id":int(w["player_id"]),"name":w["web_name"],"team":w["team_short"],"price":round(float(sell),1)},
                "buy": {"id":int(t["id"]),"name":t["web_name"],"team":t["team_short"],"price":round(float(t["price_m"]),1)},
                "score_gain": round(float(t["score"]-w["score"]),2)
            })
    return {"note":"Naive heuristic. Replace with your model.","moves":moves,"remaining_itb":round(remain,1)}
