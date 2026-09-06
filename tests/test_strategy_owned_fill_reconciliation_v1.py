from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.decision_gate.strategy_owned_fill_reconciliation_v1 import (
    BrokerCumulativeFillEvidenceV1,
    StrategyOwnedFillLineageV1,
    StrategyOwnedFillReconciliationError,
    reconcile_cumulative_fill_v1,
)
from src.decision_gate.strategy_owned_inventory_v1 import project_strategy_owned_inventory_v1
from src.decision_gate.strategy_owned_reduction_authorization_v1 import (
    StrategyOwnedReductionAuthorizationError,
    StrategyOwnedReductionRequestV1,
    authorize_strategy_owned_reduction_v1,
)

NOW = datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)


def _lineage(**changes):
    values = dict(
        trading_account_id=7, venue="bitvavo", market="SOL-EUR",
        strategy_bucket_id="AUTO_SHORTTF_FIB", strategy_id="fib",
        strategy_version="1", trade_id="trade-1",
        source_execution_plan_id="plan-1", source_order_id="order-1", side="BUY",
    )
    values.update(changes)
    return StrategyOwnedFillLineageV1(**values)


def _evidence(snapshot: str, cumulative: str):
    return BrokerCumulativeFillEvidenceV1(
        source_snapshot_id=snapshot,
        cumulative_filled_base_quantity=Decimal(cumulative),
        observed_ts_utc=NOW,
    )


def test_cumulative_fill_emits_only_positive_delta_and_replay_is_idempotent():
    fact1, event1 = reconcile_cumulative_fill_v1((), lineage=_lineage(), evidence=_evidence("snap-1", "2"))
    assert event1 is not None and event1.filled_base_quantity == Decimal("2")

    fact2, event2 = reconcile_cumulative_fill_v1((fact1,), lineage=_lineage(), evidence=_evidence("snap-2", "3.5"))
    assert event2 is not None and event2.filled_base_quantity == Decimal("1.5")

    replayed, replay_event = reconcile_cumulative_fill_v1((fact1, fact2), lineage=_lineage(), evidence=_evidence("snap-2", "3.5"))
    assert replayed == fact2
    assert replay_event is None

    positions = project_strategy_owned_inventory_v1((event1, event2))
    assert positions[0].owned_base_quantity == Decimal("3.5")


def test_unchanged_cumulative_snapshot_creates_fact_but_no_inventory_event():
    fact1, _ = reconcile_cumulative_fill_v1((), lineage=_lineage(), evidence=_evidence("snap-1", "2"))
    fact2, event2 = reconcile_cumulative_fill_v1((fact1,), lineage=_lineage(), evidence=_evidence("snap-2", "2"))
    assert fact2.attributed_delta_base_quantity == Decimal("0")
    assert event2 is None


def test_backwards_cumulative_fill_fails_closed():
    fact1, _ = reconcile_cumulative_fill_v1((), lineage=_lineage(), evidence=_evidence("snap-1", "2"))
    with pytest.raises(StrategyOwnedFillReconciliationError, match="CUMULATIVE_FILL_MOVED_BACKWARDS"):
        reconcile_cumulative_fill_v1((fact1,), lineage=_lineage(), evidence=_evidence("snap-2", "1"))


def test_same_order_cannot_be_rebound_to_another_strategy():
    fact1, _ = reconcile_cumulative_fill_v1((), lineage=_lineage(), evidence=_evidence("snap-1", "2"))
    with pytest.raises(StrategyOwnedFillReconciliationError, match="SOURCE_ORDER_LINEAGE_CONFLICT"):
        reconcile_cumulative_fill_v1(
            (fact1,), lineage=_lineage(strategy_bucket_id="LONG_TERM_MOONSHOT"),
            evidence=_evidence("snap-2", "3"),
        )


def test_scoped_reduction_cannot_consume_other_strategy_inventory():
    _, fib_event = reconcile_cumulative_fill_v1((), lineage=_lineage(), evidence=_evidence("snap-fib", "4"))
    _, long_event = reconcile_cumulative_fill_v1(
        (), lineage=_lineage(strategy_bucket_id="LONG_TERM_MOONSHOT", strategy_id="long", trade_id="trade-2", source_order_id="order-2"),
        evidence=_evidence("snap-long", "6"),
    )
    positions = project_strategy_owned_inventory_v1((fib_event, long_event))  # type: ignore[arg-type]
    auth = authorize_strategy_owned_reduction_v1(
        positions,
        request=StrategyOwnedReductionRequestV1(
            trading_account_id=7, venue="bitvavo", market="SOL-EUR",
            strategy_bucket_id="AUTO_SHORTTF_FIB", strategy_id="fib",
            strategy_version="1", trade_id="trade-1", requested_base_quantity=Decimal("4"),
        ),
    )
    assert auth.owned_base_quantity == Decimal("4")
    assert auth.remaining_after_reduction_base_quantity == Decimal("0")

    with pytest.raises(StrategyOwnedReductionAuthorizationError, match="REDUCTION_EXCEEDS_STRATEGY_OWNED_QUANTITY"):
        authorize_strategy_owned_reduction_v1(
            positions,
            request=StrategyOwnedReductionRequestV1(
                trading_account_id=7, venue="bitvavo", market="SOL-EUR",
                strategy_bucket_id="AUTO_SHORTTF_FIB", strategy_id="fib",
                strategy_version="1", trade_id="trade-1", requested_base_quantity=Decimal("5"),
            ),
        )
