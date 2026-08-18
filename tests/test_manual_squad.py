import pandas as pd
import pytest

from src import manual_squad


def _elements():
    """Synthetic 2/5/5/3 pool, all cheap so a full pick stays under budget."""
    rows = []
    pid = 1
    layout = {1: 2, 2: 5, 3: 5, 4: 4}  # one spare FWD to allow choice
    for etype, n in layout.items():
        for _ in range(n):
            rows.append({"id": pid, "element_type": etype, "now_cost": 40 + pid})
            pid += 1
    return pd.DataFrame(rows)


def _legal_15(elements):
    need = {1: 2, 2: 5, 3: 5, 4: 3}
    ids = []
    for etype, n in need.items():
        pool = elements[elements["element_type"] == etype].head(n)
        ids += [int(x) for x in pool["id"].tolist()]
    return ids


def test_build_shape_and_positions():
    el = _elements()
    ids = _legal_15(el)
    mt = manual_squad.build_manual_myteam(el, ids, planning_event_id=1)

    assert len(mt["picks"]) == 15
    starters = [p for p in mt["picks"] if p["position"] <= 11]
    bench = [p for p in mt["picks"] if p["position"] >= 12]
    assert len(starters) == 11
    assert len(bench) == 4
    # Default XI is 3-4-3: exactly one starting GK.
    gk_ids = set(el[el["element_type"] == 1]["id"])
    start_gks = [p for p in starters if p["element"] in gk_ids]
    assert len(start_gks) == 1
    assert sum(1 for p in mt["picks"] if p["is_captain"]) == 1
    assert sum(1 for p in mt["picks"] if p["is_vice_captain"]) == 1


def test_entry_history_and_flags():
    el = _elements()
    ids = _legal_15(el)
    total = int(el.set_index("id").loc[ids, "now_cost"].sum())
    mt = manual_squad.build_manual_myteam(el, ids, planning_event_id=2)

    eh = mt["entry_history"]
    assert eh["event"] == 2
    assert eh["value"] == total
    assert eh["bank"] == manual_squad.BUDGET_TENTHS - total
    assert mt["active_chip"] is None
    assert mt["_source"] == "manual"
    assert mt["_pre_deadline"] is True


def test_explicit_captain_respected():
    el = _elements()
    ids = _legal_15(el)
    # A specified captain is honored as long as it's one of the starting XI.
    default = manual_squad.build_manual_myteam(el, ids, planning_event_id=1)
    starters = [p["element"] for p in default["picks"] if p["position"] <= 11]
    chosen = starters[-1]
    mt = manual_squad.build_manual_myteam(el, ids, captain_id=chosen, planning_event_id=1)
    caps = [p["element"] for p in mt["picks"] if p["is_captain"]]
    assert caps == [chosen]


def test_benched_captain_falls_back_to_a_starter():
    el = _elements()
    ids = _legal_15(el)
    default = manual_squad.build_manual_myteam(el, ids, planning_event_id=1)
    bench = [p["element"] for p in default["picks"] if p["position"] >= 12]
    mt = manual_squad.build_manual_myteam(el, ids, captain_id=bench[0], planning_event_id=1)
    cap = next(p for p in mt["picks"] if p["is_captain"])
    assert cap["position"] <= 11  # captain is always a starter


def test_wrong_count_rejected():
    el = _elements()
    with pytest.raises(ValueError, match="exactly 15"):
        manual_squad.build_manual_myteam(el, _legal_15(el)[:14], planning_event_id=1)


def test_wrong_composition_rejected():
    el = _elements()
    ids = _legal_15(el)
    # Swap a MID for the spare FWD -> 4 FWD / 4 MID, illegal.
    spare_fwd = int(el[el["element_type"] == 4]["id"].tolist()[-1])
    a_mid = next(i for i in ids if int(el.set_index("id").loc[i, "element_type"]) == 3)
    bad = [spare_fwd if i == a_mid else i for i in ids]
    with pytest.raises(ValueError):
        manual_squad.build_manual_myteam(el, bad, planning_event_id=1)


def test_over_budget_rejected():
    el = _elements()
    el.loc[el["id"] == 1, "now_cost"] = 5000  # blow the budget
    with pytest.raises(ValueError, match="over the"):
        manual_squad.build_manual_myteam(el, _legal_15(el), planning_event_id=1)


def test_unknown_id_rejected():
    el = _elements()
    ids = _legal_15(el)
    with pytest.raises(ValueError, match="Unknown"):
        manual_squad.build_manual_myteam(el, ids[:-1] + [99999], planning_event_id=1)


def test_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("FPL_MANUAL_SQUAD_DIR", str(tmp_path))
    saved = manual_squad.save_manual_squad(588004, [1, 2, 3], captain_id=2, vice_id=3)
    assert saved["player_ids"] == [1, 2, 3]
    loaded = manual_squad.load_manual_squad(588004)
    assert loaded["player_ids"] == [1, 2, 3]
    assert loaded["captain_id"] == 2
    assert manual_squad.clear_manual_squad(588004) is True
    assert manual_squad.load_manual_squad(588004) is None
