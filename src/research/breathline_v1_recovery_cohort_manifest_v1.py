"""
Breathline V1 recovery cohort payload and approval-envelope loader/validator.

Safety markers:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PAYLOAD_FIELDS = (
    "canonical_symbols",
    "canonical_base_anchors",
    "checkpoint_ratios",
    "cycle_days",
    "offset_grid",
    "cohort_source",
)

ENVELOPE_FIELDS = (
    "envelope_id",
    "cohort_payload_sha256",
    "approval_status",
    "approved_by",
    "approved_at_utc",
)

APPROVAL_STATUS_APPROVED = "APPROVED"

# Frozen V1 semantics lock.
#
# These are explicit compatibility constants, not runtime-discovered values.
# src/research/backtest_breath_curve_partial_to_full_v1.py is frozen and must
# never be imported here to derive them. They mirror that module's argparse
# defaults for --checkpoints, --cycle-days, and --offsets exactly.
V1_CHECKPOINT_RATIOS: tuple[str, ...] = ("0.618", "0.786")
V1_CYCLE_DAYS: str = "21.0"
V1_OFFSET_GRID: tuple[str, ...] = ("-10.5", "-7", "-5", "-3", "0", "3", "5", "7", "10.5")


class CohortManifestError(RuntimeError):
    pass


@dataclass(frozen=True)
class CohortPayload:
    canonical_symbols: tuple[str, ...]
    canonical_base_anchors: tuple[str, ...]
    checkpoint_ratios: tuple[str, ...]
    cycle_days: str
    offset_grid: tuple[str, ...]
    cohort_source: Any
    payload_sha256: str


@dataclass(frozen=True)
class ApprovalEnvelope:
    envelope_id: str
    cohort_payload_sha256: str
    approval_status: str
    approved_by: str
    approved_at_utc: str


def canonical_payload_bytes(fields: dict[str, Any]) -> bytes:
    """Serialize exactly the hashed payload fields as canonical UTF-8 JSON.

    Canonical form: sorted keys, compact separators, no whitespace. The
    payload must contain only PAYLOAD_FIELDS -- in particular it must never
    carry its own hash or an approval_status; those belong to the separate
    approval envelope.
    """
    missing = [name for name in PAYLOAD_FIELDS if name not in fields]
    if missing:
        raise CohortManifestError(f"cohort payload missing required fields: {missing}")
    extra = sorted(set(fields) - set(PAYLOAD_FIELDS))
    if extra:
        raise CohortManifestError(f"cohort payload has unexpected fields: {extra}")
    ordered = {name: fields[name] for name in PAYLOAD_FIELDS}
    return json.dumps(ordered, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_payload_sha256(fields: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_payload_bytes(fields)).hexdigest()


def payload_filename(payload_sha256: str) -> str:
    return f"cohort_payload_{payload_sha256}.json"


def envelope_filename(envelope_id: str) -> str:
    return f"approval_envelope_{envelope_id}.json"


def _strip_single_trailing_newline(raw_bytes: bytes) -> bytes:
    if raw_bytes.endswith(b"\n"):
        return raw_bytes[:-1]
    return raw_bytes


def load_cohort_payload(path: Path) -> CohortPayload:
    if not path.is_file():
        raise CohortManifestError(f"cohort payload file not found: {path}")
    raw_bytes = path.read_bytes()
    try:
        fields = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise CohortManifestError(f"cohort payload is not valid JSON: {path}") from exc
    if not isinstance(fields, dict):
        raise CohortManifestError(f"cohort payload must be a JSON object: {path}")

    canonical_bytes = canonical_payload_bytes(fields)
    # A trailing newline is tolerated (many editors/tools add one); any other
    # deviation from canonical bytes -- key order, spacing, formatting -- is
    # rejected so the on-disk file and its content hash can never disagree.
    if _strip_single_trailing_newline(raw_bytes) != canonical_bytes:
        raise CohortManifestError(
            "cohort payload file is not canonical JSON "
            f"(sorted keys, compact separators, no extra whitespace): {path}"
        )

    computed_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
    expected_filename = payload_filename(computed_sha256)
    if path.name != expected_filename:
        raise CohortManifestError(
            "cohort payload filename does not match its own content hash: "
            f"expected {expected_filename}, found {path.name}"
        )

    return CohortPayload(
        canonical_symbols=tuple(fields["canonical_symbols"]),
        canonical_base_anchors=tuple(fields["canonical_base_anchors"]),
        checkpoint_ratios=tuple(fields["checkpoint_ratios"]),
        cycle_days=str(fields["cycle_days"]),
        offset_grid=tuple(fields["offset_grid"]),
        cohort_source=fields["cohort_source"],
        payload_sha256=computed_sha256,
    )


def load_approval_envelope(path: Path) -> ApprovalEnvelope:
    if not path.is_file():
        raise CohortManifestError(f"approval envelope file not found: {path}")
    try:
        fields = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CohortManifestError(f"approval envelope is not valid JSON: {path}") from exc
    if not isinstance(fields, dict):
        raise CohortManifestError(f"approval envelope must be a JSON object: {path}")

    missing = [name for name in ENVELOPE_FIELDS if name not in fields]
    if missing:
        raise CohortManifestError(f"approval envelope missing required fields: {missing}")

    envelope_id = str(fields["envelope_id"])
    expected_filename = envelope_filename(envelope_id)
    if path.name != expected_filename:
        raise CohortManifestError(
            "approval envelope filename does not match its envelope_id: "
            f"expected {expected_filename}, found {path.name}"
        )

    return ApprovalEnvelope(
        envelope_id=envelope_id,
        cohort_payload_sha256=str(fields["cohort_payload_sha256"]),
        approval_status=str(fields["approval_status"]),
        approved_by=str(fields["approved_by"]),
        approved_at_utc=str(fields["approved_at_utc"]),
    )


def verify_v1_semantics(payload: CohortPayload) -> None:
    """Reject any payload whose V1 semantics differ from the frozen lock.

    These fields are a compatibility declaration, not runtime configuration:
    the frozen V1 subprocess always runs with its own hardcoded defaults.
    """
    if tuple(payload.checkpoint_ratios) != V1_CHECKPOINT_RATIOS:
        raise CohortManifestError(
            "checkpoint_ratios does not match frozen V1 compatibility constant: "
            f"expected {V1_CHECKPOINT_RATIOS}, got {tuple(payload.checkpoint_ratios)}"
        )
    if payload.cycle_days != V1_CYCLE_DAYS:
        raise CohortManifestError(
            "cycle_days does not match frozen V1 compatibility constant: "
            f"expected {V1_CYCLE_DAYS!r}, got {payload.cycle_days!r}"
        )
    if tuple(payload.offset_grid) != V1_OFFSET_GRID:
        raise CohortManifestError(
            "offset_grid does not match frozen V1 compatibility constant: "
            f"expected {V1_OFFSET_GRID}, got {tuple(payload.offset_grid)}"
        )


def resolve_approved_cohort(
    payload_path: Path,
    envelope_path: Path,
) -> tuple[CohortPayload, ApprovalEnvelope]:
    """Load, validate, and approve a cohort. Raises before any job enumeration.

    Order: load+validate the payload (canonical bytes, filename hash), lock
    its V1 semantics, then load+validate the envelope and require it to
    reference this exact payload hash and carry APPROVED status.
    """
    payload = load_cohort_payload(payload_path)
    verify_v1_semantics(payload)
    envelope = load_approval_envelope(envelope_path)
    if envelope.cohort_payload_sha256 != payload.payload_sha256:
        raise CohortManifestError(
            "approval envelope cohort_payload_sha256 does not match loaded payload: "
            f"envelope={envelope.cohort_payload_sha256} payload={payload.payload_sha256}"
        )
    if envelope.approval_status != APPROVAL_STATUS_APPROVED:
        raise CohortManifestError(
            f"cohort payload approval_status is not {APPROVAL_STATUS_APPROVED}: "
            f"{envelope.approval_status}"
        )
    return payload, envelope
