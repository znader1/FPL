# Fresh News Sources (A+B complementary) — Design

**Date:** 2026-07-26
**Problem:** The squad-picker player-knowledge rail digests `kb/auto/news/*.md`, but
those 80 articles are Feb-2026 (last-season) transfer rumours with no refresh
mechanism. The LLM digest can surface stale, irrelevant signals. We need a live,
robust injury/availability source and a way to refresh the news corpus.

## Approach: C (A + B, complementary)

### A — Bootstrap-news digester (live, no LLM, first-party truth)
The FPL bootstrap already carries live per-player injury data
(`status`, `chance_of_playing_next_round`, `news` with expected return dates).
At time of writing: 46 flagged players, e.g. `J.Timber — Groin injury - Expected
back 21 Aug`. This is fetched on every build already — zero scrape, never stale.

`src/news_digest.py :: digest_bootstrap_news(elements, events, current_gw)` maps
each flagged player to a player-knowledge entry (same schema as the manual rail):

| Bootstrap state | Entry |
|---|---|
| `status` in i/s/u/n, return date parseable & future | `availability=1.0`, `available_from_gw=<GW of return date>` (out until then, fine after) |
| `status` in i/s/u/n, unknown/no return | `availability=0.0`, `available_from_gw=null` (zeroed whole horizon) |
| `status`=d (doubt) | `availability=chance/100` (fallback 0.5), `available_from_gw=null` |
| `status`=a | skip (available, nothing to flag) |

- `minutes_mult=1.0`, `note=<news text>`, `source="fpl_bootstrap"`.
- `_parse_return_gw(news_text, events)`: regex a `DD Mon` date from
  "Expected back …" / "Suspended until …" / "back …"; infer the year from the
  events' date range; return the id of the first event whose `deadline_time`
  date ≥ return date. Return date after the last event → a GW beyond the horizon
  (effectively out all horizon). Unparseable → `None`.
- Pure function: tested with synthetic elements + events, no network/LLM.

### B — RSS refresh routine (repopulate the stale corpus)
`src/news_fetch.py`:
- `fetch_rss(feeds, max_age_days, now)` — parse each feed with stdlib
  `xml.etree` (no new dependency). Item = title / link / published / summary.
  Keep only items published within `max_age_days`. `now` injected for tests.
- `article_to_markdown(entry, elements, generate)` — Claude-haiku digests the
  RSS **title + summary only** (one call/article) into JSON
  `{summary:[…], players:[…], teams:[…], tags:[…]}`; rendered deterministically
  to the existing md format (`# title`, `- Source/URL/Published/Fetched`,
  `## Summary`, `## Entities`, `## Tags`). `generate` injectable → tests offline.
- `prune_stale(kb_dir, max_age_days, now)` — delete md whose `Published` is older
  than the cutoff (scraps the Feb-2026 rumours automatically).

`scripts/refresh_news.py` — the routine: fetch all feeds → skip URLs already in
kb → Claude-digest new items → write `kb/auto/news/<domain>/<slug>.md` → prune
stale. CLI, run manually now, schedulable via cron/launchd. Uses
`news_digest._anthropic_generate` (Claude) for the digest.

Config: `NEWS_FEEDS` (sportsmole/football-talk/betfair RSS URLs verified live),
`NEWS_MAX_AGE_DAYS = 14`.

### Merge — the complementary bit
`/squad-picker/digest-news` runs **both**:
1. `digest_bootstrap_news` (A) → first-party proposals.
2. existing md-corpus LLM digest (B's output) → narrative proposals.

Merge = article proposals first, then overlay bootstrap (`{**article, **bootstrap}`)
so **bootstrap wins on conflict** (injury truth beats a rumour), while articles
add rotation/predicted-XI signal bootstrap lacks. Each proposal keeps its
`source`. Response gains `bootstrap_flags` count.

### Frontend
`PlayerKnowledgePanel` digest card: show `bootstrap_flags` in the header and a
per-row source tag (injury vs article) via the entry `source`. No flow change —
same Digest → Approve → Save → rebuild.

## Testing
- A: `digest_bootstrap_news` + `_parse_return_gw` — synthetic elements/events.
- B: `fetch_rss` (fixture XML), `article_to_markdown` (injected generate),
  `prune_stale` (temp dir + fixed now).
- Merge: bootstrap-wins-on-conflict unit.
- No network or live LLM in the suite.

## Out of scope
- Full-article body fetch (RSS summary only, per decision).
- Auto-scheduling wiring (script is cron-ready; schedule set up separately).
