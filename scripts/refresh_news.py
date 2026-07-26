#!/usr/bin/env python
"""Refresh the FPL news corpus from live RSS feeds (Approach B routine).

Fetches config.NEWS_FEEDS, Claude-digests each NEW recent article's
title+summary into kb/auto/news/<domain>/*.md, and prunes md older than
config.NEWS_MAX_AGE_DAYS. Idempotent: already-seen URLs are skipped.

Run manually:
    ANTHROPIC_API_KEY=... PYTHONPATH=. python scripts/refresh_news.py

Schedule (cron / launchd) to keep the corpus fresh, e.g. daily 06:00:
    0 6 * * *  cd /path/to/FPL && ANTHROPIC_API_KEY=... PYTHONPATH=. \
        .venv/bin/python scripts/refresh_news.py >> logs/refresh_news.log 2>&1
"""
import argparse
import sys

from src import config, news_fetch


def main(argv=None):
    ap = argparse.ArgumentParser(description="Refresh the FPL news corpus from RSS.")
    ap.add_argument("--kb-dir", default=None, help="override kb/auto/news dir")
    ap.add_argument("--max-age-days", type=int, default=None, help="freshness window")
    ap.add_argument("--dry-run", action="store_true", help="fetch + report, write nothing")
    args = ap.parse_args(argv)

    if args.dry_run:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        feeds = getattr(config, "NEWS_FEEDS", [])
        max_age = args.max_age_days or getattr(config, "NEWS_MAX_AGE_DAYS", 14)
        total = 0
        for feed in feeds:
            try:
                entries = news_fetch.recent(
                    news_fetch.parse_feed(news_fetch._http_get(feed["url"]), feed["source"]),
                    max_age, now)
            except Exception as e:  # noqa: BLE001
                print(f"  {feed['source']}: ERROR {e}")
                continue
            total += len(entries)
            print(f"  {feed['source']}: {len(entries)} recent items")
        print(f"dry-run: {total} recent items across {len(feeds)} feeds (nothing written)")
        return 0

    res = news_fetch.refresh(kb_dir=args.kb_dir, max_age_days=args.max_age_days)
    print(f"written: {len(res['written'])}  pruned: {len(res['pruned'])}  "
          f"errors: {len(res['errors'])}")
    for u in res["written"]:
        print(f"  + {u}")
    for p in res["pruned"]:
        print(f"  - pruned {p}")
    for e in res["errors"]:
        print(f"  ! {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
