"""Immutable persistence for decision-gate-approved manual plan previews.

This module persists execution intent only.  It imports neither executor nor
broker code and accepts an already-approved preview from the canonical manual
planner path; permission remains exclusively decision_gate-owned.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

from src.execution_planner.contract_preview_v1 import ExecutionPlanPreview, preview_to_dict
from src.manual_execution.manual_execution_request_v1 import (
    ManualExecutionRequest,
    validate_required_snapshot_binding,
)


class ManualExecutionPlanSnapshotError(ValueError):
    pass


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor
    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    return db_obj[1] if isinstance(db_obj, tuple) else db_obj


@dataclass(frozen=True)
class ManualExecutionPlanSnapshot:
    plan_snapshot_id: int | None
    request_id: int
    approval_id: int
    trading_account_id: int
    ladder_profile_id: int
    ladder_profile_version: int
    anchor_type: str
    anchor_price: Decimal
    anchor_source: str
    source_map_cycle_id: str
    source_native_map_id: str
    source_map_version: str
    provenance_id: int
    market: str
    side: str
    quantity_policy: str
    approved_quantity_base: Decimal
    planner_version: str
    payload_json: str
    created_ts_utc: datetime | None = None


def build_manual_execution_plan_snapshot(
    *, request: ManualExecutionRequest, approval_id: int, plan: ExecutionPlanPreview
) -> ManualExecutionPlanSnapshot:
    """Convert a gate-approved planner result into reproducible immutable intent."""
    if request.request_id is None:
        raise ManualExecutionPlanSnapshotError("manual execution plan snapshot requires a persisted request")
    try:
        validate_required_snapshot_binding(request)
    except ValueError as exc:
        raise ManualExecutionPlanSnapshotError(str(exc)) from exc
    if approval_id <= 0 or plan.source_decision_state != "APPROVED":
        raise ManualExecutionPlanSnapshotError("only a decision_gate-approved plan may be snapshotted")
    if plan.account_id != request.trading_account_id or plan.side != request.side:
        raise ManualExecutionPlanSnapshotError("approved plan/request binding mismatch")
    payload = preview_to_dict(plan)
    return ManualExecutionPlanSnapshot(
        plan_snapshot_id=None,
        request_id=int(request.request_id),
        approval_id=approval_id,
        trading_account_id=request.trading_account_id,
        ladder_profile_id=int(request.ladder_profile_id),
        ladder_profile_version=int(request.ladder_profile_version),
        anchor_type=str(request.anchor_type),
        anchor_price=Decimal(str(request.anchor_price)),
        anchor_source=str(request.anchor_source),
        source_map_cycle_id=str(request.source_map_cycle_id),
        source_native_map_id=str(request.source_native_map_id),
        source_map_version=str(request.source_map_version),
        provenance_id=int(request.provenance_id),
        market=f"{request.base_asset}-{request.quote_asset}",
        side=request.side,
        quantity_policy=request.quantity_policy,
        approved_quantity_base=plan.quantity_base,
        planner_version="manual_execution_contract_preview_v1",
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
    )


def _row_to_snapshot(row: Any) -> ManualExecutionPlanSnapshot:
    return ManualExecutionPlanSnapshot(
        plan_snapshot_id=int(row["manual_execution_plan_snapshot_id"]),
        request_id=int(row["manual_execution_request_id"]), approval_id=int(row["manual_execution_approval_id"]),
        trading_account_id=int(row["trading_account_id"]), ladder_profile_id=int(row["ladder_profile_id"]),
        ladder_profile_version=int(row["ladder_profile_version"]), anchor_type=str(row["anchor_type"]),
        anchor_price=Decimal(str(row["anchor_price"])), anchor_source=str(row["anchor_source"]),
        source_map_cycle_id=str(row["source_map_cycle_id"]), source_native_map_id=str(row["source_native_map_id"]),
        source_map_version=str(row["source_map_version"]), provenance_id=int(row["provenance_id"]),
        market=str(row["market"]), side=str(row["side"]), quantity_policy=str(row["quantity_policy"]),
        approved_quantity_base=Decimal(str(row["approved_quantity_base"])), planner_version=str(row["planner_version"]),
        payload_json=str(row["payload_json"]), created_ts_utc=row.get("created_ts_utc"),
    )


@dataclass
class ManualExecutionPlanSnapshotRepository:
    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False, compare=False)

    def find_by_request_id(self, request_id: int) -> ManualExecutionPlanSnapshot | None:
        with self.cursor_factory() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute("SELECT * FROM manual_execution_plan_snapshot WHERE manual_execution_request_id = %s", [request_id])
            row = cursor.fetchone()
            return _row_to_snapshot(row) if row else None

    def create_idempotent(self, snapshot: ManualExecutionPlanSnapshot) -> ManualExecutionPlanSnapshot:
        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(
                """INSERT INTO manual_execution_plan_snapshot (
                    manual_execution_request_id, manual_execution_approval_id, trading_account_id,
                    ladder_profile_id, ladder_profile_version, anchor_type, anchor_price, anchor_source,
                    source_map_cycle_id, source_native_map_id, source_map_version, provenance_id, market,
                    side, quantity_policy, approved_quantity_base, planner_version, payload_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    manual_execution_plan_snapshot_id = LAST_INSERT_ID(manual_execution_plan_snapshot_id)""",
                [snapshot.request_id, snapshot.approval_id, snapshot.trading_account_id,
                 snapshot.ladder_profile_id, snapshot.ladder_profile_version, snapshot.anchor_type,
                 snapshot.anchor_price, snapshot.anchor_source, snapshot.source_map_cycle_id,
                 snapshot.source_native_map_id, snapshot.source_map_version, snapshot.provenance_id,
                 snapshot.market, snapshot.side, snapshot.quantity_policy, snapshot.approved_quantity_base,
                 snapshot.planner_version, snapshot.payload_json],
            )
            cursor.execute("SELECT * FROM manual_execution_plan_snapshot WHERE manual_execution_plan_snapshot_id = %s", [int(cursor.lastrowid)])
            row = cursor.fetchone()
            if not row:
                raise ManualExecutionPlanSnapshotError("snapshot insert did not return canonical row")
            persisted = _row_to_snapshot(row)
            if persisted.payload_json != snapshot.payload_json:
                raise ManualExecutionPlanSnapshotError("canonical plan snapshot conflicts with retry payload")
            return persisted
