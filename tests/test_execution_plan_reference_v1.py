from decimal import Decimal

import pytest

from src.executor.execution_plan_reference_v1 import ApprovedExecutionPlanV1, ExecutionPlanLegV1

def _plan() -> ApprovedExecutionPlanV1:
    return ApprovedExecutionPlanV1("planner", "ref-1", 7, "venue", "BTC-EUR", "BUY", (ExecutionPlanLegV1(1, "BUY", Decimal("1.20"), Decimal("2.00")),))

def test_hash_is_stable_and_covers_identity() -> None:
    assert _plan().content_hash == _plan().content_hash
    assert _plan().canonical_payload()["contract_version"] == "execution_plan_reference_v1"
    assert _plan().canonical_payload()["legs"][0]["leg_index"] == 1


@pytest.mark.parametrize(
    "changed_plan",
    [
        ApprovedExecutionPlanV1("planner", "ref-1", 8, "venue", "BTC-EUR", "BUY", (ExecutionPlanLegV1(1, "BUY", Decimal("1.20"), Decimal("2.00")),)),
        ApprovedExecutionPlanV1("planner", "ref-1", 7, "other", "BTC-EUR", "BUY", (ExecutionPlanLegV1(1, "BUY", Decimal("1.20"), Decimal("2.00")),)),
        ApprovedExecutionPlanV1("planner", "ref-1", 7, "venue", "ETH-EUR", "BUY", (ExecutionPlanLegV1(1, "BUY", Decimal("1.20"), Decimal("2.00")),)),
        ApprovedExecutionPlanV1("planner", "ref-1", 7, "venue", "BTC-EUR", "SELL", (ExecutionPlanLegV1(1, "SELL", Decimal("1.20"), Decimal("2.00")),)),
        ApprovedExecutionPlanV1("planner", "ref-1", 7, "venue", "BTC-EUR", "BUY", (ExecutionPlanLegV1(1, "BUY", Decimal("1.21"), Decimal("2.00")),)),
        ApprovedExecutionPlanV1("planner", "ref-1", 7, "venue", "BTC-EUR", "BUY", (ExecutionPlanLegV1(1, "BUY", Decimal("1.20"), Decimal("2.01")),)),
    ],
)
def test_account_venue_market_side_price_and_quantity_change_hash(
    changed_plan: ApprovedExecutionPlanV1,
) -> None:
    assert changed_plan.content_hash != _plan().content_hash


def test_decimal_scale_does_not_change_plan_hash() -> None:
    equivalent = ApprovedExecutionPlanV1(
        "planner",
        "ref-1",
        7,
        "VENUE",
        "btc-eur",
        "BUY",
        (ExecutionPlanLegV1(1, "BUY", Decimal("1.2000"), Decimal("2")),),
    )
    assert equivalent.content_hash == _plan().content_hash


def test_plan_normalizes_venue_market_and_decimal_text() -> None:
    plan = ApprovedExecutionPlanV1(" planner ", " ref ", 7, " Venue ", "btc-eur", "BUY", (ExecutionPlanLegV1(1, "BUY", Decimal("0.0001000"), Decimal("2.00")),))
    assert plan.plan_source == "planner"
    assert plan.plan_reference_id == "ref"
    assert plan.venue == "venue"
    assert plan.market == "BTC-EUR"
    assert plan.canonical_payload()["legs"][0]["price"] == "0.0001"

def test_rejects_float_and_unordered_legs() -> None:
    with pytest.raises(ValueError):
        ExecutionPlanLegV1(1, "BUY", 1.0, Decimal("1"))
    with pytest.raises(ValueError):
        ApprovedExecutionPlanV1(
            "p",
            "r",
            1,
            "v",
            "m",
            "BUY",
            (
                ExecutionPlanLegV1(2, "BUY", Decimal("1"), Decimal("1")),
                ExecutionPlanLegV1(1, "BUY", Decimal("1"), Decimal("1")),
            ),
        )
