import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from src import llm


UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def now_utc_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha1(s):
    return hashlib.sha1((s or "").encode("utf-8", errors="ignore")).hexdigest()


def slugify(s, max_len=80):
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if not s:
        s = "item"
    return s[: int(max_len)]


def read_text(path):
    return Path(path).read_text(encoding="utf-8", errors="ignore")


def write_text(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return str(p)


def load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(read_text(p))
    except Exception:
        return default


def save_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch_url(url, timeout_s=20):
    r = requests.get(
        url,
        headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        timeout=int(timeout_s),
    )
    r.raise_for_status()
    return r.text


def strip_ns(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def parse_feed_xml(xml_text):
    """
    Parse RSS2 or Atom into a list of items:
      {"id","title","url","published","summary"}
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []

    items = []

    root_tag = strip_ns(root.tag).lower()
    if root_tag == "rss":
        channel = None
        for child in root:
            if strip_ns(child.tag).lower() == "channel":
                channel = child
                break
        if channel is None:
            return []

        for it in channel:
            if strip_ns(it.tag).lower() != "item":
                continue
            title = ""
            link = ""
            guid = ""
            pub = ""
            desc = ""
            for f in it:
                k = strip_ns(f.tag).lower()
                v = (f.text or "").strip()
                if k == "title":
                    title = v
                elif k == "link":
                    link = v
                elif k == "guid":
                    guid = v
                elif k == "pubdate":
                    pub = v
                elif k == "description":
                    desc = v
            url = link or guid
            if not url:
                continue
            items.append(
                {
                    "id": guid or url,
                    "title": title or url,
                    "url": url,
                    "published": pub,
                    "summary": desc,
                }
            )
        return items

    # Atom
    if root_tag == "feed":
        for entry in root:
            if strip_ns(entry.tag).lower() != "entry":
                continue
            title = ""
            url = ""
            eid = ""
            pub = ""
            summary = ""
            for f in entry:
                k = strip_ns(f.tag).lower()
                if k == "title":
                    title = (f.text or "").strip()
                elif k == "id":
                    eid = (f.text or "").strip()
                elif k in ("updated", "published"):
                    pub = (f.text or "").strip() or pub
                elif k == "link":
                    href = (f.attrib or {}).get("href")
                    rel = (f.attrib or {}).get("rel", "alternate")
                    if href and (not url) and rel in ("alternate", ""):
                        url = href.strip()
                elif k in ("summary", "content"):
                    summary = (f.text or "").strip() or summary

            if not url:
                continue
            items.append(
                {
                    "id": eid or url,
                    "title": title or url,
                    "url": url,
                    "published": pub,
                    "summary": summary,
                }
            )
        return items

    return []


def html_to_text(html):
    """
    Best-effort visible text extraction without extra deps.
    Keeps paragraphs separated.
    """
    import html as html_mod

    h = html or ""
    # drop scripts/styles
    h = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\\1>", " ", h)
    # prefer paragraph text
    paras = re.findall(r"(?is)<p\\b[^>]*>(.*?)</p>", h)
    if paras:
        txt = "\n\n".join(paras)
    else:
        txt = h
    # convert breaks
    txt = re.sub(r"(?i)<br\\s*/?>", "\n", txt)
    # strip tags
    txt = re.sub(r"(?s)<.*?>", " ", txt)
    txt = html_mod.unescape(txt)
    txt = re.sub(r"[ \\t\\x0b\\x0c]+", " ", txt)
    txt = re.sub(r"\\n{3,}", "\n\n", txt)
    return txt.strip()


def clip_text(text, max_chars):
    t = (text or "").strip()
    if not max_chars or len(t) <= int(max_chars):
        return t
    return t[: int(max_chars)] + "\n\n[TRUNCATED]"


def summarize_with_llm(title, url, published, content_text, max_bullets=6):
    prompt = (
        "You summarize football news for Fantasy Premier League (FPL) decision-making.\n"
        "Return STRICT JSON (no markdown) with keys:\n"
        '  "summary_bullets": array of short bullets (max {max_bullets}),\n'
        '  "fpl_takeaways": array of actionable takeaways (max 4),\n'
        '  "players_mentioned": array of player names,\n'
        '  "teams_mentioned": array of team names,\n'
        '  "tags": array of tags (injury, return, suspension, transfer, tactic, lineup, minutes, quotes, etc).\n'
        "Focus on injuries, minutes risk, likely starters, and anything that affects xPts.\n"
        "If the article is not about the Premier League, still summarize but mention that.\n"
    ).format(max_bullets=int(max_bullets))

    user = (
        f"TITLE: {title}\n"
        f"URL: {url}\n"
        f"PUBLISHED: {published}\n\n"
        f"ARTICLE TEXT:\n{content_text}"
    )

    msgs = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user},
    ]
    raw = llm.openai_chat(msgs, temperature=0.2, max_tokens=700)

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data, raw
    except Exception:
        pass
    return None, raw


def md_from_summary(meta, summary_json, raw_llm):
    title = meta.get("title", "").strip()
    url = meta.get("url", "").strip()
    source = meta.get("source", "").strip()
    published = meta.get("published", "").strip()
    fetched = meta.get("fetched_at", "").strip()

    bullets = []
    takeaways = []
    players = []
    teams = []
    tags = []

    if isinstance(summary_json, dict):
        bullets = summary_json.get("summary_bullets") or []
        takeaways = summary_json.get("fpl_takeaways") or []
        players = summary_json.get("players_mentioned") or []
        teams = summary_json.get("teams_mentioned") or []
        tags = summary_json.get("tags") or []

    def as_list(x):
        if isinstance(x, list):
            return [str(i).strip() for i in x if str(i).strip()]
        if isinstance(x, str) and x.strip():
            return [x.strip()]
        return []

    bullets = as_list(bullets)
    takeaways = as_list(takeaways)
    players = as_list(players)
    teams = as_list(teams)
    tags = as_list(tags)

    # Keep it tidy for retrieval
    lines = []
    lines.append(f"# {title or 'News summary'}")
    lines.append("")
    lines.append(f"- Source: {source}")
    lines.append(f"- URL: {url}")
    if published:
        lines.append(f"- Published: {published}")
    if fetched:
        lines.append(f"- Fetched: {fetched}")
    lines.append("")

    if bullets:
        lines.append("## Summary")
        for b in bullets:
            lines.append(f"- {b}")
        lines.append("")

    if takeaways:
        lines.append("## FPL takeaways")
        for t in takeaways:
            lines.append(f"- {t}")
        lines.append("")

    if players or teams:
        lines.append("## Entities")
        if players:
            lines.append("- Players: " + ", ".join(players[:40]))
        if teams:
            lines.append("- Teams: " + ", ".join(teams[:40]))
        lines.append("")

    if tags:
        lines.append("## Tags")
        lines.append("- " + ", ".join(tags[:30]))
        lines.append("")

    # Keep raw LLM for debugging if JSON parse failed
    if not bullets and raw_llm:
        lines.append("## Raw LLM output (debug)")
        lines.append("```")
        lines.append(str(raw_llm)[:4000])
        lines.append("```")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def guess_source(url):
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        host = ""
    host = host.replace("www.", "")
    return host or "unknown"


def ingest_one_item(item, out_dir, max_chars=12000, fetch_full_article=True, timeout_s=20, sleep_s=0.5):
    title = (item.get("title") or "").strip()
    url = (item.get("url") or "").strip()
    published = (item.get("published") or "").strip()
    summary = (item.get("summary") or "").strip()
    source = guess_source(url)

    content_text = ""
    if fetch_full_article:
        try:
            html = fetch_url(url, timeout_s=timeout_s)
            content_text = html_to_text(html)
        except Exception:
            # fall back to RSS summary/description
            content_text = html_to_text(summary)
    else:
        content_text = html_to_text(summary)

    content_text = clip_text(content_text, max_chars=max_chars)

    summary_json = None
    raw_llm = ""
    try:
        summary_json, raw_llm = summarize_with_llm(title, url, published, content_text)
    except Exception as e:
        raw_llm = f"LLM not available: {e}"

    meta = {
        "id": item.get("id") or url,
        "title": title,
        "url": url,
        "source": source,
        "published": published,
        "fetched_at": now_utc_iso(),
    }

    # File name: date + slug + short hash
    date_prefix = ""
    if published:
        date_prefix = re.sub(r"[^0-9]", "", published)[:8]
    if not date_prefix:
        date_prefix = datetime.now().strftime("%Y%m%d")

    h = sha1(url)[:10]
    name = f"{date_prefix}_{slugify(title)}_{h}.md"
    path = Path(out_dir) / source / name

    md = md_from_summary(meta, summary_json, raw_llm)
    write_text(path, md)

    if sleep_s:
        time.sleep(float(sleep_s))

    return str(path)


def ingest(feeds, out_dir, state_path, limit=10, max_chars=12000, fetch_full_article=True, timeout_s=20, sleep_s=0.5, dry_run=False):
    state = load_json(state_path, default={"seen": {}})
    seen = state.get("seen") or {}
    if not isinstance(seen, dict):
        seen = {}

    new_written = []

    for feed_url in feeds:
        try:
            xml = fetch_url(feed_url, timeout_s=timeout_s)
        except Exception as e:
            print(f"[WARN] Feed fetch failed: {feed_url} ({e})")
            continue

        items = parse_feed_xml(xml)
        if not items:
            print(f"[WARN] No items parsed: {feed_url}")
            continue

        for item in items:
            url = (item.get("url") or "").strip()
            if not url:
                continue
            key = sha1(url)
            if key in seen:
                continue

            if dry_run:
                print(f"[DRY] Would ingest: {item.get('title')} ({url})")
                seen[key] = {"url": url, "ts": now_utc_iso(), "dry_run": True}
                continue

            try:
                path = ingest_one_item(
                    item=item,
                    out_dir=out_dir,
                    max_chars=max_chars,
                    fetch_full_article=fetch_full_article,
                    timeout_s=timeout_s,
                    sleep_s=sleep_s,
                )
                print(f"[OK] Wrote: {path}")
                new_written.append(path)
                seen[key] = {"url": url, "ts": now_utc_iso(), "path": path}
            except Exception as e:
                print(f"[WARN] Failed item: {url} ({e})")
                seen[key] = {"url": url, "ts": now_utc_iso(), "error": str(e)[:200]}

            if limit and len(new_written) >= int(limit):
                break
        if limit and len(new_written) >= int(limit):
            break

    state["seen"] = seen
    if not dry_run:
        save_json(state_path, state)

    return new_written


def main():
    p = argparse.ArgumentParser(description="Ingest RSS feeds and write summarized Markdown into kb/auto/ for RAG.")
    p.add_argument("--feeds", default=os.environ.get("NEWS_FEEDS", ""), help="Comma-separated RSS/Atom feed URLs.")
    p.add_argument("--out", default=os.environ.get("NEWS_OUT_DIR", "kb/auto/news"), help="Output dir for markdown.")
    p.add_argument("--state", default=os.environ.get("NEWS_STATE_PATH", "cache/news_state.json"), help="State json path.")
    p.add_argument("--limit", type=int, default=int(os.environ.get("NEWS_LIMIT", "10") or 10), help="Max new items per run.")
    p.add_argument("--max-chars", type=int, default=int(os.environ.get("NEWS_MAX_CHARS", "12000") or 12000), help="Max chars to summarize.")
    p.add_argument("--rss-only", action="store_true", help="Do not fetch full article HTML; summarize RSS description only.")
    p.add_argument("--timeout", type=int, default=int(os.environ.get("NEWS_TIMEOUT_S", "20") or 20), help="HTTP timeout seconds.")
    p.add_argument("--sleep", type=float, default=float(os.environ.get("NEWS_SLEEP_S", "0.5") or 0.5), help="Sleep between items.")
    p.add_argument("--dry-run", action="store_true", help="List items to ingest without writing.")

    args = p.parse_args()

    feeds = [x.strip() for x in str(args.feeds).split(",") if x.strip()]
    if not feeds:
        print("No feeds provided. Set NEWS_FEEDS or pass --feeds.")
        print("Example:")
        print('  NEWS_FEEDS="https://example.com/rss.xml,https://example.com/atom.xml" python scripts/ingest_news.py')
        return 2

    out_dir = args.out
    state_path = args.state

    new_written = ingest(
        feeds=feeds,
        out_dir=out_dir,
        state_path=state_path,
        limit=args.limit,
        max_chars=args.max_chars,
        fetch_full_article=(not args.rss_only),
        timeout_s=args.timeout,
        sleep_s=args.sleep,
        dry_run=args.dry_run,
    )

    print(f"Done. New files: {len(new_written)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

