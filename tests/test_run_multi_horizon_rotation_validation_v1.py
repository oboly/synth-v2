from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.research.run_multi_horizon_rotation_validation_v1 import (
    load_rows,
    load_split_manifest,
    validate_phase_scoped_rows,
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


def _validation_row(timestamp: datetime, asset_id: int):
    from src.research.multi_horizon_rotation_validation_v1 import ValidationRow

    return ValidationRow(
        venue="bitvavo",
        asset_id=asset_id,
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


def _raw_row(**overrides):
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
    row.update(overrides)
    return row


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


def test_manifest_rejects_off_grid_boundary(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["splits"]["validation"]["end"] = (BASE + timedelta(days=8, minutes=1)).isoformat()  # type: ignore[index]
    path = tmp_path / "split.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    try:
        load_split_manifest(path)
    except ValueError as exc:
        assert "15m grid" in str(exc)
    else:
        raise AssertionError("expected off-grid manifest to fail")


def test_manifest_rejects_inverted_phase(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["splits"]["discovery"]["end"] = (BASE - timedelta(days=1)).isoformat()  # type: ignore[index]
    path = tmp_path / "split.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    try:
        load_split_manifest(path)
    except ValueError as exc:
        assert "end must be after start" in str(exc)
    else:
        raise AssertionError("expected inverted manifest to fail")


def test_phase_scoped_validation_artifact_passes() -> None:
    manifest = _manifest()
    rows = [
        _validation_row(BASE + timedelta(days=6, hours=1), 1),
        _validation_row(BASE + timedelta(days=7), 2),
    ]
    assert validate_phase_scoped_rows(rows, manifest, "validation") == rows


def test_mixed_phase_or_holdout_artifact_fails_closed() -> None:
    manifest = _manifest()
    rows = [
        _validation_row(BASE + timedelta(days=7), 1),
        _validation_row(BASE + timedelta(days=9), 2),
    ]
    try:
        validate_phase_scoped_rows(rows, manifest, "validation")
    except ValueError as exc:
        assert "not phase-scoped" in str(exc)
    else:
        raise AssertionError("mixed validation/holdout artifact must fail")


def test_final_holdout_phase_is_not_available() -> None:
    manifest = _manifest()
    rows = [_validation_row(BASE + timedelta(days=9), 1)]
    try:
        validate_phase_scoped_rows(rows, manifest, "final_holdout")
    except ValueError as exc:
        assert "final holdout" in str(exc)
    else:
        raise AssertionError("final holdout must not be accessible")


def test_load_rows_preserves_missing_baselines(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps(_raw_row()) + "\n", encoding="utf-8")
    rows = load_rows(path)
    assert len(rows) == 1
    assert rows[0].candidate_score == 12.5
    assert rows[0].b0_score is None
    assert rows[0].b1_return is None


def test_load_rows_rejects_non_finite_numeric_value(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps(_raw_row(candidate_score="NaN")) + "\n", encoding="utf-8")
    try:
        load_rows(path)
    except ValueError as exc:
        assert "must be finite" in str(exc)
    else:
        raise AssertionError("non-finite metric must fail")


def test_load_rows_rejects_duplicate_identity(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    row = _raw_row()
    path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    try:
        load_rows(path)
    except ValueError as exc:
        assert "duplicate validation row identity" in str(exc)
    else:
        raise AssertionError("duplicate validation identity must fail")
