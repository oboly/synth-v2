from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Sequence

from src.execution.bitvavo_client import BitvavoClient, BitvavoOrderRequest


@dataclass(frozen=True, slots=True)
class LimitBuyLadderLevel:
    limit_price: Decimal
    quote_notional: Decimal
    note: str = ""


def validate_limit_buy_ladder_levels(
    levels: Sequence[LimitBuyLadderLevel],
) -> list[str]:
    errors: list[str] = []

    for index, level in enumerate(levels):
        if level.limit_price <= 0:
            errors.append(f"levels[{index}].limit_price must be > 0")
        if level.quote_notional <= 0:
            errors.append(f"levels[{index}].quote_notional must be > 0")

    return errors


def quantize_decimal(value: Decimal, quantum: Decimal | None) -> Decimal:
    if quantum is None:
        return value
    return value.quantize(quantum, rounding=ROUND_DOWN)


def compute_base_amount_from_quote_notional(
    *,
    quote_notional: Decimal,
    limit_price: Decimal,
) -> Decimal:
    if quote_notional <= 0:
        raise ValueError("quote_notional must be > 0")
    if limit_price <= 0:
        raise ValueError("limit_price must be > 0")
    return quote_notional / limit_price


def build_limit_buy_ladder_orders(
    *,
    market: str,
    levels: Sequence[LimitBuyLadderLevel],
    price_quantize: Decimal | None = None,
    amount_quantize: Decimal | None = None,
    post_only: bool = True,
) -> list[BitvavoOrderRequest]:
    validation_errors = validate_limit_buy_ladder_levels(levels)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))

    orders: list[BitvavoOrderRequest] = []
    for level in levels:
        amount = compute_base_amount_from_quote_notional(
            quote_notional=level.quote_notional,
            limit_price=level.limit_price,
        )
        quantized_amount = quantize_decimal(amount, amount_quantize)
        quantized_price = quantize_decimal(level.limit_price, price_quantize)

        orders.append(
            BitvavoOrderRequest(
                market=market,
                side="buy",
                order_type="limit",
                amount=str(quantized_amount),
                price=str(quantized_price),
                post_only=post_only,
                time_in_force="GTC",
            )
        )

    return orders


def place_limit_buy_ladder_orders(
    *,
    client: BitvavoClient,
    orders: Sequence[BitvavoOrderRequest],
    confirm_real_orders: bool,
) -> list[dict[str, Any]]:
    if confirm_real_orders is not True:
        raise PermissionError(
            "Limit buy ladder placement requires confirm_real_orders=True."
        )
    raise PermissionError(
        "Direct limit buy ladder broker placement is disabled. "
        "Live order submission must pass the executor permission-consumption gate."
    )


def preview_limit_buy_ladder_orders(
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
