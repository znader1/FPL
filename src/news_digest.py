"""Phase 2: semi-auto news digestion for the player-knowledge rail.

Reads the pre-digested kb/auto/news/*.md corpus (title + metadata + Summary /
FPL takeaways / Entities / Tags), entity-matches the article Players to
bootstrap web_names (no embeddings), and asks an LLM to PROPOSE player-knowledge
entries (availability / return-GW / minutes) with the source article cited.

Nothing is applied here -- the caller (endpoint + UI) reviews the proposals and
writes approved ones to player_knowledge.json via the Phase 1 rail. The LLM call
is dependency-injected (`generate`) so tests run without the network.
"""
import glob
import json
import os
import re
from datetime import date, timedelta

from src import config
from src.player_knowledge import _norm

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_OUT_STATUS = {"i", "s", "u", "n"}  # injured / suspended / unavailable / not-in-squad
_STATUS_NOTE = {"i": "injured", "s": "suspended", "u": "unavailable", "n": "not in squad"}

SYSTEM = (
    "You are an FPL analyst. Given recent news about ONE player, decide if there "
    "is a concrete AVAILABILITY or MINUTES signal for the upcoming gameweeks. "
    "Injuries, suspensions, expected return dates, rotation risk, losing/gaining a "
    "starting role count. Transfer rumours, goals, or generic praise DO NOT. "
    "Respond with ONLY a JSON object, no prose:\n"
    '{"change": bool, "availability": 0..1, "available_from_gw": int|null, '
    '"minutes_mult": 0..1.2, "note": "<=12 words"}. '
    "If there is no concrete signal, return {\"change\": false}. "
    "availability: 1 fit, 0.5 doubt, 0 out. minutes_mult: 1 nailed, <1 rotation risk."
)


def _parse_article(text, path):
    lines = text.splitlines()
    title = next((ln[2:].strip() for ln in lines if ln.startswith("# ")), "")

    def meta(key):
        m = re.search(rf"^- {key}:\s*(.+)$", text, re.MULTILINE)
        return m.group(1).strip() if m else None

    sections, cur, buf = {}, None, []
    for ln in lines:
        h = re.match(r"^##\s+(.+)$", ln)
        if h:
            if cur is not None:
                sections[cur] = "\n".join(buf).strip()
            cur, buf = h.group(1).strip().lower(), []
        elif cur is not None:
            buf.append(ln)
    if cur is not None:
        sections[cur] = "\n".join(buf).strip()

    players = []
    pm = re.search(r"^-?\s*Players:\s*(.+)$", sections.get("entities", ""), re.MULTILINE)
    if pm:
        players = [p.strip() for p in pm.group(1).split(",") if p.strip()]
    tags = [re.sub(r"^-\s*", "", l).strip() for l in sections.get("tags", "").splitlines() if l.strip()]
    return {
        "path": path, "title": title, "source": meta("Source"), "url": meta("URL"),
        "published": meta("Published"), "fetched": meta("Fetched"),
        "summary": sections.get("summary", ""),
        "fpl_takeaways": sections.get("fpl takeaways", ""),
        "players": players, "tags": tags,
    }


def load_news_articles(kb_dir=None):
    kb_dir = kb_dir or getattr(config, "NEWS_KB_DIR", "kb/auto/news")
    out = []
    for path in sorted(glob.glob(os.path.join(kb_dir, "**", "*.md"), recursive=True)):
        try:
            with open(path) as f:
                out.append(_parse_article(f.read(), path))
        except OSError:
            continue
    return out


def index_by_player(articles, elements):
    """{player_id: [article, ...]} by matching article Players to bootstrap
    web_names (normalized; surname/token fallback). Unmatched names dropped."""
    idx = {}
    if elements is not None and {"id", "web_name"}.issubset(elements.columns):
        for _, r in elements.iterrows():
            idx.setdefault(_norm(r["web_name"]), int(r["id"]))
    out = {}
    for a in articles:
        seen = set()
        for name in a["players"]:
            nm = _norm(name)
            tokens = nm.split()
            pid = idx.get(nm) or (idx.get(tokens[-1]) if tokens else None)
            if pid is None:
                for t in tokens:
                    if t in idx:
                        pid = idx[t]
                        break
            if pid is not None and pid not in seen:
                out.setdefault(pid, []).append(a)
                seen.add(pid)
    return out


# --- Approach A: live bootstrap-news digester (first-party, no LLM) ----------

def _event_date(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _parse_return_gw(news_text, events):
    """Map an expected-return date in the bootstrap `news` text ("Expected back
    21 Aug", "Suspended until 29 Aug") to the id of the first event whose
    deadline is on/after that date. Returns None if no date is present, and
    (last_gw + 1) if the return falls past every known event (still out all
    horizon). The year is inferred from the events' date range."""
    if not news_text:
        return None
    m = re.search(r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",
                  news_text, re.IGNORECASE)
    if not m:
        return None
    day, mon = int(m.group(1)), _MONTHS[m.group(2).lower()[:3]]
    evs = [(int(e["id"]), _event_date(e.get("deadline_time"))) for e in (events or [])]
    evs = [(i, d) for i, d in evs if d]
    if not evs:
        return None
    evs.sort(key=lambda x: x[1])
    first = evs[0][1]
    cands = []
    for y in sorted({d.year for _, d in evs}):
        try:
            cands.append(date(y, mon, day))
        except ValueError:
            continue
    if not cands:
        return None
    window = [d for d in cands if d >= first - timedelta(days=45)]
    target = min(window) if window else min(cands)
    for i, d in evs:
        if d >= target:
            return i
    return evs[-1][0] + 1


def digest_bootstrap_news(elements, events, current_gw=1):
    """Turn the live FPL bootstrap injury signals (status / news /
    chance_of_playing_next_round) into PROPOSED player-knowledge entries. Same
    schema as the manual rail; source="fpl_bootstrap". Available players are
    skipped. No network, no LLM -- this is first-party truth fetched on every
    build."""
    players = {}
    if elements is None or "id" not in getattr(elements, "columns", []):
        return {"players": players}
    for _, r in elements.iterrows():
        status = str(r.get("status") or "").strip().lower()
        news = str(r.get("news") or "").strip()
        chance = r.get("chance_of_playing_next_round")
        try:
            chance = None if chance is None or chance != chance else float(chance)
        except (TypeError, ValueError):
            chance = None

        if status in _OUT_STATUS:
            rgw = _parse_return_gw(news, events)
            if rgw is not None:
                if rgw <= int(current_gw):
                    continue  # already back by the first projected GW
                entry = {"availability": 1.0, "available_from_gw": rgw}
            else:
                entry = {"availability": 0.0, "available_from_gw": None}
        elif status == "d":
            av = chance / 100.0 if chance is not None else 0.5
            if av >= 1.0:
                continue
            entry = {"availability": round(av, 3), "available_from_gw": None}
        else:
            continue  # 'a' (available) or unknown -> nothing to flag

        entry.update({
            "minutes_mult": 1.0,
            "note": news or _STATUS_NOTE.get(status, status),
            "source": "fpl_bootstrap",
        })
        players[str(int(r["id"]))] = entry
    return {"players": players}


def merge_proposals(article, bootstrap):
    """Combine article-derived and bootstrap-derived proposals. Bootstrap wins
    on player-id conflict (first-party injury truth beats a scraped rumour);
    article-only entries are kept for narrative/rotation signal."""
    merged = dict((article or {}).get("players", {}))
    merged.update((bootstrap or {}).get("players", {}))
    return {"players": merged}


def _extract_json(raw):
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    return m.group(0) if m else raw


def _anthropic_generate(prompt, model=None):
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    model = model or os.environ.get("FPL_EXPLAIN_MODEL", "claude-haiku-4-5-20251001")
    msg = client.messages.create(
        model=model, max_tokens=400, system=SYSTEM,
        messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text


def _build_prompt(name, articles, current_gw):
    blocks = []
    for a in articles[:4]:
        blocks.append(
            f"Title: {a['title']}\nTags: {', '.join(a['tags'])}\n"
            f"Summary:\n{a['summary']}\nFPL takeaways:\n{a['fpl_takeaways']}")
    return (f"Player: {name}\nUpcoming gameweek: {current_gw}\n\n"
            + "\n---\n".join(blocks))


def propose_player_knowledge(player_to_articles, elements, generate=None, current_gw=1):
    """Return {"players": {id: entry}} of PROPOSED entries. Applies nothing.
    `generate(prompt) -> str(json)` is injectable; defaults to Anthropic."""
    generate = generate or _anthropic_generate
    id_to_name = {}
    if elements is not None and {"id", "web_name"}.issubset(elements.columns):
        id_to_name = dict(zip(elements["id"].astype(int), elements["web_name"]))
    players = {}
    for pid, arts in player_to_articles.items():
        try:
            raw = generate(_build_prompt(id_to_name.get(int(pid), pid), arts, current_gw))
            entry = json.loads(_extract_json(raw))
        except Exception:
            continue
        if not isinstance(entry, dict) or not entry.get("change"):
            continue
        players[str(int(pid))] = {
            "availability": entry.get("availability", 1.0),
            "available_from_gw": entry.get("available_from_gw"),
            "minutes_mult": entry.get("minutes_mult", 1.0),
            "note": (entry.get("note") or "").strip(),
            "source": arts[0]["path"],
        }
    return {"players": players}
