"""Focused #203 coverage for the authoritative manual ladder pipeline."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.execution_planner.contract_preview_v1 import SLEEVE_PROFILES, _build_ladder_legs
from src.market_rules.venue_execution_constraints_v1 import STATUS_FRESH, VenueExecutionConstraints


def _constraints(**overrides: object) -> VenueExecutionConstraints:
    values: dict[str, object] = {
        "venue": "bitvavo", "market": "BTC-EUR", "tick_size": Decimal("1"),
        "qty_step_size": Decimal("0.1"), "min_base_quantity": Decimal("0.1"),
        "min_quote_notional": Decimal("5"), "supported_order_types": ("limit",),
        "supported_time_in_force": ("GTC",), "source_provenance": "TEST",
        "metadata_synced_ts_utc": datetime.now(timezone.utc), "status": STATUS_FRESH,
    }
    values.update(overrides)
    return VenueExecutionConstraints(**values)  # type: ignore[arg-type]


def _build(*, side: str = "SELL", levels=((Decimal("100"), Decimal("1")),), quantity=Decimal("1"), constraints=None):
    return _build_ladder_legs(
        side=side, levels=levels, max_notional_eur=None, quantity_base=quantity,
        tick_size=Decimal("1"), profile=SLEEVE_PROFILES["CORE_STRUCTURAL"],
        constraints=constraints or _constraints(),
    )


def test_sell_target_rounds_up_and_buy_reentry_rounds_down() -> None:
    assert _build(levels=((Decimal("100.1"), Decimal("1")),))[0].target_price_eur == Decimal("101")
    assert _build(side="BUY", levels=((Decimal("100.9"), Decimal("1")),))[0].target_price_eur == Decimal("100")


def test_quantity_rounding_leaves_residual_dust_unallocated() -> None:
    legs = _build(
        levels=((Decimal("100"), Decimal("0.5")), (Decimal("101"), Decimal("0.5"))),
        quantity=Decimal("1.05"),
    )
    assert [leg.quantity_base for leg in legs] == [Decimal("0.5"), Decimal("0.5")]
    assert sum(leg.quantity_base for leg in legs) == Decimal("1.0")
    assert sum(leg.quantity_base for leg in legs) <= Decimal("1.05")


def test_minimum_quantity_and_notional_fail_closed_after_rounding() -> None:
    with pytest.raises(ValueError, match="LADDER_LEG_1_INVALID:BELOW_MIN_BASE_QUANTITY"):
        _build(quantity=Decimal("0.11"), constraints=_constraints(min_base_quantity=Decimal("0.2")))
    with pytest.raises(ValueError, match="LADDER_LEG_1_INVALID:BELOW_MIN_QUOTE_NOTIONAL"):
        _build(quantity=Decimal("0.1"), constraints=_constraints(min_quote_notional=Decimal("11")))
    with pytest.raises(ValueError, match="LADDER_LEG_1_INVALID:BELOW_MIN_BASE_QUANTITY"):
        _build(quantity=Decimal("0.19"), constraints=_constraints(min_base_quantity=Decimal("0.15")))


def test_minimum_boundaries_pass_using_rounded_leg_values() -> None:
    leg = _build(quantity=Decimal("0.1"), constraints=_constraints(min_quote_notional=Decimal("10")))[0]
    assert leg.quantity_base == Decimal("0.1")
    assert leg.target_notional_eur == Decimal("10.0")


def test_active_manual_caller_uses_contract_preview_not_legacy_ladders() -> None:
    service = Path("src/manual_execution/manual_execution_service_v1.py").read_text(encoding="utf-8")
    assert "build_manual_sell_execution_plan_preview" in service
    assert "from src.execution_ladder" not in service
    assert "from src.execution.limit_sell_ladder" not in service
