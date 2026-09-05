"""Issue #752: strategy-owned inventory ledger -- pure ownership/authority logic.

No canonical existing owner fits this fact today (see the #752 audit):
``account_position_snapshot``/reconciliation own raw broker-wallet balance
truth only, and nothing in the #399 automatic-BUY lineage persists
``strategy_bucket_id``/``strategy_id`` as queryable columns on a fill/order
row. This module is therefore new persistence for a fact reconciliation does
not own, layered strictly on top of (never replacing) reconciliation's
broker-wallet truth:

    broker wallet balance  = reconciliation fact (existing, unchanged)
    strategy-owned quantity = allocation/position ownership fact (this module)

It never re-derives ownership by heuristically splitting a wallet balance;
ownership exists only as the deterministic sum of explicitly attributed fill
events, deduplicated by canonical fill/order identity.

Lineage identity (the exact scope one strategy may reduce):

    (trading_account_id, venue, market, strategy_bucket_id, strategy_id,
     strategy_version, setup_id)

Two different lineages may own quantity in the exact same
(trading_account_id, venue, market) without collision -- each is tracked and
summed independently; a SELL request against one lineage is validated only
against that lineage's own remaining owned quantity, never against another
lineage's quantity or the raw broker wallet total.

Legacy/unattributed inventory: any quantity never recorded here through an
explicit attributed BUY fill has no lineage a caller can query, so
``validate_sell_authority_v1`` structurally has nothing to authorize for it
(0 remaining owned quantity for that lineage). This is the fail-closed
default; a future explicit, reviewed adoption action (not implemented here)
would be the only way to attribute pre-existing/manual inventory to a
lineage.

Pure functions only: no DB access, no broker, no execution, no market
ranking. A caller-side repository (not this module) is responsible for
loading persisted ``StrategyOwnedFillEventV1`` rows and for the idempotent
insert respecting the ledger table's canonical-identity uniqueness
constraint.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final, Iterable

LEDGER_CONTRACT_VERSION: Final[str] = "1"

SIDE_BUY: Final[str] = "BUY"
SIDE_SELL: Final[str] = "SELL"
SUPPORTED_SIDES: Final[frozenset[str]] = frozenset({SIDE_BUY, SIDE_SELL})


class StrategyOwnedInventoryLedgerError(ValueError):
    """Fail-closed ledger/authority error. ``args[0]`` is the reason code."""


@dataclass(frozen=True)
class StrategyOwnershipLineageV1:
    """Exact ownership scope one strategy/trade lineage may reduce.

    Two lineages differing only in ``strategy_bucket_id``, ``strategy_id``,
    ``strategy_version``, or ``setup_id`` are wholly independent even for the
    identical (``trading_account_id``, ``venue``, ``market``).
    """

    trading_account_id: int
    venue: str
    market: str
    strategy_bucket_id: str
    strategy_id: str
    strategy_version: str
    setup_id: str


@dataclass(frozen=True)
class StrategyOwnedFillEventV1:
    """One durable, immutable, attributed BUY or SELL fill event.

    ``order_identity`` is the canonical fill/order identity used for
    deterministic deduplication (e.g. ``client_order_id`` or
    ``client_order_id:leg_index``) -- a duplicate reconciliation event for
    the same ``order_identity`` must never double-count. ``lineage`` binds
    the event to exactly one strategy/trade's ownership scope.
    ``execution_plan_reference_id`` is the source #399 plan identity (which
    itself folds in the source decision_gate decision's state/reason/ceiling
    and strategy identity via its hash); it is preserved here purely as
    provenance, not re-validated.
    """

    lineage: StrategyOwnershipLineageV1
    order_identity: str
    execution_plan_reference_id: str
    side: str
    base_quantity: Decimal
    quote_notional: Decimal
    occurred_ts_utc: datetime
    source_provenance: str


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _positive_decimal(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value > 0


def _nonnegative_decimal(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value >= 0


def validate_lineage_v1(lineage: StrategyOwnershipLineageV1) -> None:
    """Fail closed on any incomplete/malformed lineage identity.

    A lineage with any empty identity field can never be used to query or
    authorize a reduction -- this is the structural guarantee that
    unattributed inventory (which has no complete lineage recorded for it)
    can never accidentally resolve to "everything" via a wildcard/blank
    scope.
    """
    if (
        lineage.trading_account_id <= 0
        or not _nonempty(lineage.venue)
        or not _nonempty(lineage.market)
        or not _nonempty(lineage.strategy_bucket_id)
        or not _nonempty(lineage.strategy_id)
        or not _nonempty(lineage.strategy_version)
        or not _nonempty(lineage.setup_id)
    ):
        raise StrategyOwnedInventoryLedgerError("INVALID_STRATEGY_OWNERSHIP_LINEAGE")


def validate_fill_event_v1(event: StrategyOwnedFillEventV1) -> None:
    validate_lineage_v1(event.lineage)
    if not _nonempty(event.order_identity):
        raise StrategyOwnedInventoryLedgerError("INVALID_ORDER_IDENTITY")
    if not _nonempty(event.execution_plan_reference_id):
        raise StrategyOwnedInventoryLedgerError("INVALID_EXECUTION_PLAN_REFERENCE_ID")
    if event.side not in SUPPORTED_SIDES:
        raise StrategyOwnedInventoryLedgerError("INVALID_FILL_EVENT_SIDE")
    if not _positive_decimal(event.base_quantity):
        raise StrategyOwnedInventoryLedgerError("INVALID_FILL_EVENT_BASE_QUANTITY")
    if not _nonnegative_decimal(event.quote_notional):
        raise StrategyOwnedInventoryLedgerError("INVALID_FILL_EVENT_QUOTE_NOTIONAL")
    if not _aware(event.occurred_ts_utc):
        raise StrategyOwnedInventoryLedgerError("INVALID_FILL_EVENT_TIMESTAMP")
    if not _nonempty(event.source_provenance):
        raise StrategyOwnedInventoryLedgerError("INVALID_FILL_EVENT_SOURCE_PROVENANCE")


def _dedup_by_order_identity(
    events: Iterable[StrategyOwnedFillEventV1],
) -> tuple[StrategyOwnedFillEventV1, ...]:
    """Deterministic dedup by canonical ``order_identity``.

    A duplicate reconciliation event (same ``order_identity`` observed more
    than once, e.g. from an at-least-once delivery or a restart replay) must
    never double-increment or double-decrement owned quantity. The first
    occurrence in the supplied iteration order wins; callers are expected to
    supply events pre-sorted by ``occurred_ts_utc`` when order matters, but
    the dedup result is identical regardless of input order since only one
    fact per ``order_identity`` is kept and its own fields never conflict for
    a legitimately duplicated event.
    """
    seen: dict[str, StrategyOwnedFillEventV1] = {}
    for event in events:
        existing = seen.get(event.order_identity)
        if existing is None:
            seen[event.order_identity] = event
            continue
        if (
            existing.lineage != event.lineage
            or existing.side != event.side
            or existing.base_quantity != event.base_quantity
        ):
            raise StrategyOwnedInventoryLedgerError("CONFLICTING_DUPLICATE_ORDER_IDENTITY")
    return tuple(seen.values())


def compute_owned_quantity_v1(
    events: Iterable[StrategyOwnedFillEventV1],
    *,
    lineage: StrategyOwnershipLineageV1,
) -> Decimal:
    """Return exactly this lineage's remaining owned base quantity.

    ``owned_qty(lineage) = sum(attributed BUY fills) - sum(attributed SELL
    fills)``, deduplicated by canonical ``order_identity`` first (so a
    duplicate reconciliation event never double-counts), then filtered to
    events matching ``lineage`` exactly. Events for any other lineage --
    including a different strategy/trade in the identical
    (trading_account_id, venue, market) -- are ignored entirely; they can
    never inflate or deflate this lineage's quantity.

    Fails closed if the deduplicated ledger for this lineage is internally
    inconsistent (computed remaining quantity would be negative) rather than
    silently clamping to zero -- a negative result means an upstream
    SELL-authority check was bypassed and must be treated as a data
    integrity failure, not tolerated here.
    """
    validate_lineage_v1(lineage)
    deduped = _dedup_by_order_identity(events)
    total = Decimal("0")
    for event in deduped:
        if event.lineage != lineage:
            continue
        validate_fill_event_v1(event)
        if event.side == SIDE_BUY:
            total += event.base_quantity
        else:
            total -= event.base_quantity
    if total < 0:
        raise StrategyOwnedInventoryLedgerError("NEGATIVE_OWNED_QUANTITY_LEDGER_INCONSISTENT")
    return total


def validate_sell_authority_v1(
    events: Iterable[StrategyOwnedFillEventV1],
    *,
    lineage: StrategyOwnershipLineageV1,
    requested_reduce_base_quantity: Decimal,
) -> Decimal:
    """Fail closed unless the requested reduction fits this lineage's own quantity.

    Broker wallet total balance is never consulted here and can never
    increase this authority -- only ``events`` matching ``lineage`` exactly
    are summed. Returns the pre-reduction remaining owned quantity on
    success (callers may use it for post-reduction bookkeeping); raises
    :class:`StrategyOwnedInventoryLedgerError` otherwise.

    This function does not distinguish a protective/reducing exit from a
    discretionary one -- that policy (crossing ``allocation_max_pct`` blocks
    NEW exposure but never blocks a valid reducing/protective exit) is owned
    by the caller (decision_gate), which must apply
    ``strategy_bucket_capacity_v1`` allocation-ceiling checks only to NEW
    entries and always route reductions through this function regardless of
    current bucket allocation state.
    """
    if not _positive_decimal(requested_reduce_base_quantity):
        raise StrategyOwnedInventoryLedgerError("INVALID_REQUESTED_REDUCE_QUANTITY")
    remaining = compute_owned_quantity_v1(events, lineage=lineage)
    if requested_reduce_base_quantity > remaining:
        raise StrategyOwnedInventoryLedgerError("SELL_QUANTITY_EXCEEDS_OWNED_LINEAGE_QUANTITY")
    return remaining
