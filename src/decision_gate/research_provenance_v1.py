"""
research_provenance_v1 — canonical research-provenance / explicit-override
record for manual execution requests.

Layer: governance, adjacent to decision_gate. Records why an
externally-sourced research value (e.g. an uploaded A+ report's
expected-rise/spike target) was allowed into one specific, scoped, manual
execution preview — see
docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md
findings F7/F17 and AGENTS.md's external-note governance rule:

    external note -> normalized research label -> validation report
    -> optional feature/candidate after validation

This module implements the "explicit override, this instance only" branch
of that rule for a single, narrowly scoped manual execution preview. It
does NOT implement the "optional feature/candidate after validation"
promotion branch: selection_weight and decision_weight are hard-required to
be exactly 0 for every record buildable here (both in Python, via
build_research_provenance_record, and in the DB, via CHECK constraints on
execution_research_provenance) — there is no function anywhere in this
module that can set them to a nonzero value. Promoting research into an
actual selection/decision-weighted candidate is a separate, not-yet-built
lane and remains explicitly out of scope here. live_permission is likewise
hard-required to be False, matching the repository-wide
live-trading-permission=NOT_GRANTED state.

selection_engine and decision_gate scoring functions must never import this
module or read its selection_weight/decision_weight fields as scoring
input — see tests/test_manual_execution_p0_architecture_boundaries_v1.py.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Final


SOURCE_CLASSIFICATION_EXTERNAL_UPLOAD_RESEARCH: Final[str] = "EXTERNAL_UPLOAD_RESEARCH"

INGESTION_STATUS_UPLOADED_NOT_INGESTED: Final[str] = "UPLOADED_NOT_INGESTED"
INGESTION_STATUS_VALIDATED: Final[str] = "VALIDATED"
INGESTION_STATUS_REJECTED: Final[str] = "REJECTED"
VALID_INGESTION_STATUSES: Final[frozenset[str]] = frozenset(
    {
        INGESTION_STATUS_UPLOADED_NOT_INGESTED,
        INGESTION_STATUS_VALIDATED,
        INGESTION_STATUS_REJECTED,
    }
)

OVERRIDE_SCOPE_SINGLE_INSTANCE_MANUAL_EXECUTION_ONLY: Final[str] = (
    "SINGLE_INSTANCE_MANUAL_EXECUTION_ONLY"
)

VALID_ALLOWED_SIDES: Final[frozenset[str]] = frozenset({"BUY", "SELL", "BOTH"})

REQUIRED_SELECTION_WEIGHT: Final[Decimal] = Decimal("0")
REQUIRED_DECISION_WEIGHT: Final[Decimal] = Decimal("0")


class ResearchProvenanceValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ResearchProvenanceRecord:
    provenance_id: int | None
    source_classification: str
    source_path_or_identifier: str
    source_sha256: str
    source_ts_utc: datetime
    ingestion_status: str
    selection_weight: Decimal
    decision_weight: Decimal
    override_scope: str
    approving_user: str
    approval_ts_utc: datetime
    allowed_assets: tuple[str, ...]
    allowed_side: str
    preview_permission: bool
    live_permission: bool
    expires_ts_utc: datetime | None
    single_use: bool
    consumed_ts_utc: datetime | None = None
    created_ts_utc: datetime | None = None


def build_research_provenance_record(
    *,
    source_classification: str,
    source_path_or_identifier: str,
    source_sha256: str,
    source_ts_utc: datetime,
    ingestion_status: str,
    override_scope: str,
    approving_user: str,
    approval_ts_utc: datetime,
    allowed_assets: tuple[str, ...],
    allowed_side: str,
    preview_permission: bool,
    live_permission: bool,
    expires_ts_utc: datetime | None,
    single_use: bool,
    selection_weight: Decimal = REQUIRED_SELECTION_WEIGHT,
    decision_weight: Decimal = REQUIRED_DECISION_WEIGHT,
) -> ResearchProvenanceRecord:
    """Construct a validated, not-yet-persisted provenance record.

    Hard-fails if selection_weight/decision_weight are anything other than
    zero, if live_permission is True, if allowed_side is not
    BUY/SELL/BOTH, if ingestion_status is unknown, if source_sha256 is not a
    64-hex-char digest, or if allowed_assets is empty.
    """
    if selection_weight != REQUIRED_SELECTION_WEIGHT:
        raise ResearchProvenanceValidationError(
            "selection_weight must be exactly 0 for a research-override record; "
            "promotion into selection_engine scoring is a separate, unbuilt lane"
        )
    if decision_weight != REQUIRED_DECISION_WEIGHT:
        raise ResearchProvenanceValidationError(
            "decision_weight must be exactly 0 for a research-override record; "
            "promotion into decision_gate scoring is a separate, unbuilt lane"
        )
    if live_permission:
        raise ResearchProvenanceValidationError(
            "live_permission must be False; live trading permission is NOT_GRANTED"
        )
    if allowed_side not in VALID_ALLOWED_SIDES:
        raise ResearchProvenanceValidationError("allowed_side must be BUY, SELL, or BOTH")
    if ingestion_status not in VALID_INGESTION_STATUSES:
        raise ResearchProvenanceValidationError(f"unknown ingestion_status: {ingestion_status}")
    normalized_sha = source_sha256.lower()
    if len(normalized_sha) != 64 or any(c not in "0123456789abcdef" for c in normalized_sha):
        raise ResearchProvenanceValidationError("source_sha256 must be a 64-hex-char sha256 digest")
    if not allowed_assets:
        raise ResearchProvenanceValidationError("allowed_assets must not be empty")

    return ResearchProvenanceRecord(
        provenance_id=None,
        source_classification=source_classification,
        source_path_or_identifier=source_path_or_identifier,
        source_sha256=normalized_sha,
        source_ts_utc=source_ts_utc,
        ingestion_status=ingestion_status,
        selection_weight=selection_weight,
        decision_weight=decision_weight,
        override_scope=override_scope,
        approving_user=approving_user,
        approval_ts_utc=approval_ts_utc,
        allowed_assets=tuple(a.upper() for a in allowed_assets),
        allowed_side=allowed_side,
        preview_permission=preview_permission,
        live_permission=live_permission,
        expires_ts_utc=expires_ts_utc,
        single_use=single_use,
    )


def validate_override_for_use(
    record: ResearchProvenanceRecord,
    *,
    asset_symbol: str,
    side: str,
    now: datetime,
    for_live: bool = False,
) -> tuple[bool, tuple[str, ...]]:
    """Check whether this provenance record authorizes using its research
    target for one specific asset+side+preview/live request right now."""
    reasons: list[str] = []

    if asset_symbol.upper() not in record.allowed_assets:
        reasons.append("ASSET_NOT_IN_ALLOWED_SCOPE")
    if record.allowed_side != "BOTH" and side.upper() != record.allowed_side:
        reasons.append("SIDE_NOT_IN_ALLOWED_SCOPE")
    if for_live and not record.live_permission:
        reasons.append("LIVE_PERMISSION_NOT_GRANTED")
    if not for_live and not record.preview_permission:
        reasons.append("PREVIEW_PERMISSION_NOT_GRANTED")

    expires = record.expires_ts_utc
    if expires is not None:
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        now_aware = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        if now_aware > expires:
            reasons.append("OVERRIDE_EXPIRED")

    if record.single_use and record.consumed_ts_utc is not None:
        reasons.append("OVERRIDE_ALREADY_CONSUMED")

    if record.selection_weight != 0 or record.decision_weight != 0:
        reasons.append("NONZERO_WEIGHT_NOT_PERMITTED_FOR_OVERRIDE_RECORD")

    return (not reasons, tuple(reasons))


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor

    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    if isinstance(db_obj, tuple):
        return db_obj[1]
    return db_obj


@dataclass
class ResearchProvenanceRepository:
    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False, compare=False)

    def create(self, record: ResearchProvenanceRecord) -> ResearchProvenanceRecord:
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                INSERT INTO execution_research_provenance (
                    source_classification, source_path_or_identifier, source_sha256,
                    source_ts_utc, ingestion_status, selection_weight, decision_weight,
                    override_scope, approving_user, approval_ts_utc, allowed_assets_json,
                    allowed_side, preview_permission, live_permission, expires_ts_utc,
                    single_use
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    record.source_classification,
                    record.source_path_or_identifier,
                    record.source_sha256,
                    record.source_ts_utc,
                    record.ingestion_status,
                    record.selection_weight,
                    record.decision_weight,
                    record.override_scope,
                    record.approving_user,
                    record.approval_ts_utc,
                    json.dumps(list(record.allowed_assets)),
                    record.allowed_side,
                    int(record.preview_permission),
                    int(record.live_permission),
                    record.expires_ts_utc,
                    int(record.single_use),
                ],
            )
            provenance_id = int(cursor.lastrowid)
        return dataclasses.replace(record, provenance_id=provenance_id)

    def mark_consumed(self, provenance_id: int, *, consumed_ts_utc: datetime) -> None:
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """
                UPDATE execution_research_provenance
                SET consumed_ts_utc = %s
                WHERE provenance_id = %s AND single_use = 1 AND consumed_ts_utc IS NULL
                """,
                [consumed_ts_utc, provenance_id],
            )
            if cursor.rowcount != 1:
                raise ResearchProvenanceValidationError(
                    f"provenance_id={provenance_id} could not be marked consumed "
                    "(already consumed, not single_use, or not found)"
                )
