from decimal import Decimal
import unittest

from src.execution.limit_sell_ladder_v1 import (
    LimitSellLadderLevel,
    build_limit_sell_ladder_orders,
    compute_offset_limit_price,
    place_limit_sell_ladder_orders,
    preview_limit_sell_ladder_orders,
    validate_limit_sell_ladder_levels,
)


class LimitSellLadderV1Tests(unittest.TestCase):
    def test_compute_offset_limit_price(self) -> None:
        self.assertEqual(
            compute_offset_limit_price(Decimal("10"), Decimal("1.5")),
            Decimal("9.850"),
        )

    def test_build_limit_sell_ladder_orders_quantizes_amount_and_price(self) -> None:
        # Regression: price rounding for a SELL leg must round UP to the
        # tick (never place a sell below the analytical target) via the
        # canonical rounding service, not the previous unconditional
        # ROUND_DOWN. 0.45678 * 0.99 = 0.4522122 -> ROUND_UP to 0.001 -> 0.453.
        # See docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md
        # finding F3.
        orders = build_limit_sell_ladder_orders(
            market="WLD-EUR",
            available_qty=Decimal("100"),
            levels=[
                LimitSellLadderLevel(
                    level_price=Decimal("0.45678"),
                    offset_pct=Decimal("1"),
                    quantity_pct=Decimal("25"),
                )
            ],
            price_quantize=Decimal("0.001"),
            amount_quantize=Decimal("0.00000001"),
        )

        self.assertEqual(len(orders), 1)
        order = orders[0]
        self.assertEqual(order.market, "WLD-EUR")
        self.assertEqual(order.side, "sell")
        self.assertEqual(order.order_type, "limit")
        self.assertEqual(order.amount, "25.00000000")
        self.assertEqual(order.price, "0.453")
        self.assertTrue(order.post_only)
        self.assertEqual(order.time_in_force, "GTC")

    def test_build_limit_sell_ladder_orders_never_rounds_price_down(self) -> None:
        # Direct regression for F3: a raw price that is not exactly on a
        # tick boundary must never be quantized below its raw value for a
        # SELL leg.
        orders = build_limit_sell_ladder_orders(
            market="WLD-EUR",
            available_qty=Decimal("100"),
            levels=[
                LimitSellLadderLevel(
                    level_price=Decimal("1.23456"),
                    offset_pct=Decimal("0"),
                    quantity_pct=Decimal("100"),
                )
            ],
            price_quantize=Decimal("0.01"),
            amount_quantize=Decimal("0.00000001"),
        )
        rounded_price = Decimal(orders[0].price)
        self.assertGreaterEqual(rounded_price, Decimal("1.23456"))

    def test_preview_limit_sell_ladder_orders(self) -> None:
        orders = build_limit_sell_ladder_orders(
            market="WLD-EUR",
            available_qty=Decimal("100"),
            levels=[
                LimitSellLadderLevel(
                    level_price=Decimal("0.500"),
                    offset_pct=Decimal("0"),
                    quantity_pct=Decimal("25"),
                )
            ],
            price_quantize=Decimal("0.001"),
            amount_quantize=Decimal("0.00000001"),
        )

        rows = preview_limit_sell_ladder_orders(orders)

        self.assertEqual(
            rows,
            [
                {
                    "market": "WLD-EUR",
                    "side": "sell",
                    "order_type": "limit",
                    "amount": "25.00000000",
                    "price": "0.500",
                    "post_only": True,
                    "time_in_force": "GTC",
                }
            ],
        )

    def test_validate_limit_sell_ladder_levels_rejects_invalid_values(self) -> None:
        errors = validate_limit_sell_ladder_levels(
            [
                LimitSellLadderLevel(
                    level_price=Decimal("0"),
                    offset_pct=Decimal("-1"),
                    quantity_pct=Decimal("101"),
                )
            ]
        )

        self.assertEqual(
            errors,
            [
                "levels[0].level_price must be > 0",
                "levels[0].offset_pct must be >= 0",
                "levels[0].quantity_pct must be <= 100",
                "sum quantity_pct must be <= 100",
            ],
        )

    def test_place_limit_sell_ladder_orders_requires_confirmation(self) -> None:
        with self.assertRaises(PermissionError):
            place_limit_sell_ladder_orders(
                client=object(),  # type: ignore[arg-type]
                orders=[],
                confirm_real_orders=False,
            )

    def test_place_limit_sell_ladder_orders_never_calls_broker_directly(self) -> None:
        class Client:
            def place_order(self, _order):  # noqa: ANN001
                raise AssertionError("direct broker placement must not be called")

        with self.assertRaises(PermissionError):
            place_limit_sell_ladder_orders(
                client=Client(),  # type: ignore[arg-type]
                orders=[],
                confirm_real_orders=True,
            )


if __name__ == "__main__":
    unittest.main()
