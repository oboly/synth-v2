"""
manual_execution_submission_orchestrator_v1 — the one executor-owned,
crash-safe, per-leg broker submission orchestrator for a #206 executor
handoff (Issue #369).

Layer: executor. Consumes an already-CLAIMED
src.executor.manual_execution_handoff_v1.ManualExecutionExecutorHandoff and
its exact persisted
src.execution_planner.manual_execution_plan_snapshot_v1.ManualExecutionPlanSnapshot
legs unchanged — this module never recomputes price, quantity, ladder
spacing, allocation, or market selection.

The broker/order-placement boundary is fully injected via
OrderPlacementAdapter, so the exact same orchestration path is exercised by
a non-live stub in tests/paper acceptance and by the real Bitvavo adapter in
production; there is no second orchestrator.

Per-leg state machine and crash-safety authority live in
src.executor.manual_execution_submission_leg_v1 — read that module's
docstring for the concurrency/idempotency contract this orchestrator relies
on. Summary of the hard invariants enforced here:

  - Legs are attempted strictly sequentially, in leg_index order; the
    orchestrator stops at the first leg that is not in an ACCEPTED_STATES
    outcome (never attempts a later leg after an unresolved/rejected leg).
  - Before any broker call, the leg is atomically transitioned
    PREPARED -> SUBMISSION_UNCERTAIN (worst-case-first: assume ambiguous
    until proven otherwise). A crash at any point from here on is always
    recovered by reconciling via the leg's deterministic clientOrderId,
    never by blindly resubmitting.
  - Earlier accepted legs are never rolled back or cancelled.

broker_private_calls=0 (this module itself makes none; the injected adapter
    may, depending on which adapter is wired in)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from src.execution_planner.manual_execution_plan_snapshot_v1 import (
    ManualExecutionPlanSnapshot,
)
from src.executor.manual_execution_client_order_id_v1 import derive_client_order_id
from src.executor.manual_execution_handoff_v1 import (
    CLAIM_STATE_CLAIMED,
    ExecutorHandoffDeniedError,
    ManualExecutionExecutorHandoff,
)
from src.executor.manual_execution_submission_leg_v1 import (
    ACCEPTED_STATES,
    STATE_PREPARED,
    STATE_SUBMISSION_UNCERTAIN,
    STATE_SUBMITTED,
    TERMINAL_FAILURE_STATES,
    ManualExecutionSubmissionLeg,
    ManualExecutionSubmissionLegRepository,
)


class SubmissionUncertainError(RuntimeError):
    """Adapter contract: raise this to mean the broker's true state for
    this attempt is unknown (timeout, connection drop, or any other
    ambiguous failure). The orchestrator never treats this as safe to
    resubmit; it always reconciles by clientOrderId first."""


class BrokerOrderRejectedError(RuntimeError):
    """Adapter contract: raise this only when a real, definitive broker
    response confirms the order was NOT created (never for network-level
    ambiguity)."""

    def __init__(self, *, safe_error_code: str, broker_status: str | None = None) -> None:
        self.safe_error_code = safe_error_code
        self.broker_status = broker_status
        super().__init__(safe_error_code)


@dataclass(frozen=True)
class OrderAck:
    broker_order_id: str
    broker_status: str


class OrderPlacementAdapter(Protocol):
    """Injected broker boundary. The exact same orchestration path in this
    module is exercised against a non-live stub adapter and the real
    Bitvavo adapter (src.executor.manual_execution_bitvavo_order_adapter_v1)."""

    def place_order(
        self,
        *,
        market: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        client_order_id: str,
        operator_id: int,
    ) -> OrderAck: ...

    def find_order_by_client_order_id(
        self, *, market: str, client_order_id: str
    ) -> OrderAck | None:
        """Return the confirmed order if the broker has one for this
        clientOrderId, or None if the broker definitively confirms none
        exists. Must raise SubmissionUncertainError if existence cannot be
        confidently resolved — never guess by returning None."""
        ...


@dataclass(frozen=True)
class PlanLeg:
    leg_index: int
    side: str
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class LegOutcome:
    leg_index: int
    submission_leg_id: int
    submission_state: str
    broker_order_id: str | None
    safe_error_code: str | None


@dataclass(frozen=True)
class LadderSubmissionResult:
    handoff_id: int
    plan_snapshot_id: int
    leg_outcomes: list[LegOutcome]
    stopped_reason: str | None  # None only if every leg reached an ACCEPTED state


def extract_plan_legs(plan_snapshot: ManualExecutionPlanSnapshot) -> list[PlanLeg]:
    payload = json.loads(plan_snapshot.payload_json)
    raw_legs = payload.get("legs") or []
    if not raw_legs:
        raise ValueError(
            f"PLAN_SNAPSHOT_HAS_NO_LEGS: plan_snapshot_id={plan_snapshot.plan_snapshot_id}"
        )
    legs: list[PlanLeg] = []
    for raw in raw_legs:
        price = raw.get("target_price_eur")
        quantity = raw.get("quantity_base")
        if price is None or quantity is None:
            raise ValueError(
                f"PLAN_SNAPSHOT_LEG_MISSING_PRICE_OR_QUANTITY: leg_index={raw.get('leg_index')}"
            )
        legs.append(
            PlanLeg(
                leg_index=int(raw["leg_index"]),
                side=str(raw["side"]),
                price=Decimal(str(price)),
                quantity=Decimal(str(quantity)),
            )
        )
    legs.sort(key=lambda leg: leg.leg_index)
    return legs


def submit_manual_sell_ladder(
    *,
    handoff: ManualExecutionExecutorHandoff,
    plan_snapshot: ManualExecutionPlanSnapshot,
    operator_id: int,
    adapter: OrderPlacementAdapter,
    submission_leg_repository: ManualExecutionSubmissionLegRepository | None = None,
) -> LadderSubmissionResult:
    """The single crash-safe orchestration entrypoint. Idempotent: calling
    this again for the same handoff/plan_snapshot after a crash, timeout, or
    concurrent invocation resumes from exactly the persisted per-leg state,
    never blindly resubmits, and never rolls back an already-accepted leg."""
    if handoff.plan_snapshot_id != plan_snapshot.plan_snapshot_id:
        raise ValueError(
            "HANDOFF_PLAN_SNAPSHOT_MISMATCH: "
            f"handoff.plan_snapshot_id={handoff.plan_snapshot_id} "
            f"plan_snapshot.plan_snapshot_id={plan_snapshot.plan_snapshot_id}"
        )
    if handoff.claim_state != CLAIM_STATE_CLAIMED:
        raise ExecutorHandoffDeniedError(
            f"HANDOFF_NOT_CLAIMED: claim_state={handoff.claim_state}"
        )
    if handoff.handoff_id is None:
        raise ValueError("handoff must be persisted")

    repo = submission_leg_repository or ManualExecutionSubmissionLegRepository()
    plan_legs = extract_plan_legs(plan_snapshot)

    outcomes: list[LegOutcome] = []
    stopped_reason: str | None = None

    for plan_leg in plan_legs:
        if plan_leg.side != handoff.side:
            raise ValueError(
                f"PLAN_LEG_SIDE_MISMATCH: leg_index={plan_leg.leg_index} "
                f"plan_leg.side={plan_leg.side} handoff.side={handoff.side}"
            )

        client_order_id = derive_client_order_id(
            plan_snapshot_id=plan_snapshot.plan_snapshot_id,
            leg_index=plan_leg.leg_index,
            trading_account_id=handoff.trading_account_id,
            venue=handoff.venue,
            market=handoff.market,
        )
        leg, _created = repo.claim_prepared(
            handoff_id=handoff.handoff_id,
            plan_snapshot_id=plan_snapshot.plan_snapshot_id,
            leg_index=plan_leg.leg_index,
            trading_account_id=handoff.trading_account_id,
            venue=handoff.venue,
            market=handoff.market,
            side=plan_leg.side,
            client_order_id=client_order_id,
            operator_id=operator_id,
            immutable_price=plan_leg.price,
            immutable_quantity=plan_leg.quantity,
        )

        leg = _resolve_leg(leg, adapter=adapter, repo=repo, market=handoff.market)

        outcomes.append(
            LegOutcome(
                leg_index=plan_leg.leg_index,
                submission_leg_id=leg.submission_leg_id,
                submission_state=leg.submission_state,
                broker_order_id=leg.broker_order_id,
                safe_error_code=leg.safe_error_code,
            )
        )

        if leg.submission_state in ACCEPTED_STATES:
            continue

        # SUBMISSION_UNCERTAIN, a terminal failure, or lost ownership of the
        # attempt to another process — never attempt a later leg.
        stopped_reason = leg.submission_state
        break

    return LadderSubmissionResult(
        handoff_id=handoff.handoff_id,
        plan_snapshot_id=plan_snapshot.plan_snapshot_id,
        leg_outcomes=outcomes,
        stopped_reason=stopped_reason,
    )


def _resolve_leg(
    leg: ManualExecutionSubmissionLeg,
    *,
    adapter: OrderPlacementAdapter,
    repo: ManualExecutionSubmissionLegRepository,
    market: str,
) -> ManualExecutionSubmissionLeg:
    if leg.submission_state in ACCEPTED_STATES or leg.submission_state in TERMINAL_FAILURE_STATES:
        return leg  # already resolved by a prior run; nothing to do

    if leg.submission_state == STATE_SUBMISSION_UNCERTAIN:
        return _reconcile_uncertain_leg(leg, adapter=adapter, repo=repo, market=market)

    assert leg.submission_state == STATE_PREPARED
    claimed, won = repo.begin_attempt(leg.submission_leg_id)
    if not won:
        # Another process already holds (or has resolved) this attempt.
        return claimed
    return _attempt_submit(claimed, adapter=adapter, repo=repo, market=market)


def _attempt_submit(
    leg: ManualExecutionSubmissionLeg,
    *,
    adapter: OrderPlacementAdapter,
    repo: ManualExecutionSubmissionLegRepository,
    market: str,
) -> ManualExecutionSubmissionLeg:
    try:
        ack = adapter.place_order(
            market=market,
            side=leg.side,
            price=leg.immutable_price,
            quantity=leg.immutable_quantity,
            client_order_id=leg.client_order_id,
            operator_id=leg.operator_id,
        )
    except BrokerOrderRejectedError as exc:
        return repo.resolve_rejected(
            leg.submission_leg_id,
            safe_error_code=exc.safe_error_code,
            broker_status=exc.broker_status,
        )
    except Exception:
        # SubmissionUncertainError and every other unexpected exception are
        # treated identically and conservatively: the leg was already
        # persisted SUBMISSION_UNCERTAIN by begin_attempt above, so there is
        # nothing further to write. Never assume "definitely not created".
        found = repo.find_by_id(leg.submission_leg_id)
        if found is None:
            raise
        return found

    return repo.resolve_accepted(
        leg.submission_leg_id,
        new_state=STATE_SUBMITTED,
        broker_order_id=ack.broker_order_id,
        broker_status=ack.broker_status,
    )


def _reconcile_uncertain_leg(
    leg: ManualExecutionSubmissionLeg,
    *,
    adapter: OrderPlacementAdapter,
    repo: ManualExecutionSubmissionLegRepository,
    market: str,
) -> ManualExecutionSubmissionLeg:
    try:
        found = adapter.find_order_by_client_order_id(
            market=market, client_order_id=leg.client_order_id
        )
    except Exception:
        # Existence still cannot be confidently resolved: fail closed,
        # leave SUBMISSION_UNCERTAIN, require explicit operator action.
        repo.mark_reconciled(leg.submission_leg_id)
        resolved = repo.find_by_id(leg.submission_leg_id)
        if resolved is None:
            raise
        return resolved

    repo.mark_reconciled(leg.submission_leg_id)

    if found is not None:
        return repo.resolve_accepted(
            leg.submission_leg_id,
            new_state=STATE_SUBMITTED,
            broker_order_id=found.broker_order_id,
            broker_status=found.broker_status,
        )

    # The broker definitively confirmed no such order exists: safe to
    # attempt submission for the first time. Reuses the same
    # atomic-conditional-UPDATE primitives as a first attempt — never a
    # direct/blind POST.
    reset_leg, won = repo.reset_to_prepared(leg.submission_leg_id)
    if not won:
        return reset_leg
    claimed, won2 = repo.begin_attempt(reset_leg.submission_leg_id)
    if not won2:
        return claimed
    return _attempt_submit(claimed, adapter=adapter, repo=repo, market=market)
