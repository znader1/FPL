from src import fpl_client


def list_user_leagues(entry_id):
    info = fpl_client.get_entry(entry_id)
    leagues = (info.get("leagues") or {}).get("classic") or []
    return [
        {
            "id": l.get("id"),
            "name": l.get("name"),
            "entry_rank": l.get("entry_rank"),
            "entry_last_rank": l.get("entry_last_rank"),
            "league_type": l.get("league_type"),
            "scoring": l.get("scoring"),
            "size": l.get("rank_count") or l.get("admin_entry"),
        }
        for l in leagues
        if l.get("id") is not None
    ]


def fetch_league_standings(league_id, max_entries=50):
    standings_payload = fpl_client.get_classic_league_standings(league_id)
    league_meta = standings_payload.get("league") or {}
    results = ((standings_payload.get("standings") or {}).get("results")) or []
    return {
        "league_id": league_meta.get("id"),
        "league_name": league_meta.get("name"),
        "entries": [
            {
                "entry_id": r.get("entry"),
                "player_name": r.get("player_name"),
                "entry_name": r.get("entry_name"),
                "rank": r.get("rank"),
                "last_rank": r.get("last_rank"),
                "total": r.get("total"),
                "event_total": r.get("event_total"),
            }
            for r in results[:max_entries]
        ],
    }


def find_user_position(standings, entry_id):
    for idx, e in enumerate(standings["entries"]):
        if int(e.get("entry_id") or 0) == int(entry_id):
            return idx, e
    return None, None


def neighbours(standings, entry_id, above=2, below=2):
    idx, _ = find_user_position(standings, entry_id)
    if idx is None:
        return {"above": [], "below": []}
    entries = standings["entries"]
    return {
        "above": entries[max(0, idx - above): idx],
        "below": entries[idx + 1: idx + 1 + below],
    }


def fetch_rival_squad(entry_id, event_id):
    picks = fpl_client.get_entry_picks(entry_id, event_id)
    return {
        "entry_id": entry_id,
        "event_id": event_id,
        "active_chip": picks.get("active_chip"),
        "picks": [
            {
                "element": p.get("element"),
                "position": p.get("position"),
                "is_captain": p.get("is_captain"),
                "is_vice_captain": p.get("is_vice_captain"),
                "multiplier": p.get("multiplier"),
            }
            for p in (picks.get("picks") or [])
        ],
    }


def league_ownership(rival_squads):
    counts = {}
    n = max(1, len(rival_squads))
    for sq in rival_squads:
        for p in sq.get("picks") or []:
            pid = p.get("element")
            if pid is None:
                continue
            counts[pid] = counts.get(pid, 0) + 1
    return {pid: c / n for pid, c in counts.items()}


def differentials(my_picks, rival_picks_by_entry):
    my_ids = {p.get("element") for p in my_picks if p.get("element") is not None}
    rival_union = set()
    for picks in rival_picks_by_entry.values():
        for p in picks:
            if p.get("element") is not None:
                rival_union.add(p.get("element"))
    return {
        "owned_by_me_not_rivals": sorted(my_ids - rival_union),
        "owned_by_rivals_not_me": sorted(rival_union - my_ids),
        "shared": sorted(my_ids & rival_union),
    }
