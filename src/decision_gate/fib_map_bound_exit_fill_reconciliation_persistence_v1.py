"""Issue #753 B7.6: persistence seam for Fib-map-bound PAPER SELL fills."""
from __future__ import annotations

from typing import Any

from src.decision_gate.fib_map_bound_exit_fill_reconciliation_v1 import (
    FibMapBoundExitFillPlanIdentityV1,
    reconcile_fib_map_bound_exit_paper_fill_v1,
)
from src.decision_gate.strategy_owned_fill_reconciliation_repository_v1 import (
    append_strategy_owned_fill_reconciliation_fact_v1,
    load_strategy_owned_fill_reconciliation_facts_v1,
)
from src.decision_gate.strategy_owned_fill_reconciliation_v1 import (
    BrokerCumulativeFillEvidenceV1,
    StrategyOwnedFillReconciliationFactV1,
)
from src.decision_gate.strategy_owned_inventory_repository_v1 import (
    append_strategy_owned_inventory_event_v1,
    load_strategy_owned_inventory_events_v1,
)
from src.decision_gate.strategy_owned_inventory_v1 import StrategyOwnedInventoryEventV1


def reconcile_and_persist_fib_map_bound_exit_paper_fill_v1(
    conn: Any,
    *,
    identity: FibMapBoundExitFillPlanIdentityV1,
    evidence: BrokerCumulativeFillEvidenceV1,
) -> tuple[StrategyOwnedFillReconciliationFactV1, StrategyOwnedInventoryEventV1 | None]:
    prior_facts = load_strategy_owned_fill_reconciliation_facts_v1(
        conn,
        trading_account_id=identity.trading_account_id,
        venue=identity.venue,
        source_order_id=identity.source_order_id,
    )
    prior_events = load_strategy_owned_inventory_events_v1(
        conn,
        trading_account_id=identity.trading_account_id,
    )
    fact, event = reconcile_fib_map_bound_exit_paper_fill_v1(
        identity=identity,
        evidence=evidence,
        prior_facts=prior_facts,
        prior_inventory_events=prior_events,
    )
    if fact not in prior_facts:
        append_strategy_owned_fill_reconciliation_fact_v1(conn, fact=fact)
        if event is not None:
            append_strategy_owned_inventory_event_v1(conn, event=event)
    return fact, event
