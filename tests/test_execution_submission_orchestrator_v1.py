"""Tests for src/executor/execution_submission_orchestrator_v1.py (Issue #206).

Proves BUY and SELL run through the exact same orchestration machinery, and
covers the P0 hardening this module adds over the manual-only orchestrator:
canonical ack-state classification (ACTIVE/PARTIALLY_FILLED/FILLED accepted;
CANCELED/EXPIRED/REJECTED never accepted) and fail-closed
SUBMISSION_UNCERTAIN -> RECONCILIATION_REQUIRED (never an automatic second
POST), plus concurrency/duplicate-submission and identity-mismatch guards.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from src.executor import _trusted_clock_v1 as trusted_clock
from src.executor.broker_ack_classification_v1 import (
    ACK_STATE_ACTIVE,
    ACK_STATE_CANCELED,
    ACK_STATE_EXPIRED,
    ACK_STATE_FILLED,
    ACK_STATE_PARTIALLY_FILLED,
    ACK_STATE_REJECTED,
)
from src.executor.execution_handoff_v1 import (
    CLAIM_STATE_CLAIMED,
    CLAIM_STATE_CONSUMED,
    ExecutionHandoff,
    ExecutionHandoffDeniedError,
)
from src.executor.execution_leg_v1 import (
    ExecutionLegRepository,
    STATE_CANCELED,
    STATE_FILLED,
    STATE_PARTIALLY_FILLED,
    STATE_RECONCILIATION_REQUIRED,
    STATE_REJECTED,
    STATE_SUBMISSION_UNCERTAIN,
)
from src.executor.execution_plan_reference_v1 import ApprovedExecutionPlanLegV1
from src.executor.execution_submission_orchestrator_v1 import (
    OrderAck,
    SubmissionUncertainError,
    submit_execution_ladder,
)
from src.executor.stub_order_adapter_v1 import (
    StubOrderPlacementAdapter,
    acked_with_state,
    rejected,
    uncertain_once,
)
from tests.test_execution_leg_v1 import _FakeBackend, _FakeSession


NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trusted_clock, "utc_now", lambda: NOW)


def _repo(backend: _FakeBackend | None = None) -> tuple[ExecutionLegRepository, _FakeBackend]:
    backend = backend or _FakeBackend()
    return ExecutionLegRepository(cursor_factory=lambda **_: _FakeSession(backend)), backend


def _handoff(*, side: str = "SELL", **overrides: Any) -> ExecutionHandoff:
    defaults: dict[str, Any] = dict(
        handoff_id=1, plan_source="AUTOMATIC_EXIT_PLAN_V1", plan_reference_id="ref-1",
        plan_content_hash="a" * 64, trading_account_id=1, venue="bitvavo", market="BTC-EUR",
        side=side, executor_mode="PAPER", executor_identity="algo-v1", runtime_owner="odroid",
        executor_credential_binding_id=1, claim_state=CLAIM_STATE_CLAIMED,
        claimed_ts_utc=NOW, consumed_ts_utc=None, outcome_code=None, outcome_detail=None,
        created_ts_utc=NOW,
    )
    defaults.update(overrides)
    return ExecutionHandoff(**defaults)


def _legs(side: str, prices_qtys: list[tuple[Decimal, Decimal]]) -> tuple[ApprovedExecutionPlanLegV1, ...]:
    return tuple(
        ApprovedExecutionPlanLegV1(leg_index=idx, side=side, price=price, quantity=qty)
        for idx, (price, qty) in enumerate(prices_qtys, start=1)
    )


THREE_LEGS = [(Decimal("50000"), Decimal("0.1")), (Decimal("51000"), Decimal("0.1")), (Decimal("52000"), Decimal("0.1"))]


def _cid_for(handoff: ExecutionHandoff, leg_index: int) -> str:
    from src.executor.execution_client_order_id_v1 import derive_client_order_id

    return derive_client_order_id(
        handoff_id=handoff.handoff_id, leg_index=leg_index,
        trading_account_id=handoff.trading_account_id, venue=handoff.venue, market=handoff.market,
    )


class TestSharedMachineryAcrossSides:
    @pytest.mark.parametrize("side", ["BUY", "SELL"])
    def test_all_legs_accepted_regardless_of_side(self, side: str) -> None:
        repo, _ = _repo()
        handoff = _handoff(side=side)
        legs = _legs(side, THREE_LEGS)
        adapter = StubOrderPlacementAdapter()

        result = submit_execution_ladder(
            handoff=handoff, legs=legs, operator_id=777, adapter=adapter, execution_leg_repository=repo,
        )

        assert result.side == side
        assert result.stopped_reason is None
        assert len(result.leg_outcomes) == 3
        assert all(o.submission_state == "ACTIVE" for o in result.leg_outcomes)

    def test_buy_and_sell_use_the_identical_orchestrator_function(self) -> None:
        # There is exactly one submit_execution_ladder; this test proves it
        # by driving both sides through the same import with no branching
        # helper in this test module.
        for side in ("BUY", "SELL"):
            repo, _ = _repo()
            handoff = _handoff(side=side)
            result = submit_execution_ladder(
                handoff=handoff, legs=_legs(side, THREE_LEGS[:1]), operator_id=1,
                adapter=StubOrderPlacementAdapter(), execution_leg_repository=repo,
            )
            assert result.leg_outcomes[0].submission_state == "ACTIVE"


class TestBrokerAckClassificationGuard:
    def test_post_only_cancellation_never_accepted(self) -> None:
        repo, _ = _repo()
        handoff = _handoff()
        legs = _legs("SELL", THREE_LEGS[:1])
        cid = _cid_for(handoff, 1)
        adapter = StubOrderPlacementAdapter(
            script={cid: acked_with_state(ACK_STATE_CANCELED, broker_status="canceledPostOnly")}
        )

        result = submit_execution_ladder(
            handoff=handoff, legs=legs, operator_id=1, adapter=adapter, execution_leg_repository=repo,
        )

        assert result.leg_outcomes[0].submission_state == STATE_CANCELED
        assert result.stopped_reason == STATE_CANCELED

    def test_expired_never_accepted(self) -> None:
        repo, _ = _repo()
        handoff = _handoff()
        cid = _cid_for(handoff, 1)
        adapter = StubOrderPlacementAdapter(script={cid: acked_with_state(ACK_STATE_EXPIRED, broker_status="expired")})

        result = submit_execution_ladder(
            handoff=handoff, legs=_legs("SELL", THREE_LEGS[:1]), operator_id=1, adapter=adapter,
            execution_leg_repository=repo,
        )
        assert result.leg_outcomes[0].submission_state == "EXPIRED"

    def test_partially_filled_and_filled_are_accepted(self) -> None:
        for ack_state, expected in ((ACK_STATE_PARTIALLY_FILLED, STATE_PARTIALLY_FILLED), (ACK_STATE_FILLED, STATE_FILLED)):
            repo, _ = _repo()
            handoff = _handoff()
            cid = _cid_for(handoff, 1)
            adapter = StubOrderPlacementAdapter(script={cid: acked_with_state(ack_state, broker_status="raw")})
            result = submit_execution_ladder(
                handoff=handoff, legs=_legs("SELL", THREE_LEGS[:1]), operator_id=1, adapter=adapter,
                execution_leg_repository=repo,
            )
            assert result.leg_outcomes[0].submission_state == expected
            assert result.stopped_reason is None

    def test_reject_stops_ladder(self) -> None:
        repo, _ = _repo()
        handoff = _handoff()
        cid = _cid_for(handoff, 2)
        adapter = StubOrderPlacementAdapter(script={cid: rejected("BROKER_REJECTED_HTTP_400")})

        result = submit_execution_ladder(
            handoff=handoff, legs=_legs("SELL", THREE_LEGS), operator_id=1, adapter=adapter,
            execution_leg_repository=repo,
        )
        assert len(result.leg_outcomes) == 2
        assert result.leg_outcomes[0].submission_state == "ACTIVE"
        assert result.leg_outcomes[1].submission_state == STATE_REJECTED
        assert result.stopped_reason == STATE_REJECTED


class TestSubmissionUncertainFailClosed:
    def test_timeout_marks_uncertain_and_stops(self) -> None:
        repo, _ = _repo()
        handoff = _handoff()
        cid = _cid_for(handoff, 1)
        adapter = StubOrderPlacementAdapter(script={cid: uncertain_once()})

        result = submit_execution_ladder(
            handoff=handoff, legs=_legs("SELL", THREE_LEGS[:1]), operator_id=1, adapter=adapter,
            execution_leg_repository=repo,
        )
        assert result.stopped_reason == STATE_SUBMISSION_UNCERTAIN

    def test_confirmed_present_on_reconcile_resolves_accepted(self) -> None:
        repo, _ = _repo()
        handoff = _handoff()
        cid = _cid_for(handoff, 1)
        adapter = StubOrderPlacementAdapter(script={cid: uncertain_once()})

        first = submit_execution_ladder(
            handoff=handoff, legs=_legs("SELL", THREE_LEGS[:1]), operator_id=1, adapter=adapter,
            execution_leg_repository=repo,
        )
        assert first.stopped_reason == STATE_SUBMISSION_UNCERTAIN

        adapter.confirmed[cid] = OrderAck(broker_order_id="real-order", broker_status="new", ack_state=ACK_STATE_ACTIVE)

        second = submit_execution_ladder(
            handoff=handoff, legs=_legs("SELL", THREE_LEGS[:1]), operator_id=1, adapter=adapter,
            execution_leg_repository=repo,
        )
        assert second.stopped_reason is None
        assert second.leg_outcomes[0].submission_state == "ACTIVE"
        assert second.leg_outcomes[0].broker_order_id == "real-order"

    def test_confirmed_absent_never_auto_resubmits_issue_206_p0b(self) -> None:
        """Issue #206 P0-B: this is the deliberate divergence from the
        manual lane's manual_execution_submission_orchestrator_v1 (which
        automatically resubmits once on confirmed-absent). Here, confirmed
        absence must fail closed to RECONCILIATION_REQUIRED and the ladder
        must stop -- no second POST is ever issued automatically."""
        repo, _ = _repo()
        handoff = _handoff()
        cid = _cid_for(handoff, 1)
        adapter = StubOrderPlacementAdapter(script={cid: uncertain_once()})

        first = submit_execution_ladder(
            handoff=handoff, legs=_legs("SELL", THREE_LEGS[:1]), operator_id=1, adapter=adapter,
            execution_leg_repository=repo,
        )
        assert first.stopped_reason == STATE_SUBMISSION_UNCERTAIN
        # adapter.confirmed has no entry for cid -> find_order_by_client_order_id
        # returns None (definitively absent) on the next reconcile pass.

        second = submit_execution_ladder(
            handoff=handoff, legs=_legs("SELL", THREE_LEGS[:1]), operator_id=1, adapter=adapter,
            execution_leg_repository=repo,
        )
        assert second.stopped_reason == STATE_RECONCILIATION_REQUIRED
        assert second.leg_outcomes[0].submission_state == STATE_RECONCILIATION_REQUIRED
        # Never resubmitted: place_order was called exactly once across both runs.
        leg = repo.find_by_handoff_and_leg(handoff_id=handoff.handoff_id, leg_index=1)
        assert leg.broker_order_id is None
        assert leg.submission_state == STATE_RECONCILIATION_REQUIRED

        # A third run also does not automatically resubmit -- the state is a
        # stable fail-closed dead end for the orchestrator.
        third = submit_execution_ladder(
            handoff=handoff, legs=_legs("SELL", THREE_LEGS[:1]), operator_id=1, adapter=adapter,
            execution_leg_repository=repo,
        )
        assert third.stopped_reason == STATE_RECONCILIATION_REQUIRED

    def test_explicit_rearm_then_resubmit_succeeds(self) -> None:
        repo, _ = _repo()
        handoff = _handoff()
        cid = _cid_for(handoff, 1)
        adapter = StubOrderPlacementAdapter(script={cid: uncertain_once()})

        submit_execution_ladder(
            handoff=handoff, legs=_legs("SELL", THREE_LEGS[:1]), operator_id=1, adapter=adapter,
            execution_leg_repository=repo,
        )
        submit_execution_ladder(
            handoff=handoff, legs=_legs("SELL", THREE_LEGS[:1]), operator_id=1, adapter=adapter,
            execution_leg_repository=repo,
        )
        leg = repo.find_by_handoff_and_leg(handoff_id=handoff.handoff_id, leg_index=1)
        assert leg.submission_state == STATE_RECONCILIATION_REQUIRED

        # Only an explicit, separately-audited action -- never the
        # orchestrator itself -- may re-arm the leg.
        repo.rearm_after_reconciliation(leg.execution_leg_id, reconciled_by="ops-bob")

        result = submit_execution_ladder(
            handoff=handoff, legs=_legs("SELL", THREE_LEGS[:1]), operator_id=1, adapter=adapter,
            execution_leg_repository=repo,
        )
        assert result.stopped_reason is None
        assert result.leg_outcomes[0].submission_state == "ACTIVE"

    def test_unresolved_ambiguity_remains_uncertain(self) -> None:
        repo, _ = _repo()
        handoff = _handoff()

        class _AlwaysUncertainAdapter:
            def place_order(self, **_kwargs):
                raise SubmissionUncertainError("STUB_TIMEOUT")

            def find_order_by_client_order_id(self, **_kwargs):
                raise SubmissionUncertainError("STUB_RECONCILE_TIMEOUT")

        adapter = _AlwaysUncertainAdapter()

        first = submit_execution_ladder(
            handoff=handoff, legs=_legs("SELL", THREE_LEGS[:1]), operator_id=1, adapter=adapter,
            execution_leg_repository=repo,
        )
        second = submit_execution_ladder(
            handoff=handoff, legs=_legs("SELL", THREE_LEGS[:1]), operator_id=1, adapter=adapter,
            execution_leg_repository=repo,
        )
        assert first.stopped_reason == STATE_SUBMISSION_UNCERTAIN
        assert second.stopped_reason == STATE_SUBMISSION_UNCERTAIN


class TestConcurrencyAndDuplicateSubmission:
    def test_duplicate_invocation_cannot_submit_same_leg_twice(self) -> None:
        repo, _ = _repo()
        handoff = _handoff()
        legs = _legs("SELL", THREE_LEGS)
        adapter = StubOrderPlacementAdapter()

        submit_execution_ladder(handoff=handoff, legs=legs, operator_id=1, adapter=adapter, execution_leg_repository=repo)
        submit_execution_ladder(handoff=handoff, legs=legs, operator_id=1, adapter=adapter, execution_leg_repository=repo)

        assert len(adapter.confirmed) == 3  # not 6

    def test_concurrent_invocation_cannot_double_submit_same_leg(self) -> None:
        repo, _ = _repo()
        handoff = _handoff()
        legs = _legs("SELL", THREE_LEGS[:1])
        adapter = StubOrderPlacementAdapter()
        call_count = {"n": 0}
        lock = threading.Lock()
        original_place = adapter.place_order

        def counting_place_order(**kwargs):
            with lock:
                call_count["n"] += 1
            return original_place(**kwargs)

        adapter.place_order = counting_place_order  # type: ignore[method-assign]

        def run() -> None:
            submit_execution_ladder(handoff=handoff, legs=legs, operator_id=1, adapter=adapter, execution_leg_repository=repo)

        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert call_count["n"] == 1


class TestArchitectureGuards:
    def test_rejects_a_handoff_that_is_not_claimed(self) -> None:
        repo, _ = _repo()
        handoff = _handoff(claim_state=CLAIM_STATE_CONSUMED)
        with pytest.raises(ExecutionHandoffDeniedError, match="HANDOFF_NOT_CLAIMED"):
            submit_execution_ladder(
                handoff=handoff, legs=_legs("SELL", THREE_LEGS[:1]), operator_id=1,
                adapter=StubOrderPlacementAdapter(), execution_leg_repository=repo,
            )

    def test_rejects_leg_side_mismatched_with_handoff_side(self) -> None:
        repo, _ = _repo()
        handoff = _handoff(side="SELL")
        mismatched_legs = _legs("BUY", THREE_LEGS[:1])
        with pytest.raises(ValueError, match="PLAN_LEG_SIDE_MISMATCH"):
            submit_execution_ladder(
                handoff=handoff, legs=mismatched_legs, operator_id=1,
                adapter=StubOrderPlacementAdapter(), execution_leg_repository=repo,
            )

    def test_rejects_empty_legs(self) -> None:
        repo, _ = _repo()
        handoff = _handoff()
        with pytest.raises(ValueError, match="EXECUTION_PLAN_HAS_NO_LEGS"):
            submit_execution_ladder(
                handoff=handoff, legs=(), operator_id=1,
                adapter=StubOrderPlacementAdapter(), execution_leg_repository=repo,
            )
