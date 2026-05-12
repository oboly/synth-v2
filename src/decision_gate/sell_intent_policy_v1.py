from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


POLICY_NAME = "sell_intent_policy_v1"
POLICY_VERSION = "0.1"


@dataclass(frozen=True)
class SellIntentPolicyInput:
    account_enabled: int
    account_live_trading_enabled: int
    broker_write_permission_state: str
    hard_safety_nonzero: bool
    source_duplicate_symbol_rows: int
    source_negative_quantity_rows: int
    source_missing_mark_price_rows: int
    position_exists: bool
    position_quantity_base: Decimal
    available_quantity_base: Decimal
    reserved_quantity_base: Decimal
    open_sell_order_remaining_base: Decimal
    requested_quantity_base: Decimal
    mark_price_exists: bool
    source_freshness_ok: bool
    tolerance: Decimal = Decimal("0.00000001")


@dataclass(frozen=True)
class SellIntentPolicyDecision:
    policy_name: str
    policy_version: str
    preview_state: str
    actual_execution_permission: str
    blocking_reasons: tuple[str, ...]
    requested_quantity_base: Decimal
    available_quantity_base: Decimal
    reserved_quantity_base: Decimal
    open_sell_order_remaining_base: Decimal
    reserved_open_order_diff_base: Decimal


def evaluate_sell_intent_policy_v1(
    policy_input: SellIntentPolicyInput,
) -> SellIntentPolicyDecision:
    blockers: list[str] = []

    if policy_input.account_enabled != 1:
        blockers.append("ACCOUNT_DISABLED")

    if policy_input.account_live_trading_enabled != 0:
        blockers.append("LIVE_TRADING_ENABLED_NOT_ALLOWED")

    if policy_input.broker_write_permission_state == "GRANTED":
        blockers.append("BROKER_WRITE_PERMISSION_GRANTED")

    if policy_input.hard_safety_nonzero:
        blockers.append("HARD_SAFETY_NONZERO")

    if policy_input.source_duplicate_symbol_rows != 0:
        blockers.append("SOURCE_DUPLICATES")

    if policy_input.source_negative_quantity_rows != 0:
        blockers.append("SOURCE_NEGATIVE_QUANTITIES")

    if policy_input.source_missing_mark_price_rows != 0:
        blockers.append("SOURCE_MISSING_MARK_PRICE")

    if not policy_input.source_freshness_ok:
        blockers.append("SOURCE_STALE")

    if not policy_input.position_exists:
        blockers.append("NO_POSITION")
        reserved_diff = Decimal("0") - policy_input.open_sell_order_remaining_base
        return SellIntentPolicyDecision(
            policy_name=POLICY_NAME,
            policy_version=POLICY_VERSION,
            preview_state="BLOCKED",
            actual_execution_permission="NOT_GRANTED",
            blocking_reasons=tuple(blockers),
            requested_quantity_base=policy_input.requested_quantity_base,
            available_quantity_base=Decimal("0"),
            reserved_quantity_base=Decimal("0"),
            open_sell_order_remaining_base=policy_input.open_sell_order_remaining_base,
            reserved_open_order_diff_base=reserved_diff,
        )

    if policy_input.position_quantity_base <= 0:
        blockers.append("NO_POSITION_QUANTITY")

    if policy_input.available_quantity_base <= 0:
        if policy_input.reserved_quantity_base > 0:
            blockers.append("NO_AVAILABLE_QUANTITY_RESERVED")
        else:
            blockers.append("NO_AVAILABLE_QUANTITY")

    if policy_input.requested_quantity_base <= 0:
        blockers.append("REQUESTED_QUANTITY_NOT_POSITIVE")

    if policy_input.requested_quantity_base > policy_input.available_quantity_base + policy_input.tolerance:
        blockers.append("REQUEST_EXCEEDS_AVAILABLE_QUANTITY")

    if not policy_input.mark_price_exists:
        blockers.append("MISSING_MARK_PRICE")

    reserved_diff = (
        policy_input.reserved_quantity_base
        - policy_input.open_sell_order_remaining_base
    )

    if abs(reserved_diff) > policy_input.tolerance:
        blockers.append("RESERVED_OPEN_ORDER_MISMATCH")

    preview_state = (
        "WOULD_APPROVE_SELL_INTENT_PREVIEW"
        if not blockers
        else "BLOCKED"
    )

    return SellIntentPolicyDecision(
        policy_name=POLICY_NAME,
        policy_version=POLICY_VERSION,
        preview_state=preview_state,
        actual_execution_permission="NOT_GRANTED",
        blocking_reasons=tuple(blockers),
        requested_quantity_base=policy_input.requested_quantity_base,
        available_quantity_base=policy_input.available_quantity_base,
        reserved_quantity_base=policy_input.reserved_quantity_base,
        open_sell_order_remaining_base=policy_input.open_sell_order_remaining_base,
        reserved_open_order_diff_base=reserved_diff,
    )
