"""Issue #753 B7.6: reconcile Fib-map-bound PAPER SELL fills into #752 ownership.

Pure decision_gate logic. Exact lineage comes from the already-approved Fib-map
bound exit plan/handoff. Wallet balances never imply ownership. Any emitted SELL
delta must first be authorized against the exact current #752-owned lineage.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.decision_gate.strategy_owned_fill_reconciliation_v1 import (
    BrokerCumulativeFillEvidenceV1,
    StrategyOwnedFillLineageV1,
    StrategyOwnedFillReconciliationFactV1,
    reconcile_cumulative_fill_v1,
)
from src.decision_gate.strategy_owned_inventory_v1 import (
    StrategyOwnedInventoryEventV1,
    project_strategy_owned_inventory_v1,
)
from src.decision_gate.strategy_owned_reduction_authorization_v1 import (
    StrategyOwnedReductionRequestV1,
    authorize_strategy_owned_reduction_v1,
)

SIDE_SELL = "SELL"


class FibMapBoundExitFillReconciliationError(ValueError):
    pass


@dataclass(frozen=True)
class FibMapBoundExitFillPlanIdentityV1:
    trading_account_id: int
    venue: str
    market: str
    strategy_bucket_id: str
    strategy_id: str
    strategy_version: str
    trade_id: str
    source_execution_plan_id: str
    source_order_id: str


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_identity(identity: FibMapBoundExitFillPlanIdentityV1) -> None:
    if isinstance(identity.trading_account_id, bool) or identity.trading_account_id <= 0:
        raise FibMapBoundExitFillReconciliationError("INVALID_TRADING_ACCOUNT_ID")
    for value in (
        identity.venue,
        identity.market,
        identity.strategy_bucket_id,
        identity.strategy_id,
        identity.strategy_version,
        identity.trade_id,
        identity.source_execution_plan_id,
        identity.source_order_id,
    ):
        if not _nonempty(value):
            raise FibMapBoundExitFillReconciliationError("INVALID_FIB_EXIT_FILL_IDENTITY")


def reconcile_fib_map_bound_exit_paper_fill_v1(
    *,
    identity: FibMapBoundExitFillPlanIdentityV1,
    evidence: BrokerCumulativeFillEvidenceV1,
    prior_facts: Iterable[StrategyOwnedFillReconciliationFactV1],
    prior_inventory_events: Iterable[StrategyOwnedInventoryEventV1],
) -> tuple[StrategyOwnedFillReconciliationFactV1, StrategyOwnedInventoryEventV1 | None]:
    """Reconcile one cumulative PAPER SELL fill snapshot, replay-safely.

    The generic #752 cumulative reconciler determines only the newly-attributed
    delta. Before returning an emitted SELL event, decision_gate authorizes that
    exact delta against the current exact-lineage owned quantity. No wallet or
    broker balance participates.
    """
    _validate_identity(identity)
    facts = tuple(prior_facts)
    inventory_events = tuple(prior_inventory_events)
    lineage = StrategyOwnedFillLineageV1(
        trading_account_id=identity.trading_account_id,
        venue=identity.venue,
        market=identity.market,
        strategy_bucket_id=identity.strategy_bucket_id,
        strategy_id=identity.strategy_id,
        strategy_version=identity.strategy_version,
        trade_id=identity.trade_id,
        source_execution_plan_id=identity.source_execution_plan_id,
        source_order_id=identity.source_order_id,
        side=SIDE_SELL,
    )
    fact, event = reconcile_cumulative_fill_v1(facts, lineage=lineage, evidence=evidence)
    if event is None:
        return fact, None

    positions = project_strategy_owned_inventory_v1(inventory_events)
    authorize_strategy_owned_reduction_v1(
        positions,
        request=StrategyOwnedReductionRequestV1(
            trading_account_id=identity.trading_account_id,
            venue=identity.venue,
            market=identity.market,
            strategy_bucket_id=identity.strategy_bucket_id,
            strategy_id=identity.strategy_id,
            strategy_version=identity.strategy_version,
            trade_id=identity.trade_id,
            requested_base_quantity=event.filled_base_quantity,
        ),
    )
    return fact, event
