"""
Tests for src/execution_planner/canonical_rounding_v1.py, plus repository-
wide regression tests proving no SELL price-rounding path still uses the
incorrect unconditional ROUND_DOWN behavior identified in
docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md
finding F3.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.execution_planner.canonical_rounding_v1 import (
    REJECTION_BELOW_MIN_BASE_QUANTITY,
    REJECTION_BELOW_MIN_QUOTE_NOTIONAL,
    REJECTION_VENUE_CONSTRAINTS_NOT_USABLE,
    round_leg_for_side,
    round_price_for_side,
    round_quantity_down,
)
from src.market_rules.venue_execution_constraints_v1 import (
    STATUS_FRESH,
    STATUS_MISSING,
    VenueExecutionConstraints,
)


def _constraints(**overrides) -> VenueExecutionConstraints:
    defaults = dict(
        venue="bitvavo",
        market="BTC-EUR",
        tick_size=Decimal("0.01"),
        qty_step_size=Decimal("0.00000001"),
        min_base_quantity=Decimal("0.0001"),
        min_quote_notional=Decimal("5.00"),
        supported_order_types=("limit",),
        supported_time_in_force=("GTC",),
        source_provenance="BITVAVO_PUBLIC_MARKETS_API_V2",
        metadata_synced_ts_utc=datetime.now(timezone.utc),
        status=STATUS_FRESH,
    )
    defaults.update(overrides)
    return VenueExecutionConstraints(**defaults)


class TestSideAwarePriceRounding:
    def test_sell_rounds_up(self) -> None:
        assert round_price_for_side(Decimal("100.111"), Decimal("0.01"), "SELL") == Decimal("100.12")

    def test_buy_rounds_down(self) -> None:
        assert round_price_for_side(Decimal("100.119"), Decimal("0.01"), "BUY") == Decimal("100.11")

    def test_sell_never_rounds_below_raw_price(self) -> None:
        for raw in (Decimal("0.4522122"), Decimal("1.23456"), Decimal("99999.001")):
            rounded = round_price_for_side(raw, Decimal("0.001"), "SELL")
            assert rounded >= raw

    def test_buy_never_rounds_above_raw_price(self) -> None:
        for raw in (Decimal("0.4522122"), Decimal("1.23456"), Decimal("99999.999")):
            rounded = round_price_for_side(raw, Decimal("0.001"), "BUY")
            assert rounded <= raw

    def test_exact_tick_boundary_unchanged_either_side(self) -> None:
        assert round_price_for_side(Decimal("100.00"), Decimal("0.01"), "SELL") == Decimal("100.00")
        assert round_price_for_side(Decimal("100.00"), Decimal("0.01"), "BUY") == Decimal("100.00")

    def test_invalid_side_rejected(self) -> None:
        with pytest.raises(ValueError):
            round_price_for_side(Decimal("1"), Decimal("0.01"), "HOLD")


class TestQuantityRoundingNeverExceedsApproved:
    def test_quantity_always_rounds_down_regardless_of_side(self) -> None:
        approved = Decimal("1.23456789")
        rounded = round_quantity_down(approved, Decimal("0.00000001"))
        assert rounded <= approved

    def test_quantity_rounding_is_not_side_parameterized(self) -> None:
        # round_quantity_down takes no side argument at all — quantity
        # rounding direction must never depend on side.
        import inspect
        sig = inspect.signature(round_quantity_down)
        assert "side" not in sig.parameters


class TestMinimumChecksRunAfterRounding:
    def test_leg_below_min_base_quantity_after_rounding_is_rejected(self) -> None:
        constraints = _constraints(min_base_quantity=Decimal("1.0"))
        result = round_leg_for_side(
            side="SELL", raw_price=Decimal("100"), raw_quantity_base=Decimal("0.5"),
            constraints=constraints,
        )
        assert not result.is_valid
        assert REJECTION_BELOW_MIN_BASE_QUANTITY in result.rejection_reasons

    def test_leg_below_min_notional_after_rounding_is_rejected(self) -> None:
        constraints = _constraints(min_quote_notional=Decimal("1000"))
        result = round_leg_for_side(
            side="SELL", raw_price=Decimal("100"), raw_quantity_base=Decimal("0.5"),
            constraints=constraints,
        )
        assert not result.is_valid
        assert REJECTION_BELOW_MIN_QUOTE_NOTIONAL in result.rejection_reasons

    def test_valid_leg_passes_when_above_both_minimums(self) -> None:
        constraints = _constraints(min_base_quantity=Decimal("0.001"), min_quote_notional=Decimal("5"))
        result = round_leg_for_side(
            side="SELL", raw_price=Decimal("100"), raw_quantity_base=Decimal("1"),
            constraints=constraints,
        )
        assert result.is_valid
        assert result.rejection_reasons == ()

    def test_stale_or_missing_constraints_always_invalid(self) -> None:
        missing = _constraints(status=STATUS_MISSING, tick_size=Decimal("0"), qty_step_size=Decimal("0"))
        result = round_leg_for_side(
            side="SELL", raw_price=Decimal("100"), raw_quantity_base=Decimal("1"),
            constraints=missing,
        )
        assert not result.is_valid
        assert REJECTION_VENUE_CONSTRAINTS_NOT_USABLE in result.rejection_reasons


class TestNoSellPathStillUsesIncorrectRoundDown:
    """Static regression proving the three ladder-building call sites named
    in audit finding F3 delegate to the canonical rounding service rather
    than re-implementing an unconditional ROUND_DOWN quantizer."""

    _REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
    _FILES_THAT_MUST_NOT_LOCALLY_ROUND_DOWN_PRICES = (
        "src/execution_planner/contract_preview_v1.py",
        "src/execution/limit_sell_ladder_v1.py",
    )

    def test_named_files_import_canonical_rounding_service(self) -> None:
        for rel_path in self._FILES_THAT_MUST_NOT_LOCALLY_ROUND_DOWN_PRICES:
            text = (self._REPO_ROOT / rel_path).read_text()
            assert "canonical_rounding_v1" in text, (
                f"{rel_path} must delegate price rounding to "
                "src.execution_planner.canonical_rounding_v1"
            )

    def test_named_files_contain_no_local_round_down_quantizer_for_price(self) -> None:
        # A local `to_integral_value(rounding=ROUND_DOWN)` used to compute a
        # tick-quantized *price* is exactly the F3 bug. Detect any remaining
        # unconditional ROUND_DOWN quantize call sites in these two files by
        # walking the AST rather than grepping, so this survives reformatting.
        for rel_path in self._FILES_THAT_MUST_NOT_LOCALLY_ROUND_DOWN_PRICES:
            tree = ast.parse((self._REPO_ROOT / rel_path).read_text())
            offending = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == "to_integral_value":
                        for kw in node.keywords:
                            if kw.arg == "rounding" and isinstance(kw.value, ast.Name):
                                if kw.value.id == "ROUND_DOWN":
                                    offending.append(node.lineno)
            assert offending == [], (
                f"{rel_path} still calls to_integral_value(rounding=ROUND_DOWN) "
                f"directly at line(s) {offending}; price rounding must go "
                "through canonical_rounding_v1.round_price_for_side"
            )

    def test_execution_ladder_resolver_offers_a_rounded_preview_path(self) -> None:
        text = (self._REPO_ROOT / "src/execution_ladder/resolver.py").read_text()
        assert "canonical_rounding_v1" in text
        assert "round_ladder_preview" in text
