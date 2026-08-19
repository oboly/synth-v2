"""Deterministic non-networked adapter for the shared executor DRY_RUN mode."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.executor.broker_ack_classification_v1 import BrokerAckStateV1, OrderAckV1


@dataclass(frozen=True)
class DryRunOrderPlacementAdapterV1:
    """Record a synthetic executor acknowledgement without a broker operation."""

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
        del market, side, price, quantity, operator_id
        return OrderAckV1(
            broker_order_id=f"synthetic-dry-run-{client_order_id}",
            state=BrokerAckStateV1.ACTIVE,
            broker_raw_status="SYNTHETIC_DRY_RUN_NO_BROKER",
        )

    def find_order_by_client_order_id(
        self, *, market: str, client_order_id: str
    ) -> OrderAckV1 | None:
        del market, client_order_id
        return None
