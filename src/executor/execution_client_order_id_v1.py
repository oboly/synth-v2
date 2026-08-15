"""Deterministic UUIDv5 client order identity for shared executor legs."""
from __future__ import annotations

import uuid
from typing import Final

EXECUTION_CLIENT_ORDER_ID_NAMESPACE: Final[uuid.UUID] = uuid.UUID(
    "e9d6a9d5-bb0b-531b-83db-55b8aabf2893"
)


def derive_execution_client_order_id(
    *,
    handoff_id: int,
    plan_source: str,
    plan_reference_id: str,
    plan_content_hash: str,
    leg_index: int,
    trading_account_id: int,
    venue: str,
    market: str,
) -> str:
    for name, value in (
        ("handoff_id", handoff_id),
        ("leg_index", leg_index),
        ("trading_account_id", trading_account_id),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    text_values = (
        plan_source,
        plan_reference_id,
        plan_content_hash,
        venue,
        market,
    )
    if any(not isinstance(value, str) or not value.strip() for value in text_values):
        raise ValueError("client order identity text is required")
    if len(plan_content_hash) != 64:
        raise ValueError("plan_content_hash must be a SHA-256 hex digest")
    try:
        int(plan_content_hash, 16)
    except ValueError as exc:
        raise ValueError("plan_content_hash must be a SHA-256 hex digest") from exc

    canonical_name = "|".join(
        (
            str(handoff_id),
            plan_source.strip(),
            plan_reference_id.strip(),
            plan_content_hash.lower(),
            str(leg_index),
            str(trading_account_id),
            venue.strip().lower(),
            market.strip().upper(),
        )
    )
    return str(uuid.uuid5(EXECUTION_CLIENT_ORDER_ID_NAMESPACE, canonical_name))
