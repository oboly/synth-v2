"""Issue #753 B7.6: atomic persistence seam for Fib-map-bound PAPER SELL fills.

A SELL reduction is account-aware state mutation. This seam serializes the
exact strategy/trade lineage by locking its existing #752 inventory rows, then
performs authorization, reconciliation-fact append and optional inventory-event
append in one caller connection transaction. Any exception rolls the whole
mutation back before the lock is released.
"""
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


class FibMapBoundExitFillPersistenceError(RuntimeError):
    pass


def _lock_exact_inventory_lineage_v1(
    conn: Any,
    *,
    identity: FibMapBoundExitFillPlanIdentityV1,
) -> None:
    """Take the InnoDB row lock that serializes one exact owned lineage.

    A valid SELL can only reduce a lineage that already contains a BUY event,
    so an empty result is a fail-closed persistence error rather than a reason
    to invent a separate lock identity/table. ``FOR UPDATE`` holds until this
    seam commits or rolls back.
    """
    sql = """
    SELECT strategy_owned_inventory_event_id
    FROM strategy_owned_inventory_event_v1
    WHERE trading_account_id = %s
      AND venue = %s
      AND market = %s
      AND strategy_bucket_id = %s
      AND strategy_id = %s
      AND strategy_version = %s
      AND trade_id = %s
    ORDER BY strategy_owned_inventory_event_id
    FOR UPDATE
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                identity.trading_account_id,
                identity.venue,
                identity.market,
                identity.strategy_bucket_id,
                identity.strategy_id,
                identity.strategy_version,
                identity.trade_id,
            ),
        )
        rows = cur.fetchall()
    if not rows:
        raise FibMapBoundExitFillPersistenceError("STRATEGY_OWNED_LINEAGE_NOT_LOCKABLE")


def reconcile_and_persist_fib_map_bound_exit_paper_fill_v1(
    conn: Any,
    *,
    identity: FibMapBoundExitFillPlanIdentityV1,
    evidence: BrokerCumulativeFillEvidenceV1,
) -> tuple[StrategyOwnedFillReconciliationFactV1, StrategyOwnedInventoryEventV1 | None]:
    """Atomically reconcile/persist one PAPER SELL cumulative-fill snapshot.

    Transaction ownership is deliberate here: authorization and both append-only
    writes form one indivisible account-aware reduction. The exact-lineage
    ``FOR UPDATE`` prevents two concurrent exits from authorizing against the
    same pre-reduction quantity. Exact snapshot replay remains idempotent.
    """
    try:
        _lock_exact_inventory_lineage_v1(conn, identity=identity)
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
        conn.commit()
        return fact, event
    except Exception:
        conn.rollback()
        raise
