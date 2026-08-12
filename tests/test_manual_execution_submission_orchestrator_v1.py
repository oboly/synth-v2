"""Tests for src/executor/manual_execution_submission_orchestrator_v1.py
(Issue #369) — crash-safe per-leg manual SELL ladder submission."""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from src.execution_planner.manual_execution_plan_snapshot_v1 import ManualExecutionPlanSnapshot
from src.executor.manual_execution_handoff_v1 import (
    CLAIM_STATE_CLAIMED,
    CLAIM_STATE_CONSUMED,
    ExecutorHandoffDeniedError,
    ManualExecutionExecutorHandoff,
)
from src.executor.manual_execution_stub_order_adapter_v1 import (
    StubOrderPlacementAdapter,
    rejected,
    uncertain_once,
)
from src.executor.manual_execution_submission_leg_v1 import (
    ManualExecutionSubmissionLegRepository,
    STATE_REJECTED,
    STATE_SUBMISSION_UNCERTAIN,
    STATE_SUBMITTED,
)
from src.executor.manual_execution_submission_orchestrator_v1 import (
    OrderAck,
    SubmissionUncertainError,
    submit_manual_sell_ladder,
)
from src.manual_execution import _trusted_clock_v1 as trusted_clock
from tests.test_manual_execution_submission_leg_v1 import _FakeBackend, _FakeSession


NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trusted_clock, "utc_now", lambda: NOW)


def _repo(backend: _FakeBackend | None = None) -> tuple[ManualExecutionSubmissionLegRepository, _FakeBackend]:
    backend = backend or _FakeBackend()
    return ManualExecutionSubmissionLegRepository(cursor_factory=lambda **_: _FakeSession(backend)), backend


def _payload_json(legs: list[tuple[Decimal, Decimal]]) -> str:
    return json.dumps(
        {
            "legs": [
                {
                    "leg_index": idx,
                    "side": "SELL",
                    "target_price_eur": str(price),
                    "quantity_base": str(qty),
                }
                for idx, (price, qty) in enumerate(legs, start=1)
            ]
        }
    )


def _plan_snapshot(*, legs: list[tuple[Decimal, Decimal]], plan_snapshot_id: int = 701) -> ManualExecutionPlanSnapshot:
    return ManualExecutionPlanSnapshot(
        plan_snapshot_id=plan_snapshot_id, request_id=1, approval_id=1, trading_account_id=1,
        ladder_profile_id=1, ladder_profile_version=1, anchor_type="X", anchor_price=Decimal("1"),
        anchor_source="x", source_map_cycle_id="c", source_native_map_id="m", source_map_version="v",
        provenance_id=1, market="BTC-EUR", side="SELL", quantity_policy="LADDER_LEVELS",
        approved_quantity_base=Decimal("1"), planner_version="v1",
        payload_json=_payload_json(legs),
    )


def _handoff(**overrides: Any) -> ManualExecutionExecutorHandoff:
    defaults: dict[str, Any] = dict(
        handoff_id=1, request_id=1, approval_id=1, plan_snapshot_id=701,
        trading_account_id=1, venue="bitvavo", market="BTC-EUR", side="SELL",
        executor_mode="PAPER", executor_identity="executor-v1", runtime_owner="devlap",
        executor_credential_binding_id=1, claim_state=CLAIM_STATE_CLAIMED,
        claimed_ts_utc=NOW, consumed_ts_utc=None, outcome_code=None, outcome_detail=None,
        created_ts_utc=NOW,
    )
    defaults.update(overrides)
    return ManualExecutionExecutorHandoff(**defaults)


THREE_LEGS = [(Decimal("50000"), Decimal("0.1")), (Decimal("51000"), Decimal("0.1")), (Decimal("52000"), Decimal("0.1"))]


def _client_order_id_for(leg_index: int) -> str:
    from src.executor.manual_execution_client_order_id_v1 import derive_client_order_id

    return derive_client_order_id(
        plan_snapshot_id=701, leg_index=leg_index, trading_account_id=1, venue="bitvavo", market="BTC-EUR"
    )


@dataclass
class _CapturingAdapter:
    calls: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def place_order(self, *, market, side, price, quantity, client_order_id, operator_id):
        with self._lock:
            self.calls.append((client_order_id, price, quantity, operator_id))
        return OrderAck(broker_order_id=f"order-{client_order_id[:8]}", broker_status="open")

    def find_order_by_client_order_id(self, *, market, client_order_id):
        return None


class TestHappyPath:
    def test_valid_sequential_multi_leg_ladder_all_accepted(self) -> None:
        repo, _backend = _repo()
        handoff = _handoff()
        plan_snapshot = _plan_snapshot(legs=THREE_LEGS)
        adapter = StubOrderPlacementAdapter()

        result = submit_manual_sell_ladder(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=777,
            adapter=adapter, submission_leg_repository=repo,
        )

        assert result.stopped_reason is None
        assert len(result.leg_outcomes) == 3
        assert all(o.submission_state == STATE_SUBMITTED for o in result.leg_outcomes)
        assert all(o.broker_order_id for o in result.leg_outcomes)

    def test_immutable_price_and_quantity_sent_unchanged(self) -> None:
        repo, _backend = _repo()
        handoff = _handoff()
        plan_snapshot = _plan_snapshot(legs=THREE_LEGS)
        adapter = _CapturingAdapter()

        submit_manual_sell_ladder(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=999,
            adapter=adapter, submission_leg_repository=repo,
        )

        assert len(adapter.calls) == 3
        for (client_order_id, price, quantity, operator_id), (expected_price, expected_qty) in zip(
            adapter.calls, THREE_LEGS
        ):
            assert price == expected_price
            assert quantity == expected_qty
            assert operator_id == 999

    def test_operator_id_included_in_every_call(self) -> None:
        repo, _backend = _repo()
        handoff = _handoff()
        plan_snapshot = _plan_snapshot(legs=THREE_LEGS[:1])
        adapter = _CapturingAdapter()

        submit_manual_sell_ladder(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=4242,
            adapter=adapter, submission_leg_repository=repo,
        )
        assert adapter.calls[0][3] == 4242

    def test_deterministic_client_order_id_used_for_broker_call(self) -> None:
        repo, _backend = _repo()
        handoff = _handoff()
        plan_snapshot = _plan_snapshot(legs=THREE_LEGS[:1])
        adapter = _CapturingAdapter()

        submit_manual_sell_ladder(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
            adapter=adapter, submission_leg_repository=repo,
        )
        assert adapter.calls[0][0] == _client_order_id_for(1)


class TestIdempotencyAndCrashSafety:
    def test_duplicate_invocation_cannot_submit_same_leg_twice(self) -> None:
        repo, _backend = _repo()
        handoff = _handoff()
        plan_snapshot = _plan_snapshot(legs=THREE_LEGS)
        adapter = _CapturingAdapter()

        submit_manual_sell_ladder(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
            adapter=adapter, submission_leg_repository=repo,
        )
        submit_manual_sell_ladder(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
            adapter=adapter, submission_leg_repository=repo,
        )

        assert len(adapter.calls) == 3  # not 6

    def test_crash_before_broker_call_is_safely_retried(self) -> None:
        repo, backend = _repo()
        handoff = _handoff()
        plan_snapshot = _plan_snapshot(legs=THREE_LEGS[:1])

        # Simulate a prior run that created the PREPARED row and then died
        # before ever calling the broker.
        repo.claim_prepared(
            handoff_id=1, plan_snapshot_id=701, leg_index=1, trading_account_id=1,
            venue="bitvavo", market="BTC-EUR", side="SELL",
            client_order_id=_client_order_id_for(1), operator_id=1,
            immutable_price=THREE_LEGS[0][0], immutable_quantity=THREE_LEGS[0][1],
        )

        adapter = _CapturingAdapter()
        result = submit_manual_sell_ladder(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
            adapter=adapter, submission_leg_repository=repo,
        )

        assert result.stopped_reason is None
        assert len(adapter.calls) == 1

    def test_concurrent_invocation_cannot_double_submit_same_leg(self) -> None:
        repo, backend = _repo()
        handoff = _handoff()
        plan_snapshot = _plan_snapshot(legs=THREE_LEGS[:1])
        adapter = _CapturingAdapter()

        def run() -> None:
            submit_manual_sell_ladder(
                handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
                adapter=adapter, submission_leg_repository=repo,
            )

        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(adapter.calls) == 1


class TestTimeoutAmbiguity:
    def test_timeout_marks_uncertain_and_stops_ladder(self) -> None:
        repo, _backend = _repo()
        handoff = _handoff()
        plan_snapshot = _plan_snapshot(legs=THREE_LEGS)
        adapter = StubOrderPlacementAdapter(
            script={_client_order_id_for(1): uncertain_once()}
        )

        result = submit_manual_sell_ladder(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
            adapter=adapter, submission_leg_repository=repo,
        )

        assert result.stopped_reason == STATE_SUBMISSION_UNCERTAIN
        assert len(result.leg_outcomes) == 1
        assert result.leg_outcomes[0].submission_state == STATE_SUBMISSION_UNCERTAIN

    def test_retry_after_timeout_reconciles_by_client_order_id_first(self) -> None:
        repo, _backend = _repo()
        handoff = _handoff()
        plan_snapshot = _plan_snapshot(legs=THREE_LEGS[:1])
        cid = _client_order_id_for(1)
        adapter = StubOrderPlacementAdapter(script={cid: uncertain_once()})

        first = submit_manual_sell_ladder(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
            adapter=adapter, submission_leg_repository=repo,
        )
        assert first.stopped_reason == STATE_SUBMISSION_UNCERTAIN

        # Broker confirms the order actually landed.
        adapter.confirmed[cid] = OrderAck(broker_order_id="broker-real-order", broker_status="open")

        second = submit_manual_sell_ladder(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
            adapter=adapter, submission_leg_repository=repo,
        )
        assert second.stopped_reason is None
        assert second.leg_outcomes[0].submission_state == STATE_SUBMITTED
        assert second.leg_outcomes[0].broker_order_id == "broker-real-order"

    def test_confirmed_absent_allows_exactly_one_resubmission(self) -> None:
        repo, _backend = _repo()
        handoff = _handoff()
        plan_snapshot = _plan_snapshot(legs=THREE_LEGS[:1])
        cid = _client_order_id_for(1)
        adapter = StubOrderPlacementAdapter(script={cid: uncertain_once()})

        first = submit_manual_sell_ladder(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
            adapter=adapter, submission_leg_repository=repo,
        )
        assert first.stopped_reason == STATE_SUBMISSION_UNCERTAIN
        # adapter.confirmed has no entry for cid -> find_order_by_client_order_id
        # returns None (definitively absent) on the next reconcile.

        second = submit_manual_sell_ladder(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
            adapter=adapter, submission_leg_repository=repo,
        )
        assert second.stopped_reason is None
        assert second.leg_outcomes[0].submission_state == STATE_SUBMITTED

    def test_unresolved_ambiguity_remains_fail_closed(self) -> None:
        repo, _backend = _repo()
        handoff = _handoff()
        plan_snapshot = _plan_snapshot(legs=THREE_LEGS[:1])
        cid = _client_order_id_for(1)

        class _AlwaysUncertainAdapter:
            def place_order(self, **_kwargs):
                raise SubmissionUncertainError("STUB_TIMEOUT")

            def find_order_by_client_order_id(self, **_kwargs):
                raise SubmissionUncertainError("STUB_RECONCILE_TIMEOUT")

        adapter = _AlwaysUncertainAdapter()

        first = submit_manual_sell_ladder(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
            adapter=adapter, submission_leg_repository=repo,
        )
        second = submit_manual_sell_ladder(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
            adapter=adapter, submission_leg_repository=repo,
        )

        assert first.stopped_reason == STATE_SUBMISSION_UNCERTAIN
        assert second.stopped_reason == STATE_SUBMISSION_UNCERTAIN
        leg = repo.find_by_plan_and_leg(plan_snapshot_id=701, leg_index=1)
        assert leg.submission_state == STATE_SUBMISSION_UNCERTAIN
        assert leg.broker_order_id is None


class TestPartialLadderBehavior:
    def test_middle_leg_rejection_leaves_earlier_accepted_and_later_unsubmitted(self) -> None:
        repo, _backend = _repo()
        handoff = _handoff()
        plan_snapshot = _plan_snapshot(legs=THREE_LEGS)
        adapter = StubOrderPlacementAdapter(
            script={_client_order_id_for(2): rejected("BROKER_REJECTED_HTTP_400")}
        )

        result = submit_manual_sell_ladder(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
            adapter=adapter, submission_leg_repository=repo,
        )

        assert len(result.leg_outcomes) == 2
        assert result.leg_outcomes[0].submission_state == STATE_SUBMITTED
        assert result.leg_outcomes[1].submission_state == STATE_REJECTED
        assert result.stopped_reason == STATE_REJECTED
        # leg 3 was never attempted: no persisted row at all.
        assert repo.find_by_plan_and_leg(plan_snapshot_id=701, leg_index=3) is None


class TestArchitectureGuards:
    def test_rejects_a_handoff_that_is_not_claimed(self) -> None:
        repo, _backend = _repo()
        handoff = _handoff(claim_state=CLAIM_STATE_CONSUMED)
        plan_snapshot = _plan_snapshot(legs=THREE_LEGS[:1])
        adapter = StubOrderPlacementAdapter()

        with pytest.raises(ExecutorHandoffDeniedError, match="HANDOFF_NOT_CLAIMED"):
            submit_manual_sell_ladder(
                handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
                adapter=adapter, submission_leg_repository=repo,
            )

    def test_rejects_mismatched_plan_snapshot(self) -> None:
        repo, _backend = _repo()
        handoff = _handoff(plan_snapshot_id=701)
        plan_snapshot = _plan_snapshot(legs=THREE_LEGS[:1], plan_snapshot_id=702)
        adapter = StubOrderPlacementAdapter()

        with pytest.raises(ValueError, match="HANDOFF_PLAN_SNAPSHOT_MISMATCH"):
            submit_manual_sell_ladder(
                handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
                adapter=adapter, submission_leg_repository=repo,
            )
