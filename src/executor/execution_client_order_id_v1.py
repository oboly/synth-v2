"""
execution_client_order_id_v1 -- deterministic per-leg broker order identity
for the shared algorithmic BUY/SELL executor boundary (Issue #206).

Layer: executor-only, pure/no DB access, no broker calls.

Side-neutral generalization of
src.executor.manual_execution_client_order_id_v1: same deterministic-UUIDv5
approach (never a random UUID minted at submit time, so the exact same
immutable leg always produces the exact same clientOrderId across process
restarts and retries -- the precondition for safe crash/timeout
reconciliation), but keyed to the generic (executor_execution_handoff_id,
leg_index, trading_account_id, venue, market) identity instead of a
manual_execution_plan_snapshot_id, so it is usable by any upstream plan
source (manual, automatic exit #392, future automatic entry #399).

This module intentionally uses its own UUID namespace, distinct from the
manual-lane namespace in manual_execution_client_order_id_v1 -- the two
identity spaces (plan_snapshot_id vs. handoff_id) are not comparable, so
reusing the same namespace constant would not preserve any determinism
guarantee and would only invite confusion.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

import uuid
from typing import Final

# Fixed, documented Synth namespace for the shared algorithmic executor
# boundary's client_order_id derivation. Computed once via:
#   uuid.uuid5(uuid.NAMESPACE_URL,
#              "https://synth.internal/executor/execution-client-order-id/v1")
# Must never change; changing it would silently mint a different
# clientOrderId for every already-persisted leg.
SYNTH_EXECUTION_CLIENT_ORDER_ID_NAMESPACE: Final[uuid.UUID] = uuid.UUID(
    "6e2f7f8a-8f2b-5a1a-9c3f-6c9e0f6b7a2d"
)


def derive_client_order_id(
    *,
    handoff_id: int,
    leg_index: int,
    trading_account_id: int,
    venue: str,
    market: str,
) -> str:
    """Deterministic UUIDv5 clientOrderId for one immutable persisted
    executor_execution_leg row. Same (handoff_id, leg_index,
    trading_account_id, venue, market) always yields the same value; any
    difference in any one of those fields yields a different value."""
    if handoff_id <= 0:
        raise ValueError("handoff_id must be a persisted positive ID")
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
        f"executor_execution_handoff:{handoff_id}"
        f"|leg_index:{leg_index}"
        f"|trading_account_id:{trading_account_id}"
        f"|venue:{normalized_venue}"
        f"|market:{normalized_market}"
    )
    return str(uuid.uuid5(SYNTH_EXECUTION_CLIENT_ORDER_ID_NAMESPACE, name))
