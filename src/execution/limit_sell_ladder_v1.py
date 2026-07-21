from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Sequence

from src.execution.bitvavo_client import BitvavoClient, BitvavoOrderRequest


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


def quantize_decimal(value: Decimal, quantum: Decimal | None) -> Decimal:
    if quantum is None:
        return value
    return value.quantize(quantum, rounding=ROUND_DOWN)


def build_limit_sell_ladder_orders(
    *,
    market: str,
    available_qty: Decimal,
    levels: Sequence[LimitSellLadderLevel],
    price_quantize: Decimal | None = None,
    amount_quantize: Decimal | None = None,
) -> list[BitvavoOrderRequest]:
    validation_errors = validate_limit_sell_ladder_levels(levels)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    if available_qty <= 0:
        raise ValueError("available_qty must be > 0")

    orders: list[BitvavoOrderRequest] = []
    for level in levels:
        amount = available_qty * level.quantity_pct / Decimal("100")
        price = compute_offset_limit_price(level.level_price, level.offset_pct)
        quantized_amount = quantize_decimal(amount, amount_quantize)
        quantized_price = quantize_decimal(price, price_quantize)
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
