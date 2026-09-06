"""Issue #753 B5: bind a real automatic-BUY fill's lineage into #752 reconciliation.

Resolves the RE_ENTER lineage-continuity decision Phase B4 explicitly deferred
(see docs/architecture/automatic_buy_trade_lineage_identity_v1.md, "Explicitly
deferred: RE_ENTER lineage continuity") using #752's own replay-safe inventory
projection, then reconciles the fill through #752's existing, unchanged
``reconcile_cumulative_fill_v1``. This module never fabricates identity: every
field it emits is either copied verbatim from the caller-supplied automatic-BUY
plan/handoff identity (trading_account_id, venue, market, strategy_bucket_id,
strategy_id, strategy_version -- exactly the lineage bridged by #770) or
resolved from #752's own reviewed inventory projection. It never infers
ownership from wallet balance.

What this module does NOT do -- see
docs/status/issue_753_paper_acceptance_blocker_v1.md: it does not produce
``BrokerCumulativeFillEvidenceV1`` itself. No PAPER order-placement adapter
exists yet anywhere in the shared executor handoff path that automatic-BUY
plans flow through (``src/executor/shared_execution_runtime_v1.py`` explicitly
raises ``PAPER_ADAPTER_NOT_CONFIGURED`` for PAPER mode, a reviewed, tested
guard -- see ``tests/test_shared_execution_runtime_v1.py``). There is
therefore currently no reviewed source of a real automatic-BUY PAPER fill's
cumulative quantity to call this module with. Building a synthetic PAPER fill
producer is a separate, unresolved architectural decision (what a "truthful"
PAPER fill simulation means: fill at plan price on ack? read latest market
price like the legacy per-plan paper executor? partial fills over time?) that
this module does not fabricate.

broker_private_calls=0
broker_writes=0
order_submission=0
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

SIDE_BUY = "BUY"


class AutomaticBuyFillReconciliationError(ValueError):
    pass


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class AutomaticBuyFillPlanIdentityV1:
    """Exact lineage carried by one approved automatic-BUY plan/handoff.

    Callers build this from ``AutomaticBuyPlanV1`` (trading_account_id, venue,
    market, strategy_bucket_id, strategy_id, strategy_version, trade_id) and
    the resolved execution handoff/broker order identity
    (source_execution_plan_id = the handoff's plan_reference_id,
    source_order_id = the broker/client order id the fill evidence names).
    Every field must be copied verbatim from those upstream contracts --
    never inferred, never recomputed here.
    """

    trading_account_id: int
    venue: str
    market: str
    strategy_bucket_id: str
    strategy_id: str
    strategy_version: str
    genesis_trade_id: str
    source_execution_plan_id: str
    source_order_id: str


def _validate_identity(identity: AutomaticBuyFillPlanIdentityV1) -> None:
    if identity.trading_account_id <= 0:
        raise AutomaticBuyFillReconciliationError("INVALID_TRADING_ACCOUNT_ID")
    for value in (
        identity.venue, identity.market, identity.strategy_bucket_id,
        identity.strategy_id, identity.strategy_version, identity.genesis_trade_id,
        identity.source_execution_plan_id, identity.source_order_id,
    ):
        if not _nonempty(value):
            raise AutomaticBuyFillReconciliationError("INVALID_AUTOMATIC_BUY_FILL_IDENTITY")


def resolve_automatic_buy_fill_lineage_v1(
    *,
    identity: AutomaticBuyFillPlanIdentityV1,
    prior_inventory_events: Iterable[StrategyOwnedInventoryEventV1],
) -> StrategyOwnedFillLineageV1:
    """Resolve the exact ``trade_id`` this fill attributes to.

    Per the B4 reviewed contract, the planner mints a fresh genesis
    ``trade_id`` for every approved decision, including RE_ENTER, and
    explicitly defers resolving whether a RE_ENTER should instead continue an
    already-open strategy-owned position to this module. This uses #752's own
    replay-safe inventory projection: if exactly one open position
    (``owned_base_quantity > 0``) already exists for the exact
    (trading_account_id, venue, market, strategy_bucket_id, strategy_id,
    strategy_version) lineage, its ``trade_id`` is reused -- never the
    planner's fresh genesis id, which would otherwise fragment one continued
    trade into two adjacent lineages. If no open position matches, the
    genesis id is used (first ENTER). If more than one open position matches
    -- which correct accounting should never produce, but which this function
    does not assume safe by construction -- it fails closed rather than
    guessing.
    """
    _validate_identity(identity)
    positions = project_strategy_owned_inventory_v1(prior_inventory_events)
    open_matches = tuple(
        position for position in positions
        if position.trading_account_id == identity.trading_account_id
        and position.venue == identity.venue
        and position.market == identity.market
        and position.strategy_bucket_id == identity.strategy_bucket_id
        and position.strategy_id == identity.strategy_id
        and position.strategy_version == identity.strategy_version
        and position.owned_base_quantity > 0
    )
    if len(open_matches) > 1:
        raise AutomaticBuyFillReconciliationError("AMBIGUOUS_OPEN_STRATEGY_OWNED_POSITION")
    resolved_trade_id = open_matches[0].trade_id if open_matches else identity.genesis_trade_id
    return StrategyOwnedFillLineageV1(
        trading_account_id=identity.trading_account_id,
        venue=identity.venue,
        market=identity.market,
        strategy_bucket_id=identity.strategy_bucket_id,
        strategy_id=identity.strategy_id,
        strategy_version=identity.strategy_version,
        trade_id=resolved_trade_id,
        source_execution_plan_id=identity.source_execution_plan_id,
        source_order_id=identity.source_order_id,
        side=SIDE_BUY,
    )


def reconcile_automatic_buy_paper_fill_v1(
    *,
    identity: AutomaticBuyFillPlanIdentityV1,
    evidence: BrokerCumulativeFillEvidenceV1,
    prior_facts: Iterable[StrategyOwnedFillReconciliationFactV1],
    prior_inventory_events: Iterable[StrategyOwnedInventoryEventV1],
) -> tuple[StrategyOwnedFillReconciliationFactV1, StrategyOwnedInventoryEventV1 | None]:
    """Reconcile one real automatic-BUY PAPER fill snapshot into #752 ownership.

    Pure and replay-safe: resolves RE_ENTER continuity above, then defers
    entirely to #752's own ``reconcile_cumulative_fill_v1``. Duplicate/replayed
    snapshots, backwards cumulative fills, and any attempt to rebind one
    broker order to a different strategy lineage all fail exactly as #752
    already guarantees; this module adds no parallel reconciliation rule.
    """
    lineage = resolve_automatic_buy_fill_lineage_v1(
        identity=identity, prior_inventory_events=prior_inventory_events,
    )
    return reconcile_cumulative_fill_v1(prior_facts, lineage=lineage, evidence=evidence)
