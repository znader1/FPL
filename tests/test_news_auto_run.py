import json
import os
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
    assert nar.acquire_lock(env.out) is True
    assert nar.acquire_lock(env.out) is False
    assert nar.read_status(env.out, env.auto)["running"] is True
    r = env.go()
    assert r["ok"] is False
    nar.release_lock(env.out)
    assert nar.acquire_lock(env.out) is True


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
    assert nar.acquire_lock(env.out) is True
