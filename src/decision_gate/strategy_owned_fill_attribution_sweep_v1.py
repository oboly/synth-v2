"""Issue #756 Codex block: decision_gate-owned authoritative fill-attribution
sweep over the shared #206 executor substrate.

Architecture note (superseding an earlier draft of this fix): the executor
layer must never import decision_gate's sleeve/ledger modules (enforced by
``tests/test_strategy_capital_sleeves_architecture_guards_v1.py``'s existing
``test_executor_does_not_import_sleeve_capacity_or_ledger_modules`` guard --
"executor must not compute sleeve/allocation policy"). Attribution is
therefore owned entirely from the decision_gate side, exactly like
``strategy_bucket_buy_reservation_v1``'s bucket-scoped reservation read
model: this module reads ``executor_execution_leg``/``executor_execution_handoff``
by raw SQL only (no import of ``src.executor``), never writes to them, and
appends to decision_gate's own ``strategy_owned_inventory_ledger_v1`` table
through the existing repository. No second reconciliation truth: quantity/
price/state stay owned entirely by ``executor_execution_leg``; this only
derives an attribution fact from those already-persisted, already-canonical
values.

The narrowest accepted fill-confirmation seam this reads is a leg's
``state = 'FILLED'`` -- the shared executor state machine's single terminal
fill acknowledgement, reached identically whether the leg got there via a
direct submission ack or a reconciliation replay. ``PARTIALLY_FILLED`` is
never attributed: the executor's leg state machine does not track an actual
partial-fill quantity (``leg.quantity`` is always the original planned
amount), so attributing only at the final ``FILLED`` transition using the
leg's full planned quantity/price is the correct and only available V1
behavior given the executor's current fill-tracking granularity.

A handoff with no strategy lineage (``strategy_bucket_id IS NULL`` --
manual execution, or any non-automatic-buy plan source) is excluded by the
query itself and therefore never attributed.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Final, NamedTuple

from src.decision_gate.strategy_owned_inventory_ledger_repository_v1 import (
    StrategyOwnedInventoryLedgerConflictError,
    record_strategy_owned_fill_event_v1,
)
from src.decision_gate.strategy_owned_inventory_ledger_v1 import (
    StrategyOwnedFillEventV1,
    StrategyOwnershipLineageV1,
    validate_fill_event_v1,
)

SOURCE_PROVENANCE: Final[str] = "strategy_owned_fill_attribution_sweep_v1"


class StrategyOwnedFillAttributionSweepError(RuntimeError):
    """Fail-closed sweep error. ``args[0]`` is the reason code."""


class AttributionSweepResultV1(NamedTuple):
    candidates_seen: int
    newly_attributed: int
    already_attributed: int


def _aware(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise StrategyOwnedFillAttributionSweepError("FILLED_LEG_MISSING_UPDATED_TS_UTC")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def run_strategy_owned_fill_attribution_sweep_v1(conn: Any) -> AttributionSweepResultV1:
    """Attribute every canonical automatic-buy ``FILLED`` leg not yet
    recorded in the strategy-owned inventory ledger, across every account.

    Idempotent and safe to run repeatedly/concurrently: appending is
    deduplicated by canonical ``order_identity`` (the leg's own
    ``client_order_id``) inside ``record_strategy_owned_fill_event_v1``. A
    conflicting duplicate (same order_identity, different recorded fields --
    a data-integrity condition, never expected in practice since a leg's
    identity fields are immutable once persisted) fails the whole sweep
    closed rather than silently skipping it.
    """
    sql = """
    SELECT
        leg.trading_account_id AS trading_account_id, leg.venue AS venue, leg.market AS market,
        leg.client_order_id AS client_order_id, leg.side AS side, leg.price AS price,
        leg.quantity AS quantity, leg.updated_ts_utc AS updated_ts_utc,
        handoff.plan_reference_id AS plan_reference_id, handoff.strategy_bucket_id AS strategy_bucket_id,
        handoff.strategy_id AS strategy_id, handoff.strategy_version AS strategy_version,
        handoff.setup_id AS setup_id
    FROM executor_execution_leg leg
    JOIN executor_execution_handoff handoff
      ON handoff.executor_execution_handoff_id = leg.executor_execution_handoff_id
    WHERE leg.state = 'FILLED'
      AND handoff.strategy_bucket_id IS NOT NULL
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = [dict(row) for row in cur.fetchall()]

    newly_attributed = 0
    already_attributed = 0
    for row in rows:
        lineage = StrategyOwnershipLineageV1(
            trading_account_id=int(row["trading_account_id"]),
            venue=str(row["venue"]),
            market=str(row["market"]),
            strategy_bucket_id=str(row["strategy_bucket_id"]),
            strategy_id=str(row["strategy_id"]),
            strategy_version=str(row["strategy_version"]),
            setup_id=str(row["setup_id"]),
        )
        event = StrategyOwnedFillEventV1(
            lineage=lineage,
            order_identity=str(row["client_order_id"]),
            execution_plan_reference_id=str(row["plan_reference_id"]),
            side=str(row["side"]),
            base_quantity=Decimal(str(row["quantity"])),
            quote_notional=Decimal(str(row["price"])) * Decimal(str(row["quantity"])),
            occurred_ts_utc=_aware(row["updated_ts_utc"]),
            source_provenance=SOURCE_PROVENANCE,
        )
        validate_fill_event_v1(event)
        try:
            inserted = record_strategy_owned_fill_event_v1(conn, event=event)
        except StrategyOwnedInventoryLedgerConflictError as exc:
            raise StrategyOwnedFillAttributionSweepError(str(exc)) from exc
        if inserted:
            newly_attributed += 1
        else:
            already_attributed += 1
    return AttributionSweepResultV1(
        candidates_seen=len(rows), newly_attributed=newly_attributed, already_attributed=already_attributed,
    )
