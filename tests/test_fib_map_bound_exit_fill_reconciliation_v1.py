from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from src.decision_gate.fib_map_bound_exit_fill_reconciliation_v1 import (
    FibMapBoundExitFillPlanIdentityV1,
    reconcile_fib_map_bound_exit_paper_fill_v1,
)
from src.decision_gate.strategy_owned_fill_reconciliation_v1 import BrokerCumulativeFillEvidenceV1
from src.decision_gate.strategy_owned_inventory_v1 import StrategyOwnedInventoryEventV1
from src.decision_gate.strategy_owned_reduction_authorization_v1 import StrategyOwnedReductionAuthorizationError
from tests.test_automatic_buy_paper_fill_execution_v1 import NOW


def _buy(*, qty: Decimal = Decimal("9"), bucket: str = "AUTO_SHORTTF_FIB") -> StrategyOwnedInventoryEventV1:
    return StrategyOwnedInventoryEventV1(
        event_id="buy-event-1",
        trading_account_id=1,
        venue="bitvavo",
        market="SOL-EUR",
        strategy_bucket_id=bucket,
        strategy_id="shorttf_fib",
        strategy_version="1",
        trade_id="trade-1",
        source_execution_plan_id="buy-plan-1",
        source_fill_id="buy-fill-1",
        side="BUY",
        filled_base_quantity=qty,
        fill_notional_eur=None,
        occurred_ts_utc=NOW - timedelta(minutes=10),
    )


def _identity(**overrides: object) -> FibMapBoundExitFillPlanIdentityV1:
    values: dict[str, object] = dict(
        trading_account_id=1,
        venue="bitvavo",
        market="SOL-EUR",
        strategy_bucket_id="AUTO_SHORTTF_FIB",
        strategy_id="shorttf_fib",
        strategy_version="1",
        trade_id="trade-1",
        source_execution_plan_id="exit-plan-1",
        source_order_id="paper-order-1",
    )
    values.update(overrides)
    return FibMapBoundExitFillPlanIdentityV1(**values)  # type: ignore[arg-type]


def _evidence(qty: Decimal = Decimal("3")) -> BrokerCumulativeFillEvidenceV1:
    return BrokerCumulativeFillEvidenceV1(
        source_snapshot_id="sell-snapshot-1",
        cumulative_filled_base_quantity=qty,
        observed_ts_utc=NOW,
    )


def test_sell_delta_is_authorized_against_exact_owned_lineage() -> None:
    fact, event = reconcile_fib_map_bound_exit_paper_fill_v1(
        identity=_identity(),
        evidence=_evidence(),
        prior_facts=(),
        prior_inventory_events=(_buy(),),
    )
    assert fact.side == "SELL"
    assert fact.attributed_delta_base_quantity == Decimal("3")
    assert event is not None
    assert event.side == "SELL"
    assert event.filled_base_quantity == Decimal("3")
    assert event.trade_id == "trade-1"


def test_replay_same_snapshot_is_idempotent_without_second_reduction() -> None:
    fact, event = reconcile_fib_map_bound_exit_paper_fill_v1(
        identity=_identity(),
        evidence=_evidence(),
        prior_facts=(),
        prior_inventory_events=(_buy(),),
    )
    assert event is not None
    replay_fact, replay_event = reconcile_fib_map_bound_exit_paper_fill_v1(
        identity=_identity(),
        evidence=_evidence(),
        prior_facts=(fact,),
        prior_inventory_events=(_buy(), event),
    )
    assert replay_fact == fact
    assert replay_event is None


def test_over_reduction_fails_closed_before_event_is_returned() -> None:
    with pytest.raises(StrategyOwnedReductionAuthorizationError, match="REDUCTION_EXCEEDS"):
        reconcile_fib_map_bound_exit_paper_fill_v1(
            identity=_identity(),
            evidence=_evidence(Decimal("3")),
            prior_facts=(),
            prior_inventory_events=(_buy(qty=Decimal("2")),),
        )


def test_wrong_bucket_cannot_reduce_other_bucket_inventory() -> None:
    with pytest.raises(StrategyOwnedReductionAuthorizationError, match="UNRESOLVED"):
        reconcile_fib_map_bound_exit_paper_fill_v1(
            identity=_identity(strategy_bucket_id="OTHER_BUCKET"),
            evidence=_evidence(),
            prior_facts=(),
            prior_inventory_events=(_buy(),),
        )
