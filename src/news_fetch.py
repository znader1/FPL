"""Approach B: refresh the news corpus from live RSS feeds.

Fetches the source RSS feeds (verified live: sportsmole / football-talk /
betfair), keeps only recent items, and asks Claude to digest each NEW article's
title+summary into the same markdown format the Phase-2 pipeline already reads
(`# title`, `- Source/URL/Published/Fetched`, `## Summary/Entities/Tags`). The
digested md drops into `kb/auto/news/<domain>/` so `news_digest` picks it up.

Network + LLM are dependency-injected (`fetch`, `generate`, `now`) so the whole
module tests offline. See scripts/refresh_news.py for the runnable routine.
"""
import glob
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from src import config
from src.news_digest import _extract_json, _parse_article

_ATOM = {"a": "http://www.w3.org/2005/Atom"}

SYSTEM = (
    "You are an FPL analyst. Summarise this football news item for Fantasy "
    "Premier League managers. Respond with ONLY a JSON object, no prose:\n"
    '{"summary": ["<=5 short bullets"], "players": ["Full Name", ...], '
    '"teams": ["Team", ...], "tags": ["injury"|"suspension"|"rotation"|'
    '"transfer"|"return"|"lineup", ...]}. '
    "players/teams: only those explicitly named. Keep it factual."
)


def domain_of(url):
    net = urlparse(url).netloc.lower()
    return net[4:] if net.startswith("www.") else net


def _clean_html(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _parse_date(s):
    """Parse an RFC-822 (RSS pubDate) or ISO-8601 (Atom) date to a tz-aware
    UTC datetime; naive inputs are assumed UTC. Returns None on failure."""
    if not s:
        return None
    dt = None
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _text(el):
    return (el.text or "").strip() if el is not None else ""


def parse_feed(xml_data, source):
    """Parse RSS 2.0 (<item>) or Atom (<entry>) into a list of entry dicts."""
    root = ET.fromstring(xml_data.encode() if isinstance(xml_data, str) else xml_data)
    entries = []
    items = root.findall(".//item")
    if items:
        for it in items:
            pub = _text(it.find("pubDate"))
            entries.append({
                "source": source,
                "title": _text(it.find("title")),
                "url": _text(it.find("link")),
                "published": _parse_date(pub),
                "published_raw": pub,
                "summary": _clean_html(_text(it.find("description"))),
            })
        return entries
    for it in root.findall(".//a:entry", _ATOM):
        pub = _text(it.find("a:published", _ATOM)) or _text(it.find("a:updated", _ATOM))
        link = it.find("a:link", _ATOM)
        entries.append({
            "source": source,
            "title": _text(it.find("a:title", _ATOM)),
            "url": link.get("href") if link is not None else "",
            "published": _parse_date(pub),
            "published_raw": pub,
            "summary": _clean_html(_text(it.find("a:summary", _ATOM))
                                   or _text(it.find("a:content", _ATOM))),
        })
    return entries


def recent(entries, max_age_days, now):
    cutoff = now - timedelta(days=max_age_days)
    return [e for e in entries if e["published"] and e["published"] >= cutoff]


def _slug(entry):
    path = urlparse(entry["url"]).path.rstrip("/")
    base = os.path.basename(path) or re.sub(r"[^a-z0-9]+", "-", entry["title"].lower()).strip("-")
    base = re.sub(r"\.(html?|php)$", "", base)
    return (base or "article")[:120]


def article_to_markdown(entry, generate, now, elements=None):
    """Claude-digest an entry's title+summary into the shared md format."""
    prompt = f"Title: {entry['title']}\n\nSummary:\n{entry['summary']}"
    data = json.loads(_extract_json(generate(SYSTEM + "\n\n" + prompt)))
    summary = data.get("summary") or []
    players = data.get("players") or []
    teams = data.get("teams") or []
    tags = data.get("tags") or []
    fetched = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"# {entry['title']}", "",
        f"- Source: {entry['source']}",
        f"- URL: {entry['url']}",
        f"- Published: {entry.get('published_raw') or ''}",
        f"- Fetched: {fetched}", "",
        "## Summary",
        *[f"- {s}" for s in summary], "",
        "## Entities",
        f"- Players: {', '.join(players)}",
        f"- Teams: {', '.join(teams)}", "",
        "## Tags",
        *[f"- {t}" for t in tags], "",
    ]
    return "\n".join(lines)


def write_article(kb_dir, entry, md):
    out_dir = os.path.join(kb_dir, entry["source"])
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, _slug(entry) + ".md")
    with open(path, "w") as f:
        f.write(md)
    return path


def existing_urls(kb_dir):
    urls = set()
    for path in glob.glob(os.path.join(kb_dir, "**", "*.md"), recursive=True):
        try:
            with open(path) as f:
                a = _parse_article(f.read(), path)
        except OSError:
            continue
        if a.get("url"):
            urls.add(a["url"])
    return urls


def prune_stale(kb_dir, max_age_days, now):
    """Delete digested md whose Published date is older than the cutoff."""
    cutoff = now - timedelta(days=max_age_days)
    removed = []
    for path in glob.glob(os.path.join(kb_dir, "**", "*.md"), recursive=True):
        try:
            with open(path) as f:
                a = _parse_article(f.read(), path)
        except OSError:
            continue
        pub = _parse_date(a.get("published"))
        if pub and pub < cutoff:
            os.remove(path)
            removed.append(path)
    return removed


def _http_get(url):  # pragma: no cover - network
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def refresh(kb_dir=None, feeds=None, max_age_days=None, now=None,
            fetch=_http_get, generate=None):
    """Fetch all feeds, digest new (unseen) recent articles via Claude, write
    them to kb, and prune stale md. Returns a summary dict. Injectable for
    tests; defaults hit the live network + Claude."""
    kb_dir = kb_dir or getattr(config, "NEWS_KB_DIR", "kb/auto/news")
    feeds = feeds if feeds is not None else getattr(config, "NEWS_FEEDS", [])
    max_age_days = max_age_days if max_age_days is not None else getattr(config, "NEWS_MAX_AGE_DAYS", 14)
    now = now or datetime.now(timezone.utc)
    if generate is None:
        from src.news_digest import _anthropic_generate as generate
    seen = existing_urls(kb_dir)
    written, errors = [], []
    for feed in feeds:
        try:
            entries = recent(parse_feed(fetch(feed["url"]), feed["source"]),
                             max_age_days, now)
        except Exception as e:  # noqa: BLE001 - one bad feed shouldn't kill the run
            errors.append(f"{feed.get('source')}: {e}")
            continue
        for e in entries:
            if not e["url"] or e["url"] in seen:
                continue
            try:
                write_article(kb_dir, e, article_to_markdown(e, generate, now))
                written.append(e["url"])
                seen.add(e["url"])
            except Exception as ex:  # noqa: BLE001
                errors.append(f"{e['url']}: {ex}")
    pruned = prune_stale(kb_dir, max_age_days, now)
    return {"written": written, "pruned": pruned, "errors": errors}
