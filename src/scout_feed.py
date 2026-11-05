"""Read The Scout's FPL articles from the Premier League content feed.

Pure parsing only (the network calls live in scripts/monitor_backfill.py).
The feed returns each article as JSON with an HTML `body`. Two formats exist:

* Scout Selection and the transfer radar: one ``<h5>`` per player,
  ``Name (Club) £X.Xm``. Parsed by rule.
* The season-start squad and the wildcard squads: prose under thematic
  headings. No rule can read their fifteen, so they come back with no players
  and ``needs_review``; the picks are entered by hand in the overrides file and
  count only once the owner has confirmed them.

Nothing here guesses: a missing captain stays missing, an article with the
wrong number of players is flagged, never padded or trimmed.
"""
from __future__ import annotations

import html
import re

ARTICLE_URL = "https://www.premierleague.com/en/news/{id}"
SELECTION_SIZE = 11
SQUAD_SIZE = 15
REASON_MAX_CHARS = 300

_GW = re.compile(r"\b(?:gameweek|gw)\s*(\d{1,2})\b")
_HEADING = re.compile(r"<h5[^>]*>(.*?)</h5>", re.S | re.I)
_PARAGRAPH = re.compile(r"<p[^>]*>(.*?)</p>", re.S | re.I)
_PLAYER_HEADING = re.compile(r"^(?P<name>.+?)\s*\((?P<club>[^()]+)\)\s*£\s*(?P<price>\d+(?:\.\d+)?)m$")
_VICE = re.compile(r"vice-captain", re.I)
_CAPTAIN_CUE = re.compile(r"(?<!vice-)captain|armband", re.I)   # "captain" on its own, not inside "vice-captain"
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# A section that talks about the decision itself ("the captaincy decision", "captain
# favourite"), not one that merely calls a player an alternative or a club captain.
_CAPTAIN_DECISION = re.compile(
    r"captaincy decision|armband decision|captain (?:choice|favourite)|captaincy (?:choice|pick)", re.I)


def _text(fragment):
    """HTML fragment → plain text with single spaces."""
    s = re.sub(r"<[^>]+>", " ", str(fragment or ""))
    s = html.unescape(s).replace("\xa0", " ")
    return " ".join(s.split())


def _strip_code(body):
    return re.sub(r"<(script|style)\b.*?</\1>", " ", str(body or ""), flags=re.S | re.I)


def classify_article(title):
    """→ (series, gw) for a Scout article this dashboard uses, else None."""
    t = str(title or "").replace("’", "'").lower()
    if "scout selection" in t and "best fantasy squad for 20" in t:
        return ("season_squad", 1)
    m = _GW.search(t)
    if not m:
        return None
    gw = int(m.group(1))
    if "scout selection" in t and "best fantasy team" in t:
        return ("selection", gw)
    if "transfer radar" in t:
        return ("transfer_radar", gw)
    if "wildcard squad" in t or "squad for wildcarders" in t:
        return ("wildcard", gw)
    return None


def pick_articles(listing, season_start, overrides=None):
    """Feed items → {(gw, series): item}. Items before `season_start` (ISO date)
    are another season's. Two items for one key: the latest published wins,
    unless the overrides pin an article id for that key."""
    pins = (overrides or {}).get("pins") or {}
    out = {}
    for item in listing or []:
        if str(item.get("date") or "") < str(season_start):
            continue
        cls = classify_article(item.get("title"))
        if cls is None:
            continue
        series, gw = cls
        key = (gw, series)
        pinned = pins.get(f"{gw}|{series}")
        if pinned is not None:
            if int(item.get("id")) == int(pinned):
                out[key] = item
            continue
        if key not in out or str(item.get("date")) > str(out[key].get("date")):
            out[key] = item
    return out


def _sections(body):
    """[(heading text, section html)] for every <h5>; a section runs to the next <h5>."""
    body = _strip_code(body)
    heads = list(_HEADING.finditer(body))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        out.append((_text(m.group(1)), body[m.end():end]))
    return out


def _section_text(section_html):
    return " ".join(t for t in (_text(p) for p in _PARAGRAPH.findall(section_html)) if t)


def parse_players(body_html):
    """One row per <h5> heading of the form `Name (Club) £X.Xm`."""
    players = []
    for heading, section in _sections(body_html):
        m = _PLAYER_HEADING.match(heading)
        if not m:
            continue
        players.append({
            "name_raw": m.group("name").strip(),
            "club_raw": m.group("club").strip(),
            "price_m": float(m.group("price")),
            "reason": _section_text(section)[:REASON_MAX_CHARS].strip(),
        })
    return players


def _mentions(sentence, names):
    """[(start, end, name)] of listed players named in a sentence, in order. A
    player is named by his full name or by his surname alone, the latter only
    when no other listed player shares it."""
    surnames = [n.split()[-1] for n in names]
    found = []
    for name, surname in zip(names, surnames):
        at, length = sentence.find(name), len(name)
        if at < 0 and surnames.count(surname) == 1:
            m = re.search(rf"(?<![\w-]){re.escape(surname)}(?![\w-])", sentence)
            at, length = (m.start(), len(surname)) if m else (-1, 0)
        if at >= 0:
            found.append((at, at + length, name))
    return sorted(found)


def _gap(a, b):
    """Characters between two spans (0 when they touch or overlap)."""
    return max(a[0] - b[1], b[0] - a[1], 0)


def _assign_roles(named, vice_span, cue_spans):
    """(captain, vice) for two named players, or None when the sentence does not
    settle it. Each player belongs with the word he stands nearest: the pairing
    with the smaller total distance to "vice-captain" and to a captain cue wins.
    A dead heat ("X and Y are named captain and vice-captain respectively") is
    read in order, but only when both names sit on the same side of both words."""
    first, second = named

    def to_cue(mention):
        return min(_gap(mention[:2], c) for c in cue_spans)

    first_is_vice = _gap(first[:2], vice_span) + to_cue(second)
    second_is_vice = _gap(second[:2], vice_span) + to_cue(first)
    if first_is_vice < second_is_vice:
        return second[2], first[2]
    if second_is_vice < first_is_vice:
        return first[2], second[2]
    words = sorted([("vice", vice_span)] + [("captain", c) for c in cue_spans], key=lambda w: w[1])
    before = second[1] <= words[0][1][0]
    after = first[0] >= words[-1][1][1]
    if before or after:
        return (first[2], second[2]) if words[0][0] == "captain" else (second[2], first[2])
    return None


def parse_captain(body_html, players):
    """→ {"captain", "vice", "stated", "inferred", "unclear"} (names as written, or None).

    Stated: the Scout names captain and vice-captain together in one sentence,
    in wording that changes weekly ("X earns the captain's armband, with Y named
    as vice-captain", "X and Y are named captain and vice-captain respectively",
    "Y is handed the vice-captaincy, with X taking the armband"). A sentence is
    the statement only when it has "vice-captain", a captain cue of its own
    ("captain" or "armband") and exactly two listed players. The vice is the one
    named nearest the word "vice-captain", whichever side; the other is captain.

    A "vice-captain" sentence that does not meet that is `unclear`: nothing is
    stated and the article is flagged, because a wrong captain doubles the wrong
    player's points.

    Inferred: nothing stated, and exactly one player's own section discusses the
    captaincy decision. Kept apart from a statement, and deliberately narrow: a
    team-mate called "an alternative for the captaincy" or "the Arsenal captain"
    is not the pick.
    """
    names = [p["name_raw"] for p in players or [] if p.get("name_raw")]
    body = _strip_code(body_html)
    unclear = False
    for para in _PARAGRAPH.findall(body):
        for sentence in _SENTENCE_END.split(_text(para)):
            word = _VICE.search(sentence)
            if not word:
                continue
            named = _mentions(sentence, names)
            cues = [m.span() for m in _CAPTAIN_CUE.finditer(sentence)]
            roles = _assign_roles(named, word.span(), cues) if len(named) == 2 and cues else None
            if roles is None:
                unclear = True
                continue
            captain, vice = roles
            return {"captain": captain, "vice": vice, "stated": True, "inferred": None, "unclear": False}
    if unclear:
        return {"captain": None, "vice": None, "stated": False, "inferred": None, "unclear": True}
    hinted = []
    for heading, section in _sections(body):
        m = _PLAYER_HEADING.match(heading)
        if m and _CAPTAIN_DECISION.search(_section_text(section)):
            hinted.append(m.group("name").strip())
    inferred = hinted[0] if len(hinted) == 1 else None
    return {"captain": None, "vice": None, "stated": False, "inferred": inferred, "unclear": False}


def _review(series, players, from_override, confirmed, captain_unclear=False):
    """→ (needs_review, reason)."""
    n = len(players)
    if series is None:
        return True, "article type not recognised from its title"
    if series == "selection" and n != SELECTION_SIZE:
        return True, f"expected {SELECTION_SIZE} players, found {n}"
    if series == "selection" and captain_unclear:
        return True, "the captain sentence could not be read"
    if series == "transfer_radar" and n == 0:
        return True, "no player headings found"
    if series in ("wildcard", "season_squad"):
        if not from_override:
            return True, "squad article written as prose: the fifteen must be entered by hand"
        if n != SQUAD_SIZE:
            return True, f"expected {SQUAD_SIZE} players, found {n}"
        if not confirmed:
            return True, "hand-entered squad not yet confirmed by the owner"
    return False, None


def parse_article(article, overrides):
    """One feed article → the picks it publishes, flagged when a rule cannot read it.

    `overrides["articles"][<id>]` may carry `players` ([{name, club}]) for a
    prose squad, `confirmed_by_owner`, and `series` / `gw` to correct the title.
    """
    aid = int(article["id"])
    ov = ((overrides or {}).get("articles") or {}).get(str(aid)) or {}
    cls = classify_article(article.get("title"))
    series = ov.get("series") or (cls[0] if cls else None)
    gw = ov.get("gw") or (cls[1] if cls else None)

    from_override = bool(ov.get("players"))
    if from_override:
        players = [{"name_raw": str(p["name"]), "club_raw": str(p["club"]), "price_m": None, "reason": ""}
                   for p in ov["players"]]
        cap = {"captain": ov.get("captain"), "vice": ov.get("vice"),
               "stated": bool(ov.get("captain")), "inferred": None, "unclear": False}
    else:
        players = parse_players(article.get("body"))
        cap = parse_captain(article.get("body"), players)

    needs_review, reason = _review(series, players, from_override, bool(ov.get("confirmed_by_owner")),
                                   captain_unclear=cap["unclear"])
    return {
        "series": series,
        "gw": int(gw) if gw is not None else None,
        "article_id": aid,
        "url": ARTICLE_URL.format(id=aid),
        "title": article.get("title"),
        "published_at": article.get("date"),
        "players": players,
        "captain": cap["captain"],
        "vice": cap["vice"],
        "captain_stated": cap["stated"],
        "captain_inferred": cap["inferred"],
        "needs_review": needs_review,
        "review_reason": reason,
    }
