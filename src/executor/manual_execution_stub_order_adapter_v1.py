"""
manual_execution_stub_order_adapter_v1 — the non-live OrderPlacementAdapter
used to exercise
src.executor.manual_execution_submission_orchestrator_v1.submit_manual_sell_ladder
end to end (per-leg persistence, deterministic clientOrderId, sequential
submission, ack persistence, partial success, timeout/uncertain reconcile)
without ever calling a broker (Issue #369).

This is not a second orchestrator: it is only the injected broker boundary.
Behavior per clientOrderId is configured explicitly by the caller (e.g. one
test wires "reject leg 2", another wires "timeout leg 1 once, then confirm
on reconcile") — nothing here infers behavior from ladder content.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Callable

from src.executor.manual_execution_submission_orchestrator_v1 import (
    BrokerOrderRejectedError,
    OrderAck,
    SubmissionUncertainError,
)


@dataclass
class StubOrderPlacementAdapter:
    """Deterministic in-memory stub. ``script`` maps client_order_id to a
    zero-arg callable invoked on the *next* place_order call for that id;
    the callable returns an OrderAck, or raises SubmissionUncertainError /
    BrokerOrderRejectedError. Any client_order_id absent from ``script``
    place_order succeeds with a synthesized ack. ``confirmed`` records
    every clientOrderId this stub has actually acked, so
    find_order_by_client_order_id reflects only orders that were really
    "sent" — it never fabricates an order the ladder never placed."""

    script: dict[str, Callable[[], OrderAck]] = field(default_factory=dict)
    confirmed: dict[str, OrderAck] = field(default_factory=dict)
    reconcile_script: dict[str, Callable[[], OrderAck | None]] = field(default_factory=dict)
    _order_id_seq: itertools.count = field(default_factory=lambda: itertools.count(1))

    def place_order(
        self,
        *,
        market: str,
        side: str,
        price,
        quantity,
        client_order_id: str,
        operator_id: int,
    ) -> OrderAck:
        step = self.script.pop(client_order_id, None)
        if step is not None:
            ack = step()
            self.confirmed[client_order_id] = ack
            return ack
        ack = OrderAck(
            broker_order_id=f"stub-order-{next(self._order_id_seq)}",
            broker_status="OPEN",
        )
        self.confirmed[client_order_id] = ack
        return ack

    def find_order_by_client_order_id(
        self, *, market: str, client_order_id: str
    ) -> OrderAck | None:
        step = self.reconcile_script.pop(client_order_id, None)
        if step is not None:
            result = step()
            if result is not None:
                self.confirmed[client_order_id] = result
            return result
        return self.confirmed.get(client_order_id)


def uncertain_once(message: str = "STUB_TIMEOUT") -> Callable[[], OrderAck]:
    def _raise() -> OrderAck:
        raise SubmissionUncertainError(message)

    return _raise


def rejected(safe_error_code: str) -> Callable[[], OrderAck]:
    def _raise() -> OrderAck:
        raise BrokerOrderRejectedError(safe_error_code=safe_error_code)

    return _raise
