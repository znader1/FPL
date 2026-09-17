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

from . import config

MAX_PER_TEAM = 3


def _num(v, default=0.0):
    n = pd.to_numeric(v, errors="coerce")
    return default if pd.isna(n) else float(n)


def _red_flag(r):
    """True when a player is a likely-unavailable transfer target: an injury/
    suspension/unavailable status, or a next-round playing chance at/below the
    configured floor (e.g. 0 == ruled out). Missing status/chance columns
    resolve to "available" -- never force a sell on data we don't have."""
    statuses = {
        str(s).lower() for s in getattr(config, "TRANSFER_PLANNER_RED_FLAG_STATUSES", ("i", "s", "u"))
    }
    max_chance = getattr(config, "TRANSFER_PLANNER_RED_FLAG_MAX_CHANCE", 0.0)
    status = str(r.get("status") or "a").lower()
    chance = r.get("chance_of_playing_next_round")
    try:
        chance = float(chance)
    except (TypeError, ValueError):
        chance = None
    return status in statuses or (chance is not None and chance <= max_chance)


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
            "red_flag": _red_flag(r),
        }
    return info


def _horizon(info, pid, remaining):
    xg = info[pid]["xg"]
    return sum(xg.get(g, 0.0) for g in remaining)


def _xi_floors(squad, info, hz):
    """Likely XI (top 11 by remaining-horizon value) and its weakest member
    per position / overall — the bar an incoming player must beat to turn a
    bench slot into real points."""
    xi_ids = set(sorted(squad, key=lambda p: hz.get(p, 0.0), reverse=True)[:11])
    by_pos, overall = {}, None
    for pid in xi_ids:
        v, pos = hz.get(pid, 0.0), info[pid]["pos"]
        by_pos[pos] = min(by_pos.get(pos, v), v)
        overall = v if overall is None else min(overall, v)
    return xi_ids, by_pos, (overall or 0.0)


def _h2h_conflicts(buy_pos, buy_team, seller, squad_all, info, opps_gw):
    """Own players directly opposed to the candidate buy this GW: a GKP/DEF
    buy vs owned attackers, or an attacker buy vs owned GKP/DEF."""
    opp_teams = opps_gw.get(buy_team) if opps_gw else None
    if not opp_teams:
        return []
    attackerish = buy_pos in ("MID", "FWD")
    other_side = ("GKP", "DEF") if attackerish else ("MID", "FWD")
    return [pid for pid in squad_all
            if pid != seller
            and info[pid]["team"] in opp_teams
            and info[pid]["pos"] in other_side]


def _best_swap(squad, info, unowned, hz, bank, team_counts, xi=None,
               squad_all=None, opps_gw=None, h2h_pen=0.0):
    """Best single like-for-like swap: maximizes remaining-horizon gain subject
    to budget and the 3-per-club cap. Returns {sell, buy, pos, gain} or None.

    With `xi` (from _xi_floors), a bench seller's swap only counts the points
    the buyer would add by displacing the weakest same-position XI member —
    upgrading a player who stays on the bench is worth nothing."""
    xi_ids, xi_min_by_pos, xi_min_overall = xi if xi else (None, None, None)
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
            if xi_ids is not None and s not in xi_ids:
                floor = xi_min_by_pos.get(s_pos, xi_min_overall)
                gain = max(0.0, hz[b] - floor)
            else:
                gain = hz[b] - s_hz
            conflicts = []
            if h2h_pen > 0 and opps_gw:
                conflicts = _h2h_conflicts(s_pos, bi["team"], s,
                                           squad_all or squad, info, opps_gw)
                gain -= h2h_pen * len(conflicts)
            if best is None or gain > best["gain"]:
                best = {"sell": s, "buy": b, "pos": s_pos, "gain": gain,
                        "conflicts": conflicts}
    return best


def _ranked_swaps(squad, info, unowned, hz, bank, team_counts, xi, opps_gw, h2h_pen,
                  min_gain, pos_mult, n):
    """One best-swap candidate per squad member, ranked by horizon gain, then
    walked to keep only DISTINCT buy targets (each player appears at most
    once) and at most two candidates per position. Several sellers tying on
    the same XI-floor-driven buy (e.g. two bench keepers both wanting the
    same replacement) would otherwise collapse the list onto a couple of
    targets and say nothing new -- computed independently per seller, so
    ties are broken by rank (the higher-gain seller keeps the target).
    A candidate that loses points (gain <= 0 -- the seller's best available
    buy is still worse than what they already own) is never a real
    alternative, so it's dropped before ranking rather than shown "below
    bar": below-bar is for swaps that gain something but not enough,
    negative-gain swaps gain nothing at all.

    Feeds `verdict_detail.runner_ups` ("also considered")."""
    cands = []
    for s in squad:
        best = _best_swap({s}, info, unowned, hz, bank, team_counts, xi=xi,
                          squad_all=squad, opps_gw=opps_gw, h2h_pen=h2h_pen)
        if best is None or best["gain"] <= 0:
            continue
        bar = float(min_gain) * float(pos_mult.get(best["pos"], 1.0))
        best["clears_bar"] = bool(best["gain"] > bar)
        cands.append(best)
    cands.sort(key=lambda m: m["gain"], reverse=True)

    ranked, seen_buys, pos_counts = [], set(), {}
    for m in cands:
        if m["buy"] in seen_buys:
            continue
        if pos_counts.get(m["pos"], 0) >= 2:
            continue
        seen_buys.add(m["buy"])
        pos_counts[m["pos"]] = pos_counts.get(m["pos"], 0) + 1
        ranked.append(m)
    return ranked[:n]


def _move_record(m, info, gw=None):
    s, b = info[m["sell"]], info[m["buy"]]
    rec = {
        "position": m["pos"],
        "sell": {"id": s["id"], "name": s["name"], "team": s["team"], "price": round(s["price"], 1)},
        "buy": {"id": b["id"], "name": b["name"], "team": b["team"], "price": round(b["price"], 1)},
        "score_gain": round(m["gain"], 2),
    }
    if gw is not None:
        # score_gain is the HORIZON total — surface the immediate-week slice
        # too so a multi-week edge never masquerades as this week's gain.
        rec["this_gw_gain"] = round(
            float(b["xg"].get(gw, 0.0)) - float(s["xg"].get(gw, 0.0)), 2)
    if m.get("forced_injury"):
        rec["forced_injury"] = True
    if m.get("conflicts"):
        rec["h2h_conflicts"] = [info[p]["name"] for p in m["conflicts"]]
    return rec


def _detail_move(m):
    """Compact move for verdict_detail from a `_move_record` output."""
    return {
        "sell": m["sell"],
        "buy": m["buy"],
        "position": m.get("position"),
        "this_gw_gain": round(float(m.get("this_gw_gain", 0.0)), 2),
        "horizon_gain": round(float(m["score_gain"]), 2),
        "forced_injury": bool(m.get("forced_injury", False)),
        "h2h_conflicts": list(m.get("h2h_conflicts") or []),
    }


def _verdict_detail(result, min_gain, rejected=None, runner_ups=None):
    """Structured twin of `reasoning`, built from the finished plan.

    `rejected` is the plan the roll-vs-move counterfactual lost: the roll
    walk when the verdict is spend, or the spend walk when the verdict was
    flipped to roll. None when no comparison ran (injury urgency, roll with
    nothing to compare, single-GW horizon).

    `runner_ups` is the pre-converted "also considered" list (see
    `_ranked_swaps` / `plan_transfers`); the key is always present, empty
    when nothing was computed (e.g. the `_skip_first_gw` counterfactual leg)."""
    plan = result.get("plan") or []
    gws = list(result.get("gws") or [])
    first = plan[0] if plan else None
    moves = ([_detail_move(m) for m in first["moves"]]
             if first and first["action"] == "transfer" else [])
    detail = {
        "action": result["verdict"],
        "horizon": {
            "start_gw": gws[0] if gws else None,
            "end_gw": gws[-1] if gws else None,
            "n": len(gws),
        },
        "ft_before": int(result["first_gw_ft_before"]),
        "ft_after": int(result["first_gw_ft_after"]),
        "threshold": float(min_gain),
        "moves": moves,
        "this_gw_gain": round(sum(m["this_gw_gain"] for m in moves), 2),
        "horizon_gain": round(sum(m["horizon_gain"] for m in moves), 2),
        "hit_cost": float(first["hit_cost"]) if first else 0.0,
        "plan_net": float(result["total_net_gain"]),
        "roll_alternative": None,
        "next_move": None,
        "runner_ups": list(runner_ups) if runner_ups else [],
    }
    if result["verdict"] == "roll":
        later = next((p for p in plan[1:] if p["action"] == "transfer"), None)
        if later is not None:
            detail["next_move"] = {
                "gw": int(later["gw"]),
                "moves": [_detail_move(m) for m in later["moves"]],
                "horizon_gain": round(float(later["gw_gain"]), 2),
            }
    if rejected is not None:
        alt_first = next((p for p in (rejected.get("plan") or [])
                          if p["action"] == "transfer"), None)
        detail["roll_alternative"] = {
            "net": float(rejected["total_net_gain"]),
            "gw": int(alt_first["gw"]) if alt_first else None,
            "moves": [_detail_move(m) for m in alt_first["moves"]] if alt_first else [],
        }
    return detail


def _note(moves, ft_before, info, gw=None):
    if not moves:
        return f"Roll — no move above the bar; bank the free transfer (had {ft_before})."
    parts = []
    for m in moves:
        gain_txt = f"+{round(m['gain'], 1)}"
        if gw is not None:
            tg = float(info[m["buy"]]["xg"].get(gw, 0.0)) - float(info[m["sell"]]["xg"].get(gw, 0.0))
            gain_txt = f"+{round(tg, 1)} this GW, +{round(m['gain'], 1)} over horizon"
        parts.append(f"{info[m['sell']]['name']} → {info[m['buy']]['name']} ({gain_txt})")
    return "; ".join(parts)


def scaled_min_gain(n_gws, base=None, ref_gws=None):
    """Gain bar for a plan spanning `n_gws`: the configured bar is defined over
    TRANSFER_PLAN_MIN_GAIN_REF_GWS gameweeks and scales linearly with the
    number of GWs whose gains are summed (a 1-GW plan needs a third of the
    3-GW bar). Never below 0.1 so a degenerate horizon can't fire on noise."""
    base = float(getattr(config, "TRANSFER_PLAN_MIN_GAIN", 2.0) if base is None else base)
    ref = float(getattr(config, "TRANSFER_PLAN_MIN_GAIN_REF_GWS", 3) if ref_gws is None else ref_gws)
    return max(0.1, round(base * max(1, int(n_gws)) / max(1.0, ref), 3))


def plan_transfers(proj, squad_ids, gws, itb_m=0.0, start_ft=1, ft_cap=5,
                   hit_penalty=4.0, allow_hits=True, min_gain=2.0, max_moves_per_gw=3,
                   opponents_by_gw=None, _skip_first_gw=False):
    info = _build_info(proj, gws)
    squad = set(int(x) for x in squad_ids if int(x) in info)
    bank = float(itb_m)
    ft = int(start_ft)
    plan, total_net = [], 0.0
    runner_ups = []

    # Injury gate: a red-flagged player in the LIKELY first-GW XI (top 11 of
    # the squad by that GW's projection) gets force-sold ahead of the normal
    # greedy decision, bypassing min_gain -- an "i"/"s"/"u" status or a 0%
    # playing chance means the projection itself is close to meaningless, so
    # the usual gain threshold doesn't apply. Bench red flags don't force.
    first_gw = gws[0] if gws else None
    likely_xi = set()
    if first_gw is not None:
        by_first_gw = sorted(squad, key=lambda pid: info[pid]["xg"].get(first_gw, 0.0), reverse=True)
        likely_xi = set(by_first_gw[:11])
    forced_sells = {pid for pid in likely_xi if info[pid].get("red_flag")}

    for gi, g in enumerate(gws):
        if gi > 0:
            ft = min(ft_cap, ft + 1)  # accrue a free transfer each new GW
        ft_before = ft
        if gi == 0 and _skip_first_gw:
            # Roll-alternative counterfactual: bank the FT this week, everything
            # else plays out greedily from next week with one extra transfer.
            plan.append({
                "gw": g,
                "action": "roll",
                "free_transfers_before": ft_before,
                "free_transfers_after": ft_before,
                "hits": 0,
                "hit_cost": 0.0,
                "gw_gain": 0.0,
                "net_gain": 0.0,
                "bank_after": round(bank, 2),
                "moves": [],
                "note": "Roll (counterfactual) — banked the free transfer.",
            })
            continue

        remaining = gws[gi:]
        hz = {pid: _horizon(info, pid, remaining) for pid in info}
        xi = (_xi_floors(squad, info, hz)
              if bool(getattr(config, "TRANSFER_PLAN_XI_AWARE", True)) else None)
        team_counts = {}
        for pid in squad:
            t = info[pid]["team"]
            team_counts[t] = team_counts.get(t, 0) + 1

        pos_mult = getattr(config, "TRANSFER_PLAN_POS_GAIN_MULT", {}) or {}
        opps_gw = (opponents_by_gw or {}).get(g) or {}
        h2h_pen = float(getattr(config, "TRANSFER_H2H_CONFLICT_PENALTY", 0.0) or 0.0)

        if gi == 0:
            # Runner-ups: the best swap for each OTHER squad member, scored
            # on the same pre-move state as the chosen move — before any
            # forced sell or greedy move mutates squad/bank/team_counts.
            unowned0 = [x for x in info if x not in squad]
            runner_up_cands = _ranked_swaps(
                squad, info, unowned0, hz, bank, team_counts, xi, opps_gw, h2h_pen,
                min_gain, pos_mult, int(getattr(config, "TRANSFER_PLAN_RUNNER_UPS", 5)))

        moves, hits = [], 0

        if gi == 0:
            for pid in sorted(forced_sells, key=lambda p: info[p]["xg"].get(g, 0.0)):
                if pid not in squad or len(moves) >= max_moves_per_gw or len(moves) >= ft:
                    break
                unowned = [x for x in info if x not in squad]
                best = _best_swap({pid}, info, unowned, hz, bank, team_counts)
                if best is None:
                    continue
                s, b = best["sell"], best["buy"]
                squad.discard(s)
                squad.add(b)
                bank += info[s]["price"] - info[b]["price"]
                team_counts[info[s]["team"]] = team_counts.get(info[s]["team"], 0) - 1
                team_counts[info[b]["team"]] = team_counts.get(info[b]["team"], 0) + 1
                best["forced_injury"] = True
                moves.append(best)

        # The cap follows the free transfers actually available this GW: 2 FT
        # banked → up to 2 moves may be recommended (each still clears its own
        # bar, and the whole plan still has to beat the roll counterfactual).
        follow_ft = (bool(getattr(config, "TRANSFER_PLAN_MOVES_FOLLOW_FT", True))
                     and not allow_hits)  # a hit IS a move beyond FT — don't clamp it away
        gw_cap = (max(1, min(int(max_moves_per_gw), int(ft)))
                  if follow_ft else int(max_moves_per_gw))
        while len(moves) < gw_cap:
            within_ft = len(moves) < ft
            if not within_ft and not allow_hits:
                break
            threshold = min_gain if within_ft else hit_penalty
            unowned = [pid for pid in info if pid not in squad]
            # Positional bar: the best raw swap may be a GKP/DEF trade that
            # fails its (higher) bar while a slightly smaller MID/FWD gain
            # passes its own — so retry with the failing position excluded
            # instead of giving up on the first miss.
            pool = set(squad)
            best = None
            while pool:
                cand = _best_swap(pool, info, unowned, hz, bank, team_counts, xi=xi,
                                  squad_all=squad, opps_gw=opps_gw, h2h_pen=h2h_pen)
                if cand is None:
                    break
                bar = threshold * float(pos_mult.get(cand["pos"], 1.0))
                if cand["gain"] > bar:
                    best = cand
                    break
                pool = {pid for pid in pool if info[pid]["pos"] != cand["pos"]}
            if best is None:
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
            "moves": [_move_record(m, info, gw=g) for m in moves],
            "note": _note(moves, ft_before, info, gw=g),
        })
        ft = ft_after

        if gi == 0:
            # Drop by buy id, not just the exact (sell, buy) pair: a runner-up
            # naming a player you already just bought (via a different sell)
            # is not "also considered" -- it's the same pick restated.
            chosen_buys = {m["buy"] for m in moves}
            runner_ups = []
            for m in runner_up_cands:
                if m["buy"] in chosen_buys:
                    continue
                dm = _detail_move(_move_record(m, info, gw=g))
                dm["clears_bar"] = bool(m["clears_bar"])
                runner_ups.append(dm)

    verdict, reasoning = _verdict_and_reasoning(plan, min_gain, ft_cap, gws)

    result = {
        "gws": list(gws),
        "horizon_gws": len(gws),
        "start_free_transfers": int(start_ft),
        "ft_cap": int(ft_cap),
        "allow_hits": bool(allow_hits),
        "hit_penalty": float(hit_penalty),
        "total_net_gain": round(total_net, 2),
        "final_bank": round(bank, 2),
        "plan": plan,
        "verdict": verdict,
        "reasoning": reasoning,
        "first_gw_ft_before": plan[0]["free_transfers_before"] if plan else int(start_ft),
        "first_gw_ft_after": (
            min(int(ft_cap), plan[0]["free_transfers_before"] + 1)
            if plan and plan[0]["action"] == "roll"
            else plan[0]["free_transfers_after"] if plan else int(start_ft)
        ),
    }
    result["verdict_detail"] = _verdict_detail(result, min_gain, runner_ups=runner_ups)

    # The user's decision framework, made explicit: a first-GW spend must beat
    # the counterfactual of rolling and having an extra transfer next week.
    # Injury-forced spends are urgency and skip the comparison.
    if (not _skip_first_gw and len(gws) > 1 and plan
            and plan[0]["action"] == "transfer" and verdict != "spend_forced_injury"):
        # The banked FT must actually be spendable next week, or the roll path
        # is judged with one hand tied behind its back.
        alt_cap = max(int(max_moves_per_gw), min(int(ft_cap), int(start_ft) + 1))
        alt = plan_transfers(
            proj, squad_ids, gws, itb_m=itb_m, start_ft=start_ft, ft_cap=ft_cap,
            hit_penalty=hit_penalty, allow_hits=allow_hits, min_gain=min_gain,
            max_moves_per_gw=alt_cap, opponents_by_gw=opponents_by_gw,
            _skip_first_gw=True,
        )
        alt_net = round(float(alt["total_net_gain"]), 2)
        result["roll_alternative_net_gain"] = float(alt_net)
        alt_first = next((p for p in alt["plan"] if p["action"] == "transfer"), None)
        alt_moves_txt = (
            " + ".join(f"{m['sell']['name']} -> {m['buy']['name']}" for m in alt_first["moves"])
            if alt_first else "no move"
        )
        if alt_net > float(result["total_net_gain"]) + 1e-9:
            alt["roll_alternative_net_gain"] = float(alt_net)
            alt["verdict"] = "roll"
            alt["reasoning"] = (
                f"Roll: banking beats moving now (+{round(float(alt_net), 1)} vs "
                f"+{round(float(result['total_net_gain']), 1)} over {_gw_range(gws)}); "
                f"next move {alt_moves_txt} in GW{alt_first['gw'] if alt_first else gws[-1]}."
            )
            alt["verdict_detail"] = _verdict_detail(alt, min_gain, rejected=result)
            alt["verdict_detail"]["runner_ups"] = result["verdict_detail"]["runner_ups"]
            return alt
        result["verdict_detail"] = _verdict_detail(result, min_gain, rejected=alt,
                                                    runner_ups=runner_ups)

    return result


def _gw_range(gws):
    if not gws:
        return "the horizon"
    return f"GW{gws[0]}" if gws[0] == gws[-1] else f"GW{gws[0]}-{gws[-1]}"


def _verdict_and_reasoning(plan, min_gain, ft_cap, gws):
    """Top-level verdict for the first horizon GW: an injury-forced sell always
    wins (it isn't optional), otherwise it's whichever the greedy walk chose
    (spend now vs roll the FT). One clause; the numbers live in verdict_detail."""
    first = plan[0] if plan else None
    rng = _gw_range(gws)
    forced_moves = [m for m in first["moves"] if m.get("forced_injury")] if first else []
    if forced_moves:
        flagged = ", ".join(m["sell"]["name"] for m in forced_moves)
        reasoning = (f"Flagged player ({flagged}) in your likely XI -- replacing "
                     f"them takes priority over rolling, even below the usual gain bar.")
        return "spend_forced_injury", reasoning

    if first and first["action"] == "transfer":
        names = ", ".join(f"{m['sell']['name']} -> {m['buy']['name']}" for m in first["moves"])
        this_gw = round(sum(float(m.get("this_gw_gain", 0.0)) for m in first["moves"]), 1)
        if first.get("hits"):
            reasoning = (f"Move now: {names} (net +{round(float(first['net_gain']), 1)} "
                         f"over {rng} after -{first['hit_cost']:g} in hits).")
        else:
            reasoning = (f"Move now: {names} (+{this_gw} this GW, "
                         f"+{round(float(first['gw_gain']), 1)} over {rng}).")
        return "spend", reasoning

    if first:
        ft_after = min(int(ft_cap), first["free_transfers_before"] + 1)
        nxt = next((p for p in plan[1:] if p["action"] == "transfer"), None)
        if nxt:
            names = ", ".join(f"{m['sell']['name']} -> {m['buy']['name']}" for m in nxt["moves"])
            follow = (f" Next planned move: {names} in GW{nxt['gw']} "
                      f"(+{round(float(nxt['gw_gain']), 1)}).")
        else:
            follow = f" No move clears +{min_gain} over {rng}."
        reasoning = (f"Roll: bank the FT ({first['free_transfers_before']}->{ft_after})."
                     f"{follow}")
        return "roll", reasoning

    return "roll", "No horizon GWs."
