"""Temporarily override ``src.config`` values (backtests, shadow projections).

Every key is validated before anything changes, so a typo can never leave
config half-patched, and the originals are restored even on exception.
"""
from __future__ import annotations

from contextlib import contextmanager

from src import config


@contextmanager
def config_overrides(overrides):
    overrides = dict(overrides or {})
    values = vars(config)
    for key in overrides:
        if not (isinstance(key, str) and key.isupper() and key in values):
            raise KeyError(f"unknown config key: {key}")
    originals = {key: values[key] for key in overrides}
    try:
        for key, value in overrides.items():
            setattr(config, key, value)
        yield
    finally:
        for key, value in originals.items():
            setattr(config, key, value)
