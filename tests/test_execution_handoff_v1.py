"""Tests for src/executor/execution_handoff_v1.py (Issue #206).

Covers the side-neutral canonical executor handoff shared by algorithmic
BUY and SELL: identity binding, plan_content_hash conflict detection,
credential denial, and claim/consume/fail lifecycle.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from src.executor import _trusted_clock_v1 as trusted_clock
from src.executor.execution_handoff_v1 import (
    CLAIM_STATE_CLAIMED,
    CLAIM_STATE_CONSUMED,
    DuplicateExecutionHandoffClaimError,
    ExecutionHandoffDeniedError,
    ExecutionHandoffIdentityConflictError,
    ExecutionHandoffRepository,
    OUTCOME_PAPER_ACKNOWLEDGED,
    RUNTIME_MODE_LIVE_DISABLED,
    RUNTIME_MODE_PAPER,
)
from src.executor.execution_plan_reference_v1 import (
    ApprovedExecutionPlanLegV1,
    ApprovedExecutionPlanV1,
)
from src.executor.manual_execution_credential_scope_v1 import (
    CredentialScopeBinding,
    CredentialScopeDeniedError,
)


NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trusted_clock, "utc_now", lambda: NOW)


class _FakeCursor:
    def __init__(self, backend: "_FakeBackend") -> None:
        self.backend = backend
        self._result: list[dict] = []
        self.lastrowid: int | None = None
        self.rowcount = 0

    def execute(self, sql: str, params: list) -> None:
        sql_norm = " ".join(sql.split())
        backend = self.backend

        if sql_norm.startswith("INSERT INTO executor_execution_handoff"):
            (
                plan_source, plan_reference_id, plan_content_hash,
                trading_account_id, venue, market, side, executor_mode,
                executor_identity, runtime_owner, executor_credential_binding_id,
                claim_state, claimed_ts_utc,
            ) = params
            with backend.lock:
                key = (plan_source, plan_reference_id)
                existing_id = backend.rows_by_reference.get(key)
                if existing_id is not None:
                    self.lastrowid = existing_id
                else:
                    new_id = backend.next_id
                    backend.next_id += 1
                    backend.rows_by_id[new_id] = {
                        "executor_execution_handoff_id": new_id,
                        "plan_source": plan_source,
                        "plan_reference_id": plan_reference_id,
                        "plan_content_hash": plan_content_hash,
                        "trading_account_id": trading_account_id,
                        "venue": venue,
                        "market": market,
                        "side": side,
                        "executor_mode": executor_mode,
                        "executor_identity": executor_identity,
                        "runtime_owner": runtime_owner,
                        "executor_credential_binding_id": executor_credential_binding_id,
                        "claim_state": claim_state,
                        "claimed_ts_utc": claimed_ts_utc,
                        "consumed_ts_utc": None,
                        "outcome_code": None,
                        "outcome_detail": None,
                        "created_ts_utc": NOW,
                    }
                    backend.rows_by_reference[key] = new_id
                    self.lastrowid = new_id
            return

        if sql_norm.startswith(
            "SELECT * FROM executor_execution_handoff WHERE executor_execution_handoff_id"
        ):
            (handoff_id,) = params
            with backend.lock:
                row = backend.rows_by_id.get(handoff_id)
                self._result = [dict(row)] if row else []
            return

        if sql_norm.startswith("UPDATE executor_execution_handoff SET claim_state"):
            new_state, consumed_ts, outcome_code, outcome_detail, handoff_id, required_state = params
            with backend.lock:
                row = backend.rows_by_id.get(handoff_id)
                if row is not None and row["claim_state"] == required_state:
                    row["claim_state"] = new_state
                    row["consumed_ts_utc"] = consumed_ts
                    row["outcome_code"] = outcome_code
                    row["outcome_detail"] = outcome_detail
                    self.rowcount = 1
                else:
                    self.rowcount = 0
            return

        raise AssertionError(f"unexpected SQL in fake execution handoff cursor: {sql_norm}")

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result


class _FakeSession:
    def __init__(self, backend: "_FakeBackend") -> None:
        self.backend = backend

    def __enter__(self) -> _FakeCursor:
        return _FakeCursor(self.backend)

    def __exit__(self, *exc: Any) -> bool:
        return False


class _FakeBackend:
    def __init__(self) -> None:
        self.rows_by_id: dict[int, dict] = {}
        self.rows_by_reference: dict[tuple, int] = {}
        self.next_id = 1
        self.lock = threading.Lock()


class _AllowingCredentialScopeStub:
    """Stands in for ExecutorCredentialScopeRepository.resolve() without
    exercising the (already SHARED_GENERIC, unchanged) real SQL join."""

    def __init__(self, binding_id: int = 501) -> None:
        self.binding_id = binding_id
        self.calls: list[dict] = []

    def resolve(self, **kwargs) -> CredentialScopeBinding:
        self.calls.append(kwargs)
        return CredentialScopeBinding(
            executor_credential_binding_id=self.binding_id,
            trading_account_credential_id=1,
            trading_account_id=kwargs["trading_account_id"],
            venue=kwargs["venue"],
            permission_scope="TRADE_EXECUTION",
            executor_identity=kwargs["executor_identity"],
            runtime_owner=kwargs["runtime_owner"],
            credential_status="ACTIVE",
            credential_source="test",
            allowed_order_write=True,
            allowed_withdrawal=False,
        )


class _DenyingCredentialScopeStub:
    def resolve(self, **kwargs) -> CredentialScopeBinding:
        raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_NOT_BOUND: test denial")


def _plan(*, side: str = "SELL", plan_reference_id: str = "ref-1") -> ApprovedExecutionPlanV1:
    return ApprovedExecutionPlanV1(
        plan_source="AUTOMATIC_EXIT_PLAN_V1",
        plan_reference_id=plan_reference_id,
        trading_account_id=1,
        venue="bitvavo",
        market="BTC-EUR",
        side=side,
        legs=(
            ApprovedExecutionPlanLegV1(leg_index=1, side=side, price=Decimal("50000"), quantity=Decimal("0.1")),
        ),
    )


def _repo(*, backend: _FakeBackend | None = None, credential_repo=None) -> tuple[ExecutionHandoffRepository, _FakeBackend]:
    backend = backend or _FakeBackend()
    repo = ExecutionHandoffRepository(
        cursor_factory=lambda **_: _FakeSession(backend),
        credential_scope_repository=credential_repo or _AllowingCredentialScopeStub(),
    )
    return repo, backend


class TestIntakeHappyPath:
    def test_sell_plan_intake_creates_handoff(self) -> None:
        repo, backend = _repo()
        handoff = repo.intake(
            plan=_plan(side="SELL"), executor_mode=RUNTIME_MODE_PAPER,
            executor_identity="algo-exit-v1", runtime_owner="odroid",
        )
        assert handoff.side == "SELL"
        assert handoff.claim_state == CLAIM_STATE_CLAIMED
        assert len(backend.rows_by_id) == 1

    def test_buy_plan_intake_uses_the_same_repository_class(self) -> None:
        repo, _ = _repo()
        handoff = repo.intake(
            plan=_plan(side="BUY", plan_reference_id="ref-buy-1"), executor_mode=RUNTIME_MODE_PAPER,
            executor_identity="algo-entry-v1", runtime_owner="odroid",
        )
        assert handoff.side == "BUY"

    def test_retry_intake_is_idempotent(self) -> None:
        repo, backend = _repo()
        plan = _plan()
        first = repo.intake(plan=plan, executor_mode=RUNTIME_MODE_PAPER, executor_identity="a", runtime_owner="odroid")
        second = repo.intake(plan=plan, executor_mode=RUNTIME_MODE_PAPER, executor_identity="a", runtime_owner="odroid")
        assert first.handoff_id == second.handoff_id
        assert len(backend.rows_by_id) == 1

    def test_retry_with_different_plan_content_same_reference_fails_closed(self) -> None:
        repo, _ = _repo()
        plan_a = _plan(plan_reference_id="ref-shared")
        repo.intake(plan=plan_a, executor_mode=RUNTIME_MODE_PAPER, executor_identity="a", runtime_owner="odroid")
        plan_b = ApprovedExecutionPlanV1(
            plan_source="AUTOMATIC_EXIT_PLAN_V1", plan_reference_id="ref-shared",
            trading_account_id=1, venue="bitvavo", market="BTC-EUR", side="SELL",
            legs=(ApprovedExecutionPlanLegV1(leg_index=1, side="SELL", price=Decimal("999999"), quantity=Decimal("0.1")),),
        )
        with pytest.raises(ExecutionHandoffIdentityConflictError):
            repo.intake(plan=plan_b, executor_mode=RUNTIME_MODE_PAPER, executor_identity="a", runtime_owner="odroid")


class TestIntakeDenials:
    def test_live_disabled_mode_denied(self) -> None:
        repo, _ = _repo()
        with pytest.raises(ExecutionHandoffDeniedError, match="EXECUTOR_MODE_NOT_PERMITTED_FOR_INTAKE"):
            repo.intake(
                plan=_plan(), executor_mode=RUNTIME_MODE_LIVE_DISABLED,
                executor_identity="a", runtime_owner="odroid",
            )

    def test_unknown_mode_denied(self) -> None:
        repo, _ = _repo()
        with pytest.raises(ExecutionHandoffDeniedError, match="UNKNOWN_EXECUTOR_MODE"):
            repo.intake(plan=_plan(), executor_mode="LIVE", executor_identity="a", runtime_owner="odroid")

    def test_missing_executor_identity_denied(self) -> None:
        repo, _ = _repo()
        with pytest.raises(ExecutionHandoffDeniedError, match="EXECUTOR_IDENTITY_REQUIRED"):
            repo.intake(plan=_plan(), executor_mode=RUNTIME_MODE_PAPER, executor_identity=" ", runtime_owner="odroid")

    def test_credential_denial_propagates_fail_closed(self) -> None:
        repo, _ = _repo(credential_repo=_DenyingCredentialScopeStub())
        with pytest.raises(ExecutionHandoffDeniedError, match="CREDENTIAL_SCOPE_NOT_BOUND"):
            repo.intake(plan=_plan(), executor_mode=RUNTIME_MODE_PAPER, executor_identity="a", runtime_owner="odroid")


class TestClaimLifecycle:
    def test_consume_transitions_claimed_to_consumed(self) -> None:
        repo, _ = _repo()
        handoff = repo.intake(plan=_plan(), executor_mode=RUNTIME_MODE_PAPER, executor_identity="a", runtime_owner="odroid")
        resolved = repo.consume(handoff.handoff_id, outcome_code=OUTCOME_PAPER_ACKNOWLEDGED)
        assert resolved.claim_state == CLAIM_STATE_CONSUMED

    def test_double_consume_with_different_outcome_conflicts(self) -> None:
        repo, _ = _repo()
        handoff = repo.intake(plan=_plan(), executor_mode=RUNTIME_MODE_PAPER, executor_identity="a", runtime_owner="odroid")
        repo.consume(handoff.handoff_id, outcome_code="A")
        with pytest.raises(DuplicateExecutionHandoffClaimError):
            repo.consume(handoff.handoff_id, outcome_code="B")

    def test_concurrent_consume_only_one_winner_semantics(self) -> None:
        repo, _ = _repo()
        handoff = repo.intake(plan=_plan(), executor_mode=RUNTIME_MODE_PAPER, executor_identity="a", runtime_owner="odroid")
        results: list[str] = []
        lock = threading.Lock()

        def run() -> None:
            resolved = repo.consume(handoff.handoff_id, outcome_code="SAME")
            with lock:
                results.append(resolved.claim_state)

        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert all(state == CLAIM_STATE_CONSUMED for state in results)
