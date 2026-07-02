from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.research.breathline_v1_recovery_cohort_manifest_v1 import (
    APPROVAL_STATUS_APPROVED,
    V1_CHECKPOINT_RATIOS,
    V1_CYCLE_DAYS,
    V1_OFFSET_GRID,
    CohortManifestError,
    CohortPayload,
    canonical_payload_bytes,
    compute_payload_sha256,
    envelope_filename,
    load_approval_envelope,
    load_cohort_payload,
    payload_filename,
    resolve_approved_cohort,
    verify_v1_semantics,
)

FROZEN_V1_SOURCE_PATH = PROJECT_ROOT / "src/research/backtest_breath_curve_partial_to_full_v1.py"

VALID_PAYLOAD_FIELDS = {
    "canonical_symbols": ["BTC", "ETH"],
    "canonical_base_anchors": ["2025-01-01", "2025-01-22"],
    "checkpoint_ratios": list(V1_CHECKPOINT_RATIOS),
    "cycle_days": V1_CYCLE_DAYS,
    "offset_grid": list(V1_OFFSET_GRID),
    "cohort_source": {"note": "synthetic test fixture, not real research data"},
}


def write_payload_file(tmp_path: Path, fields: dict) -> Path:
    payload_sha256 = compute_payload_sha256(fields)
    path = tmp_path / payload_filename(payload_sha256)
    path.write_bytes(canonical_payload_bytes(fields))
    return path


def write_envelope_file(
    tmp_path: Path,
    *,
    envelope_id: str,
    cohort_payload_sha256: str,
    approval_status: str = APPROVAL_STATUS_APPROVED,
    approved_by: str = "unit-test",
    approved_at_utc: str = "2025-01-01T00:00:00Z",
) -> Path:
    fields = {
        "envelope_id": envelope_id,
        "cohort_payload_sha256": cohort_payload_sha256,
        "approval_status": approval_status,
        "approved_by": approved_by,
        "approved_at_utc": approved_at_utc,
    }
    path = tmp_path / envelope_filename(envelope_id)
    path.write_text(json.dumps(fields, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return path


def _payload_with(**overrides: object) -> CohortPayload:
    base: dict[str, object] = dict(
        canonical_symbols=("BTC",),
        canonical_base_anchors=("2025-01-01",),
        checkpoint_ratios=V1_CHECKPOINT_RATIOS,
        cycle_days=V1_CYCLE_DAYS,
        offset_grid=V1_OFFSET_GRID,
        cohort_source={"note": "synthetic"},
        payload_sha256="deadbeef",
    )
    base.update(overrides)
    return CohortPayload(**base)


def test_payload_hash_excludes_approval_fields() -> None:
    base_hash = compute_payload_sha256(VALID_PAYLOAD_FIELDS)
    tampered = dict(VALID_PAYLOAD_FIELDS)
    tampered["approval_status"] = APPROVAL_STATUS_APPROVED
    with pytest.raises(CohortManifestError, match="unexpected fields"):
        compute_payload_sha256(tampered)
    assert compute_payload_sha256(dict(VALID_PAYLOAD_FIELDS)) == base_hash


def test_load_cohort_payload_round_trips(tmp_path: Path) -> None:
    path = write_payload_file(tmp_path, VALID_PAYLOAD_FIELDS)
    payload = load_cohort_payload(path)
    assert payload.canonical_symbols == ("BTC", "ETH")
    assert payload.canonical_base_anchors == ("2025-01-01", "2025-01-22")
    assert payload.checkpoint_ratios == V1_CHECKPOINT_RATIOS
    assert payload.cycle_days == V1_CYCLE_DAYS
    assert payload.offset_grid == V1_OFFSET_GRID
    assert payload.payload_sha256 == compute_payload_sha256(VALID_PAYLOAD_FIELDS)


def test_noncanonical_payload_bytes_rejected(tmp_path: Path) -> None:
    payload_sha256 = compute_payload_sha256(VALID_PAYLOAD_FIELDS)
    path = tmp_path / payload_filename(payload_sha256)
    path.write_text(json.dumps(VALID_PAYLOAD_FIELDS, indent=2, sort_keys=True), encoding="utf-8")
    with pytest.raises(CohortManifestError, match="not canonical JSON"):
        load_cohort_payload(path)


def test_payload_tolerates_single_trailing_newline(tmp_path: Path) -> None:
    payload_sha256 = compute_payload_sha256(VALID_PAYLOAD_FIELDS)
    path = tmp_path / payload_filename(payload_sha256)
    path.write_bytes(canonical_payload_bytes(VALID_PAYLOAD_FIELDS) + b"\n")
    payload = load_cohort_payload(path)
    assert payload.payload_sha256 == payload_sha256


def test_filename_hash_mismatch_rejected(tmp_path: Path) -> None:
    path = tmp_path / payload_filename("0" * 64)
    path.write_bytes(canonical_payload_bytes(VALID_PAYLOAD_FIELDS))
    with pytest.raises(CohortManifestError, match="does not match its own content hash"):
        load_cohort_payload(path)


def test_envelope_draft_for_approval_rejected(tmp_path: Path) -> None:
    payload_path = write_payload_file(tmp_path, VALID_PAYLOAD_FIELDS)
    payload = load_cohort_payload(payload_path)
    envelope_path = write_envelope_file(
        tmp_path,
        envelope_id="env-1",
        cohort_payload_sha256=payload.payload_sha256,
        approval_status="DRAFT_FOR_APPROVAL",
    )
    with pytest.raises(CohortManifestError, match="approval_status is not APPROVED"):
        resolve_approved_cohort(payload_path, envelope_path)


def test_envelope_rejected_status_rejected(tmp_path: Path) -> None:
    payload_path = write_payload_file(tmp_path, VALID_PAYLOAD_FIELDS)
    payload = load_cohort_payload(payload_path)
    envelope_path = write_envelope_file(
        tmp_path,
        envelope_id="env-1",
        cohort_payload_sha256=payload.payload_sha256,
        approval_status="REJECTED",
    )
    with pytest.raises(CohortManifestError, match="approval_status is not APPROVED"):
        resolve_approved_cohort(payload_path, envelope_path)


def test_envelope_payload_hash_mismatch_rejected(tmp_path: Path) -> None:
    payload_path = write_payload_file(tmp_path, VALID_PAYLOAD_FIELDS)
    envelope_path = write_envelope_file(
        tmp_path,
        envelope_id="env-1",
        cohort_payload_sha256="f" * 64,
    )
    with pytest.raises(CohortManifestError, match="does not match loaded payload"):
        resolve_approved_cohort(payload_path, envelope_path)


def test_envelope_filename_must_match_envelope_id(tmp_path: Path) -> None:
    payload_path = write_payload_file(tmp_path, VALID_PAYLOAD_FIELDS)
    payload = load_cohort_payload(payload_path)
    fields = {
        "envelope_id": "actual-id",
        "cohort_payload_sha256": payload.payload_sha256,
        "approval_status": APPROVAL_STATUS_APPROVED,
        "approved_by": "unit-test",
        "approved_at_utc": "2025-01-01T00:00:00Z",
    }
    wrong_path = tmp_path / envelope_filename("different-id")
    wrong_path.write_text(json.dumps(fields), encoding="utf-8")
    with pytest.raises(CohortManifestError, match="does not match its envelope_id"):
        load_approval_envelope(wrong_path)


def test_checkpoint_ratios_mismatch_rejected() -> None:
    payload = _payload_with(checkpoint_ratios=("0.5", "0.786"))
    with pytest.raises(CohortManifestError, match="checkpoint_ratios does not match"):
        verify_v1_semantics(payload)


def test_cycle_days_mismatch_rejected() -> None:
    payload = _payload_with(cycle_days="7.0")
    with pytest.raises(CohortManifestError, match="cycle_days does not match"):
        verify_v1_semantics(payload)


def test_offset_grid_mismatch_rejected() -> None:
    payload = _payload_with(offset_grid=("-5", "0", "5"))
    with pytest.raises(CohortManifestError, match="offset_grid does not match"):
        verify_v1_semantics(payload)


def test_v1_semantics_checked_before_envelope_is_read(tmp_path: Path) -> None:
    fields = dict(VALID_PAYLOAD_FIELDS)
    fields["cycle_days"] = "7.0"
    payload_path = write_payload_file(tmp_path, fields)
    nonexistent_envelope = tmp_path / envelope_filename("does-not-exist")
    with pytest.raises(CohortManifestError, match="cycle_days does not match"):
        resolve_approved_cohort(payload_path, nonexistent_envelope)


def test_resolve_approved_cohort_accepts_approved_envelope(tmp_path: Path) -> None:
    payload_path = write_payload_file(tmp_path, VALID_PAYLOAD_FIELDS)
    payload = load_cohort_payload(payload_path)
    envelope_path = write_envelope_file(
        tmp_path,
        envelope_id="env-1",
        cohort_payload_sha256=payload.payload_sha256,
    )
    resolved_payload, resolved_envelope = resolve_approved_cohort(payload_path, envelope_path)
    assert resolved_payload.payload_sha256 == payload.payload_sha256
    assert resolved_envelope.approval_status == APPROVAL_STATUS_APPROVED


def test_frozen_v1_defaults_match_compatibility_constants() -> None:
    # Test-side source inspection only: read the frozen V1 module's text and
    # extract its own argparse defaults. Never import or execute frozen V1.
    source_text = FROZEN_V1_SOURCE_PATH.read_text(encoding="utf-8")

    checkpoints_match = re.search(r'"--checkpoints",\s*default="([^"]+)"', source_text)
    cycle_days_match = re.search(r'"--cycle-days",\s*type=float,\s*default=([0-9.]+)', source_text)
    offsets_match = re.search(r'"--offsets",\s*default="([^"]+)"', source_text)

    assert checkpoints_match is not None, "could not locate --checkpoints default in frozen V1 source"
    assert cycle_days_match is not None, "could not locate --cycle-days default in frozen V1 source"
    assert offsets_match is not None, "could not locate --offsets default in frozen V1 source"

    assert tuple(checkpoints_match.group(1).split(",")) == V1_CHECKPOINT_RATIOS
    assert cycle_days_match.group(1) == V1_CYCLE_DAYS
    assert tuple(offsets_match.group(1).split(",")) == V1_OFFSET_GRID
