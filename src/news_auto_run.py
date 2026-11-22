"""Orchestrates one news -> guarded minute-cut run.

Fetch+digest feeds, pick fresh unprocessed articles, one LLM call per club,
guard the output (news_auto.guard_cuts), merge into the auto knowledge file.
Invariant: a run that fails part-way writes nothing to the auto file or the
processed-URL store; the auto file is replaced atomically only at the end.
Never imported by backtest/replay paths.
"""
import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone

from src import config, llm_usage, news_auto, news_fetch
from src.news_digest import load_news_articles
from src.player_knowledge import load_auto_knowledge
from src.squad_draft import _next_gw
from src.transforms import tables_from_bootstrap


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _env_flag(name, default):
    v = (os.environ.get(name) or "").strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return bool(default)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- files -----------------------------------------------------------------

def _atomic_write_json(path, data):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_auto(path, data):
    _atomic_write_json(path, data)


def append_log(out_dir, events, run_id):
    if not events:
        return
    os.makedirs(out_dir, exist_ok=True)
    ts = _iso(datetime.now(timezone.utc))
    with open(os.path.join(out_dir, "changes.jsonl"), "a") as f:
        for ev in events:
            f.write(json.dumps({**ev, "run_id": run_id, "ts": ts}) + "\n")


def _read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# ---- lock ------------------------------------------------------------------

def _lock_path(out_dir):
    return os.path.join(out_dir, "run.lock")


def _lock_active(out_dir):
    p = _lock_path(out_dir)
    if not os.path.exists(p):
        return False
    try:
        age = time.time() - os.path.getmtime(p)
    except OSError:
        return False
    return age <= config.NEWS_AUTO_MAX_RUN_SECONDS * 2


def _read_token(p):
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return None


def _create_lock(p, token):
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as f:
        f.write(str(token))
    return True


def acquire_lock(out_dir, token):
    """Take the run lock, recording `token` (the run_id) in it. A stale lock is
    taken over by renaming it to a unique name first (only one contender's
    rename can succeed), then O_EXCL-creating a fresh one."""
    os.makedirs(out_dir, exist_ok=True)
    p = _lock_path(out_dir)
    if _create_lock(p, token):
        return True
    if _lock_active(out_dir):
        return False
    grave = f"{p}.stale.{uuid.uuid4().hex}"
    try:
        os.rename(p, grave)
    except OSError:
        return False  # lost the takeover race (or lock vanished)
    try:
        age = time.time() - os.path.getmtime(grave)
        if age <= config.NEWS_AUTO_MAX_RUN_SECONDS * 2:
            # we grabbed a lock that was refreshed meanwhile: put it back
            try:
                os.link(grave, p)
            except OSError:
                pass
            return False
    finally:
        try:
            os.remove(grave)
        except OSError:
            pass
    return _create_lock(p, token)


def touch_lock(out_dir):
    try:
        os.utime(_lock_path(out_dir))
    except OSError:
        pass


def release_lock(out_dir, token):
    """Remove the lock only if it still carries `token`."""
    p = _lock_path(out_dir)
    if _read_token(p) == str(token):
        try:
            os.remove(p)
        except OSError:
            pass


def read_status(out_dir=None, auto_path=None):
    out_dir = out_dir or config.NEWS_AUTO_DIR
    return {
        "running": _lock_active(out_dir),
        "last_run": _read_json(os.path.join(out_dir, "last_run.json")),
        "active": load_auto_knowledge(auto_path or config.PLAYER_KNOWLEDGE_AUTO_PATH).get("players", {}),
    }


# ---- default LLM generators --------------------------------------------------

def _anthropic(system, prompt, model, feature, max_tokens):
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"),
                                 timeout=config.NEWS_AUTO_LLM_TIMEOUT_SECONDS)
    msg = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": prompt}])
    llm_usage.record_usage(msg, feature=feature, model=model)
    return msg.content[0].text


def digest_generate(prompt):
    # article_to_markdown prepends SYSTEM to the prompt; send it as the system
    # message only, not twice.
    if prompt.startswith(news_fetch.SYSTEM):
        prompt = prompt[len(news_fetch.SYSTEM):].lstrip()
    return _anthropic(news_fetch.SYSTEM, prompt, config.NEWS_AUTO_DIGEST_MODEL,
                      "news_auto_digest", 400)


def team_generate(prompt):
    return _anthropic(news_auto.SYSTEM_TEAM, prompt, config.NEWS_AUTO_MODEL,
                      "news_auto", 600)


# ---- run -------------------------------------------------------------------

def _processed_path(out_dir):
    return os.path.join(out_dir, "processed.json")


def run(bootstrap, *, run_id, lock_held=False, now=None, fetch=None,
        digest_generate=None, team_generate=None, kb_dir=None, out_dir=None,
        auto_path=None, dry_run=None, max_seconds=None):
    now = now or datetime.now(timezone.utc)
    out_dir = out_dir or config.NEWS_AUTO_DIR
    auto_path = auto_path or config.PLAYER_KNOWLEDGE_AUTO_PATH
    kb_dir = kb_dir or config.NEWS_KB_DIR
    if dry_run is None:
        dry_run = _env_flag("NEWS_AUTO_DRY_RUN", config.NEWS_AUTO_DRY_RUN)
    max_seconds = config.NEWS_AUTO_MAX_RUN_SECONDS if max_seconds is None else max_seconds
    receipt = {"run_id": run_id, "ok": False, "dry_run": bool(dry_run),
               "started": _iso(now), "finished": None, "next_gw": None,
               "fetched": 0, "fresh_articles": 0, "teams_called": 0, "cuts": 0,
               "events": [], "errors": []}

    if not _env_flag("NEWS_AUTO_ENABLED", config.NEWS_AUTO_ENABLED):
        receipt.update(ok=True, skipped="disabled", finished=_iso(now))
        if lock_held:
            release_lock(out_dir, run_id)
        return receipt

    acquired = False
    if not lock_held:
        if not acquire_lock(out_dir, run_id):
            receipt.update(finished=_iso(now), errors=["another run is in progress"])
            return receipt
        acquired = True
    try:
        _run_locked(receipt, bootstrap, now, fetch, digest_generate, team_generate,
                    kb_dir, out_dir, auto_path, bool(dry_run), max_seconds)
    except Exception as e:  # noqa: BLE001 - any failure: write nothing, report
        receipt["ok"] = False
        receipt["errors"].append(f"{type(e).__name__}: {e}")
    finally:
        try:
            receipt["finished"] = _iso(datetime.now(timezone.utc))
            try:
                _atomic_write_json(os.path.join(out_dir, "last_run.json"), receipt)
            except Exception as e:  # noqa: BLE001
                receipt["errors"].append(f"receipt write failed: {e}")
        finally:
            if acquired or lock_held:
                release_lock(out_dir, run_id)
    return receipt


def _run_locked(receipt, bootstrap, now, fetch, digest_generate_fn, team_generate_fn,
                kb_dir, out_dir, auto_path, dry_run, max_seconds):
    t0 = time.monotonic()
    digest_generate_fn = digest_generate_fn or digest_generate
    team_generate_fn = team_generate_fn or team_generate

    def over_budget():
        return time.monotonic() - t0 >= max_seconds

    gw = _next_gw(bootstrap)
    receipt["next_gw"] = gw
    elements, _teams_df, _types = tables_from_bootstrap(bootstrap)
    teams = bootstrap.get("teams", [])
    team_names = {int(t["id"]): t.get("name") for t in teams}
    team_short = {int(t["id"]): t.get("short_name") for t in teams}

    stats = {"feed_ok": 0, "feed_fail": 0, "dig_ok": 0, "dig_fail": 0}
    raw_fetch = fetch or news_fetch._http_get

    def counted_fetch(url):
        try:
            r = raw_fetch(url)
        except Exception:
            stats["feed_fail"] += 1
            raise
        stats["feed_ok"] += 1
        return r

    def counted_digest(prompt):
        try:
            r = digest_generate_fn(prompt)
        except Exception:
            stats["dig_fail"] += 1
            raise
        stats["dig_ok"] += 1
        return r

    rr = news_fetch.refresh(kb_dir=kb_dir, now=now, generate=counted_digest,
                            pl_terms=news_fetch.pl_terms_from_teams(teams),
                            fetch=counted_fetch)
    receipt["fetched"] = len(rr.get("written", []))
    receipt["errors"].extend(rr.get("errors", []))
    if stats["feed_fail"] and not stats["feed_ok"]:
        raise RuntimeError("every news feed failed")
    if stats["dig_fail"] and not stats["dig_ok"]:
        raise RuntimeError("every article digest failed")
    if over_budget():
        raise TimeoutError("time budget exceeded")

    articles = load_news_articles(kb_dir)
    corpus_urls = {a.get("url") for a in articles if a.get("url")}
    processed = set(_read_json(_processed_path(out_dir), []) or [])
    since = news_auto.latest_past_deadline(bootstrap.get("events", []), now)
    fresh = [a for a in articles if news_auto.is_fresh(a, since)]
    todo = news_auto.unprocessed(fresh, processed)
    receipt["fresh_articles"] = len(todo)

    grouped = news_auto.group_by_team(todo, teams)
    tids = sorted(grouped, key=lambda t: (-len(grouped[t]), t))[:config.NEWS_AUTO_MAX_TEAMS_PER_RUN]
    cuts_by_team, sources_by_team, used = {}, {}, set()
    for tid in tids:
        if over_budget():
            raise TimeoutError("time budget exceeded")
        touch_lock(out_dir)
        arts = grouped[tid][:config.NEWS_AUTO_MAX_ARTICLES_PER_TEAM]
        squad = news_auto.squad_list(elements, tid)
        prompt = news_auto.build_team_prompt(team_names.get(tid), arts, squad, gw)
        raw = team_generate_fn(prompt)
        receipt["teams_called"] += 1
        cuts = news_auto.guard_cuts(raw, squad, config.NEWS_AUTO_MIN_MULT)
        cuts_by_team[tid] = cuts
        sources_by_team[tid] = [a["url"] for a in arts if a.get("url")]
        used.update(sources_by_team[tid])

    entries = news_auto.build_entries(cuts_by_team, sources_by_team, team_short, gw,
                                      receipt["run_id"])
    auto, events = news_auto.merge_auto(load_auto_knowledge(auto_path), entries, gw, _iso(now))
    receipt["cuts"] = len(entries)
    receipt["events"] = events

    # Commit point: everything below only runs after all LLM work succeeded.
    if not dry_run:
        write_auto(auto_path, auto)
    append_log(out_dir, events, receipt["run_id"])
    _atomic_write_json(_processed_path(out_dir), sorted((processed | used) & corpus_urls))
    receipt["ok"] = True
