"""Learned strategy rules stay out of the specialist prompts unless switched on.

The reflection agent's rules (src/agent_memory strategy_rules table) were
injected into every /chat/captain|transfer|chip call as "apply these". They
came from 2-4 GWs of a 2025-26 backtest and let the LLM override the engine's
pick, so AGENT_INJECT_LEARNED_RULES gates them, default off.
"""
import pytest

from api import chat
from src import agent_memory, config


@pytest.fixture()
def store_with_rule(tmp_path, monkeypatch):
    db = tmp_path / "decisions.db"
    real_store = agent_memory.MemoryStore
    real_store(db_path=db).add_strategy_rule(
        "Avoid captaining Erling Haaland in consecutive gameweeks.", [18, 19]
    )
    # _load_rules_text imports MemoryStore at call time; point it at the tmp DB.
    monkeypatch.setattr(agent_memory, "MemoryStore", lambda *a, **k: real_store(db_path=db))
    return db


def test_flag_defaults_off():
    assert config.AGENT_INJECT_LEARNED_RULES is False


def test_rules_not_loaded_when_flag_off(store_with_rule, monkeypatch):
    monkeypatch.setattr(config, "AGENT_INJECT_LEARNED_RULES", False)
    assert chat._load_rules_text() is None


def test_flag_off_never_opens_the_store(monkeypatch):
    monkeypatch.setattr(config, "AGENT_INJECT_LEARNED_RULES", False)

    def boom(*a, **k):
        raise AssertionError("MemoryStore opened while injection is off")

    monkeypatch.setattr(agent_memory, "MemoryStore", boom)
    assert chat._load_rules_text() is None


def test_rules_loaded_when_flag_on(store_with_rule, monkeypatch):
    monkeypatch.setattr(config, "AGENT_INJECT_LEARNED_RULES", True)
    text = chat._load_rules_text()
    assert text is not None
    assert "Haaland" in text
