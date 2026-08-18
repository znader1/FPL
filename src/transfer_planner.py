"""Horizon transfer planner for the squad picker.

Given a 15-man squad and per-GW projections (``xpts_gw{N}`` columns), sequence
transfers across the fixture horizon under the real FPL rules: 1 free transfer
accrues per GW (banked up to a cap), each GW you either USE free transfers on
the best like-for-like swaps or ROLL to accumulate, and an extra transfer costs
a -4 hit (taken only when its remaining-horizon gain beats the 4-point cost).

Policy is greedy-per-GW: take value early (a point this GW is worth more than
the same point next GW), roll when nothing clears the bar. A transfer's gain is
scored on the REMAINING horizon (this GW onward), so making it earlier is worth
more -- which is what makes roll-vs-use fall out naturally.

Pure/data-only: operates on a projections DataFrame, no network. Selling price
is approximated by current price (purchase price isn't tracked here).
"""
import pandas as pd

MAX_PER_TEAM = 3


def _num(v, default=0.0):
    n = pd.to_numeric(v, errors="coerce")
    return default if pd.isna(n) else float(n)


def _build_info(proj, gws):
    df = proj.drop_duplicates("id")
    info = {}
    for _, r in df.iterrows():
        pid = int(r["id"])
        info[pid] = {
            "id": pid,
            "name": r.get("web_name"),
            "pos": r.get("pos"),
            "team": str(r.get("team_short") or "?"),
            "price": _num(r.get("price_m")),
            "xg": {g: _num(r.get(f"xpts_gw{g}")) for g in gws},
        }
    return info


def _horizon(info, pid, remaining):
    xg = info[pid]["xg"]
    return sum(xg.get(g, 0.0) for g in remaining)


def _best_swap(squad, info, unowned, hz, bank, team_counts):
    """Best single like-for-like swap: maximizes remaining-horizon gain subject
    to budget and the 3-per-club cap. Returns {sell, buy, pos, gain} or None."""
    best = None
    for s in squad:
        si = info[s]
        s_hz, s_price, s_team, s_pos = hz[s], si["price"], si["team"], si["pos"]
        budget = bank + s_price
        for b in unowned:
            bi = info[b]
            if bi["pos"] != s_pos:
                continue
            if bi["price"] > budget + 1e-9:
                continue
            bt = bi["team"]
            count_after = team_counts.get(bt, 0) - (1 if bt == s_team else 0)
            if count_after + 1 > MAX_PER_TEAM:
                continue
            gain = hz[b] - s_hz
            if best is None or gain > best["gain"]:
                best = {"sell": s, "buy": b, "pos": s_pos, "gain": gain}
    return best


def _move_record(m, info):
    s, b = info[m["sell"]], info[m["buy"]]
    return {
        "position": m["pos"],
        "sell": {"id": s["id"], "name": s["name"], "team": s["team"], "price": round(s["price"], 1)},
        "buy": {"id": b["id"], "name": b["name"], "team": b["team"], "price": round(b["price"], 1)},
        "score_gain": round(m["gain"], 2),
    }


def _note(moves, ft_before, info):
    if not moves:
        return f"Roll — no move above the bar; bank the free transfer (had {ft_before})."
    parts = [f"{info[m['sell']]['name']} → {info[m['buy']]['name']} (+{round(m['gain'], 1)})"
             for m in moves]
    return "; ".join(parts)


def plan_transfers(proj, squad_ids, gws, itb_m=0.0, start_ft=1, ft_cap=5,
                   hit_penalty=4.0, allow_hits=True, min_gain=2.0, max_moves_per_gw=3):
    info = _build_info(proj, gws)
    squad = set(int(x) for x in squad_ids if int(x) in info)
    bank = float(itb_m)
    ft = int(start_ft)
    plan, total_net = [], 0.0

    for gi, g in enumerate(gws):
        if gi > 0:
            ft = min(ft_cap, ft + 1)  # accrue a free transfer each new GW
        ft_before = ft
        remaining = gws[gi:]
        hz = {pid: _horizon(info, pid, remaining) for pid in info}
        team_counts = {}
        for pid in squad:
            t = info[pid]["team"]
            team_counts[t] = team_counts.get(t, 0) + 1

        moves, hits = [], 0
        while len(moves) < max_moves_per_gw:
            unowned = [pid for pid in info if pid not in squad]
            best = _best_swap(squad, info, unowned, hz, bank, team_counts)
            if best is None:
                break
            within_ft = len(moves) < ft
            threshold = min_gain if within_ft else hit_penalty
            if best["gain"] <= threshold:
                break
            if not within_ft and not allow_hits:
                break
            s, b = best["sell"], best["buy"]
            squad.discard(s)
            squad.add(b)
            bank += info[s]["price"] - info[b]["price"]
            team_counts[info[s]["team"]] = team_counts.get(info[s]["team"], 0) - 1
            team_counts[info[b]["team"]] = team_counts.get(info[b]["team"], 0) + 1
            if not within_ft:
                hits += 1
            moves.append(best)

        used = len(moves)
        hit_cost = hits * hit_penalty
        gw_gain = round(sum(m["gain"] for m in moves), 2)
        net = round(gw_gain - hit_cost, 2)
        total_net += net
        ft_after = ft_before if used == 0 else max(0, ft_before - min(used, ft_before))
        plan.append({
            "gw": g,
            "action": "roll" if used == 0 else "transfer",
            "free_transfers_before": ft_before,
            "free_transfers_after": ft_after,
            "hits": hits,
            "hit_cost": round(hit_cost, 2),
            "gw_gain": gw_gain,
            "net_gain": net,
            "bank_after": round(bank, 2),
            "moves": [_move_record(m, info) for m in moves],
            "note": _note(moves, ft_before, info),
        })
        ft = ft_after

    return {
        "gws": list(gws),
        "horizon_gws": len(gws),
        "start_free_transfers": int(start_ft),
        "ft_cap": int(ft_cap),
        "allow_hits": bool(allow_hits),
        "hit_penalty": float(hit_penalty),
        "total_net_gain": round(total_net, 2),
        "final_bank": round(bank, 2),
        "plan": plan,
    }
