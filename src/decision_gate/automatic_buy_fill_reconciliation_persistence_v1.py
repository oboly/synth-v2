"""Issue #753 B5: persist one real automatic-BUY PAPER fill through #752.

Thin DB-facing wiring only. Loads prior facts/events via the existing,
unchanged #752 repositories, calls
``automatic_buy_fill_reconciliation_v1``'s pure reconciliation, and persists
the resulting fact (always) and inventory event (if any) via those same
repositories. Adds no new tables and no new reconciliation rule.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from typing import Any

from src.decision_gate.automatic_buy_fill_reconciliation_v1 import (
    AutomaticBuyFillPlanIdentityV1,
    reconcile_automatic_buy_paper_fill_v1,
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


def reconcile_and_persist_automatic_buy_paper_fill_v1(
    conn: Any,
    *,
    identity: AutomaticBuyFillPlanIdentityV1,
    evidence: BrokerCumulativeFillEvidenceV1,
) -> tuple[StrategyOwnedFillReconciliationFactV1, StrategyOwnedInventoryEventV1 | None]:
    """Reconcile and durably persist one automatic-BUY PAPER fill snapshot.

    Idempotent: replaying the exact same broker snapshot for the same order
    returns the already-persisted fact and writes nothing new, matching
    #752's own replay guarantee (``reconcile_cumulative_fill_v1`` returns the
    existing fact unchanged and no event for an exact snapshot replay).
    """
    prior_facts = load_strategy_owned_fill_reconciliation_facts_v1(
        conn, trading_account_id=identity.trading_account_id,
        venue=identity.venue, source_order_id=identity.source_order_id,
    )
    prior_events = load_strategy_owned_inventory_events_v1(
        conn, trading_account_id=identity.trading_account_id,
    )
    fact, event = reconcile_automatic_buy_paper_fill_v1(
        identity=identity, evidence=evidence,
        prior_facts=prior_facts, prior_inventory_events=prior_events,
    )
    if fact not in prior_facts:
        append_strategy_owned_fill_reconciliation_fact_v1(conn, fact=fact)
        if event is not None:
            append_strategy_owned_inventory_event_v1(conn, event=event)
    return fact, event
