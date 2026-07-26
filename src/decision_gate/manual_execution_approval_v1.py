"""Persisted manual SELL approval authority.

Only ``ManualExecutionGateRepository.approve_and_reserve`` writes the
underlying table. The production planner resolves request and approval
identities through :func:`resolve_persisted_manual_execution_authority`;
there is no caller-selectable repository in that planner API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Final

from src.manual_execution.manual_execution_request_v1 import (
    ManualExecutionRequest,
    ManualExecutionRequestRepository,
)


APPROVAL_STATE_APPROVED: Final[str] = "APPROVED"
APPROVAL_TTL_SECONDS: Final[int] = 5 * 60


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor

    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    if isinstance(db_obj, tuple):
        return db_obj[1]
    return db_obj


@dataclass(frozen=True)
class ManualExecutionApprovalRecord:
    approval_id: int
    idempotency_key: str
    request_id: int
    trading_account_id: int
    account_code: str
    venue: str
    asset_id: int
    base_asset: str
    quote_asset: str
    side: str
    approved_quantity_base: Decimal
    wallet_snapshot_id: int
    wallet_snapshot_version_ts_utc: datetime
    reservation_id: int
    approved_ts_utc: datetime
    expires_ts_utc: datetime
    mode: str
    provenance_id: int
    approval_state: str
    decision_reason: str

    persisted_reservation_id: int
    reservation_request_id: int | None
    reservation_trading_account_id: int
    reservation_venue: str
    reservation_asset_id: int
    reservation_symbol: str
    reservation_quantity_base: Decimal
    reservation_state: str

    persisted_snapshot_id: int
    snapshot_trading_account_id: int
    snapshot_venue: str
    snapshot_asset_id: int
    snapshot_ts_utc: datetime


def _row_to_approval(row: Any) -> ManualExecutionApprovalRecord:
    return ManualExecutionApprovalRecord(
        approval_id=int(row["manual_execution_approval_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request_id=int(row["manual_execution_request_id"]),
        trading_account_id=int(row["trading_account_id"]),
        account_code=str(row["account_code"]),
        venue=str(row["venue"]),
        asset_id=int(row["asset_id"]),
        base_asset=str(row["base_asset"]),
        quote_asset=str(row["quote_asset"]),
        side=str(row["side"]),
        approved_quantity_base=Decimal(str(row["approved_quantity_base"])),
        wallet_snapshot_id=int(row["wallet_snapshot_id"]),
        wallet_snapshot_version_ts_utc=row["wallet_snapshot_version_ts_utc"],
        reservation_id=int(row["reservation_id"]),
        approved_ts_utc=row["approved_ts_utc"],
        expires_ts_utc=row["expires_ts_utc"],
        mode=str(row["mode"]),
        provenance_id=int(row["provenance_id"]),
        approval_state=str(row["approval_state"]),
        decision_reason=str(row["decision_reason"]),
        persisted_reservation_id=int(row["persisted_reservation_id"]),
        reservation_request_id=(
            int(row["reservation_request_id"])
            if row.get("reservation_request_id") is not None
            else None
        ),
        reservation_trading_account_id=int(row["reservation_trading_account_id"]),
        reservation_venue=str(row["reservation_venue"]),
        reservation_asset_id=int(row["reservation_asset_id"]),
        reservation_symbol=str(row["reservation_symbol"]),
        reservation_quantity_base=Decimal(str(row["reservation_quantity_base"])),
        reservation_state=str(row["reservation_state"]),
        persisted_snapshot_id=int(row["persisted_snapshot_id"]),
        snapshot_trading_account_id=int(row["snapshot_trading_account_id"]),
        snapshot_venue=str(row["snapshot_venue"]),
        snapshot_asset_id=int(row["snapshot_asset_id"]),
        snapshot_ts_utc=row["snapshot_ts_utc"],
    )


_APPROVAL_SELECT: Final[str] = """
    SELECT
        approval.*,
        reservation.manual_execution_request_id AS reservation_request_id,
        reservation.reservation_id AS persisted_reservation_id,
        reservation.trading_account_id AS reservation_trading_account_id,
        reservation.venue AS reservation_venue,
        reservation.asset_id AS reservation_asset_id,
        reservation.symbol AS reservation_symbol,
        reservation.quantity_base AS reservation_quantity_base,
        reservation.reservation_state AS reservation_state,
        snapshot.account_position_snapshot_id AS persisted_snapshot_id,
        snapshot.trading_account_id AS snapshot_trading_account_id,
        snapshot.venue AS snapshot_venue,
        snapshot.asset_id AS snapshot_asset_id,
        snapshot.snapshot_ts_utc AS snapshot_ts_utc
    FROM manual_execution_approval AS approval
    INNER JOIN execution_sell_reservation AS reservation
        ON reservation.reservation_id = approval.reservation_id
    INNER JOIN account_position_snapshot AS snapshot
        ON snapshot.account_position_snapshot_id = approval.wallet_snapshot_id
"""


@dataclass
class _ManualExecutionApprovalRepository:
    """Decision-gate-owned persisted approval reader.

    This repository is deliberately private. Production planner composition
    below constructs it with the production cursor binding and exposes no
    repository-selection argument.
    """

    cursor_factory: Callable[..., Any] = field(
        default=_legacy_db_cursor,
        repr=False,
        compare=False,
    )

    def find_approval_by_id(
        self,
        approval_id: int,
        *,
        cursor: Any | None = None,
    ) -> ManualExecutionApprovalRecord | None:
        if approval_id <= 0:
            return None

        if cursor is not None:
            return self._find_approval_by_id(cursor, approval_id)

        with self.cursor_factory() as db_obj:
            return self._find_approval_by_id(_unwrap_cursor(db_obj), approval_id)

    def find_approval_by_request_id(
        self,
        request_id: int,
        *,
        cursor: Any | None = None,
    ) -> ManualExecutionApprovalRecord | None:
        if request_id <= 0:
            return None

        if cursor is not None:
            return self._find_approval_by_request_id(cursor, request_id)

        with self.cursor_factory() as db_obj:
            return self._find_approval_by_request_id(_unwrap_cursor(db_obj), request_id)

    @staticmethod
    def _find_approval_by_id(cursor: Any, approval_id: int) -> ManualExecutionApprovalRecord | None:
        cursor.execute(
            _APPROVAL_SELECT
            + " WHERE approval.manual_execution_approval_id = %s",
            [approval_id],
        )
        row = cursor.fetchone()
        return _row_to_approval(row) if row else None

    @staticmethod
    def _find_approval_by_request_id(
        cursor: Any,
        request_id: int,
    ) -> ManualExecutionApprovalRecord | None:
        cursor.execute(
            _APPROVAL_SELECT
            + " WHERE approval.manual_execution_request_id = %s",
            [request_id],
        )
        row = cursor.fetchone()
        return _row_to_approval(row) if row else None


@dataclass(frozen=True)
class PersistedManualExecutionAuthority:
    request: ManualExecutionRequest
    approval: ManualExecutionApprovalRecord


def resolve_persisted_manual_execution_authority(
    *,
    request_id: int,
    approval_id: int,
) -> PersistedManualExecutionAuthority:
    """Resolve the production request/approval pair from canonical storage.

    Only identity values cross the planner boundary. The concrete readers are
    selected here and cannot be replaced through a planner, service, CLI, or
    compatibility-call argument.
    """
    if request_id <= 0:
        raise LookupError("request_id must be a persisted positive ID")
    if approval_id <= 0:
        raise LookupError("approval_id must be a persisted positive ID")

    request = ManualExecutionRequestRepository().find_by_id(request_id)
    if request is None:
        raise LookupError("unknown manual execution request_id")
    if request.request_id != request_id:
        raise LookupError("persisted manual execution request identity mismatch")

    approval = _ManualExecutionApprovalRepository().find_approval_by_id(approval_id)
    if approval is None:
        raise LookupError("unknown manual execution approval_id")
    if approval.approval_id != approval_id:
        raise LookupError("persisted manual execution approval identity mismatch")

    return PersistedManualExecutionAuthority(
        request=request,
        approval=approval,
    )
