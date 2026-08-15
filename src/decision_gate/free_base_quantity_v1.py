"""
free_base_quantity_v1 — canonical FREE_BASE_QUANTITY resolver.

Layer: decision_gate. Account-aware. Consumes an already-fetched wallet
snapshot and local reservation state; does not call the broker itself and
must not be called by selection_engine.

Formula:

    FREE_BASE_QUANTITY =
        broker_reported_available_base_quantity
        - sum(local reservations not yet reflected by the broker)

"Not yet reflected by the broker" means exactly the reservations in state
APPROVED_NOT_SUBMITTED (see src.decision_gate.sell_reservation_v1). Once a
reservation reaches SUBMITTED_AWAITING_RECONCILIATION, OPEN, or
PARTIALLY_FILLED it corresponds to a real broker order, and the broker's
own `available` balance field already excludes it — subtracting it again
here would be double subtraction (audit finding F1/F9). Any reservation
still in SUBMITTED_AWAITING_RECONCILIATION makes the broker-reflection
assumption unverifiable, so resolution fails closed (REASON_RECONCILIATION_
PENDING) rather than guessing which side of the divide it falls on.

selection_engine never calls this module and never receives its output —
this resolver is account-aware by construction and has no market-only use.

execution_planner must consume only the immutable FreeBaseQuantityResult
this function returns; it must never call this resolver against live
broker state directly, and must never fetch private broker state itself.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Final

from src.manual_execution import _trusted_clock_v1 as trusted_clock


STATUS_OK: Final[str] = "OK"
STATUS_BLOCKED: Final[str] = "BLOCKED"

REASON_STALE_WALLET_SNAPSHOT: Final[str] = "STALE_WALLET_SNAPSHOT"
REASON_INCOMPLETE_WALLET_SNAPSHOT: Final[str] = "INCOMPLETE_WALLET_SNAPSHOT"
REASON_CONTRADICTORY_WALLET_SNAPSHOT: Final[str] = "CONTRADICTORY_WALLET_SNAPSHOT"
REASON_ACCOUNT_VENUE_ASSET_MISMATCH: Final[str] = "ACCOUNT_VENUE_ASSET_MISMATCH"
REASON_RECONCILIATION_PENDING: Final[str] = "RECONCILIATION_PENDING"
REASON_NEGATIVE_RESULT: Final[str] = "NEGATIVE_FREE_BASE_QUANTITY"

DEFAULT_MAX_WALLET_SNAPSHOT_AGE_SECONDS: Final[int] = 15 * 60

_RESERVATION_SEMANTICS_NOTE: Final[str] = (
    "free_base_quantity = broker_available_base_quantity - "
    "sum(APPROVED_NOT_SUBMITTED local reservations); "
    "SUBMITTED_AWAITING_RECONCILIATION/OPEN/PARTIALLY_FILLED reservations are "
    "already reflected in broker_available_base_quantity and are not "
    "subtracted again"
)


@dataclass(frozen=True)
class WalletAvailableSnapshot:
    trading_account_id: int
    venue: str
    asset_id: int
    symbol: str
    available_base_quantity: Decimal
    total_base_quantity: Decimal | None
    source_name: str
    snapshot_ts_utc: datetime
    # Snapshot row identity/version (e.g. account_position_snapshot_id). Optional
    # for backward compatibility with existing direct-construction callers;
    # src.decision_gate.manual_execution_gate_v1 always populates this so a
    # persisted manual execution approval can bind to a specific version.
    snapshot_id: int | None = None


@dataclass(frozen=True)
class FreeBaseQuantityResult:
    status: str  # OK | BLOCKED
    trading_account_id: int
    venue: str
    asset_id: int
    symbol: str
    free_base_quantity: Decimal | None
    broker_available_base_quantity: Decimal
    local_non_broker_reflected_reservation_base: Decimal
    reservation_semantics: str
    source_name: str
    snapshot_ts_utc: datetime
    resolved_ts_utc: datetime
    blocking_reasons: tuple[str, ...]


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def resolve_free_base_quantity_core_v1(
    *,
    wallet_snapshot: WalletAvailableSnapshot,
    approved_not_submitted_reservation_base: Decimal,
    reconciliation_pending_reservation_count: int,
    max_wallet_snapshot_age_seconds: int = DEFAULT_MAX_WALLET_SNAPSHOT_AGE_SECONDS,
    expected_trading_account_id: int | None = None,
    expected_venue: str | None = None,
    expected_asset_id: int | None = None,
    evaluation_ts_utc: datetime,
) -> FreeBaseQuantityResult:
    """Resolve the one canonical FREE_BASE_QUANTITY value for one asset.

    Fails closed (status=BLOCKED, free_base_quantity=None) on any of: a
    stale wallet snapshot, an incomplete/contradictory wallet snapshot, an
    account/venue/asset mismatch against the caller's expectations, any
    reservation still pending broker reconciliation, or a negative result.
    """
    reasons: list[str] = []
    resolved_now = evaluation_ts_utc

    if (
        expected_trading_account_id is not None
        and wallet_snapshot.trading_account_id != expected_trading_account_id
    ):
        reasons.append(REASON_ACCOUNT_VENUE_ASSET_MISMATCH)
    if expected_venue is not None and wallet_snapshot.venue != expected_venue:
        reasons.append(REASON_ACCOUNT_VENUE_ASSET_MISMATCH)
    if expected_asset_id is not None and wallet_snapshot.asset_id != expected_asset_id:
        reasons.append(REASON_ACCOUNT_VENUE_ASSET_MISMATCH)

    if wallet_snapshot.available_base_quantity is None:
        reasons.append(REASON_INCOMPLETE_WALLET_SNAPSHOT)
    elif wallet_snapshot.available_base_quantity < 0:
        reasons.append(REASON_CONTRADICTORY_WALLET_SNAPSHOT)
    elif (
        wallet_snapshot.total_base_quantity is not None
        and wallet_snapshot.available_base_quantity > wallet_snapshot.total_base_quantity
    ):
        reasons.append(REASON_CONTRADICTORY_WALLET_SNAPSHOT)

    snapshot_ts = _ensure_aware(wallet_snapshot.snapshot_ts_utc)
    now_aware = _ensure_aware(resolved_now)
    age = now_aware - snapshot_ts
    if age > timedelta(seconds=max_wallet_snapshot_age_seconds) or age < timedelta(0):
        reasons.append(REASON_STALE_WALLET_SNAPSHOT)

    if reconciliation_pending_reservation_count > 0:
        reasons.append(REASON_RECONCILIATION_PENDING)

    if approved_not_submitted_reservation_base < 0:
        reasons.append(REASON_CONTRADICTORY_WALLET_SNAPSHOT)

    free_qty: Decimal | None = None
    if not reasons:
        free_qty = (
            wallet_snapshot.available_base_quantity
            - approved_not_submitted_reservation_base
        )
        if free_qty < 0:
            reasons.append(REASON_NEGATIVE_RESULT)
            free_qty = None

    return FreeBaseQuantityResult(
        status=STATUS_BLOCKED if reasons else STATUS_OK,
        trading_account_id=wallet_snapshot.trading_account_id,
        venue=wallet_snapshot.venue,
        asset_id=wallet_snapshot.asset_id,
        symbol=wallet_snapshot.symbol,
        free_base_quantity=free_qty,
        broker_available_base_quantity=wallet_snapshot.available_base_quantity,
        local_non_broker_reflected_reservation_base=approved_not_submitted_reservation_base,
        reservation_semantics=_RESERVATION_SEMANTICS_NOTE,
        source_name=wallet_snapshot.source_name,
        snapshot_ts_utc=wallet_snapshot.snapshot_ts_utc,
        resolved_ts_utc=resolved_now,
        blocking_reasons=tuple(reasons),
    )


def resolve_free_base_quantity(
    *, wallet_snapshot: WalletAvailableSnapshot,
    approved_not_submitted_reservation_base: Decimal,
    reconciliation_pending_reservation_count: int,
    max_wallet_snapshot_age_seconds: int = DEFAULT_MAX_WALLET_SNAPSHOT_AGE_SECONDS,
    expected_trading_account_id: int | None = None,
    expected_venue: str | None = None,
    expected_asset_id: int | None = None,
) -> FreeBaseQuantityResult:
    """Real-time compatibility wrapper around the explicit-time pure core."""
    return resolve_free_base_quantity_core_v1(
        wallet_snapshot=wallet_snapshot,
        approved_not_submitted_reservation_base=approved_not_submitted_reservation_base,
        reconciliation_pending_reservation_count=reconciliation_pending_reservation_count,
        max_wallet_snapshot_age_seconds=max_wallet_snapshot_age_seconds,
        expected_trading_account_id=expected_trading_account_id,
        expected_venue=expected_venue,
        expected_asset_id=expected_asset_id,
        evaluation_ts_utc=trusted_clock.utc_now(),
    )
