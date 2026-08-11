"""
manual_execution_gate_v1 — decision_gate's public contract for one
ManualExecutionRequest (src.manual_execution.manual_execution_request_v1).

Layer: decision_gate. Account-aware permission for manual execution
requests only — see
docs/reviews/manual_execution_ladder_p0_implementation_review_20260725.md
findings B1/B2 ("no authoritative end-to-end manual SELL ladder call
graph"; "FREE_BASE_QUANTITY is a correct-shaped pure function with no
trusted producer or mandatory consumer").

This module is the trusted producer free_base_quantity_v1 was missing:
evaluate_manual_execution_request() is pure (no DB) and consumes only a
ManualExecutionGateInput assembled by ManualExecutionGateRepository from
account_position_snapshot (wallet), trading_account (account flags), and
src.decision_gate.sell_reservation_v1 (existing local reservations) — never
a caller-constructed snapshot.

`approve_and_reserve()` is decision_gate's single authoritative entrypoint:
it is the only function anywhere that inserts a persisted manual execution
approval, and it creates the account's SELL reservation atomically with
that approval, under a per-(trading_account_id, venue, asset_id) row lock — see
docs/reviews/manual_execution_ladder_p0_remediation_implementation_20260726.md
findings/design for why this closes the prior round's "atomic reservation
creation" gap: two concurrent requests for the same account/asset can no
longer both read the same free quantity and both approve against it,
because the second request's transaction blocks on the row lock until the
first's reservation insert has committed, then re-reads reservation totals
that already include it.

Explicitly out of scope here (see
docs/reviews/manual_execution_ladder_p0_remediation_implementation_20260726.md
for the full boundary): reconciliation (broker-state-driven transitions
remain owned exclusively by
src.decision_gate.sell_reservation_v1.reconcile_reservation_state), live
execution, and BUY-side quantity resolution (fails closed instead of
guessing).

selection_engine must never import this module.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Final

from src.decision_gate.free_base_quantity_v1 import (
    STATUS_OK,
    FreeBaseQuantityResult,
    WalletAvailableSnapshot,
    resolve_free_base_quantity,
)
from src.decision_gate.manual_execution_approval_v1 import (
    APPROVAL_STATE_APPROVED,
    APPROVAL_TTL_SECONDS,
    ManualExecutionApprovalRecord,
    _ManualExecutionApprovalRepository,
)
from src.decision_gate.sell_reservation_v1 import SellReservationRepository
from src.manual_execution.manual_execution_request_v1 import (
    MODE_PAPER,
    QUANTITY_POLICY_FIXED_BASE_QUANTITY,
    QUANTITY_POLICY_FULL_AVAILABLE_BASE,
    ManualExecutionRequest,
)
from src.manual_execution import _trusted_clock_v1 as trusted_clock


GATE_DECISION_EXECUTION_ALLOWED: Final[str] = "EXECUTION_ALLOWED"
GATE_DECISION_BLOCKED: Final[str] = "BLOCKED"

REASON_LIVE_TRADING_NOT_GRANTED: Final[str] = "LIVE_TRADING_NOT_GRANTED"
REASON_MANUAL_BUY_GATE_NOT_YET_IMPLEMENTED: Final[str] = "MANUAL_BUY_GATE_NOT_YET_IMPLEMENTED"
REASON_QUANTITY_POLICY_NOT_YET_SUPPORTED: Final[str] = "QUANTITY_POLICY_NOT_YET_SUPPORTED"
REASON_ACCOUNT_DISABLED: Final[str] = "ACCOUNT_DISABLED"
REASON_ACCOUNT_LIVE_TRADING_ENABLED: Final[str] = "ACCOUNT_LIVE_TRADING_ENABLED_NOT_ALLOWED_FOR_PAPER"
REASON_ACCOUNT_NOT_PAPER_MODE: Final[str] = "ACCOUNT_NOT_PAPER_MODE"
REASON_WALLET_SNAPSHOT_UNAVAILABLE: Final[str] = "WALLET_SNAPSHOT_UNAVAILABLE"
REASON_PROVENANCE_BINDING_REQUIRED: Final[str] = "PROVENANCE_BINDING_REQUIRED"
REASON_REQUESTED_QUANTITY_NOT_POSITIVE: Final[str] = "REQUESTED_QUANTITY_NOT_POSITIVE"
REASON_NO_FREE_BASE_QUANTITY: Final[str] = "NO_FREE_BASE_QUANTITY"

_SELL_LOCK_TIMEOUT_SECONDS: Final[int] = 10

# Quantity policies this gate can resolve into a base-quantity approval today.
# FIXED_QUOTE_NOTIONAL and LADDER_LEVELS require a market price to convert to
# base quantity, which is out of decision_gate's account-aware scope — see
# module docstring; both fail closed here rather than guessing a price.
_SUPPORTED_QUANTITY_POLICIES: Final[frozenset[str]] = frozenset(
    {QUANTITY_POLICY_FULL_AVAILABLE_BASE, QUANTITY_POLICY_FIXED_BASE_QUANTITY}
)


@dataclass(frozen=True)
class ManualExecutionGateInput:
    wallet_snapshot: WalletAvailableSnapshot | None
    approved_not_submitted_reservation_base: Decimal
    reconciliation_pending_count: int
    account_enabled: bool
    account_live_trading_enabled: bool
    account_mode: str


@dataclass(frozen=True)
class ManualExecutionGateResult:
    decision_state: str  # EXECUTION_ALLOWED | BLOCKED
    decision_reason: str
    blocking_reasons: tuple[str, ...]
    approved_quantity_base: Decimal | None
    free_base_quantity_result: FreeBaseQuantityResult | None


@dataclass(frozen=True)
class ManualExecutionApprovalOutcome:
    gate_result: ManualExecutionGateResult
    approval_id: int | None


def manual_execution_request_idempotency_keys(
    request: ManualExecutionRequest,
) -> tuple[str, str]:
    """Return gate-owned idempotency keys from the canonical request row."""
    if request.request_id is None or request.request_id <= 0:
        raise ValueError("manual execution gate requires a persisted request_id")
    return (
        f"manual_execution_request:{request.request_id}",
        f"manual_execution_approval:{request.request_id}",
    )


def _blocked(
    reason: str,
    *,
    blocking_reasons: tuple[str, ...] = (),
    free_base_quantity_result: FreeBaseQuantityResult | None = None,
) -> ManualExecutionGateResult:
    return ManualExecutionGateResult(
        decision_state=GATE_DECISION_BLOCKED,
        decision_reason=reason,
        blocking_reasons=blocking_reasons or (reason,),
        approved_quantity_base=None,
        free_base_quantity_result=free_base_quantity_result,
    )


def evaluate_manual_execution_request(
    request: ManualExecutionRequest,
    gate_input: ManualExecutionGateInput,
) -> ManualExecutionGateResult:
    """Resolve one account-aware permission decision for one manual
    execution request. Pure function: no DB, no broker. Fails closed on
    every incomplete/unsupported/contradictory input."""
    if request.mode != MODE_PAPER:
        return _blocked(REASON_LIVE_TRADING_NOT_GRANTED)

    if request.provenance_id is None:
        return _blocked(REASON_PROVENANCE_BINDING_REQUIRED)

    if request.side != "SELL":
        return _blocked(REASON_MANUAL_BUY_GATE_NOT_YET_IMPLEMENTED)

    if request.quantity_policy not in _SUPPORTED_QUANTITY_POLICIES:
        return _blocked(REASON_QUANTITY_POLICY_NOT_YET_SUPPORTED)

    if not gate_input.account_enabled:
        return _blocked(REASON_ACCOUNT_DISABLED)

    if gate_input.account_live_trading_enabled:
        return _blocked(REASON_ACCOUNT_LIVE_TRADING_ENABLED)

    if gate_input.account_mode != "paper":
        return _blocked(REASON_ACCOUNT_NOT_PAPER_MODE)

    if gate_input.wallet_snapshot is None:
        return _blocked(REASON_WALLET_SNAPSHOT_UNAVAILABLE)

    free_result = resolve_free_base_quantity(
        wallet_snapshot=gate_input.wallet_snapshot,
        approved_not_submitted_reservation_base=gate_input.approved_not_submitted_reservation_base,
        reconciliation_pending_reservation_count=gate_input.reconciliation_pending_count,
        expected_trading_account_id=request.trading_account_id,
        expected_venue=request.venue,
        expected_asset_id=request.asset_id,
    )

    if free_result.status != STATUS_OK:
        return _blocked(
            free_result.blocking_reasons[0] if free_result.blocking_reasons else "FREE_BASE_QUANTITY_BLOCKED",
            blocking_reasons=free_result.blocking_reasons,
            free_base_quantity_result=free_result,
        )

    free_quantity = free_result.free_base_quantity
    if free_quantity is None or free_quantity <= 0:
        return _blocked(REASON_NO_FREE_BASE_QUANTITY, free_base_quantity_result=free_result)

    if request.quantity_policy == QUANTITY_POLICY_FULL_AVAILABLE_BASE:
        approved_quantity = free_quantity
    else:
        requested = request.requested_base_quantity
        if requested is None or requested <= 0:
            return _blocked(
                REASON_REQUESTED_QUANTITY_NOT_POSITIVE,
                free_base_quantity_result=free_result,
            )
        approved_quantity = min(requested, free_quantity)

    return ManualExecutionGateResult(
        decision_state=GATE_DECISION_EXECUTION_ALLOWED,
        decision_reason="OK",
        blocking_reasons=(),
        approved_quantity_base=approved_quantity,
        free_base_quantity_result=free_result,
    )


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor

    return db_cursor(commit=commit, database=database)


def _unwrap_cursor(db_obj: Any) -> Any:
    if isinstance(db_obj, tuple):
        return db_obj[1]
    return db_obj


@dataclass
class ManualExecutionGateRepository:
    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False, compare=False)
    reservation_repository: SellReservationRepository | None = None

    def __post_init__(self) -> None:
        if self.reservation_repository is None:
            self.reservation_repository = SellReservationRepository(cursor_factory=self.cursor_factory)

    def _approval_reader(self) -> _ManualExecutionApprovalRepository:
        return _ManualExecutionApprovalRepository(cursor_factory=self.cursor_factory)

    def fetch_account_flags(self, trading_account_id: int) -> tuple[bool, bool, str] | None:
        with self.cursor_factory() as db_obj:
            return self._fetch_account_flags(_unwrap_cursor(db_obj), trading_account_id)

    def _fetch_account_flags(self, cursor: Any, trading_account_id: int) -> tuple[bool, bool, str] | None:
        cursor.execute(
            """
            SELECT enabled, live_trading_enabled, account_mode
            FROM trading_account
            WHERE trading_account_id = %s
            """,
            [trading_account_id],
        )
        row = cursor.fetchone()

        if not row:
            return None
        return (bool(row["enabled"]), bool(row["live_trading_enabled"]), str(row["account_mode"]))

    def fetch_wallet_available_snapshot(
        self,
        *,
        trading_account_id: int,
        venue: str,
        asset_id: int,
        symbol: str,
    ) -> WalletAvailableSnapshot | None:
        with self.cursor_factory() as db_obj:
            return self._fetch_wallet_available_snapshot(
                _unwrap_cursor(db_obj),
                trading_account_id=trading_account_id,
                venue=venue,
                asset_id=asset_id,
                symbol=symbol,
            )

    def _fetch_wallet_available_snapshot(
        self,
        cursor: Any,
        *,
        trading_account_id: int,
        venue: str,
        asset_id: int,
        symbol: str,
    ) -> WalletAvailableSnapshot | None:
        cursor.execute(
            """
            SELECT account_position_snapshot_id, available_quantity_base, quantity_base,
                   snapshot_ts_utc, source_name
            FROM account_position_snapshot
            WHERE trading_account_id = %s AND venue = %s AND asset_id = %s
            ORDER BY snapshot_ts_utc DESC
            LIMIT 1
            """,
            [trading_account_id, venue, asset_id],
        )
        row = cursor.fetchone()

        if not row:
            return None

        snapshot_ts = row["snapshot_ts_utc"]
        if snapshot_ts.tzinfo is None:
            snapshot_ts = snapshot_ts.replace(tzinfo=timezone.utc)

        return WalletAvailableSnapshot(
            trading_account_id=trading_account_id,
            venue=venue,
            asset_id=asset_id,
            symbol=symbol,
            available_base_quantity=Decimal(str(row["available_quantity_base"])),
            total_base_quantity=Decimal(str(row["quantity_base"])),
            source_name=str(row["source_name"]),
            snapshot_ts_utc=snapshot_ts,
            snapshot_id=int(row["account_position_snapshot_id"]),
        )

    def load_gate_input(
        self,
        request: ManualExecutionRequest,
    ) -> ManualExecutionGateInput:
        account_flags = self.fetch_account_flags(request.trading_account_id)
        if account_flags is None:
            return ManualExecutionGateInput(
                wallet_snapshot=None,
                approved_not_submitted_reservation_base=Decimal("0"),
                reconciliation_pending_count=0,
                account_enabled=False,
                account_live_trading_enabled=True,
                account_mode="UNKNOWN",
            )

        account_enabled, account_live_trading_enabled, account_mode = account_flags

        wallet_snapshot = self.fetch_wallet_available_snapshot(
            trading_account_id=request.trading_account_id,
            venue=request.venue,
            asset_id=request.asset_id,
            symbol=request.base_asset,
        )

        assert self.reservation_repository is not None
        reservation_sum = self.reservation_repository.sum_approved_not_submitted(
            trading_account_id=request.trading_account_id,
            venue=request.venue,
            asset_id=request.asset_id,
        )
        reconciliation_pending = self.reservation_repository.count_reconciliation_pending(
            trading_account_id=request.trading_account_id,
            venue=request.venue,
            asset_id=request.asset_id,
        )

        return ManualExecutionGateInput(
            wallet_snapshot=wallet_snapshot,
            approved_not_submitted_reservation_base=reservation_sum,
            reconciliation_pending_count=reconciliation_pending,
            account_enabled=account_enabled,
            account_live_trading_enabled=account_live_trading_enabled,
            account_mode=account_mode,
        )

    def approve_and_reserve(
        self,
        request: ManualExecutionRequest,
    ) -> ManualExecutionApprovalOutcome:
        """The single authoritative decision_gate entrypoint: resolves
        account-derived free quantity and creates the SELL reservation
        atomically, under a per-(trading_account_id, venue, asset_id) row
        lock in `manual_execution_sell_lock`
        (db/migrations/20260726_manual_execution_atomic_approval_v1.sql,
        created but not applied).

        `request` must already be persisted (request.request_id is not
        None) — src.manual_execution.manual_execution_service_v1.process()
        always persists via ManualExecutionRequestRepository first.

        Idempotent: retrying with the same persisted canonical request ID returns
        the approval bound to the existing reservation without re-deriving
        the decision from (possibly since-changed) account/wallet state —
        this matters because a naive retry that re-ran the gate could
        legitimately compute a different result once the wallet has moved,
        which would not be a true retry.
        """
        if request.request_id is None:
            raise ValueError("approve_and_reserve requires a persisted request (request_id is not None)")

        resolved_now = trusted_clock.utc_now()
        assert self.reservation_repository is not None
        reservation_idempotency_key, approval_idempotency_key = (
            manual_execution_request_idempotency_keys(request)
        )

        with self.cursor_factory(commit=True) as db_obj:
            cursor = _unwrap_cursor(db_obj)

            # Idempotent-retry short-circuit, read before taking the lock:
            # a second call for the same request must reproduce the first
            # call's outcome exactly, not re-derive a possibly different one.
            existing_reservation = self.reservation_repository.find_by_idempotency_key(
                reservation_idempotency_key, cursor=cursor
            )
            if existing_reservation is not None:
                return self._outcome_from_existing_reservation(
                    existing_reservation,
                    request,
                    cursor=cursor,
                )

            # Ensure + take the per-account/venue/asset row lock for the
            # remainder of this transaction. INSERT IGNORE guarantees a row
            # exists to lock even on the very first reservation for this key;
            # SELECT ... FOR UPDATE blocks any other transaction taking the
            # same lock until this one commits or rolls back.
            cursor.execute(
                """
                INSERT IGNORE INTO manual_execution_sell_lock (trading_account_id, venue, asset_id)
                VALUES (%s, %s, %s)
                """,
                [request.trading_account_id, request.venue, request.asset_id],
            )
            cursor.execute(
                """
                SELECT trading_account_id FROM manual_execution_sell_lock
                WHERE trading_account_id = %s AND venue = %s AND asset_id = %s
                FOR UPDATE
                """,
                [request.trading_account_id, request.venue, request.asset_id],
            )

            # Fresh reads, taken only after the lock is held, so no other
            # transaction can insert a competing reservation between the read
            # and the write below.
            account_flags = self._fetch_account_flags(cursor, request.trading_account_id)
            if account_flags is None:
                # Unknown account: mirror load_gate_input's fail-closed
                # fallback and still run the full evaluate_manual_execution_request
                # ordering (mode/side/quantity-policy checks precede the
                # account-enabled check there).
                account_enabled, account_live_trading_enabled, account_mode = False, True, "UNKNOWN"
                wallet_snapshot = None
            else:
                account_enabled, account_live_trading_enabled, account_mode = account_flags
                wallet_snapshot = self._fetch_wallet_available_snapshot(
                    cursor,
                    trading_account_id=request.trading_account_id,
                    venue=request.venue,
                    asset_id=request.asset_id,
                    symbol=request.base_asset,
                )
            reservation_sum = self.reservation_repository.sum_approved_not_submitted(
                trading_account_id=request.trading_account_id,
                venue=request.venue,
                asset_id=request.asset_id,
                cursor=cursor,
            )
            reconciliation_pending = self.reservation_repository.count_reconciliation_pending(
                trading_account_id=request.trading_account_id,
                venue=request.venue,
                asset_id=request.asset_id,
                cursor=cursor,
            )

            gate_input = ManualExecutionGateInput(
                wallet_snapshot=wallet_snapshot,
                approved_not_submitted_reservation_base=reservation_sum,
                reconciliation_pending_count=reconciliation_pending,
                account_enabled=account_enabled,
                account_live_trading_enabled=account_live_trading_enabled,
                account_mode=account_mode,
            )
            gate_result = evaluate_manual_execution_request(request, gate_input)

            if gate_result.decision_state != GATE_DECISION_EXECUTION_ALLOWED:
                return ManualExecutionApprovalOutcome(gate_result=gate_result, approval_id=None)

            assert gate_result.approved_quantity_base is not None
            reservation = self.reservation_repository.create_reservation_idempotent(
                trading_account_id=request.trading_account_id,
                venue=request.venue,
                asset_id=request.asset_id,
                symbol=request.base_asset,
                idempotency_key=reservation_idempotency_key,
                quantity_base=gate_result.approved_quantity_base,
                manual_execution_request_id=request.request_id,
                cursor=cursor,
            )

            assert wallet_snapshot is not None
            if wallet_snapshot.snapshot_id is None:
                raise ValueError("wallet snapshot must have a persisted snapshot_id")
            assert request.provenance_id is not None
            cursor.execute(
                """
                INSERT INTO manual_execution_approval (
                    idempotency_key, manual_execution_request_id,
                    trading_account_id, account_code, venue, asset_id,
                    base_asset, quote_asset, side, approved_quantity_base,
                    wallet_snapshot_id, wallet_snapshot_version_ts_utc,
                    reservation_id, approved_ts_utc, expires_ts_utc, mode,
                    provenance_id, approval_state, decision_reason
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                [
                    approval_idempotency_key,
                    request.request_id,
                    request.trading_account_id,
                    request.account_code,
                    request.venue,
                    request.asset_id,
                    request.base_asset,
                    request.quote_asset,
                    request.side,
                    gate_result.approved_quantity_base,
                    wallet_snapshot.snapshot_id,
                    wallet_snapshot.snapshot_ts_utc,
                    reservation.reservation_id,
                    resolved_now,
                    resolved_now + timedelta(seconds=APPROVAL_TTL_SECONDS),
                    request.mode,
                    request.provenance_id,
                    APPROVAL_STATE_APPROVED,
                    gate_result.decision_reason,
                ],
            )
            if cursor.lastrowid is None:
                raise RuntimeError("approval insert did not return an authoritative approval ID")
            approval_id = int(cursor.lastrowid)
            if approval_id <= 0:
                raise RuntimeError("approval insert returned a non-positive approval ID")
            persisted_approval = self._approval_reader().find_approval_by_id(
                approval_id,
                cursor=cursor,
            )
            if persisted_approval is None:
                raise RuntimeError(
                    "approval insert result could not be re-read by returned approval ID"
                )
            self._verify_created_approval(
                approval=persisted_approval,
                approval_id=approval_id,
                request=request,
                reservation=reservation,
                wallet_snapshot=wallet_snapshot,
                approved_quantity=gate_result.approved_quantity_base,
                approved_ts_utc=resolved_now,
                expires_ts_utc=resolved_now
                + timedelta(seconds=APPROVAL_TTL_SECONDS),
                decision_reason=gate_result.decision_reason,
            )
            return ManualExecutionApprovalOutcome(
                gate_result=gate_result,
                approval_id=approval_id,
            )
            # Exiting this `with` block commits the transaction (or rolls
            # back on exception), releasing the FOR UPDATE lock either way —
            # see src/common/db_core_v1.py db_cursor(). A raised exception
            # here therefore leaves no partial reservation/lock state.

    def _outcome_from_existing_reservation(
        self,
        reservation: Any,
        request: ManualExecutionRequest,
        *,
        cursor: Any,
    ) -> ManualExecutionApprovalOutcome:
        approval = self._approval_reader().find_approval_by_request_id(
            request.request_id,  # type: ignore[arg-type]
            cursor=cursor,
        )
        if approval is None:
            raise RuntimeError(
                "existing manual SELL reservation has no persisted approval; "
                "refusing to reconstruct approval authority"
            )
        if approval.reservation_id != reservation.reservation_id:
            raise RuntimeError("persisted approval reservation does not match idempotent reservation")
        gate_result = ManualExecutionGateResult(
            decision_state=GATE_DECISION_EXECUTION_ALLOWED,
            decision_reason="RETRY_OF_EXISTING_RESERVATION",
            blocking_reasons=(),
            approved_quantity_base=approval.approved_quantity_base,
            free_base_quantity_result=None,
        )
        return ManualExecutionApprovalOutcome(
            gate_result=gate_result,
            approval_id=approval.approval_id,
        )

    @staticmethod
    def _verify_created_approval(
        *,
        approval: ManualExecutionApprovalRecord,
        approval_id: int,
        request: ManualExecutionRequest,
        reservation: Any,
        wallet_snapshot: WalletAvailableSnapshot,
        approved_quantity: Decimal,
        approved_ts_utc: datetime,
        expires_ts_utc: datetime,
        decision_reason: str,
    ) -> None:
        """Fail if the inserted identity cannot be re-read exactly as written."""

        def aware(value: datetime) -> datetime:
            return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

        expected = {
            "approval_id": approval_id,
            "idempotency_key": f"manual_execution_approval:{request.request_id}",
            "request_id": request.request_id,
            "trading_account_id": request.trading_account_id,
            "account_code": request.account_code,
            "venue": request.venue,
            "asset_id": request.asset_id,
            "base_asset": request.base_asset,
            "quote_asset": request.quote_asset,
            "side": request.side,
            "approved_quantity_base": approved_quantity,
            "wallet_snapshot_id": wallet_snapshot.snapshot_id,
            "reservation_id": reservation.reservation_id,
            "mode": request.mode,
            "provenance_id": request.provenance_id,
            "approval_state": APPROVAL_STATE_APPROVED,
            "decision_reason": decision_reason,
            "persisted_reservation_id": reservation.reservation_id,
            "reservation_request_id": request.request_id,
            "reservation_trading_account_id": request.trading_account_id,
            "reservation_venue": request.venue,
            "reservation_asset_id": request.asset_id,
            "reservation_symbol": request.base_asset,
            "reservation_quantity_base": approved_quantity,
            "reservation_state": "APPROVED_NOT_SUBMITTED",
            "persisted_snapshot_id": wallet_snapshot.snapshot_id,
            "snapshot_trading_account_id": request.trading_account_id,
            "snapshot_venue": request.venue,
            "snapshot_asset_id": request.asset_id,
        }
        for field_name, expected_value in expected.items():
            if getattr(approval, field_name) != expected_value:
                raise RuntimeError(
                    f"re-read persisted approval binding mismatch: {field_name}"
                )

        timestamp_expected = {
            "wallet_snapshot_version_ts_utc": wallet_snapshot.snapshot_ts_utc,
            "snapshot_ts_utc": wallet_snapshot.snapshot_ts_utc,
            "approved_ts_utc": approved_ts_utc,
            "expires_ts_utc": expires_ts_utc,
        }
        for field_name, expected_value in timestamp_expected.items():
            if aware(getattr(approval, field_name)) != aware(expected_value):
                raise RuntimeError(
                    f"re-read persisted approval binding mismatch: {field_name}"
                )
