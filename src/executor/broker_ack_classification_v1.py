"""Venue-neutral broker acknowledgement vocabulary."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BrokerAckStateV1(StrEnum):
    ACTIVE = "ACTIVE"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    AMBIGUOUS = "AMBIGUOUS"


ACCEPTED_ACK_STATES = frozenset({BrokerAckStateV1.ACTIVE, BrokerAckStateV1.PARTIALLY_FILLED, BrokerAckStateV1.FILLED})
CLOSED_ACK_STATES = frozenset({BrokerAckStateV1.CANCELED, BrokerAckStateV1.EXPIRED, BrokerAckStateV1.REJECTED})


@dataclass(frozen=True)
class OrderAckV1:
    broker_order_id: str | None
    state: BrokerAckStateV1
