"""
execution_submission_orchestrator_v1 -- the one executor-owned, crash-safe,
per-leg broker submission orchestrator shared by algorithmic SELL (#392)
and algorithmic BUY (#399) (Issue #206).

Layer: executor. Consumes an already-CLAIMED
src.executor.execution_handoff_v1.ExecutionHandoff and an
src.executor.execution_plan_reference_v1.ApprovedExecutionPlanV1's legs
unchanged -- this module never recomputes price, quantity, ladder spacing,
allocation, or market selection.

The broker/order-placement boundary is fully injected via
OrderPlacementAdapter, so the exact same orchestration path is exercised by
a non-live stub in tests/paper acceptance and by a real venue adapter (e.g.
src.executor.bitvavo_order_adapter_v1) in production; there is no second
orchestrator, and side (BUY/SELL) is never branched on here.

Generalizes src.executor.manual_execution_submission_orchestrator_v1 with
two P0 hardening changes (Issue #206):

  P0-A broker acknowledgement classification -- every OrderAck this module
  receives from the adapter carries a canonical ``ack_state`` from
  src.executor.broker_ack_classification_v1 (never a raw venue status
  string the orchestrator would have to interpret itself). Only
  ACCEPTED_ACK_STATES (ACTIVE/PARTIALLY_FILLED/FILLED) are persisted via
  resolve_accepted; CANCELED/EXPIRED/REJECTED are persisted via
  resolve_closed. This module therefore can never repeat the pre-#206
  manual-lane defect of treating any non-exception adapter return as a
  successful SUBMITTED state regardless of what the broker actually said
  (see broker_ack_classification_v1's docstring). The adapter contract
  requires ack_state to never be AMBIGUOUS -- an adapter that cannot
  confidently classify a response must raise SubmissionUncertainError
  instead of returning an ambiguous OrderAck.

  P0-B fail-closed reconciliation -- when a broker lookup during
  SUBMISSION_UNCERTAIN reconciliation definitively confirms no such order
  exists, this orchestrator transitions the leg to
  execution_leg_v1.STATE_RECONCILIATION_REQUIRED and STOPS. Unlike
  src.executor.manual_execution_submission_orchestrator_v1 (which
  automatically resets to PREPARED and immediately re-attempts submission
  on confirmed-absent -- see that module's _reconcile_uncertain_leg and its
  test test_confirmed_absent_allows_exactly_one_resubmission), this module
  NEVER automatically issues a second POST. Moving the leg forward again
  requires the separate, explicitly-audited
  execution_leg_v1.ExecutionLegRepository.rearm_after_reconciliation() call,
  which this orchestrator never invokes itself.

Per-leg state machine and crash-safety authority live in
src.executor.execution_leg_v1 -- read that module's docstring for the
concurrency/idempotency contract this orchestrator relies on. Summary of
the hard invariants enforced here:

  - Legs are attempted strictly sequentially, in leg_index order; the
    orchestrator stops at the first leg that is not in an ACCEPTED_STATES
    outcome (never attempts a later leg after an unresolved/closed leg).
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

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from src.executor.broker_ack_classification_v1 import ACCEPTED_ACK_STATES
from src.executor.execution_client_order_id_v1 import derive_client_order_id
from src.executor.execution_handoff_v1 import (
    CLAIM_STATE_CLAIMED,
    ExecutionHandoff,
    ExecutionHandoffDeniedError,
)
from src.executor.execution_leg_v1 import (
    ACCEPTED_STATES,
    STATE_PREPARED,
    STATE_RECONCILIATION_REQUIRED,
    STATE_SUBMISSION_UNCERTAIN,
    TERMINAL_FAILURE_STATES,
    ExecutionLeg,
    ExecutionLegRepository,
)
from src.executor.execution_plan_reference_v1 import ApprovedExecutionPlanLegV1


class SubmissionUncertainError(RuntimeError):
    """Adapter contract: raise this to mean the broker's true state for
    this attempt is unknown (timeout, connection drop, an ambiguous 5xx, or
    a response whose status could not be confidently classified into a
    canonical ack_state). The orchestrator never treats this as safe to
    resubmit; it always reconciles by clientOrderId first."""


class BrokerOrderRejectedError(RuntimeError):
    """Adapter contract: raise this only when a real, definitive broker
    response confirms NO order object was ever created (e.g. a 4xx
    validation rejection with no order in the response body) -- never for
    network-level ambiguity, and never when an order object was returned
    with a closed status (that case is OrderAck with ack_state in
    CANCELED/EXPIRED/REJECTED, resolved via resolve_closed instead)."""

    def __init__(self, *, safe_error_code: str, broker_status: str | None = None) -> None:
        self.safe_error_code = safe_error_code
        self.broker_status = broker_status
        super().__init__(safe_error_code)


@dataclass(frozen=True)
class OrderAck:
    """One classified broker acknowledgement. ack_state must be a member of
    src.executor.broker_ack_classification_v1.ALL_ACK_STATES and must never
    be AMBIGUOUS -- an adapter that cannot confidently classify a response
    must raise SubmissionUncertainError instead of constructing this with
    an ambiguous state."""

    broker_order_id: str
    broker_status: str
    ack_state: str


class OrderPlacementAdapter(Protocol):
    """Injected broker boundary. The exact same orchestration path in this
    module is exercised against a non-live stub
    (src.executor.stub_order_adapter_v1) and a real venue adapter (e.g.
    src.executor.bitvavo_order_adapter_v1)."""

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
        confidently resolved -- never guess by returning None."""
        ...


@dataclass(frozen=True)
class LegOutcome:
    leg_index: int
    execution_leg_id: int
    submission_state: str
    broker_order_id: str | None
    safe_error_code: str | None


@dataclass(frozen=True)
class ExecutionSubmissionResult:
    handoff_id: int
    side: str
    leg_outcomes: list[LegOutcome]
    stopped_reason: str | None  # None only if every leg reached an ACCEPTED state


def submit_execution_ladder(
    *,
    handoff: ExecutionHandoff,
    legs: tuple[ApprovedExecutionPlanLegV1, ...],
    operator_id: int,
    adapter: OrderPlacementAdapter,
    execution_leg_repository: ExecutionLegRepository | None = None,
) -> ExecutionSubmissionResult:
    """The single crash-safe orchestration entrypoint shared by BUY and
    SELL. Idempotent: calling this again for the same handoff after a
    crash, timeout, or concurrent invocation resumes from exactly the
    persisted per-leg state, never blindly resubmits, and never rolls back
    an already-accepted leg."""
    if handoff.claim_state != CLAIM_STATE_CLAIMED:
        raise ExecutionHandoffDeniedError(
            f"HANDOFF_NOT_CLAIMED: claim_state={handoff.claim_state}"
        )
    if handoff.handoff_id is None:
        raise ValueError("handoff must be persisted")
    if not legs:
        raise ValueError("EXECUTION_PLAN_HAS_NO_LEGS")

    repo = execution_leg_repository or ExecutionLegRepository()
    ordered_legs = sorted(legs, key=lambda leg: leg.leg_index)

    outcomes: list[LegOutcome] = []
    stopped_reason: str | None = None

    for plan_leg in ordered_legs:
        if plan_leg.side != handoff.side:
            raise ValueError(
                f"PLAN_LEG_SIDE_MISMATCH: leg_index={plan_leg.leg_index} "
                f"plan_leg.side={plan_leg.side} handoff.side={handoff.side}"
            )

        client_order_id = derive_client_order_id(
            handoff_id=handoff.handoff_id,
            leg_index=plan_leg.leg_index,
            trading_account_id=handoff.trading_account_id,
            venue=handoff.venue,
            market=handoff.market,
        )
        leg, _created = repo.claim_prepared(
            handoff_id=handoff.handoff_id,
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
                execution_leg_id=leg.execution_leg_id,
                submission_state=leg.submission_state,
                broker_order_id=leg.broker_order_id,
                safe_error_code=leg.safe_error_code,
            )
        )

        if leg.submission_state in ACCEPTED_STATES:
            continue

        # SUBMISSION_UNCERTAIN, RECONCILIATION_REQUIRED, a terminal failure,
        # or lost ownership of the attempt to another process -- never
        # attempt a later leg.
        stopped_reason = leg.submission_state
        break

    return ExecutionSubmissionResult(
        handoff_id=handoff.handoff_id,
        side=handoff.side,
        leg_outcomes=outcomes,
        stopped_reason=stopped_reason,
    )


def _resolve_leg(
    leg: ExecutionLeg,
    *,
    adapter: OrderPlacementAdapter,
    repo: ExecutionLegRepository,
    market: str,
) -> ExecutionLeg:
    if leg.submission_state in ACCEPTED_STATES or leg.submission_state in TERMINAL_FAILURE_STATES:
        return leg  # already resolved by a prior run; nothing to do
    if leg.submission_state == STATE_RECONCILIATION_REQUIRED:
        return leg  # fail-closed dead end; only an explicit rearm may proceed

    if leg.submission_state == STATE_SUBMISSION_UNCERTAIN:
        return _reconcile_uncertain_leg(leg, adapter=adapter, repo=repo, market=market)

    assert leg.submission_state == STATE_PREPARED
    claimed, won = repo.begin_attempt(leg.execution_leg_id)
    if not won:
        # Another process already holds (or has resolved) this attempt.
        return claimed
    return _attempt_submit(claimed, adapter=adapter, repo=repo, market=market)


def _resolve_ack(
    leg: ExecutionLeg,
    ack: OrderAck,
    *,
    repo: ExecutionLegRepository,
) -> ExecutionLeg:
    if ack.ack_state in ACCEPTED_ACK_STATES:
        return repo.resolve_accepted(
            leg.execution_leg_id,
            new_state=ack.ack_state,
            broker_order_id=ack.broker_order_id,
            broker_status=ack.broker_status,
        )
    return repo.resolve_closed(
        leg.execution_leg_id,
        new_state=ack.ack_state,
        safe_error_code=f"BROKER_ACK_{ack.ack_state}",
        broker_order_id=ack.broker_order_id,
        broker_status=ack.broker_status,
    )


def _attempt_submit(
    leg: ExecutionLeg,
    *,
    adapter: OrderPlacementAdapter,
    repo: ExecutionLegRepository,
    market: str,
) -> ExecutionLeg:
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
        return repo.resolve_closed(
            leg.execution_leg_id,
            new_state="REJECTED",
            safe_error_code=exc.safe_error_code,
            broker_status=exc.broker_status,
        )
    except Exception:
        # SubmissionUncertainError and every other unexpected exception are
        # treated identically and conservatively: the leg was already
        # persisted SUBMISSION_UNCERTAIN by begin_attempt above, so there is
        # nothing further to write. Never assume "definitely not created".
        found = repo.find_by_id(leg.execution_leg_id)
        if found is None:
            raise
        return found

    return _resolve_ack(leg, ack, repo=repo)


def _reconcile_uncertain_leg(
    leg: ExecutionLeg,
    *,
    adapter: OrderPlacementAdapter,
    repo: ExecutionLegRepository,
    market: str,
) -> ExecutionLeg:
    try:
        found = adapter.find_order_by_client_order_id(
            market=market, client_order_id=leg.client_order_id
        )
    except Exception:
        # Existence still cannot be confidently resolved: fail closed,
        # leave SUBMISSION_UNCERTAIN, require a later reconciliation pass.
        repo.mark_still_uncertain(leg.execution_leg_id)
        resolved = repo.find_by_id(leg.execution_leg_id)
        if resolved is None:
            raise
        return resolved

    if found is not None:
        return _resolve_ack(leg, found, repo=repo)

    # Issue #206 P0-B: the broker definitively confirmed no such order
    # exists. Unlike the manual lane, this is NOT treated as "safe to
    # resubmit" -- fail closed to RECONCILIATION_REQUIRED and stop. Only an
    # explicit, separately-audited rearm_after_reconciliation() call (never
    # invoked by this orchestrator) may move the leg back to PREPARED.
    return repo.mark_reconciliation_required(leg.execution_leg_id)
