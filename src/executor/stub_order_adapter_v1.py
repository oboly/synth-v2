"""Non-live test adapter: no network, credential, or broker dependency."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

from src.executor.broker_ack_classification_v1 import BrokerAckStateV1, OrderAckV1


@dataclass
class StubOrderPlacementAdapterV1:
    script: dict[str, Callable[[], OrderAckV1]] = field(default_factory=dict)
    reconciliation_script: dict[str, Callable[[], OrderAckV1 | None]] = field(default_factory=dict)
    confirmed: dict[str, OrderAckV1] = field(default_factory=dict)
    place_call_count: int = 0
    lookup_call_count: int = 0

    def place_order(
        self,
        *,
        market: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        client_order_id: str,
        operator_id: int,
    ) -> OrderAckV1:
        self.place_call_count += 1
        callback = self.script.pop(client_order_id, None)
        ack = callback() if callback is not None else OrderAckV1(f"stub-{self.place_call_count}", BrokerAckStateV1.ACTIVE)
        if ack.state != BrokerAckStateV1.AMBIGUOUS:
            self.confirmed[client_order_id] = ack
        return ack

    def find_order_by_client_order_id(self, *, market: str, client_order_id: str) -> OrderAckV1 | None:
        self.lookup_call_count += 1
        callback = self.reconciliation_script.pop(client_order_id, None)
        if callback is not None:
            ack = callback()
            if ack is not None and ack.state != BrokerAckStateV1.AMBIGUOUS:
                self.confirmed[client_order_id] = ack
            return ack
        return self.confirmed.get(client_order_id)
