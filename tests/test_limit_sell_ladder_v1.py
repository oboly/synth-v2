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

    def test_build_limit_sell_ladder_orders_is_hard_blocked(self) -> None:
        with self.assertRaises(PermissionError):
            build_limit_sell_ladder_orders(
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
