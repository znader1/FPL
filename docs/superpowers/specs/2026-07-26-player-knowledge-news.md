# Squad Picker — Player-Knowledge Layer + News Digestion

**Date:** 2026-07-26
**Status:** Design approved (pending spec review)
**Scope:** Dev-only Squad Picker (`SQUAD_PICKER_MODE=1` + `VITE_SQUAD_PICKER=1`). Picker-scoped — production projections/recommendations unchanged.

## Goal

Give the squad picker a **player-level knowledge layer** (news/injury-derived) that FPL's own pre-season flags can't capture — new-season nailed-ness, rotation risk, injury return timelines, suspensions. Two phases:

1. **Phase 1 — the rail.** A `player_knowledge.json` file + per-request param + live API + apply layer, mirroring the existing team-level `knowledge_discount.json` rail. Usable immediately by manual entry.
2. **Phase 2 — news digestion (semi-auto RAG).** Digest the existing `kb/auto/news/*.md` corpus (LLM-pre-digested articles with player entity lists) via entity-match + Anthropic LLM into **proposed** player-knowledge entries the user approves before they apply.

## Non-goals

- No attacking/role **upside** nudges (availability + minutes only — upside is easiest to over-tune).
- No embeddings / vector DB — kb articles carry `## Entities` player lists, so entity-string matching suffices.
- No production projection change — applied only in the picker's `project_pool` path.
- No auto-apply — the digestion always requires human approval.

## Existing rails this mirrors (from the codebase map)

- Team knowledge: `data/models/knowledge_discount.json` → `fixture_difficulty.apply_knowledge_discount`; per-request `team_nudges`; live `GET/POST /squad-picker/knowledge` (`api/squad_router.py:42-56`).
- Availability seam: `status` + `chance_of_playing_next_round` flow through `minutes_model`/`projections`/`squad_draft`. The `news` free-text is captured but **unused** (display only, `squad_draft._notable_exclusion_notes`).
- News corpus: `kb/auto/news/<source>/*.md`, each with `## Summary`, `## FPL takeaways`, `## Entities` (Players/Teams), `## Tags`. **Not read by any code.**
- LLM: `anthropic>=0.40.0` (only SDK); `src/explainer.py` is the structured-JSON-output pattern to reuse.

---

## Phase 1 — the rail

### Data model — `data/models/player_knowledge.json`

```json
{
  "as_of": "2026-07-26",
  "players": {
    "427": { "availability": 1.0, "available_from_gw": null, "minutes_mult": 0.6,
             "note": "rotation risk", "source": "kb/auto/news/.../x.md" },
    "311": { "availability": 0.0, "available_from_gw": 8, "minutes_mult": 1.0,
             "note": "ACL, back ~GW8", "source": "..." }
  }
}
```
- Key = player id (string) preferred; a `web_name` key is resolved to id (normalized, case/diacritic-insensitive) at load, with an unresolved-key note.
- `availability` ∈ [0,1] (0 out, 0.5 doubt, 1 fit); default 1.0.
- `available_from_gw` int|null — player is out (availability treated as 0) for GWs `< available_from_gw`, then uses `availability`.
- `minutes_mult` ∈ [0,1+] — rotation/nailed scaling; default 1.0.
- `note`, `source` — free text, display + traceability.

### Config — `src/config.py`

```python
PLAYER_KNOWLEDGE_PATH = "data/models/player_knowledge.json"
PLAYER_KNOWLEDGE_STALE_DAYS = 10   # warn if as_of older than this
```

### Loader + resolver — `src/player_knowledge.py` (new, pure)

```python
def load_player_knowledge(path=None) -> dict            # {as_of, players:{id:entry}}; {} if absent
def resolve_keys(pk, elements) -> (dict, list[str])     # web_name keys -> id; returns (by_id, unresolved_notes)
def merge_request(pk_file, request_pk) -> dict          # per-request overrides win over file
```
- Degrades cleanly: missing/unreadable file → empty knowledge, no error.
- `resolve_keys`: numeric keys pass through; non-numeric matched to `elements` web_name (normalized). Unresolved → a note string.

### Apply layer — `src/squad_draft.py:project_pool`

After `xpts_horizon` is computed, before return, apply per player per GW:
```python
avail_g = 0.0 if (from_gw is not None and g < from_gw) else availability
proj.loc[player_row, f"xpts_gw{g}"] *= avail_g * minutes_mult
# recompute xpts_horizon from the adjusted xpts_gw columns
```
- Only players present in the resolved knowledge are touched; everyone else unchanged.
- Add `pk_availability` (min avail across horizon) + `pk_note` columns to `proj` so `_pool_records` can surface them.
- `notes` gets an entry per unresolved key and an `as_of` staleness warning.

### Pool records — `src/squad_draft.py:_pool_records`

Add `pk_availability` (float|null) and `pk_note` (str|null) to each record.

### Params — `DEFAULT_PARAMS`

Add `"player_knowledge": None` (per-request override dict, same shape as the file's `players`), threaded into `project_pool` and merged over the file via `player_knowledge.merge_request`.

### API — `api/squad_router.py`

- `GET /squad-picker/player-knowledge` → the file (or `{as_of:None, players:{}}`).
- `POST /squad-picker/player-knowledge` → write `{as_of, players}` to `PLAYER_KNOWLEDGE_PATH`.
(Mirror the existing `/knowledge` handlers.)

### Frontend — `PlayerKnowledgePanel.tsx` + `squadPickerApi.ts`

- `getPlayerKnowledge()` / `savePlayerKnowledge(grid)`.
- Panel: table of entries (player search-to-add, availability select fit/doubt/out, available_from_gw, minutes_mult, note), Save.
- `PoolPlayer` gains `pk_availability`, `pk_note`. List + squad: grey/badge a player flagged out, `pk_note` on hover.

### Phase 1 testing

- `test_player_knowledge.py`: load (present/absent/malformed), `resolve_keys` (id passthrough, web_name resolve, unresolved note), `merge_request` precedence.
- `test_squad_draft.py`: a knowledge entry with `available_from_gw=3` zeroes `xpts_gw1/gw2`, keeps `gw3+`; `minutes_mult=0.5` halves; `xpts_horizon` recomputed; players not in knowledge unchanged.
- `test_squad_router.py`: GET/POST player-knowledge roundtrip; `/players` records carry `pk_availability`/`pk_note`.
- Frontend `squadPickerApi.test.ts`: get/save client shape.

---

## Phase 2 — news digestion (semi-auto RAG)

### Retrieval — `src/news_digest.py` (new, pure-ish)

```python
def load_news_articles(kb_dir="kb/auto/news") -> list[Article]   # parse md front-matter + Entities/Tags/Summary
def index_by_player(articles, elements) -> dict[int, list[Article]]  # entity Players -> bootstrap id (normalized match)
```
- Entity match: article `## Entities → Players` names normalized and matched to bootstrap `web_name` (and full name). Unmatched entities dropped (logged count). No embeddings.

### Generation — `src/news_digest.py` + Anthropic

```python
def propose_player_knowledge(player_to_articles, elements, client=None) -> dict  # {players:{id:proposed_entry}}
```
- For each player with articles, one Anthropic call (reuse `explainer` model/env pattern, structured JSON only): given the article summaries/takeaways/tags, output `{availability, available_from_gw, minutes_mult, note, source}` or "no change".
- Strict JSON schema; conservative defaults (unknown → no entry). Cite the source article path in `source`.
- Batched/capped (only players actually mentioned; skip if no articles).

### API — `POST /squad-picker/digest-news`

- Body: projection params (for `gw_start`/current GW context) + optional `kb_dir`.
- Returns `{proposals: {players:{id:entry}}, matched_players, unmatched_entities, article_count}`. **Applies nothing.**
- Frontend Digest-news button shows proposals with source; Approve merges into `player_knowledge.json` (via the Phase 1 POST); Edit/Reject per entry.

### Phase 2 testing

- `test_news_digest.py`: parse a fixture md article; `index_by_player` matches a known web_name, drops unknown; `propose_player_knowledge` with a stubbed Anthropic client returns schema-valid entries; empty kb → empty proposals.
- `test_squad_router.py`: `/digest-news` with monkeypatched client returns proposals, writes nothing.

---

## Robustness summary (the "more robust" ask)

- **Id-first resolution**, web_name fallback normalized; unresolved keys surfaced as notes, never silently dropped.
- **Staleness**: `as_of` older than `PLAYER_KNOWLEDGE_STALE_DAYS` → a visible note.
- **Traceability**: every entry carries `source`.
- **Human gate**: digestion only proposes; application is explicit.
- **Scoped**: applied in `project_pool` only — production projections/recommender untouched (same containment as the pre-season/strength/CS-bonus changes).
- **Degrades**: absent file/kb, malformed JSON, missing Anthropic key → empty knowledge, picker still works.

## Files

Phase 1: `src/player_knowledge.py` (new), `src/config.py`, `src/squad_draft.py`, `api/squad_router.py`, tests; frontend `squadPickerApi.ts`, `components/PlayerKnowledgePanel.tsx`, `pages/SquadPicker.tsx`, `squadPickerApi.test.ts`.
Phase 2: `src/news_digest.py` (new), `api/squad_router.py`, tests; frontend digest-news UI in the panel.
