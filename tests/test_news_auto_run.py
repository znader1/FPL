import json
import os
import threading
from datetime import datetime, timezone

import pytest

from src import config, news_auto_run as nar

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>F</title>
<item><title>Arsenal rotate</title><link>https://x.test/arsenal-rotate.html</link>
<pubDate>Thu, 19 Nov 2026 08:00:00 +0000</pubDate>
<description>Arsenal will rotate.</description></item></channel></rss>"""
OLD_RSS = RSS.replace("Thu, 19 Nov 2026", "Mon, 09 Nov 2026")


def bootstrap():
    return {
        "events": [
            {"id": 11, "deadline_time": "2026-11-14T10:00:00Z", "is_current": True},
            {"id": 12, "deadline_time": "2026-11-28T10:00:00Z", "is_next": True},
        ],
        "teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"},
                  {"id": 2, "name": "Chelsea", "short_name": "CHE"}],
        "element_types": [{"id": 1, "singular_name_short": "GKP"},
                          {"id": 2, "singular_name_short": "DEF"},
                          {"id": 3, "singular_name_short": "MID"},
                          {"id": 4, "singular_name_short": "FWD"}],
        "elements": [
            {"id": 10, "web_name": "Saka", "team": 1, "element_type": 3, "status": "a",
             "chance_of_playing_next_round": None, "now_cost": 100},
            {"id": 20, "web_name": "Palmer", "team": 2, "element_type": 3, "status": "a",
             "chance_of_playing_next_round": None, "now_cost": 100},
        ],
    }


DIGEST = json.dumps({"summary": ["Arsenal rotate"], "players": ["Bukayo Saka"],
                     "teams": ["Arsenal"], "tags": ["rotation"]})
CUT = json.dumps({"cuts": [{"player_id": 10, "minutes_mult": 0.8, "reason": "rotated"}]})


class Env:
    def __init__(self, tmp_path):
        self.kb = str(tmp_path / "kb")
        self.out = str(tmp_path / "news")
        self.auto = str(tmp_path / "auto.json")
        self.calls = 0

    def team(self, prompt):
        self.calls += 1
        return CUT

    def go(self, rss=RSS, team=None, **kw):
        args = dict(run_id="r1", now=NOW, fetch=lambda url: rss,
                    digest_generate=lambda p: DIGEST, team_generate=team or self.team,
                    kb_dir=self.kb, out_dir=self.out, auto_path=self.auto, dry_run=False)
        args.update(kw)
        return nar.run(bootstrap(), **args)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "NEWS_FEEDS", [{"url": "http://f", "source": "x.test"}])
    monkeypatch.delenv("NEWS_AUTO_ENABLED", raising=False)
    monkeypatch.delenv("NEWS_AUTO_DRY_RUN", raising=False)
    return Env(tmp_path)


def test_run_writes_auto_file_log_and_receipt(env):
    r = env.go()
    assert r["ok"] is True and r["next_gw"] == 12 and r["cuts"] == 1
    auto = json.load(open(env.auto))
    assert auto["players"]["10"]["minutes_mult"] == 0.8
    lines = [json.loads(x) for x in open(os.path.join(env.out, "changes.jsonl"))]
    assert [x["kind"] for x in lines] == ["add"] and lines[0]["run_id"] == "r1"
    assert json.load(open(os.path.join(env.out, "last_run.json")))["ok"] is True
    assert not os.path.exists(os.path.join(env.out, "run.lock"))


def test_dry_run_writes_log_and_receipt_but_not_auto_file(env):
    r = env.go(dry_run=True)
    assert r["ok"] and r["dry_run"] and r["cuts"] == 1
    assert not os.path.exists(env.auto)
    assert os.path.exists(os.path.join(env.out, "changes.jsonl"))


def test_stale_article_creates_no_entry(env):
    r = env.go(rss=OLD_RSS)
    assert r["ok"] and r["cuts"] == 0 and env.calls == 0
    assert not os.path.exists(env.auto) or not json.load(open(env.auto))["players"]


def test_run_failure_keeps_previous_file_and_releases_lock(env):
    open(env.auto, "w").write('{"as_of": null, "players": {}, "tombstones": {}}')
    before = open(env.auto, "rb").read()

    def boom(p):
        raise RuntimeError("llm down")
    r = env.go(team=boom)
    assert r["ok"] is False and any("llm down" in e for e in r["errors"])
    assert open(env.auto, "rb").read() == before
    assert not os.path.exists(os.path.join(env.out, "run.lock"))
    assert not os.path.exists(os.path.join(env.out, "processed.json"))


def test_second_run_refused_while_locked(env):
    assert nar.acquire_lock(env.out, "t") is True
    assert nar.acquire_lock(env.out, "t") is False
    assert nar.read_status(env.out, env.auto)["running"] is True
    r = env.go()
    assert r["ok"] is False
    nar.release_lock(env.out, "t")
    assert nar.acquire_lock(env.out, "t") is True


def test_time_budget_stops_and_writes_nothing(env):
    r = env.go(max_seconds=0)
    assert r["ok"] is False and not os.path.exists(env.auto) and env.calls == 0


def test_digest_total_failure_is_not_ok(env):
    def bad(p):
        raise RuntimeError("no key")
    r = env.go(digest_generate=bad)
    assert r["ok"] is False and r["errors"]
    assert not os.path.exists(env.auto)


def test_feed_total_failure_is_not_ok(env):
    def bad(url):
        raise OSError("down")
    assert env.go(fetch=bad)["ok"] is False


def test_clubs_with_only_processed_articles_are_not_called(env):
    assert env.go()["ok"] and env.calls == 1
    assert env.go(run_id="r2")["ok"] and env.calls == 1


def test_disabled_flag_short_circuits(env, monkeypatch):
    monkeypatch.setattr(config, "NEWS_AUTO_ENABLED", False)
    r = env.go()
    assert r["ok"] is True and r["skipped"] == "disabled" and env.calls == 0
    assert not os.path.exists(env.kb)


def test_env_flag_overrides_config(env, monkeypatch):
    monkeypatch.setenv("NEWS_AUTO_ENABLED", "false")
    assert env.go()["skipped"] == "disabled"


def test_stale_lock_is_free(env):
    os.makedirs(env.out)
    p = os.path.join(env.out, "run.lock")
    open(p, "w").write("x")
    os.utime(p, (1, 1))
    assert nar.acquire_lock(env.out, "t") is True


def test_lock_held_true_releases_on_success_and_disabled(env, monkeypatch):
    lock = os.path.join(env.out, "run.lock")
    assert nar.acquire_lock(env.out, "r1")
    assert env.go(lock_held=True)["ok"] and not os.path.exists(lock)
    assert nar.acquire_lock(env.out, "r2")
    monkeypatch.setattr(config, "NEWS_AUTO_ENABLED", False)
    assert env.go(lock_held=True, run_id="r2")["skipped"] == "disabled"
    assert not os.path.exists(lock)


def test_second_club_failure_leaves_auto_file_unchanged(env, monkeypatch):
    rss2 = RSS.replace("Arsenal rotate", "Chelsea rotate").replace("arsenal-rotate", "chelsea-rotate")
    both = RSS.replace("</channel>", rss2.split("<item>", 1)[1].rsplit("</channel>", 1)[0].join(["<item>", ""]) + "</channel>")
    digests = iter([DIGEST, DIGEST.replace("Arsenal", "Chelsea")])
    open(env.auto, "w").write('{"as_of": null, "players": {}, "tombstones": {}}')
    before = open(env.auto, "rb").read()
    n = {"c": 0}

    def team(p):
        n["c"] += 1
        if n["c"] == 2:
            raise RuntimeError("second club down")
        return CUT
    r = env.go(rss=both, team=team, digest_generate=lambda p: next(digests))
    assert n["c"] == 2 and r["ok"] is False
    assert open(env.auto, "rb").read() == before


def test_stale_lock_takeover_has_one_winner(env):
    os.makedirs(env.out)
    p = os.path.join(env.out, "run.lock")
    open(p, "w").write("old")
    os.utime(p, (1, 1))
    results, barrier = [], threading.Barrier(2)

    def contend(tok):
        barrier.wait()
        results.append(nar.acquire_lock(env.out, tok))
    ts = [threading.Thread(target=contend, args=(t,)) for t in ("a", "b")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(results) == [False, True]


def test_release_with_wrong_token_leaves_lock(env):
    assert nar.acquire_lock(env.out, "mine")
    nar.release_lock(env.out, "other")
    assert os.path.exists(os.path.join(env.out, "run.lock"))
    nar.release_lock(env.out, "mine")
    assert not os.path.exists(os.path.join(env.out, "run.lock"))


def test_flag_typo_keeps_config_default(env, monkeypatch):
    monkeypatch.setenv("NEWS_AUTO_ENABLED", "ture")
    monkeypatch.setenv("NEWS_AUTO_DRY_RUN", " Off ")
    assert nar._env_flag("NEWS_AUTO_ENABLED", True) is True
    assert nar._env_flag("NEWS_AUTO_ENABLED", False) is False
    assert nar._env_flag("NEWS_AUTO_DRY_RUN", True) is False


def test_quiet_run_with_one_failed_feed_is_ok(env, monkeypatch):
    monkeypatch.setattr(config, "NEWS_FEEDS", [{"url": "http://f", "source": "x.test"},
                                               {"url": "http://g", "source": "y.test"}])

    def fetch(url):
        if url == "http://g":
            raise OSError("down")
        return RSS
    assert env.go(fetch=fetch)["ok"]
    r = env.go(fetch=fetch, run_id="r2")
    assert r["ok"] is True and r["errors"]


# ---- _anthropic: block types, stop reasons, request params ------------------

class _Blk:
    def __init__(self, type, text=None):
        self.type = type
        if text is not None:
            self.text = text


class _Msg:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = None


def _fake_anthropic(monkeypatch, msg):
    import sys
    import types
    seen = {}

    class _Messages:
        def create(self, **kw):
            seen["create"] = kw
            return msg

    class _Client:
        def __init__(self, **kw):
            seen["client"] = kw
            self.messages = _Messages()
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=_Client))
    return seen


def test_anthropic_skips_leading_thinking_block(monkeypatch):
    seen = _fake_anthropic(monkeypatch, _Msg([_Blk("thinking"), _Blk("text", '{"cuts": []}')]))
    assert nar._anthropic("sys", "p", "claude-haiku-5-5", "f", 1000, "low") == '{"cuts": []}'
    assert seen["client"]["max_retries"] == config.NEWS_AUTO_LLM_MAX_RETRIES
    assert seen["create"]["output_config"] == {"effort": "low"}
    assert "temperature" not in seen["create"] and "thinking" not in seen["create"]


@pytest.mark.parametrize("stop", ["max_tokens", "refusal"])
def test_anthropic_truncated_or_refused_raises(monkeypatch, stop):
    _fake_anthropic(monkeypatch, _Msg([_Blk("thinking"), _Blk("text", '{"cu')], stop_reason=stop))
    with pytest.raises(RuntimeError, match=stop):
        nar._anthropic("sys", "p", "claude-haiku-5-5", "f", 1000, "low")


def test_anthropic_no_text_block_raises(monkeypatch):
    _fake_anthropic(monkeypatch, _Msg([_Blk("thinking")]))
    with pytest.raises(RuntimeError):
        nar._anthropic("sys", "p", "claude-haiku-5-5", "f", 1000, "low")


def test_generators_use_configured_budgets(monkeypatch):
    calls = []
    monkeypatch.setattr(nar, "_anthropic", lambda *a: calls.append(a) or "{}")
    nar.digest_generate("x")
    nar.team_generate("y")
    assert calls[0][4] == config.NEWS_AUTO_DIGEST_MAX_TOKENS >= 2000
    assert calls[0][5] == config.NEWS_AUTO_DIGEST_EFFORT
    assert calls[1][4] == config.NEWS_AUTO_MAX_TOKENS >= 2000
    assert calls[1][5] == config.NEWS_AUTO_EFFORT


# ---- digest success is counted on written articles -------------------------

def test_all_digests_unparseable_is_not_ok(env):
    r = env.go(digest_generate=lambda p: "sorry, no json here")
    assert r["ok"] is False and env.calls == 0
    assert not os.path.exists(os.path.join(env.out, "processed.json"))


def test_no_new_articles_is_still_ok(env):
    assert env.go()["ok"]
    r = env.go(run_id="r2", digest_generate=lambda p: "never called")
    assert r["ok"] is True


# ---- deadline edge: stale bootstrap next GW ---------------------------------

def test_run_refused_when_next_gw_deadline_passed(env):
    late = datetime(2026, 11, 28, 10, 30, tzinfo=timezone.utc)  # 30 min after GW12 deadline
    r = env.go(now=late)
    assert r["ok"] is False
    assert r["errors"] == ["bootstrap next GW deadline already passed; retry after FPL updates"]
    assert env.calls == 0
    assert not os.path.exists(env.auto)
    assert not os.path.exists(os.path.join(env.out, "processed.json"))
    assert not os.path.exists(os.path.join(env.out, "changes.jsonl"))
    assert not os.path.exists(env.kb)
    assert json.load(open(os.path.join(env.out, "last_run.json")))["run_id"] == "r1"


# ---- disabled run still writes its receipt ---------------------------------

def test_disabled_run_writes_receipt_with_run_id(env, monkeypatch):
    monkeypatch.setattr(config, "NEWS_AUTO_ENABLED", False)
    assert nar.acquire_lock(env.out, "rd")
    env.go(lock_held=True, run_id="rd")
    last = json.load(open(os.path.join(env.out, "last_run.json")))
    assert last["run_id"] == "rd" and last["ok"] is True and last["skipped"] == "disabled"


# ---- per-club article cap keeps the newest ----------------------------------

def test_club_cap_keeps_newest_articles(env, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "NEWS_AUTO_MAX_ARTICLES_PER_TEAM", 1)
    items = "".join(
        f"<item><title>Arsenal news day{d}</title><link>https://x.test/a{d}.html</link>"
        f"<pubDate>{wd}, {d} Nov 2026 08:00:00 +0000</pubDate><description>Arsenal.</description></item>"
        for wd, d in (("Mon", "16"), ("Thu", "19"), ("Tue", "17")))
    rss = RSS.split("<item>")[0] + items + "</channel></rss>"
    prompts = []

    def team(p):
        prompts.append(p)
        return CUT
    assert env.go(rss=rss, team=team)["ok"]
    assert len(prompts) == 1 and "Arsenal news day19" in prompts[0]
    assert "day16" not in prompts[0] and "day17" not in prompts[0]


def test_digest_refreshes_lock(env, monkeypatch):
    touched = []
    real = nar.touch_lock
    monkeypatch.setattr(nar, "touch_lock", lambda d: touched.append("t") or real(d))
    env.go(team=lambda p: CUT, digest_generate=lambda p: touched.append("digest") or DIGEST)
    assert touched[:2] == ["t", "digest"]
