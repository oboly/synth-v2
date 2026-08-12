"""
manual_execution_client_order_id_v1 — deterministic per-leg broker order
identity for the manual SELL ladder submission orchestrator (Issue #369).

Layer: executor-only, pure/no DB access, no broker calls.

Bitvavo's Create Order accepts an optional caller-supplied ``clientOrderId``
(a UUID) that must be unique across open orders, and Get Order can resolve
an order by that same value. This module derives that UUID deterministically
from canonical persisted leg identity only — never a random UUID minted at
submit time — so the exact same immutable leg always produces the exact
same clientOrderId across process restarts and retries, which is the
precondition for safe crash/timeout reconciliation
(src.executor.manual_execution_submission_orchestrator_v1).

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

import uuid
from typing import Final

# Fixed, documented Synth namespace for manual-execution client_order_id
# derivation. Computed once via:
#   uuid.uuid5(uuid.NAMESPACE_URL,
#              "https://synth.internal/manual-execution/client-order-id/v1")
# Must never change; changing it would silently mint a different
# clientOrderId for every already-persisted leg.
SYNTH_MANUAL_EXECUTION_CLIENT_ORDER_ID_NAMESPACE: Final[uuid.UUID] = uuid.UUID(
    "a49cf4dd-4832-57c9-8815-0c6f51c10d53"
)


def derive_client_order_id(
    *,
    plan_snapshot_id: int,
    leg_index: int,
    trading_account_id: int,
    venue: str,
    market: str,
) -> str:
    """Deterministic UUIDv5 clientOrderId for one immutable persisted plan
    leg. Same (plan_snapshot_id, leg_index, trading_account_id, venue,
    market) always yields the same value; any difference in any one of
    those fields yields a different value."""
    if plan_snapshot_id <= 0:
        raise ValueError("plan_snapshot_id must be a persisted positive ID")
    if leg_index <= 0:
        raise ValueError("leg_index must be a positive 1-based leg index")
    if trading_account_id <= 0:
        raise ValueError("trading_account_id must be a persisted positive ID")
    normalized_venue = venue.strip().lower()
    normalized_market = market.strip().upper()
    if not normalized_venue:
        raise ValueError("venue must not be empty")
    if not normalized_market:
        raise ValueError("market must not be empty")

    name = (
        f"manual_execution_plan_snapshot:{plan_snapshot_id}"
        f"|leg_index:{leg_index}"
        f"|trading_account_id:{trading_account_id}"
        f"|venue:{normalized_venue}"
        f"|market:{normalized_market}"
    )
    return str(
        uuid.uuid5(SYNTH_MANUAL_EXECUTION_CLIENT_ORDER_ID_NAMESPACE, name)
    )
