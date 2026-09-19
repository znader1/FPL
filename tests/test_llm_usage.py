"""Every LLM call must leave a priced usage record (pre-monetization audit).

``response.usage`` was dropped at all eight ``messages.create`` sites, so the
cost per user per gameweek — the only line item that scales with users — was
a guess. These tests pin the accounting helper and its wiring.
"""
import json
import logging
from types import SimpleNamespace

from src import llm_usage


def _resp(model="claude-haiku-4-5-20251001", inp=2000, out=400, cr=0, cw=0):
    usage = SimpleNamespace(
        input_tokens=inp, output_tokens=out,
        cache_read_input_tokens=cr, cache_creation_input_tokens=cw,
    )
    return SimpleNamespace(model=model, usage=usage, content=[])


def test_haiku_call_is_priced_from_the_usage_block(monkeypatch):
    monkeypatch.delenv("FPL_LLM_USAGE_LOG", raising=False)
    rec = llm_usage.record_usage(_resp(), feature="explain", gw=6, user="u1")
    assert rec["input_tokens"] == 2000 and rec["output_tokens"] == 400
    assert rec["feature"] == "explain" and rec["gw"] == 6 and rec["user"] == "u1"
    # 2000 * $1/M + 400 * $5/M
    assert rec["usd"] == 0.004


def test_dated_snapshot_prices_by_longest_prefix():
    assert llm_usage.estimate_usd("claude-sonnet-4-6", 1_000_000, 0) == 3.0
    assert llm_usage.estimate_usd("claude-haiku-4-5-20251001", 0, 1_000_000) == 5.0


def test_cache_reads_are_discounted():
    usd = llm_usage.estimate_usd("claude-haiku-4-5", 0, 0, cache_read=1_000_000)
    assert usd == 0.1


def test_unknown_model_records_tokens_but_no_price(monkeypatch):
    monkeypatch.delenv("FPL_LLM_USAGE_LOG", raising=False)
    rec = llm_usage.record_usage(_resp(model="future-model-9"), feature="x")
    assert rec["input_tokens"] == 2000 and rec["usd"] is None


def test_response_without_usage_never_raises(monkeypatch):
    monkeypatch.delenv("FPL_LLM_USAGE_LOG", raising=False)
    assert llm_usage.record_usage(SimpleNamespace(content=[]), feature="x") is None
    assert llm_usage.record_usage(None, feature="x") is None


def test_user_comes_from_request_context_when_not_passed(monkeypatch):
    monkeypatch.delenv("FPL_LLM_USAGE_LOG", raising=False)
    llm_usage.bind_user("sub-42")
    try:
        rec = llm_usage.record_usage(_resp(), feature="captain_agent")
        assert rec["user"] == "sub-42"
    finally:
        llm_usage.bind_user(None)


def test_jsonl_sink_appends_one_row_per_call(monkeypatch, tmp_path):
    path = tmp_path / "usage.jsonl"
    monkeypatch.setenv("FPL_LLM_USAGE_LOG", str(path))
    llm_usage.record_usage(_resp(), feature="a", gw=1)
    llm_usage.record_usage(_resp(out=100), feature="b", gw=1)
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    assert [r["feature"] for r in rows] == ["a", "b"]
    assert rows[1]["output_tokens"] == 100


def test_log_line_carries_the_fields_ops_will_grep(monkeypatch, caplog):
    monkeypatch.delenv("FPL_LLM_USAGE_LOG", raising=False)
    with caplog.at_level(logging.INFO, logger="fpl.llm_usage"):
        llm_usage.record_usage(_resp(), feature="explain", gw=6, user="u1")
    line = caplog.text
    assert "llm_usage feature=explain" in line and "usd=0.004" in line and "gw=6" in line


def test_explainer_records_usage_for_its_call(monkeypatch):
    """Wiring: src.explainer.explain must hand its response to record_usage."""
    import anthropic
    from src import explainer

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("FPL_EXPLAIN_MODEL", raising=False)
    explainer._cache.clear()

    class _Msgs:
        def create(self, **kw):
            r = _resp(model=kw["model"])
            r.content = [SimpleNamespace(type="text", text='{"transfers": [], "captain": {}, "chip": {}}')]
            return r

    class _Client:
        def __init__(self, api_key=None):
            self.messages = _Msgs()

    monkeypatch.setattr(anthropic, "Anthropic", _Client)
    seen = []
    monkeypatch.setattr(llm_usage, "record_usage", lambda resp, feature, **kw: seen.append((feature, kw)) or {})

    explainer.explain({"gw": 6, "transfers": [], "unique": "no-cache-hit-please"})
    assert seen and seen[0][0] == "explain"
