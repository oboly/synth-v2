"""Focused #203 corrective-delta coverage for the manual SELL pipeline.

PR #361 wired canonical_rounding_v1.round_leg_for_side into
_build_ladder_legs, but still pre-quantized the allocated quantity to a
hardcoded 8dp before handing it to the canonical rounder, and left the
single-leg EXIT_PASSIVE_LIMIT path (_build_single_leg) entirely outside
venue-aware leg validation. This module covers the missing corrective
delta: raw intended quantities reach round_leg_for_side unrounded so the
actual venue qty_step_size owns quantity normalization, on both the ladder
and single-leg paths, while the constraint-free generic BUY preview keeps
its legacy 8dp display precision.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.execution_planner import canonical_rounding_v1
from src.execution_planner.contract_preview_v1 import (
    SLEEVE_PROFILES,
    ExecutionIntentPreview,
    ExecutionMarketContextPreview,
    _build_ladder_legs,
    _build_single_leg,
    build_execution_plan_preview,
    preview_to_dict,
)
from src.market_rules.venue_execution_constraints_v1 import (
    STATUS_FRESH,
    VenueExecutionConstraints,
)

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
_PROFILE = SLEEVE_PROFILES["CORE_STRUCTURAL"]


def _constraints(**overrides: object) -> VenueExecutionConstraints:
    values: dict[str, object] = {
        "venue": "bitvavo",
        "market": "BTC-EUR",
        "tick_size": Decimal("1"),
        "qty_step_size": Decimal("0.00000001"),
        "min_base_quantity": Decimal("0.0001"),
        "min_quote_notional": Decimal("5"),
        "supported_order_types": ("limit",),
        "supported_time_in_force": ("GTC",),
        "source_provenance": "TEST",
        "metadata_synced_ts_utc": NOW,
        "status": STATUS_FRESH,
    }
    values.update(overrides)
    return VenueExecutionConstraints(**values)  # type: ignore[arg-type]


def _context(**overrides: object) -> ExecutionMarketContextPreview:
    values: dict[str, object] = {
        "reference_price_eur": Decimal("50000"),
        "best_bid_eur": Decimal("49990"),
        "best_ask_eur": Decimal("50010"),
        "tick_size": Decimal("1"),
        "spread_bps": None,
        "volatility_bucket": None,
        "regime_label": None,
    }
    values.update(overrides)
    return ExecutionMarketContextPreview(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Raw values reach the canonical rounder unrounded (ladder path)
# ---------------------------------------------------------------------------


def test_non_8dp_venue_quantity_step_is_not_truncated_before_canonical_rounding() -> None:
    legs = _build_ladder_legs(
        side="SELL",
        levels=((Decimal("50000"), Decimal("1")),),
        max_notional_eur=None,
        quantity_base=Decimal("1.000000009"),
        tick_size=Decimal("1"),
        profile=_PROFILE,
        constraints=_constraints(qty_step_size=Decimal("0.000000001")),
    )
    assert legs[0].quantity_base == Decimal("1.000000009")


def test_ladder_raw_quantity_passed_once_to_canonical_rounder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.execution_planner.contract_preview_v1 as planner

    captured: list[tuple[Decimal, Decimal]] = []
    original = canonical_rounding_v1.round_leg_for_side

    def capture(**kwargs):
        captured.append((kwargs["raw_price"], kwargs["raw_quantity_base"]))
        return original(**kwargs)

    monkeypatch.setattr(planner, "round_leg_for_side", capture)
    planner._build_ladder_legs(
        side="SELL",
        levels=((Decimal("50000.4"), Decimal("1")),),
        max_notional_eur=None,
        quantity_base=Decimal("1.000000009"),
        tick_size=Decimal("1"),
        profile=_PROFILE,
        constraints=_constraints(qty_step_size=Decimal("0.000000001")),
    )
    assert captured == [(Decimal("50000.4"), Decimal("1.000000009"))]


def test_rounding_created_min_quantity_failure_is_rejected() -> None:
    # Raw quantity is above the minimum, but the venue step rounds it below.
    with pytest.raises(ValueError, match="BELOW_MIN_BASE_QUANTITY"):
        _build_ladder_legs(
            side="SELL",
            levels=((Decimal("50000"), Decimal("1")),),
            max_notional_eur=None,
            quantity_base=Decimal("0.00109"),
            tick_size=Decimal("1"),
            profile=_PROFILE,
            constraints=_constraints(
                qty_step_size=Decimal("0.001"),
                min_base_quantity=Decimal("0.00105"),
            ),
        )


def test_min_notional_fails_closed_after_rounding() -> None:
    with pytest.raises(ValueError, match="BELOW_MIN_QUOTE_NOTIONAL"):
        _build_ladder_legs(
            side="SELL",
            levels=((Decimal("1"), Decimal("1")),),
            max_notional_eur=None,
            quantity_base=Decimal("1"),
            tick_size=Decimal("1"),
            profile=_PROFILE,
            constraints=_constraints(min_quote_notional=Decimal("5")),
        )


def test_sell_ladder_rounding_never_goes_below_raw_target() -> None:
    legs = _build_ladder_legs(
        side="SELL",
        levels=((Decimal("50000.4"), Decimal("1")),),
        max_notional_eur=None,
        quantity_base=Decimal("2"),
        tick_size=Decimal("1"),
        profile=_PROFILE,
        constraints=_constraints(),
    )
    assert legs[0].target_price_eur == Decimal("50001")
    assert legs[0].target_price_eur >= Decimal("50000.4")


# ---------------------------------------------------------------------------
# Single-leg (EXIT_PASSIVE_LIMIT) canonicalization — the item #361 left out
# ---------------------------------------------------------------------------


def test_single_leg_sell_uses_raw_quantity_with_non_8dp_venue_step() -> None:
    leg = _build_single_leg(
        side="SELL",
        intent_type="EXIT_PASSIVE_LIMIT",
        target_fraction=Decimal("1"),
        max_notional_eur=None,
        quantity_base=Decimal("1.000000009"),
        context=_context(),
        profile=_PROFILE,
        constraints=_constraints(qty_step_size=Decimal("0.000000001")),
    )
    assert leg.quantity_base == Decimal("1.000000009")


def test_single_leg_sell_min_notional_fails_closed() -> None:
    with pytest.raises(ValueError, match="BELOW_MIN_QUOTE_NOTIONAL"):
        _build_single_leg(
            side="SELL",
            intent_type="EXIT_PASSIVE_LIMIT",
            target_fraction=Decimal("1"),
            max_notional_eur=None,
            quantity_base=Decimal("0.00001"),
            context=_context(),
            profile=_PROFILE,
            constraints=_constraints(min_quote_notional=Decimal("5")),
        )


def test_single_leg_sell_rounding_is_side_correct() -> None:
    leg = _build_single_leg(
        side="SELL",
        intent_type="EXIT_PASSIVE_LIMIT",
        target_fraction=Decimal("1"),
        max_notional_eur=None,
        quantity_base=Decimal("2"),
        context=_context(best_ask_eur=Decimal("50010.4")),
        profile=_PROFILE,
        constraints=_constraints(),
    )
    # best_ask - tick_size = 50009.4, SELL rounds UP to the next tick: 50010
    assert leg.target_price_eur == Decimal("50010")
    assert leg.target_price_eur >= Decimal("50009.4")


# ---------------------------------------------------------------------------
# Compatibility — generic constraint-free BUY preview keeps its legacy 8dp
# display precision; this is an independent API and must not be migrated.
# ---------------------------------------------------------------------------


def test_generic_buy_preview_keeps_legacy_serialized_quantity() -> None:
    intent = ExecutionIntentPreview(
        account_id=1,
        sleeve_code="CORE_STRUCTURAL",
        asset_id=42,
        symbol="BTC",
        venue="bitvavo",
        side="BUY",
        intent_type="PLACE_PASSIVE_LIMIT",
        max_notional_eur=Decimal("100"),
        quantity_base=None,
        decision_state="ALLOWED",
        decision_reason="TEST",
    )
    preview = build_execution_plan_preview(intent=intent, context=_context())
    leg = preview_to_dict(preview)["legs"][0]
    assert leg["target_price_eur"] == "49991"
    assert leg["quantity_base"] == "0.00200036"
    assert leg["target_notional_eur"] == "100.00000000"
