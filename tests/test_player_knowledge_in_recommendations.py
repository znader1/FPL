"""Injury/minutes knowledge must reach the transfer paths, not just the picker.

`_apply_player_knowledge` lived in squad_draft, so the squad picker downgraded
a player flagged "out until GW9" while the transfer decision card still scored
him at full xPts. These tests pin the shared helper and the boundary: live
recommendation paths apply knowledge, backtest/replay paths must not.
"""
import pandas as pd
import pytest

from src import player_knowledge, squad_draft


def _proj(ids=(1, 2), gws=(5, 6, 7), per_gw=2.0):
    df = pd.DataFrame({"id": list(ids), "web_name": [f"P{i}" for i in ids]})
    for g in gws:
        df[f"xpts_gw{g}"] = per_gw
    df["xpts_horizon"] = per_gw * len(gws)
    return df


def test_injured_player_is_zeroed_until_his_return_gw():
    proj = _proj()
    by_id = {1: {"availability": 1.0, "available_from_gw": 7, "note": "back GW7"}}
    out = player_knowledge.apply_to_projections(proj, [5, 6, 7], by_id)
    row = out[out["id"] == 1].iloc[0]
    assert row["xpts_gw5"] == 0.0 and row["xpts_gw6"] == 0.0
    assert row["xpts_gw7"] == 2.0
    assert row["xpts_horizon"] == 2.0
    assert row["pk_note"] == "back GW7"


def test_rotation_risk_scales_every_gameweek():
    proj = _proj()
    out = player_knowledge.apply_to_projections(proj, [5, 6, 7], {2: {"minutes_mult": 0.5}})
    row = out[out["id"] == 2].iloc[0]
    assert row["xpts_horizon"] == 3.0
    assert row["pk_availability"] == 0.5


def test_players_without_knowledge_are_untouched():
    proj = _proj()
    out = player_knowledge.apply_to_projections(proj, [5, 6, 7], {1: {"availability": 0.0}})
    untouched = out[out["id"] == 2].iloc[0]
    assert untouched["xpts_horizon"] == 6.0
    assert pd.isna(untouched["pk_note"])


def test_empty_knowledge_returns_the_frame_unchanged():
    proj = _proj()
    assert player_knowledge.apply_to_projections(proj, [5, 6, 7], {}) is proj


def test_apply_reads_the_file_and_resolves_names(tmp_path):
    """The one-call helper: load -> merge -> resolve names -> apply."""
    f = tmp_path / "pk.json"
    f.write_text('{"as_of": "2026-09-19", "players": {"P1": {"availability": 0.0}}}')
    proj, notes = player_knowledge.apply(_proj(), [5, 6, 7], path=str(f))
    assert proj[proj["id"] == 1].iloc[0]["xpts_horizon"] == 0.0
    assert proj[proj["id"] == 2].iloc[0]["xpts_horizon"] == 6.0
    assert notes == []


def test_apply_survives_a_missing_file(tmp_path):
    proj, notes = player_knowledge.apply(
        _proj(), [5, 6, 7], path=str(tmp_path / "nope.json"))
    assert proj[proj["id"] == 1].iloc[0]["xpts_horizon"] == 6.0
    assert notes == []


def test_apply_warns_when_the_file_is_stale(tmp_path):
    f = tmp_path / "pk.json"
    f.write_text('{"as_of": "2026-01-01", "players": {"1": {"minutes_mult": 0.5}}}')
    import datetime as dt
    _proj_out, notes = player_knowledge.apply(
        _proj(), [5, 6, 7], path=str(f), stale_days=10, today=dt.date(2026, 9, 19))
    assert any("days old" in n for n in notes)


def test_request_overrides_beat_the_file(tmp_path):
    f = tmp_path / "pk.json"
    f.write_text('{"as_of": "2026-09-19", "players": {"1": {"availability": 0.0}}}')
    proj, _ = player_knowledge.apply(
        _proj(), [5, 6, 7], request_pk={"players": {"1": {"availability": 1.0}}}, path=str(f))
    assert proj[proj["id"] == 1].iloc[0]["xpts_horizon"] == 6.0


def test_squad_draft_still_delegates_to_the_shared_helper():
    """The picker keeps working off the same implementation, not a copy."""
    proj = _proj()
    by_id = {1: {"minutes_mult": 0.5}}
    assert squad_draft._apply_player_knowledge(proj, [5, 6, 7], by_id).equals(
        player_knowledge.apply_to_projections(proj, [5, 6, 7], by_id))


@pytest.mark.parametrize("module_path", [
    "src/replay_builder.py", "src/backtest_adapter.py",
    "scripts/backtest_season.py", "scripts/backtest_minutes_ab.py",
])
def test_backtest_paths_do_not_apply_present_day_knowledge(module_path):
    """Applying today's injury file to a historical gameweek leaks the future
    into the backtest. The boundary is load-bearing — keep it greppable."""
    import pathlib
    src = pathlib.Path(module_path)
    if not src.exists():
        pytest.skip(f"{module_path} not present")
    assert "player_knowledge" not in src.read_text()
