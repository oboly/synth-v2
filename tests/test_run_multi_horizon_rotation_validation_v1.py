from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.research.run_multi_horizon_rotation_validation_v1 import (
    load_rows,
    load_split_manifest,
    select_phase_rows,
)


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _manifest() -> dict[str, object]:
    return {
        "manifest_version": "1.0.0",
        "final_holdout_inspected": False,
        "splits": {
            "discovery": {
                "start": BASE.isoformat(),
                "end": (BASE + timedelta(days=6)).isoformat(),
            },
            "validation": {
                "start": (BASE + timedelta(days=6)).isoformat(),
                "end": (BASE + timedelta(days=8)).isoformat(),
            },
            "final_holdout": {
                "start": (BASE + timedelta(days=8)).isoformat(),
                "end": (BASE + timedelta(days=10)).isoformat(),
            },
        },
    }


def test_manifest_requires_uninspected_final_holdout(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["final_holdout_inspected"] = True
    path = tmp_path / "split.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    try:
        load_split_manifest(path)
    except ValueError as exc:
        assert "final_holdout_inspected=false" in str(exc)
    else:
        raise AssertionError("expected inspected holdout manifest to fail")


def test_manifest_requires_contiguous_phase_boundaries(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["splits"]["validation"]["start"] = (BASE + timedelta(days=7)).isoformat()  # type: ignore[index]
    path = tmp_path / "split.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    try:
        load_split_manifest(path)
    except ValueError as exc:
        assert "contiguous" in str(exc)
    else:
        raise AssertionError("expected discontinuous manifest to fail")


def test_select_phase_rows_never_exposes_holdout() -> None:
    manifest = _manifest()
    rows_path_values = [
        BASE + timedelta(days=1),
        BASE + timedelta(days=7),
        BASE + timedelta(days=9),
    ]
    from src.research.multi_horizon_rotation_validation_v1 import ValidationRow

    rows = [
        ValidationRow(
            venue="bitvavo",
            asset_id=index + 1,
            asof_ts=timestamp,
            candidate_id="C1",
            candidate_score=1.0,
            b0_score=1.0,
            b0_pressure_state="ROTATION_IN",
            b1_return=0.01,
            forward_15m=0.01,
            forward_1h=0.01,
            forward_4h=0.01,
            forward_24h=0.01,
        )
        for index, timestamp in enumerate(rows_path_values)
    ]
    validation_rows = select_phase_rows(rows, manifest, "validation")
    assert [row.asset_id for row in validation_rows] == [2]
    try:
        select_phase_rows(rows, manifest, "final_holdout")
    except ValueError as exc:
        assert "final holdout" in str(exc)
    else:
        raise AssertionError("final holdout must not be accessible")


def test_load_rows_preserves_missing_baselines(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    row = {
        "venue": "bitvavo",
        "asset_id": 1,
        "asof_ts": BASE.isoformat(),
        "candidate_id": "C1",
        "candidate_score": "12.5",
        "b0_score": None,
        "b0_pressure_state": None,
        "b1_return": None,
        "forward_15m": None,
        "forward_1h": None,
        "forward_4h": None,
        "forward_24h": None,
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    rows = load_rows(path)
    assert len(rows) == 1
    assert rows[0].candidate_score == 12.5
    assert rows[0].b0_score is None
    assert rows[0].b1_return is None
