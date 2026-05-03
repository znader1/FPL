# Refactoring backlog

Tracked separately from feature work. Pick up when feature pace allows.

## src/league_strategy.py — share projections with /recommendations
Right now `/league/strategy` and `/recommendations` both build a projections DataFrame from scratch. They duplicate ~30 lines of bootstrap → elements_df → teams_short → project_elements_next_gws. Extract a shared helper (e.g. `src/projection_service.py` or expose it from `api/main.py`) so both endpoints call one function.
**Why deferred:** behavior must stay identical first; a shared helper is a pure refactor with no user-visible change.

## src/league_strategy.py — extract LLM call helper
`_llm_narrative` and `src/explainer.py` both wrap `Anthropic().messages.create()` with similar JSON-parsing logic. Extract a `src/llm.py` helper exposing `call_json(system, user, model, max_tokens)` that handles the client, the markdown-fence stripping, and the JSON-extraction fallback. Both modules then become much shorter.

## src/ folder structure
13 → 16 files. Once Phase 3 starts, group into:
- `src/data/` (fpl_client, transforms, season_history)
- `src/model/` (projections, recommender, optimizer, lineup_builder, squad_builder)
- `src/league/` (league, league_strategy)
- `src/llm/` (explainer + the proposed shared helper)
- `src/api_helpers/` (auth, config, utils, insights, media)
**Trigger:** when imports become noisy or two contributors are stepping on each other.

## api/main.py is too long (~1000 lines)
Split per-domain routers: `api/routes_squad.py`, `api/routes_recommendations.py`, `api/routes_league.py`, `api/routes_explain.py`. Mount them on the main `FastAPI` app. Keeps the top-level file as composition only.
**Trigger:** when a single endpoint change requires scrolling through unrelated handlers.

## Defensive: cap rival squad fetch
`league_strategy.analyze_league` fetches one `/event/{gw}/picks/` per rival sequentially. Up to 6 calls per request. Fine now; if max_rivals grows beyond ~10, batch them with `concurrent.futures.ThreadPoolExecutor` (FPL API tolerates parallel reads).

## League ownership denominator
Computed across only the 3-above + 3-below sample, which makes the ratio noisy and misleading. Either fetch the full standings page (≤50 entries) for a real denominator, or drop ownership from the chase/defend candidate enrichment and keep it only for differential mode. Decided to keep as-is for now — revisit when frontend exposes it.
