"""Tests for src/executor/manual_execution_submission_leg_v1.py (Issue #369)."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pymysql
import pytest

from src.executor import manual_execution_submission_leg_v1 as leg_module
from src.executor.manual_execution_submission_leg_v1 import (
    ManualExecutionSubmissionLegRepository,
    STATE_PREPARED,
    STATE_REJECTED,
    STATE_SUBMISSION_UNCERTAIN,
    STATE_SUBMITTED,
    SubmissionLegConflictError,
)
from src.manual_execution import _trusted_clock_v1 as trusted_clock


NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)


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

        if sql_norm.startswith("INSERT INTO manual_execution_submission_leg"):
            (
                handoff_id, plan_snapshot_id, leg_index, trading_account_id, venue,
                market, side, client_order_id, operator_id, immutable_price,
                immutable_quantity, submission_state,
            ) = params
            with backend.lock:
                key = (plan_snapshot_id, leg_index)
                if key in backend.rows_by_leg:
                    raise pymysql.err.IntegrityError(1062, "duplicate")
                if client_order_id in backend.client_order_ids:
                    raise pymysql.err.IntegrityError(1062, "duplicate")
                new_id = backend.next_id
                backend.next_id += 1
                row = {
                    "submission_leg_id": new_id,
                    "manual_execution_executor_handoff_id": handoff_id,
                    "manual_execution_plan_snapshot_id": plan_snapshot_id,
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
                    "safe_error_code": None,
                    "created_ts_utc": NOW,
                }
                backend.rows_by_id[new_id] = row
                backend.rows_by_leg[key] = row
                backend.client_order_ids.add(client_order_id)
                self.lastrowid = new_id
            return

        if sql_norm.startswith("SELECT * FROM manual_execution_submission_leg WHERE submission_leg_id"):
            (submission_leg_id,) = params
            with backend.lock:
                row = backend.rows_by_id.get(submission_leg_id)
                self._result = [dict(row)] if row else []
            return

        if sql_norm.startswith(
            "SELECT * FROM manual_execution_submission_leg "
            "WHERE manual_execution_plan_snapshot_id = %s AND leg_index = %s"
        ):
            plan_snapshot_id, leg_index = params
            with backend.lock:
                row = backend.rows_by_leg.get((plan_snapshot_id, leg_index))
                self._result = [dict(row)] if row else []
            return

        if sql_norm.startswith(
            "UPDATE manual_execution_submission_leg SET submission_state = %s, "
            "attempt_started_ts_utc = %s"
        ):
            new_state, started, submission_leg_id, required_state = params
            with backend.lock:
                row = backend.rows_by_id.get(submission_leg_id)
                if row is not None and row["submission_state"] == required_state:
                    row["submission_state"] = new_state
                    row["attempt_started_ts_utc"] = started
                    self.rowcount = 1
                else:
                    self.rowcount = 0
            return

        if sql_norm.startswith(
            "UPDATE manual_execution_submission_leg SET submission_state = %s, "
            "broker_order_id = %s"
        ):
            (
                new_state, broker_order_id, broker_status, ack_ts, safe_error_code,
                submission_leg_id, required_state,
            ) = params
            with backend.lock:
                row = backend.rows_by_id.get(submission_leg_id)
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

        if sql_norm.startswith("UPDATE manual_execution_submission_leg SET submission_state = %s"):
            new_state, submission_leg_id, required_state = params
            with backend.lock:
                row = backend.rows_by_id.get(submission_leg_id)
                if row is not None and row["submission_state"] == required_state:
                    row["submission_state"] = new_state
                    self.rowcount = 1
                else:
                    self.rowcount = 0
            return

        if sql_norm.startswith("UPDATE manual_execution_submission_leg SET last_reconciled_ts_utc"):
            reconciled_ts, submission_leg_id = params
            with backend.lock:
                row = backend.rows_by_id.get(submission_leg_id)
                if row is not None:
                    row["last_reconciled_ts_utc"] = reconciled_ts
            return

        raise AssertionError(f"unexpected SQL in fake submission leg cursor: {sql_norm}")

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


def _repo(backend: _FakeBackend | None = None) -> tuple[ManualExecutionSubmissionLegRepository, _FakeBackend]:
    backend = backend or _FakeBackend()
    repo = ManualExecutionSubmissionLegRepository(cursor_factory=lambda **_: _FakeSession(backend))
    return repo, backend


def _claim(repo: ManualExecutionSubmissionLegRepository, *, leg_index: int = 1, client_order_id: str = "cid-1"):
    return repo.claim_prepared(
        handoff_id=1, plan_snapshot_id=701, leg_index=leg_index, trading_account_id=1,
        venue="bitvavo", market="BTC-EUR", side="SELL", client_order_id=client_order_id,
        operator_id=777, immutable_price=Decimal("50000"), immutable_quantity=Decimal("0.1"),
    )


class TestClaimPrepared:
    def test_first_claim_creates_row(self) -> None:
        repo, backend = _repo()
        leg, created = _claim(repo)
        assert created is True
        assert leg.submission_state == STATE_PREPARED
        assert leg.immutable_price == Decimal("50000")
        assert len(backend.rows_by_id) == 1

    def test_retry_claim_is_idempotent_not_duplicated(self) -> None:
        repo, backend = _repo()
        first, created_first = _claim(repo)
        second, created_second = _claim(repo)
        assert created_first is True
        assert created_second is False
        assert first.submission_leg_id == second.submission_leg_id
        assert len(backend.rows_by_id) == 1

    def test_conflicting_identity_on_retry_fails_closed(self) -> None:
        repo, backend = _repo()
        _claim(repo)
        with pytest.raises(SubmissionLegConflictError):
            repo.claim_prepared(
                handoff_id=1, plan_snapshot_id=701, leg_index=1, trading_account_id=1,
                venue="bitvavo", market="BTC-EUR", side="SELL", client_order_id="cid-1",
                operator_id=777, immutable_price=Decimal("99999"), immutable_quantity=Decimal("0.1"),
            )

    def test_buy_side_rejected(self) -> None:
        repo, _ = _repo()
        with pytest.raises(ValueError):
            repo.claim_prepared(
                handoff_id=1, plan_snapshot_id=701, leg_index=1, trading_account_id=1,
                venue="bitvavo", market="BTC-EUR", side="BUY", client_order_id="cid-1",
                operator_id=777, immutable_price=Decimal("1"), immutable_quantity=Decimal("1"),
            )


class TestBeginAttempt:
    def test_transitions_prepared_to_uncertain_and_wins(self) -> None:
        repo, _ = _repo()
        leg, _ = _claim(repo)
        updated, won = repo.begin_attempt(leg.submission_leg_id)
        assert won is True
        assert updated.submission_state == STATE_SUBMISSION_UNCERTAIN
        assert updated.attempt_started_ts_utc == NOW

    def test_second_attempt_from_prepared_loses(self) -> None:
        repo, _ = _repo()
        leg, _ = _claim(repo)
        repo.begin_attempt(leg.submission_leg_id)
        _second, won = repo.begin_attempt(leg.submission_leg_id)
        assert won is False

    def test_concurrent_begin_attempt_only_one_winner(self) -> None:
        repo, backend = _repo()
        leg, _ = _claim(repo)

        results: dict[str, bool] = {}

        def run(name: str) -> None:
            _row, won = repo.begin_attempt(leg.submission_leg_id)
            results[name] = won

        threads = [threading.Thread(target=run, args=(f"t{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert sum(1 for w in results.values() if w) == 1


class TestResolution:
    def test_resolve_accepted_from_uncertain(self) -> None:
        repo, _ = _repo()
        leg, _ = _claim(repo)
        repo.begin_attempt(leg.submission_leg_id)
        resolved = repo.resolve_accepted(
            leg.submission_leg_id, new_state=STATE_SUBMITTED,
            broker_order_id="order-1", broker_status="open",
        )
        assert resolved.submission_state == STATE_SUBMITTED
        assert resolved.broker_order_id == "order-1"

    def test_resolve_rejected_from_uncertain(self) -> None:
        repo, _ = _repo()
        leg, _ = _claim(repo)
        repo.begin_attempt(leg.submission_leg_id)
        resolved = repo.resolve_rejected(leg.submission_leg_id, safe_error_code="BROKER_REJECTED_HTTP_400")
        assert resolved.submission_state == STATE_REJECTED
        assert resolved.safe_error_code == "BROKER_REJECTED_HTTP_400"

    def test_cannot_resolve_directly_from_prepared(self) -> None:
        repo, _ = _repo()
        leg, _ = _claim(repo)
        with pytest.raises(SubmissionLegConflictError):
            repo.resolve_accepted(
                leg.submission_leg_id, new_state=STATE_SUBMITTED,
                broker_order_id="order-1", broker_status="open",
            )

    def test_reset_to_prepared_only_from_uncertain(self) -> None:
        repo, _ = _repo()
        leg, _ = _claim(repo)
        repo.begin_attempt(leg.submission_leg_id)
        reset_leg, won = repo.reset_to_prepared(leg.submission_leg_id)
        assert won is True
        assert reset_leg.submission_state == STATE_PREPARED

        # Cannot reset twice (already PREPARED, not UNCERTAIN).
        _again, won_again = repo.reset_to_prepared(leg.submission_leg_id)
        assert won_again is False
