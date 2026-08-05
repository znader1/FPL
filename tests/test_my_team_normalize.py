from src import fpl_client


# Representative /api/my-team/{entry}/ payload (pre-first-deadline).
MY_TEAM = {
    "picks": [
        {"element": 1, "position": 1, "selling_price": 45, "multiplier": 1,
         "purchase_price": 45, "is_captain": False, "is_vice_captain": False},
        {"element": 2, "position": 11, "selling_price": 130, "multiplier": 1,
         "purchase_price": 130, "is_captain": True, "is_vice_captain": False},
    ],
    "chips": [{"status_for_entry": "available", "name": "wildcard"}],
    "transfers": {"cost": 4, "status": "cost", "limit": 1, "made": 0,
                  "bank": 5, "value": 1000},
}


def test_normalize_maps_transfers_into_entry_history():
    out = fpl_client.normalize_my_team(MY_TEAM, planning_event_id=1)

    # picks pass through untouched (downstream reads element/is_captain/etc.)
    assert out["picks"] == MY_TEAM["picks"]

    eh = out["entry_history"]
    assert eh["event"] == 1
    assert eh["bank"] == 5          # tenths of a million → downstream /10 = £0.5m
    assert eh["value"] == 1000
    assert eh["event_transfers"] == 0

    # No chip is active pre-deadline; the availability list is preserved separately.
    assert out["active_chip"] is None
    assert out["chips"] == MY_TEAM["chips"]

    # transfers.limit is FPL's authoritative free-transfer count.
    assert out["_free_transfers"] == 1
    assert out["_source"] == "my-team"


def test_normalize_tolerates_missing_transfers_block():
    out = fpl_client.normalize_my_team({"picks": []}, planning_event_id=3)
    assert out["picks"] == []
    assert out["entry_history"]["event"] == 3
    assert out["entry_history"]["bank"] is None
    assert out["entry_history"]["event_transfers"] == 0
    assert out["_free_transfers"] is None


def test_normalize_handles_none_input():
    out = fpl_client.normalize_my_team(None, planning_event_id=1)
    assert out["picks"] == []
    assert out["_free_transfers"] is None
