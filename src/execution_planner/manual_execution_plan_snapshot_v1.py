"""
manual_execution_plan_snapshot_v1 — the immutable manual execution plan
snapshot named as missing in
db/migrations/20260628_execution_ladder_profiles_v1.sql ("Non-goals: ... no
plan snapshot") and required by GitHub Issue #202.

Layer: execution_planner. One row per approved manual execution request,
persisted only after src.execution_planner.contract_preview_v1 has already
built a plan preview from a decision_gate-approved request/approval pair.
This module never evaluates permission and never builds plan legs itself —
it only serializes an already-built ExecutionPlanPreview plus its request/
approval identity into an immutable, queryable record.

Permission boundary: build_plan_snapshot() requires a persisted
ManualExecutionApprovalRecord with approval_state == APPROVED (decision_gate
never writes a manual_execution_approval row for a BLOCKED/DENIED decision —
see src.decision_gate.manual_execution_gate_v1.approve_and_reserve), so a
denied request can never reach this module with anything to snapshot. The
one caller, src.manual_execution.manual_execution_service_v1.process(),
only calls this module after both decision_gate approval and a successful
execution_planner preview have already happened.

Side-neutral: side may be BUY or SELL (db/migrations/20260811_manual_execution_plan_snapshot_v1.sql
CHECK side IN ('BUY','SELL')). No BUY plan can be produced by production
code today because decision_gate blocks all BUY requests before an approval
row ever exists (REASON_MANUAL_BUY_GATE_NOT_YET_IMPLEMENTED) — that gap is
a separate, not-yet-implemented step, not this module's concern.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Final

from src.decision_gate.manual_execution_approval_v1 import (
    APPROVAL_STATE_APPROVED,
    ManualExecutionApprovalRecord,
)
from src.execution_planner.contract_preview_v1 import ExecutionPlanPreview
from src.manual_execution.manual_execution_request_v1 import ManualExecutionRequest


PLAN_STATE_PREVIEW_ONLY: Final[str] = "PREVIEW_ONLY"


class ManualExecutionPlanSnapshotValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ManualExecutionPlanSnapshot:
    plan_snapshot_id: int | None
    idempotency_key: str
    request_id: int
    approval_id: int

    trading_account_id: int
    account_code: str
    venue: str
    asset_id: int
    base_asset: str
    quote_asset: str
    side: str
    mode: str

    plan_type: str
    execution_mode: str
    plan_state: str
    sleeve_code: str

    ladder_profile_id: int | None
    ladder_profile_version: int | None
    anchor_reference_price: Decimal | None
    anchor_ts_utc: datetime | None

    provenance_id: int | None

    approved_quantity_base: Decimal
    total_target_fraction: Decimal
    max_notional_eur: Decimal | None
    reference_price_eur: Decimal
    best_bid_eur: Decimal
    best_ask_eur: Decimal
    tick_size: Decimal

    source_decision_state: str
    source_decision_reason: str

    legs_json: str
    created_ts_utc: datetime | None


def _legs_to_json(legs: list[Any]) -> str:
    def convert(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if hasattr(value, "__dataclass_fields__"):
            return {k: convert(v) for k, v in value.__dict__.items()}
        return value

    return json.dumps([convert(leg) for leg in legs])


def build_plan_snapshot(
    *,
    request: ManualExecutionRequest,
    approval: ManualExecutionApprovalRecord,
    plan_preview: ExecutionPlanPreview,
) -> ManualExecutionPlanSnapshot:
    """Pure builder: validates every identity binding between the request,
    the persisted approval, and the already-built plan preview, then
    serializes them into a not-yet-persisted plan snapshot. Raises on any
    mismatch instead of guessing which identity is authoritative."""
    if request.request_id is None:
        raise ManualExecutionPlanSnapshotValidationError("request is not persisted")
    if approval.request_id != request.request_id:
        raise ManualExecutionPlanSnapshotValidationError("approval/request identity mismatch")
    if approval.approval_state != APPROVAL_STATE_APPROVED:
        raise ManualExecutionPlanSnapshotValidationError(
            "a plan snapshot may only be built from an APPROVED approval"
        )
    if plan_preview.account_id != request.trading_account_id:
        raise ManualExecutionPlanSnapshotValidationError("plan preview account mismatch")
    if plan_preview.asset_id != request.asset_id:
        raise ManualExecutionPlanSnapshotValidationError("plan preview asset mismatch")
    if plan_preview.venue != request.venue:
        raise ManualExecutionPlanSnapshotValidationError("plan preview venue mismatch")
    if plan_preview.side != request.side:
        raise ManualExecutionPlanSnapshotValidationError("plan preview side mismatch")
    if plan_preview.quantity_base != approval.approved_quantity_base:
        raise ManualExecutionPlanSnapshotValidationError(
            "plan preview quantity does not match the approved quantity"
        )
    if not plan_preview.legs:
        raise ManualExecutionPlanSnapshotValidationError("plan preview has no legs to snapshot")

    return ManualExecutionPlanSnapshot(
        plan_snapshot_id=None,
        idempotency_key=f"manual_execution_plan_snapshot:{request.idempotency_key}",
        request_id=request.request_id,
        approval_id=approval.approval_id,
        trading_account_id=request.trading_account_id,
        account_code=request.account_code,
        venue=request.venue,
        asset_id=request.asset_id,
        base_asset=request.base_asset,
        quote_asset=request.quote_asset,
        side=request.side,
        mode=request.mode,
        plan_type=plan_preview.plan_type,
        execution_mode=plan_preview.execution_mode,
        plan_state=PLAN_STATE_PREVIEW_ONLY,
        sleeve_code=plan_preview.sleeve_code,
        ladder_profile_id=request.ladder_profile_id,
        ladder_profile_version=request.ladder_profile_version,
        anchor_reference_price=request.anchor_reference_price,
        anchor_ts_utc=request.anchor_ts_utc,
        provenance_id=request.provenance_id,
        approved_quantity_base=approval.approved_quantity_base,
        total_target_fraction=plan_preview.total_target_fraction,
        max_notional_eur=plan_preview.max_notional_eur,
        reference_price_eur=plan_preview.reference_price_eur,
        best_bid_eur=plan_preview.best_bid_eur,
        best_ask_eur=plan_preview.best_ask_eur,
        tick_size=plan_preview.tick_size,
        source_decision_state=plan_preview.source_decision_state,
        source_decision_reason=plan_preview.source_decision_reason,
        legs_json=_legs_to_json(plan_preview.legs),
        created_ts_utc=None,
    )


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor

    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    if isinstance(db_obj, tuple):
        return db_obj[1]
    return db_obj


def _is_duplicate_key_error(exc: Exception) -> bool:
    try:
        from pymysql.err import IntegrityError
    except ImportError:
        return False
    if not isinstance(exc, IntegrityError):
        return False
    args = exc.args
    return bool(args) and args[0] in (1062,)


# Content fields compared when an idempotency_key/request_id/approval_id
# collision resolves to an existing row, mirroring
# src.manual_execution.manual_execution_request_v1._assert_same_content —
# a colliding identity bound to different plan content must fail closed,
# never silently return a mismatched snapshot.
_CONTENT_FIELDS: Final[tuple[str, ...]] = (
    "request_id",
    "approval_id",
    "trading_account_id",
    "venue",
    "asset_id",
    "side",
    "mode",
    "plan_type",
    "sleeve_code",
    "ladder_profile_id",
    "ladder_profile_version",
    "approved_quantity_base",
    "legs_json",
)


class PlanSnapshotContentMismatchError(ManualExecutionPlanSnapshotValidationError):
    pass


def _assert_same_content(
    incoming: ManualExecutionPlanSnapshot, existing: ManualExecutionPlanSnapshot
) -> None:
    for field_name in _CONTENT_FIELDS:
        if getattr(incoming, field_name) != getattr(existing, field_name):
            raise PlanSnapshotContentMismatchError(
                f"idempotency_key={incoming.idempotency_key!r} is already bound to "
                f"plan_snapshot_id={existing.plan_snapshot_id} with a different {field_name}"
            )


def _row_to_snapshot(row: Any) -> ManualExecutionPlanSnapshot:
    return ManualExecutionPlanSnapshot(
        plan_snapshot_id=int(row["manual_execution_plan_snapshot_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request_id=int(row["manual_execution_request_id"]),
        approval_id=int(row["manual_execution_approval_id"]),
        trading_account_id=int(row["trading_account_id"]),
        account_code=str(row["account_code"]),
        venue=str(row["venue"]),
        asset_id=int(row["asset_id"]),
        base_asset=str(row["base_asset"]),
        quote_asset=str(row["quote_asset"]),
        side=str(row["side"]),
        mode=str(row["mode"]),
        plan_type=str(row["plan_type"]),
        execution_mode=str(row["execution_mode"]),
        plan_state=str(row["plan_state"]),
        sleeve_code=str(row["sleeve_code"]),
        ladder_profile_id=row.get("ladder_profile_id"),
        ladder_profile_version=row.get("ladder_profile_version"),
        anchor_reference_price=(
            Decimal(str(row["anchor_reference_price"]))
            if row.get("anchor_reference_price") is not None
            else None
        ),
        anchor_ts_utc=row.get("anchor_ts_utc"),
        provenance_id=row.get("provenance_id"),
        approved_quantity_base=Decimal(str(row["approved_quantity_base"])),
        total_target_fraction=Decimal(str(row["total_target_fraction"])),
        max_notional_eur=(
            Decimal(str(row["max_notional_eur"])) if row.get("max_notional_eur") is not None else None
        ),
        reference_price_eur=Decimal(str(row["reference_price_eur"])),
        best_bid_eur=Decimal(str(row["best_bid_eur"])),
        best_ask_eur=Decimal(str(row["best_ask_eur"])),
        tick_size=Decimal(str(row["tick_size"])),
        source_decision_state=str(row["source_decision_state"]),
        source_decision_reason=str(row["source_decision_reason"]),
        legs_json=str(row["legs_json"]),
        created_ts_utc=row.get("created_ts_utc"),
    )


@dataclass
class ManualExecutionPlanSnapshotRepository:
    """Persists ManualExecutionPlanSnapshot rows. Requires the
    manual_execution_plan_snapshot table from
    db/migrations/20260811_manual_execution_plan_snapshot_v1.sql, which is
    created but intentionally not applied by this change."""

    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False, compare=False)

    @staticmethod
    def _select_by_idempotency_key(cursor: Any, idempotency_key: str) -> ManualExecutionPlanSnapshot | None:
        cursor.execute(
            "SELECT * FROM manual_execution_plan_snapshot WHERE idempotency_key = %s",
            [idempotency_key],
        )
        row = cursor.fetchone()
        return _row_to_snapshot(row) if row else None

    def find_by_request_id(self, request_id: int) -> ManualExecutionPlanSnapshot | None:
        if request_id <= 0:
            return None
        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                "SELECT * FROM manual_execution_plan_snapshot WHERE manual_execution_request_id = %s",
                [request_id],
            )
            row = cursor.fetchone()
            return _row_to_snapshot(row) if row else None

    def create_snapshot_idempotent(
        self, snapshot: ManualExecutionPlanSnapshot
    ) -> ManualExecutionPlanSnapshot:
        """Same idempotency shape as
        src.manual_execution.manual_execution_request_v1.ManualExecutionRequestRepository.create_request_idempotent:
        a fast-path SELECT for sequential retries, a caught duplicate-key
        error on INSERT for a concurrent race, and a content check on
        whichever row is returned so a colliding identity bound to
        different plan content fails closed."""
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)

            existing = self._select_by_idempotency_key(cursor, snapshot.idempotency_key)
            if existing is not None:
                _assert_same_content(snapshot, existing)
                return existing

            insert_params = [
                snapshot.idempotency_key,
                snapshot.request_id,
                snapshot.approval_id,
                snapshot.trading_account_id,
                snapshot.account_code,
                snapshot.venue,
                snapshot.asset_id,
                snapshot.base_asset,
                snapshot.quote_asset,
                snapshot.side,
                snapshot.mode,
                snapshot.plan_type,
                snapshot.execution_mode,
                snapshot.plan_state,
                snapshot.sleeve_code,
                snapshot.ladder_profile_id,
                snapshot.ladder_profile_version,
                snapshot.anchor_reference_price,
                snapshot.anchor_ts_utc,
                snapshot.provenance_id,
                snapshot.approved_quantity_base,
                snapshot.total_target_fraction,
                snapshot.max_notional_eur,
                snapshot.reference_price_eur,
                snapshot.best_bid_eur,
                snapshot.best_ask_eur,
                snapshot.tick_size,
                snapshot.source_decision_state,
                snapshot.source_decision_reason,
                snapshot.legs_json,
            ]
            try:
                cursor.execute(
                    """
                    INSERT INTO manual_execution_plan_snapshot (
                        idempotency_key, manual_execution_request_id, manual_execution_approval_id,
                        trading_account_id, account_code, venue, asset_id, base_asset, quote_asset,
                        side, mode, plan_type, execution_mode, plan_state, sleeve_code,
                        ladder_profile_id, ladder_profile_version, anchor_reference_price, anchor_ts_utc,
                        provenance_id, approved_quantity_base, total_target_fraction, max_notional_eur,
                        reference_price_eur, best_bid_eur, best_ask_eur, tick_size,
                        source_decision_state, source_decision_reason, legs_json
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    insert_params,
                )
            except Exception as exc:  # noqa: BLE001 - duplicate-key idempotency guard
                if not _is_duplicate_key_error(exc):
                    raise
                existing = self._select_by_idempotency_key(cursor, snapshot.idempotency_key)
                if existing is None:
                    raise
                _assert_same_content(snapshot, existing)
                return existing

            snapshot_id = int(cursor.lastrowid)
            cursor.execute(
                "SELECT * FROM manual_execution_plan_snapshot WHERE manual_execution_plan_snapshot_id = %s",
                [snapshot_id],
            )
            row = cursor.fetchone()
            return _row_to_snapshot(row)
