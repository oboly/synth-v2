from decimal import Decimal
import unittest

from src.execution.limit_buy_ladder_v1 import (
    LimitBuyLadderLevel,
    build_limit_buy_ladder_orders,
    compute_base_amount_from_quote_notional,
    place_limit_buy_ladder_orders,
    preview_limit_buy_ladder_orders,
    validate_limit_buy_ladder_levels,
)


class LimitBuyLadderV1Tests(unittest.TestCase):
    def test_compute_base_amount_from_quote_notional(self) -> None:
        amount = compute_base_amount_from_quote_notional(
            quote_notional=Decimal("15"),
            limit_price=Decimal("0.345"),
        )

        self.assertEqual(amount, Decimal("43.47826086956521739130434783"))

    def test_build_limit_buy_ladder_orders_quantizes_amount_and_price(self) -> None:
        orders = build_limit_buy_ladder_orders(
            market="WLD-EUR",
            levels=[
                LimitBuyLadderLevel(
                    limit_price=Decimal("0.3459"),
                    quote_notional=Decimal("15"),
                    note="manual reload",
                )
            ],
            price_quantize=Decimal("0.001"),
            amount_quantize=Decimal("0.00000001"),
            post_only=True,
        )

        self.assertEqual(len(orders), 1)
        order = orders[0]
        self.assertEqual(order.market, "WLD-EUR")
        self.assertEqual(order.side, "buy")
        self.assertEqual(order.order_type, "limit")
        self.assertEqual(order.amount, "43.36513443")
        self.assertEqual(order.price, "0.345")
        self.assertTrue(order.post_only)
        self.assertEqual(order.time_in_force, "GTC")

    def test_preview_limit_buy_ladder_orders(self) -> None:
        orders = build_limit_buy_ladder_orders(
            market="WLD-EUR",
            levels=[
                LimitBuyLadderLevel(
                    limit_price=Decimal("0.345"),
                    quote_notional=Decimal("15"),
                )
            ],
            price_quantize=Decimal("0.001"),
            amount_quantize=Decimal("0.00000001"),
        )

        rows = preview_limit_buy_ladder_orders(orders)

        self.assertEqual(
            rows,
            [
                {
                    "market": "WLD-EUR",
                    "side": "buy",
                    "order_type": "limit",
                    "amount": "43.47826086",
                    "price": "0.345",
                    "post_only": True,
                    "time_in_force": "GTC",
                }
            ],
        )

    def test_validate_limit_buy_ladder_levels_rejects_invalid_values(self) -> None:
        errors = validate_limit_buy_ladder_levels(
            [
                LimitBuyLadderLevel(
                    limit_price=Decimal("0"),
                    quote_notional=Decimal("-1"),
                )
            ]
        )

        self.assertEqual(
            errors,
            [
                "levels[0].limit_price must be > 0",
                "levels[0].quote_notional must be > 0",
            ],
        )

    def test_place_limit_buy_ladder_orders_requires_confirmation(self) -> None:
        with self.assertRaises(PermissionError):
            place_limit_buy_ladder_orders(
                client=object(),  # type: ignore[arg-type]
                orders=[],
                confirm_real_orders=False,
            )

    def test_place_limit_buy_ladder_orders_never_calls_broker_directly(self) -> None:
        class Client:
            def place_order(self, _order):  # noqa: ANN001
                raise AssertionError("direct broker placement must not be called")

        with self.assertRaises(PermissionError):
            place_limit_buy_ladder_orders(
                client=Client(),  # type: ignore[arg-type]
                orders=[],
                confirm_real_orders=True,
            )


if __name__ == "__main__":
    unittest.main()
