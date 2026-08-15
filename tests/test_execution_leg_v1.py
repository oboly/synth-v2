"""Tests for src/executor/execution_leg_v1.py (Issue #206).

Exports _FakeBackend/_FakeSession for reuse by
tests/test_execution_submission_orchestrator_v1.py, mirroring the existing
tests.test_manual_execution_submission_leg_v1 cross-file reuse pattern.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pymysql
import pytest

from src.executor import _trusted_clock_v1 as trusted_clock
from src.executor.execution_leg_v1 import (
    ACCEPTED_STATES,
    ExecutionLegRepository,
    STATE_ACTIVE,
    STATE_CANCELED,
    STATE_FILLED,
    STATE_PARTIALLY_FILLED,
    STATE_PREPARED,
    STATE_RECONCILIATION_REQUIRED,
    STATE_REJECTED,
    STATE_SUBMISSION_UNCERTAIN,
    SubmissionLegConflictError,
    TERMINAL_FAILURE_STATES,
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

        if sql_norm.startswith("INSERT INTO executor_execution_leg"):
            (
                handoff_id, leg_index, trading_account_id, venue, market, side,
                client_order_id, operator_id, immutable_price, immutable_quantity,
                submission_state,
            ) = params
            with backend.lock:
                key = (handoff_id, leg_index)
                if key in backend.rows_by_leg:
                    raise pymysql.err.IntegrityError(1062, "duplicate")
                if client_order_id in backend.client_order_ids:
                    raise pymysql.err.IntegrityError(1062, "duplicate")
                new_id = backend.next_id
                backend.next_id += 1
                row = {
                    "executor_execution_leg_id": new_id,
                    "executor_execution_handoff_id": handoff_id,
                    "leg_index": leg_index,
                    "trading_account_id": trading_account_id,
                    "venue": venue,
                    "market": market,
                    "side": side,
                    "client_order_id": client_order_id,
                    "operator_id": operator_id,
                    "immutable_price": immutable_price,
                    "immutable_quantity": immutable_quantity,
                    "submission_state": submission_state,
                    "broker_order_id": None,
                    "broker_status": None,
                    "attempt_started_ts_utc": None,
                    "broker_ack_ts_utc": None,
                    "last_reconciled_ts_utc": None,
                    "reconciled_by": None,
                    "safe_error_code": None,
                    "created_ts_utc": NOW,
                }
                backend.rows_by_id[new_id] = row
                backend.rows_by_leg[key] = row
                backend.client_order_ids.add(client_order_id)
                self.lastrowid = new_id
            return

        if sql_norm.startswith(
            "SELECT * FROM executor_execution_leg WHERE executor_execution_leg_id"
        ):
            (execution_leg_id,) = params
            with backend.lock:
                row = backend.rows_by_id.get(execution_leg_id)
                self._result = [dict(row)] if row else []
            return

        if sql_norm.startswith(
            "SELECT * FROM executor_execution_leg "
            "WHERE executor_execution_handoff_id = %s AND leg_index = %s"
        ):
            handoff_id, leg_index = params
            with backend.lock:
                row = backend.rows_by_leg.get((handoff_id, leg_index))
                self._result = [dict(row)] if row else []
            return

        if sql_norm.startswith(
            "UPDATE executor_execution_leg SET submission_state = %s, attempt_started_ts_utc = %s"
        ):
            new_state, started, execution_leg_id, required_state = params
            with backend.lock:
                row = backend.rows_by_id.get(execution_leg_id)
                if row is not None and row["submission_state"] == required_state:
                    row["submission_state"] = new_state
                    row["attempt_started_ts_utc"] = started
                    self.rowcount = 1
                else:
                    self.rowcount = 0
            return

        if sql_norm.startswith(
            "UPDATE executor_execution_leg SET submission_state = %s, broker_order_id = %s"
        ):
            (
                new_state, broker_order_id, broker_status, ack_ts, safe_error_code,
                execution_leg_id, required_state,
            ) = params
            with backend.lock:
                row = backend.rows_by_id.get(execution_leg_id)
                if row is not None and row["submission_state"] == required_state:
                    row["submission_state"] = new_state
                    row["broker_order_id"] = broker_order_id
                    row["broker_status"] = broker_status
                    row["broker_ack_ts_utc"] = ack_ts
                    row["safe_error_code"] = safe_error_code
                    self.rowcount = 1
                else:
                    self.rowcount = 0
            return

        if sql_norm.startswith(
            "UPDATE executor_execution_leg SET submission_state = %s, last_reconciled_ts_utc = %s"
        ):
            new_state, reconciled_ts, execution_leg_id, required_state = params
            with backend.lock:
                row = backend.rows_by_id.get(execution_leg_id)
                if row is not None and row["submission_state"] == required_state:
                    row["submission_state"] = new_state
                    row["last_reconciled_ts_utc"] = reconciled_ts
                    self.rowcount = 1
                else:
                    self.rowcount = 0
            return

        if sql_norm.startswith(
            "UPDATE executor_execution_leg SET submission_state = %s, reconciled_by = %s"
        ):
            (
                new_state, reconciled_by, reconciled_ts, execution_leg_id, required_state,
            ) = params
            with backend.lock:
                row = backend.rows_by_id.get(execution_leg_id)
                if row is not None and row["submission_state"] == required_state:
                    row["submission_state"] = new_state
                    row["reconciled_by"] = reconciled_by
                    row["last_reconciled_ts_utc"] = reconciled_ts
                    self.rowcount = 1
                else:
                    self.rowcount = 0
            return

        if sql_norm.startswith("UPDATE executor_execution_leg SET last_reconciled_ts_utc"):
            reconciled_ts, execution_leg_id = params
            with backend.lock:
                row = backend.rows_by_id.get(execution_leg_id)
                if row is not None:
                    row["last_reconciled_ts_utc"] = reconciled_ts
            return

        raise AssertionError(f"unexpected SQL in fake execution leg cursor: {sql_norm}")

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
        self.rows_by_leg: dict[tuple, dict] = {}
        self.client_order_ids: set[str] = set()
        self.next_id = 1
        self.lock = threading.Lock()


def _repo(backend: _FakeBackend | None = None) -> tuple[ExecutionLegRepository, _FakeBackend]:
    backend = backend or _FakeBackend()
    return ExecutionLegRepository(cursor_factory=lambda **_: _FakeSession(backend)), backend


def _claim(repo: ExecutionLegRepository, *, side: str = "SELL", leg_index: int = 1, client_order_id: str = "cid-1"):
    return repo.claim_prepared(
        handoff_id=1, leg_index=leg_index, trading_account_id=1,
        venue="bitvavo", market="BTC-EUR", side=side, client_order_id=client_order_id,
        operator_id=777, immutable_price=Decimal("50000"), immutable_quantity=Decimal("0.1"),
    )


class TestClaimPrepared:
    def test_first_claim_creates_row(self) -> None:
        repo, backend = _repo()
        leg, created = _claim(repo)
        assert created is True
        assert leg.submission_state == STATE_PREPARED
        assert len(backend.rows_by_id) == 1

    def test_retry_claim_is_idempotent(self) -> None:
        repo, backend = _repo()
        first, created_first = _claim(repo)
        second, created_second = _claim(repo)
        assert created_first is True
        assert created_second is False
        assert first.execution_leg_id == second.execution_leg_id

    def test_conflicting_identity_on_retry_fails_closed(self) -> None:
        repo, _ = _repo()
        _claim(repo)
        with pytest.raises(SubmissionLegConflictError):
            repo.claim_prepared(
                handoff_id=1, leg_index=1, trading_account_id=1,
                venue="bitvavo", market="BTC-EUR", side="SELL", client_order_id="cid-1",
                operator_id=777, immutable_price=Decimal("99999"), immutable_quantity=Decimal("0.1"),
            )

    def test_buy_side_accepted_side_neutral(self) -> None:
        repo, _ = _repo()
        leg, created = _claim(repo, side="BUY")
        assert created is True
        assert leg.side == "BUY"

    def test_unknown_side_rejected(self) -> None:
        repo, _ = _repo()
        with pytest.raises(ValueError):
            repo.claim_prepared(
                handoff_id=1, leg_index=1, trading_account_id=1,
                venue="bitvavo", market="BTC-EUR", side="HOLD", client_order_id="cid-1",
                operator_id=777, immutable_price=Decimal("1"), immutable_quantity=Decimal("1"),
            )


class TestBeginAttempt:
    def test_transitions_prepared_to_uncertain_and_wins(self) -> None:
        repo, _ = _repo()
        leg, _ = _claim(repo)
        updated, won = repo.begin_attempt(leg.execution_leg_id)
        assert won is True
        assert updated.submission_state == STATE_SUBMISSION_UNCERTAIN

    def test_second_attempt_loses(self) -> None:
        repo, _ = _repo()
        leg, _ = _claim(repo)
        repo.begin_attempt(leg.execution_leg_id)
        _second, won = repo.begin_attempt(leg.execution_leg_id)
        assert won is False

    def test_concurrent_begin_attempt_only_one_winner(self) -> None:
        repo, _ = _repo()
        leg, _ = _claim(repo)
        results: list[bool] = []
        lock = threading.Lock()

        def run() -> None:
            _leg, won = repo.begin_attempt(leg.execution_leg_id)
            with lock:
                results.append(won)

        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert sum(results) == 1


class TestResolveAccepted:
    def test_accepts_active_partial_and_filled_states(self) -> None:
        for state in (STATE_ACTIVE, STATE_PARTIALLY_FILLED, STATE_FILLED):
            repo, _ = _repo()
            leg, _ = _claim(repo)
            repo.begin_attempt(leg.execution_leg_id)
            resolved = repo.resolve_accepted(
                leg.execution_leg_id, new_state=state, broker_order_id="b-1", broker_status="raw"
            )
            assert resolved.submission_state == state
            assert state in ACCEPTED_STATES

    def test_rejects_non_accepted_state(self) -> None:
        repo, _ = _repo()
        leg, _ = _claim(repo)
        repo.begin_attempt(leg.execution_leg_id)
        with pytest.raises(ValueError):
            repo.resolve_accepted(
                leg.execution_leg_id, new_state=STATE_CANCELED, broker_order_id="b-1", broker_status="raw"
            )


class TestResolveClosed:
    def test_canceled_expired_rejected_never_accepted(self) -> None:
        for state in (STATE_CANCELED, STATE_REJECTED):
            repo, _ = _repo()
            leg, _ = _claim(repo)
            repo.begin_attempt(leg.execution_leg_id)
            resolved = repo.resolve_closed(
                leg.execution_leg_id, new_state=state, safe_error_code=f"BROKER_{state}",
                broker_order_id="b-1", broker_status="raw",
            )
            assert resolved.submission_state == state
            assert state in TERMINAL_FAILURE_STATES
            assert resolved.submission_state not in ACCEPTED_STATES

    def test_rejects_accepted_state_via_closed_path(self) -> None:
        repo, _ = _repo()
        leg, _ = _claim(repo)
        repo.begin_attempt(leg.execution_leg_id)
        with pytest.raises(ValueError):
            repo.resolve_closed(
                leg.execution_leg_id, new_state=STATE_ACTIVE, safe_error_code="X"
            )


class TestReconciliationRequired:
    def test_marks_reconciliation_required_from_uncertain(self) -> None:
        repo, _ = _repo()
        leg, _ = _claim(repo)
        repo.begin_attempt(leg.execution_leg_id)
        resolved = repo.mark_reconciliation_required(leg.execution_leg_id)
        assert resolved.submission_state == STATE_RECONCILIATION_REQUIRED

    def test_rearm_requires_nonempty_operator(self) -> None:
        repo, _ = _repo()
        leg, _ = _claim(repo)
        repo.begin_attempt(leg.execution_leg_id)
        repo.mark_reconciliation_required(leg.execution_leg_id)
        with pytest.raises(ValueError):
            repo.rearm_after_reconciliation(leg.execution_leg_id, reconciled_by="  ")

    def test_rearm_moves_back_to_prepared_and_records_audit(self) -> None:
        repo, _ = _repo()
        leg, _ = _claim(repo)
        repo.begin_attempt(leg.execution_leg_id)
        repo.mark_reconciliation_required(leg.execution_leg_id)
        resolved, won = repo.rearm_after_reconciliation(leg.execution_leg_id, reconciled_by="ops-alice")
        assert won is True
        assert resolved.submission_state == STATE_PREPARED
        assert resolved.reconciled_by == "ops-alice"

    def test_rearm_from_wrong_state_loses(self) -> None:
        repo, _ = _repo()
        leg, _ = _claim(repo)
        # still PREPARED -- never entered RECONCILIATION_REQUIRED
        _resolved, won = repo.rearm_after_reconciliation(leg.execution_leg_id, reconciled_by="ops-alice")
        assert won is False
