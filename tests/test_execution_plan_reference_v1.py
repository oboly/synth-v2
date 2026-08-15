"""Tests for src/executor/execution_plan_reference_v1.py (Issue #206)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.executor.execution_plan_reference_v1 import (
    ApprovedExecutionPlanLegV1,
    ApprovedExecutionPlanV1,
    ApprovedExecutionPlanValidationError,
    compute_plan_content_hash,
)


def _plan(*, side: str = "SELL", plan_reference_id: str = "ref-1", legs=None) -> ApprovedExecutionPlanV1:
    if legs is None:
        legs = (
            ApprovedExecutionPlanLegV1(leg_index=1, side=side, price=Decimal("50000"), quantity=Decimal("0.1")),
            ApprovedExecutionPlanLegV1(leg_index=2, side=side, price=Decimal("51000"), quantity=Decimal("0.1")),
        )
    return ApprovedExecutionPlanV1(
        plan_source="AUTOMATIC_EXIT_PLAN_V1",
        plan_reference_id=plan_reference_id,
        trading_account_id=1,
        venue="bitvavo",
        market="BTC-EUR",
        side=side,
        legs=legs,
    )


class TestContentHashDeterminism:
    def test_same_content_same_hash(self) -> None:
        assert compute_plan_content_hash(_plan()) == compute_plan_content_hash(_plan())

    def test_leg_order_does_not_affect_hash(self) -> None:
        legs = (
            ApprovedExecutionPlanLegV1(leg_index=2, side="SELL", price=Decimal("51000"), quantity=Decimal("0.1")),
            ApprovedExecutionPlanLegV1(leg_index=1, side="SELL", price=Decimal("50000"), quantity=Decimal("0.1")),
        )
        assert compute_plan_content_hash(_plan(legs=legs)) == compute_plan_content_hash(_plan())

    def test_different_price_changes_hash(self) -> None:
        legs = (
            ApprovedExecutionPlanLegV1(leg_index=1, side="SELL", price=Decimal("999"), quantity=Decimal("0.1")),
            ApprovedExecutionPlanLegV1(leg_index=2, side="SELL", price=Decimal("51000"), quantity=Decimal("0.1")),
        )
        assert compute_plan_content_hash(_plan(legs=legs)) != compute_plan_content_hash(_plan())

    def test_buy_and_sell_plans_hash_differently(self) -> None:
        assert compute_plan_content_hash(_plan(side="BUY")) != compute_plan_content_hash(_plan(side="SELL"))

    def test_hash_is_64_char_hex(self) -> None:
        digest = compute_plan_content_hash(_plan())
        assert len(digest) == 64
        int(digest, 16)  # raises ValueError if not hex


class TestValidation:
    def test_empty_legs_rejected(self) -> None:
        plan = _plan(legs=())
        with pytest.raises(ApprovedExecutionPlanValidationError, match="PLAN_HAS_NO_LEGS"):
            compute_plan_content_hash(plan)

    def test_leg_side_mismatch_rejected(self) -> None:
        legs = (ApprovedExecutionPlanLegV1(leg_index=1, side="BUY", price=Decimal("1"), quantity=Decimal("1")),)
        plan = _plan(side="SELL", legs=legs)
        with pytest.raises(ApprovedExecutionPlanValidationError, match="LEG_SIDE_MISMATCH"):
            compute_plan_content_hash(plan)

    def test_duplicate_leg_index_rejected(self) -> None:
        legs = (
            ApprovedExecutionPlanLegV1(leg_index=1, side="SELL", price=Decimal("1"), quantity=Decimal("1")),
            ApprovedExecutionPlanLegV1(leg_index=1, side="SELL", price=Decimal("2"), quantity=Decimal("1")),
        )
        plan = _plan(legs=legs)
        with pytest.raises(ApprovedExecutionPlanValidationError, match="DUPLICATE_LEG_INDEX"):
            compute_plan_content_hash(plan)

    def test_nonpositive_price_rejected(self) -> None:
        legs = (ApprovedExecutionPlanLegV1(leg_index=1, side="SELL", price=Decimal("0"), quantity=Decimal("1")),)
        plan = _plan(legs=legs)
        with pytest.raises(ApprovedExecutionPlanValidationError, match="LEG_PRICE_NOT_POSITIVE"):
            compute_plan_content_hash(plan)

    def test_invalid_side_rejected(self) -> None:
        plan = _plan(side="HOLD", legs=(
            ApprovedExecutionPlanLegV1(leg_index=1, side="HOLD", price=Decimal("1"), quantity=Decimal("1")),
        ))
        with pytest.raises(ApprovedExecutionPlanValidationError, match="SIDE_INVALID"):
            compute_plan_content_hash(plan)
