from __future__ import annotations

# NOT an authoritative manual-execution path: build_limit_sell_ladder_orders()
# below accepts a caller-controlled available_qty and permits both
# price_quantize/amount_quantize to be omitted (no rounding at all). The
# existing place_limit_sell_ladder_orders() PermissionError is the live
# safety boundary, not this builder — see
# docs/reviews/manual_execution_ladder_p0_implementation_review_20260725.md
# bypass-list item 5. Left unmodified in this change; route real manual SELL
# execution requests through
# src.manual_execution.manual_execution_service_v1.process() instead.

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Sequence

from src.execution.bitvavo_client import BitvavoClient, BitvavoOrderRequest
from src.execution_planner.canonical_rounding_v1 import (
    round_price_for_side,
    round_quantity_down,
)


@dataclass(frozen=True, slots=True)
class LimitSellLadderLevel:
    level_price: Decimal
    offset_pct: Decimal
    quantity_pct: Decimal
    note: str = ""


def compute_offset_limit_price(
    level_price: Decimal,
    offset_pct: Decimal,
) -> Decimal:
    return level_price * (Decimal("1") - (offset_pct / Decimal("100")))


def validate_limit_sell_ladder_levels(
    levels: Sequence[LimitSellLadderLevel],
) -> list[str]:
    errors: list[str] = []
    quantity_total = Decimal("0")

    for index, level in enumerate(levels):
        if level.level_price <= 0:
            errors.append(f"levels[{index}].level_price must be > 0")
        if level.offset_pct < 0:
            errors.append(f"levels[{index}].offset_pct must be >= 0")
        if level.quantity_pct <= 0:
            errors.append(f"levels[{index}].quantity_pct must be > 0")
        if level.quantity_pct > 100:
            errors.append(f"levels[{index}].quantity_pct must be <= 100")
        quantity_total += level.quantity_pct

    if quantity_total > 100:
        errors.append("sum quantity_pct must be <= 100")

    return errors


def quantize_decimal(value: Decimal, quantum: Decimal | None, *, side: str = "SELL") -> Decimal:
    """Side-aware quantization delegating to the single canonical rounding
    service (src.execution_planner.canonical_rounding_v1). This used to be
    an unconditional ROUND_DOWN for both price and amount, which rounded
    this ladder's SELL prices below the analytical target — see
    docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md
    finding F3. `side` only affects price rounding; quantity is always
    rounded down regardless of side (never exceed the approved amount)."""
    if quantum is None:
        return value
    return round_price_for_side(value, quantum, side)


def build_limit_sell_ladder_orders(
    *,
    market: str,
    available_qty: Decimal,
    levels: Sequence[LimitSellLadderLevel],
    price_quantize: Decimal | None = None,
    amount_quantize: Decimal | None = None,
) -> list[BitvavoOrderRequest]:
    raise PermissionError(
        "direct limit SELL order construction is disabled; route through "
        "manual_execution_service_v1.process()"
    )

    # Unreachable compatibility implementation retained for migration
    # auditing; no callable path may construct these order requests.
    validation_errors = validate_limit_sell_ladder_levels(levels)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    if available_qty <= 0:
        raise ValueError("available_qty must be > 0")

    orders: list[BitvavoOrderRequest] = []
    for level in levels:
        amount = available_qty * level.quantity_pct / Decimal("100")
        price = compute_offset_limit_price(level.level_price, level.offset_pct)
        quantized_amount = (
            amount if amount_quantize is None else round_quantity_down(amount, amount_quantize)
        )
        quantized_price = quantize_decimal(price, price_quantize, side="SELL")
        orders.append(
            BitvavoOrderRequest(
                market=market,
                side="sell",
                order_type="limit",
                amount=str(quantized_amount),
                price=str(quantized_price),
                post_only=True,
                time_in_force="GTC",
            )
        )
    return orders


def place_limit_sell_ladder_orders(
    *,
    client: BitvavoClient,
    orders: Sequence[BitvavoOrderRequest],
    confirm_real_orders: bool,
) -> list[dict[str, Any]]:
    if confirm_real_orders is not True:
        raise PermissionError(
            "Limit sell ladder placement requires confirm_real_orders=True."
        )
    raise PermissionError(
        "Direct limit sell ladder broker placement is disabled. "
        "Live execution prerequisites are unavailable."
    )


def preview_limit_sell_ladder_orders(
    orders: Sequence[BitvavoOrderRequest],
) -> list[dict[str, Any]]:
    raise PermissionError(
        "direct limit SELL order preview is disabled; route through "
        "manual_execution_service_v1.process()"
    )

    # Unreachable compatibility serialization retained for read analysis.
    rows: list[dict[str, Any]] = []
    for order in orders:
        rows.append(
            {
                "market": order.market,
                "side": order.side,
                "order_type": order.order_type,
                "amount": order.amount,
                "price": order.price,
                "post_only": order.post_only,
                "time_in_force": order.time_in_force,
            }
        )
    return rows
