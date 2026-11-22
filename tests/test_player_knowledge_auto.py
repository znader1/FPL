"""Auto-written knowledge layer: sits under the manual file, expires by GW."""
import json

import pandas as pd
import pytest

from src import config, player_knowledge


def _proj(gws=(5, 6, 7), per_gw=2.0):
    df = pd.DataFrame({"id": [1], "web_name": ["Alpha"]})
    for g in gws:
        df[f"xpts_gw{g}"] = per_gw
    df["xpts_horizon"] = per_gw * len(gws)
    return df


def _write(tmp_path, name, players):
    f = tmp_path / name
    f.write_text(json.dumps({"as_of": "2099-01-01", "players": players}))
    return str(f)


def _run(tmp_path, auto, manual=None, request=None, gws=(5, 6, 7)):
    auto_path = _write(tmp_path, "auto.json", auto)
    man_path = _write(tmp_path, "manual.json", manual or {})
    out, _ = player_knowledge.apply(
        _proj(), list(gws), request_pk=request, path=man_path, auto_path=auto_path)
    return out.iloc[0]["xpts_horizon"]


def test_auto_entry_cuts_every_gw_in_horizon(tmp_path):
    h = _run(tmp_path, {"1": {"minutes_mult": 0.8, "expires_after_gw": 5}})
    assert h == pytest.approx(4.8)


def test_expired_auto_entry_is_ignored(tmp_path):
    assert _run(tmp_path, {"1": {"minutes_mult": 0.8, "expires_after_gw": 4}}) == 6.0


def test_manual_field_beats_auto_but_keeps_other_fields(tmp_path):
    h = _run(tmp_path,
             {"1": {"minutes_mult": 0.8, "availability": 1.0, "expires_after_gw": 5}},
             manual={"1": {"availability": 0.5}})
    assert h == pytest.approx(2.4)


def test_request_beats_manual_and_auto(tmp_path):
    h = _run(tmp_path, {"1": {"minutes_mult": 0.8, "expires_after_gw": 5}},
             request={"players": {"1": {"minutes_mult": 1.0}}})
    assert h == 6.0


def test_auto_file_corrupt_is_ignored(tmp_path):
    bad = tmp_path / "auto.json"
    bad.write_text("{not json")
    man = _write(tmp_path, "manual.json", {})
    out, _ = player_knowledge.apply(_proj(), [5, 6, 7], path=man, auto_path=str(bad))
    assert out.iloc[0]["xpts_horizon"] == 6.0


def test_name_keyed_manual_merges_with_id_keyed_auto(tmp_path):
    h = _run(tmp_path, {"1": {"minutes_mult": 0.8, "expires_after_gw": 5}},
             manual={"Alpha": {"availability": 0.5}})
    assert h == pytest.approx(2.4)


def test_future_created_auto_entry_is_ignored(tmp_path):
    h = _run(tmp_path, {"1": {"minutes_mult": 0.8, "created_gw": 6, "expires_after_gw": 6}})
    assert h == 6.0


def test_auto_path_defaults_to_config(tmp_path, monkeypatch):
    auto_path = _write(tmp_path, "auto.json", {"1": {"minutes_mult": 0.8, "expires_after_gw": 5}})
    man = _write(tmp_path, "manual.json", {})
    monkeypatch.setattr(config, "PLAYER_KNOWLEDGE_AUTO_PATH", auto_path)
    out, _ = player_knowledge.apply(_proj(), [5, 6, 7], path=man)
    assert out.iloc[0]["xpts_horizon"] == pytest.approx(4.8)


def test_auto_note_passes_through(tmp_path):
    auto_path = _write(tmp_path, "auto.json",
                       {"1": {"minutes_mult": 0.8, "expires_after_gw": 5, "note": "knock"}})
    man = _write(tmp_path, "manual.json", {})
    out, _ = player_knowledge.apply(_proj(), [5, 6, 7], path=man, auto_path=auto_path)
    assert out.iloc[0]["pk_note"] == "knock"
