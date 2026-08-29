from types import SimpleNamespace

import src.research.run_entry_quality_shadow_bounded_eligible_v1 as runner


def test_split_evidence_eligible_excludes_only_incomplete_rows() -> None:
    rows = [
        SimpleNamespace(asset_id=1, symbol="BTC"),
        SimpleNamespace(asset_id=2, symbol="CAP"),
    ]
    complete = {
        "quality_ts_1d_utc": "q1d",
        "quality_ts_4h_utc": "q4h",
        "quality_ts_1h_utc": "q1h",
        "signal_ts_1d_utc": "s1d",
        "signal_ts_4h_utc": "s4h",
        "signal_ts_1h_utc": "s1h",
    }
    incomplete = dict(complete)
    incomplete["signal_ts_1d_utc"] = None
    incomplete["signal_ts_1h_utc"] = None

    eligible, excluded = runner.split_evidence_eligible(
        rows,
        {1: complete, 2: incomplete},
    )

    assert [row.asset_id for row in eligible] == [1]
    assert excluded == [
        {
            "asset_id": 2,
            "symbol": "CAP",
            "missing_evidence": ("signal_ts_1d_utc", "signal_ts_1h_utc"),
        }
    ]


def test_split_evidence_eligible_treats_missing_set_as_all_fields_missing() -> None:
    row = SimpleNamespace(asset_id=9, symbol="NOEVID")
    eligible, excluded = runner.split_evidence_eligible([row], {})

    assert eligible == []
    assert len(excluded) == 1
    assert excluded[0]["asset_id"] == 9
    assert tuple(excluded[0]["missing_evidence"]) == tuple(runner.EVIDENCE_FIELDS)
