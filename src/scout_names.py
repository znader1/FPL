"""Match a Scout article's "Name (Club)" to an FPL player id.

The Scout writes full names in plain ASCII with a club ("Djordje Petrovic
(AFC Bournemouth)"); FPL carries a short display name with diacritics
("Petrović", BOU). The club is always part of the match: a bare surname can
belong to two players in the league. Anything that is not exactly one player
comes back unmatched with a reason, never a best guess, because a wrong match
would score the wrong player on the monitoring dashboard.
"""
from __future__ import annotations

import html
import re
import unicodedata

# Letters NFKD does not decompose into base + accent.
TRANSLIT = {"đ": "dj", "ß": "ss", "ø": "o", "ł": "l", "æ": "ae", "þ": "th"}

# The Scout's club spellings that differ from FPL's `name` / `short_name`.
CLUB_ALIASES = {
    "AFC Bournemouth": "BOU", "Bournemouth": "BOU",
    "Spurs": "TOT", "Tottenham Hotspur": "TOT", "Tottenham": "TOT",
    "Man City": "MCI", "Manchester City": "MCI",
    "Man Utd": "MUN", "Manchester United": "MUN", "Man United": "MUN",
    "Brighton": "BHA", "Brighton & Hove Albion": "BHA", "Brighton and Hove Albion": "BHA",
    "Nott'm Forest": "NFO", "Nottingham Forest": "NFO",
    "Wolves": "WOL", "Wolverhampton Wanderers": "WOL",
    "West Ham": "WHU", "West Ham United": "WHU",
    "Newcastle": "NEW", "Newcastle United": "NEW",
}


def normalise(text):
    """Lower-case ASCII words separated by single spaces."""
    s = html.unescape(str(text or "")).lower()
    s = "".join(TRANSLIT.get(ch, ch) for ch in s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def club_short(club_raw, teams):
    """The FPL short name for a club as the Scout wrote it, or None."""
    shorts = {str(t.get("short_name")) for t in teams or [] if t.get("short_name")}
    lookup = {}
    for alias, short in CLUB_ALIASES.items():
        if short in shorts:
            lookup[normalise(alias)] = short
    for t in teams or []:
        short = t.get("short_name")
        if not short:
            continue
        lookup[normalise(short)] = str(short)
        if t.get("name"):
            lookup[normalise(t["name"])] = str(short)
    wanted = normalise(club_raw)
    if wanted in lookup:
        return lookup[wanted]
    # "Coventry" for "Coventry City", "Leeds United" for "Leeds": accept a whole-word
    # prefix either way, but only when exactly one club fits ("Man" fits two).
    fits = {short for name, short in lookup.items()
            if wanted and (name.startswith(wanted + " ") or wanted.startswith(name + " "))}
    return fits.pop() if len(fits) == 1 else None


def _candidates(name, pool):
    """Players matching `name`, by the first rule that matches anyone."""
    tokens = set(name.split())
    first, rest = name.split()[:1], set(name.split()[1:])

    def full_tokens(p):
        return set(normalise(
            f"{p.get('first_name') or ''} {p.get('second_name') or ''} {p.get('web_name') or ''}").split())

    def short_first_name(p):
        # "Dan Ballard" for Daniel Ballard: the surname part matches in full and the
        # first name is a shortening (3+ letters) of his, or the other way round.
        if not first or not rest or not rest <= full_tokens(p):
            return False
        return any(len(first[0]) >= 3 and len(t) >= 3 and (t.startswith(first[0]) or first[0].startswith(t))
                   for t in normalise(p.get("first_name")).split())

    rules = (
        lambda p: normalise(p.get("web_name")) == name,
        lambda p: normalise(f"{p.get('first_name') or ''} {p.get('second_name') or ''}") == name,
        lambda p: bool(tokens) and tokens <= full_tokens(p),
        short_first_name,
    )
    for rule in rules:
        hits = [p for p in pool if rule(p)]
        if hits:
            return hits
    return []


def match_player(name_raw, club_raw, players, teams, overrides=None):
    """→ {"player_id": int | None, "status": matched | override | ambiguous | not_found | unknown_club}.

    `players` rows: id, first_name, second_name, web_name, team_short.
    `overrides`: {"<normalised name>|<SHORT>": player_id} for names no rule resolves.
    """
    short = club_short(club_raw, teams)
    if short is None:
        return {"player_id": None, "status": "unknown_club"}
    name = normalise(name_raw)
    pinned = (overrides or {}).get(f"{name}|{short}")
    if pinned is not None:
        return {"player_id": int(pinned), "status": "override"}
    pool = [p for p in players or [] if str(p.get("team_short")) == short]
    hits = _candidates(name, pool)
    if len(hits) == 1:
        return {"player_id": int(hits[0]["id"]), "status": "matched"}
    return {"player_id": None, "status": "ambiguous" if hits else "not_found"}
