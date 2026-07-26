"""
Tests for src/decision_gate/manual_execution_gate_v1.py's approve_and_reserve():
the single atomic approval+reservation entrypoint.

Uses an in-memory fake DB backend that models the real locking primitive
(INSERT IGNORE + SELECT ... FOR UPDATE against manual_execution_sell_lock)
with a real threading.Lock per (trading_account_id, venue, asset_id) key, so
the concurrency test below exercises genuine OS-thread contention rather
than simulating it — no real MariaDB is used or required.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from src.manual_execution import _trusted_clock_v1 as trusted_clock
from src.decision_gate.manual_execution_gate_v1 import (
    GATE_DECISION_BLOCKED,
    GATE_DECISION_EXECUTION_ALLOWED,
    ManualExecutionGateRepository,
)
from src.manual_execution.manual_execution_request_v1 import (
    MODE_PAPER,
    QUANTITY_POLICY_FIXED_BASE_QUANTITY,
    QUANTITY_POLICY_FULL_AVAILABLE_BASE,
    SOURCE_OPERATOR_CLI,
    build_manual_execution_request,
)


NOW = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)
TRADING_ACCOUNT_ID = 1
VENUE = "bitvavo"
ASSET_ID = 42


@pytest.fixture(autouse=True)
def _fixed_manual_execution_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trusted_clock, "utc_now", lambda: NOW)


def _request(*, request_id: int, idempotency_key: str, **overrides):
    import dataclasses

    defaults = dict(
        idempotency_key=idempotency_key,
        created_ts_utc=NOW,
        source=SOURCE_OPERATOR_CLI,
        requested_by="joost",
        mode=MODE_PAPER,
        trading_account_id=TRADING_ACCOUNT_ID,
        account_code="paper_sell_only_preview",
        venue=VENUE,
        asset_id=ASSET_ID,
        base_asset="BTC",
        quote_asset="EUR",
        side="SELL",
        quantity_policy=QUANTITY_POLICY_FULL_AVAILABLE_BASE,
        provenance_id=77,
    )
    defaults.update(overrides)
    request = build_manual_execution_request(**defaults)
    return dataclasses.replace(request, request_id=request_id)


class _FakeBackend:
    def __init__(self, *, available_quantity: Decimal) -> None:
        self.account_rows = [
            {"trading_account_id": TRADING_ACCOUNT_ID, "enabled": 1, "live_trading_enabled": 0, "account_mode": "paper"}
        ]
        self.snapshot_rows = [
            {
                "account_position_snapshot_id": 9001,
                "trading_account_id": TRADING_ACCOUNT_ID,
                "venue": VENUE,
                "asset_id": ASSET_ID,
                "available_quantity_base": available_quantity,
                "quantity_base": available_quantity,
                "snapshot_ts_utc": NOW - timedelta(minutes=1),
                "source_name": "account_position_snapshot",
            }
        ]
        self.reservation_rows: list[dict] = []
        self.approval_rows: list[dict] = []
        self._reservation_next_id = 1
        self._approval_next_id = 501

        self._table_guard = threading.Lock()
        self._locks_guard = threading.Lock()
        self._locks: dict[tuple, threading.Lock] = {}

        self.fail_on_insert = False
        self.fail_on_approval_insert = False
        self.omit_approval_lastrowid = False
        self.returned_approval_id_offset = 0
        self.approval_read_mode = "NORMAL"
        self.approval_select_count = 0
        self.lock_acquired_events: list[str] = []

    def get_lock(self, key: tuple) -> threading.Lock:
        with self._locks_guard:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]


class _FakeSession:
    def __init__(self, backend: _FakeBackend) -> None:
        self.backend = backend
        self._result: list[dict] | None = None
        self.lastrowid: int | None = None
        self.held_locks: list[threading.Lock] = []
        self._reservation_snapshot: list[dict] = []
        self._approval_snapshot: list[dict] = []

    def execute(self, sql: str, params: list) -> None:
        sql_norm = " ".join(sql.split())
        backend = self.backend

        if sql_norm.startswith("INSERT IGNORE INTO manual_execution_sell_lock"):
            # No-op: real row existence isn't needed by the fake — the
            # Python threading.Lock keyed below models the FOR UPDATE wait.
            return

        if sql_norm.startswith("SELECT trading_account_id FROM manual_execution_sell_lock"):
            trading_account_id, venue, asset_id = params
            lock = backend.get_lock((trading_account_id, venue, asset_id))
            lock.acquire()  # blocks a concurrent session on the same key
            self.held_locks.append(lock)
            backend.lock_acquired_events.append(threading.current_thread().name)
            self._result = [{"trading_account_id": trading_account_id}]
            return

        if sql_norm.startswith("SELECT * FROM execution_sell_reservation WHERE idempotency_key"):
            (idempotency_key,) = params
            with backend._table_guard:
                self._result = [
                    dict(r) for r in backend.reservation_rows if r["idempotency_key"] == idempotency_key
                ]
            return

        if sql_norm.startswith("INSERT INTO execution_sell_reservation"):
            if backend.fail_on_insert:
                raise RuntimeError("simulated DB failure during reservation insert")
            (
                trading_account_id, venue, asset_id, symbol, idempotency_key,
                quantity_base, reservation_state, manual_execution_request_id,
                execution_plan_id, leg_number, notes,
            ) = params
            with backend._table_guard:
                new_id = backend._reservation_next_id
                backend._reservation_next_id += 1
                row = {
                    "reservation_id": new_id,
                    "trading_account_id": trading_account_id,
                    "venue": venue,
                    "asset_id": asset_id,
                    "symbol": symbol,
                    "idempotency_key": idempotency_key,
                    "quantity_base": quantity_base,
                    "reservation_state": reservation_state,
                    "manual_execution_request_id": manual_execution_request_id,
                    "execution_plan_id": execution_plan_id,
                    "leg_number": leg_number,
                    "broker_order_id": None,
                    "notes": notes,
                    "created_ts_utc": datetime.now(timezone.utc),
                    "updated_ts_utc": datetime.now(timezone.utc),
                    "terminal_ts_utc": None,
                }
                backend.reservation_rows.append(row)
            self.lastrowid = new_id
            return

        if sql_norm.startswith("SELECT * FROM execution_sell_reservation WHERE reservation_id"):
            (reservation_id,) = params
            with backend._table_guard:
                self._result = [
                    dict(r) for r in backend.reservation_rows if r["reservation_id"] == reservation_id
                ]
            return

        if sql_norm.startswith("INSERT INTO manual_execution_approval"):
            if backend.fail_on_approval_insert:
                raise RuntimeError("simulated DB failure during approval insert")
            (
                idempotency_key, request_id, trading_account_id, account_code,
                venue, asset_id, base_asset, quote_asset, side, quantity,
                snapshot_id, snapshot_version, reservation_id, approved_ts,
                expires_ts, mode, provenance_id, approval_state, decision_reason,
            ) = params
            reservation = next(
                row for row in backend.reservation_rows
                if row["reservation_id"] == reservation_id
            )
            snapshot = next(
                row for row in backend.snapshot_rows
                if row["account_position_snapshot_id"] == snapshot_id
            )
            approval_id = backend._approval_next_id
            backend._approval_next_id += 1
            backend.approval_rows.append(
                {
                    "manual_execution_approval_id": approval_id,
                    "idempotency_key": idempotency_key,
                    "manual_execution_request_id": request_id,
                    "trading_account_id": trading_account_id,
                    "account_code": account_code,
                    "venue": venue,
                    "asset_id": asset_id,
                    "base_asset": base_asset,
                    "quote_asset": quote_asset,
                    "side": side,
                    "approved_quantity_base": quantity,
                    "wallet_snapshot_id": snapshot_id,
                    "wallet_snapshot_version_ts_utc": snapshot_version,
                    "reservation_id": reservation_id,
                    "approved_ts_utc": approved_ts,
                    "expires_ts_utc": expires_ts,
                    "mode": mode,
                    "provenance_id": provenance_id,
                    "approval_state": approval_state,
                    "decision_reason": decision_reason,
                    "persisted_reservation_id": reservation["reservation_id"],
                    "reservation_request_id": reservation["manual_execution_request_id"],
                    "reservation_trading_account_id": reservation["trading_account_id"],
                    "reservation_venue": reservation["venue"],
                    "reservation_asset_id": reservation["asset_id"],
                    "reservation_symbol": reservation["symbol"],
                    "reservation_quantity_base": reservation["quantity_base"],
                    "reservation_state": reservation["reservation_state"],
                    "snapshot_trading_account_id": snapshot["trading_account_id"],
                    "persisted_snapshot_id": snapshot["account_position_snapshot_id"],
                    "snapshot_venue": snapshot["venue"],
                    "snapshot_asset_id": snapshot["asset_id"],
                    "snapshot_ts_utc": snapshot["snapshot_ts_utc"],
                }
            )
            self.lastrowid = (
                None
                if backend.omit_approval_lastrowid
                else approval_id + backend.returned_approval_id_offset
            )
            return

        if sql_norm.startswith("SELECT approval.*,"):
            backend.approval_select_count += 1
            value = params[0]
            if "manual_execution_approval_id = %s" in sql_norm:
                key = "manual_execution_approval_id"
            elif "manual_execution_request_id = %s" in sql_norm:
                key = "manual_execution_request_id"
            else:
                raise AssertionError(sql_norm)
            rows = [
                dict(row) for row in backend.approval_rows if row[key] == value
            ]
            if backend.approval_read_mode == "MISSING":
                rows = []
            elif rows and backend.approval_read_mode == "MISMATCHED_ID":
                rows[0]["manual_execution_approval_id"] += 1
            elif rows and backend.approval_read_mode == "REPLACED_BINDING":
                rows[0]["quote_asset"] = "USD"
            self._result = rows
            return

        if sql_norm.startswith("SELECT COALESCE(SUM(quantity_base)"):
            trading_account_id, venue, asset_id, state = params
            with backend._table_guard:
                total = sum(
                    (r["quantity_base"] for r in backend.reservation_rows
                     if r["trading_account_id"] == trading_account_id
                     and r["venue"] == venue
                     and r["asset_id"] == asset_id
                     and r["reservation_state"] == state),
                    Decimal("0"),
                )
            self._result = [{"total": total}]
            return

        if sql_norm.startswith("SELECT COUNT(*) AS n"):
            trading_account_id, venue, asset_id, state = params
            with backend._table_guard:
                n = sum(
                    1 for r in backend.reservation_rows
                    if r["trading_account_id"] == trading_account_id
                    and r["venue"] == venue
                    and r["asset_id"] == asset_id
                    and r["reservation_state"] == state
                )
            self._result = [{"n": n}]
            return

        if sql_norm.startswith("SELECT enabled, live_trading_enabled, account_mode"):
            (trading_account_id,) = params
            self._result = [r for r in backend.account_rows if r["trading_account_id"] == trading_account_id]
            return

        if sql_norm.startswith("SELECT account_position_snapshot_id, available_quantity_base, quantity_base"):
            trading_account_id, venue, asset_id = params
            matches = [
                r for r in backend.snapshot_rows
                if r["trading_account_id"] == trading_account_id
                and r["venue"] == venue
                and r["asset_id"] == asset_id
            ]
            matches.sort(key=lambda r: r["snapshot_ts_utc"], reverse=True)
            self._result = matches[:1]
            return

        raise AssertionError(f"unexpected SQL in fake cursor: {sql_norm}")

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result

    def __enter__(self):
        self._reservation_snapshot = [dict(row) for row in self.backend.reservation_rows]
        self._approval_snapshot = [dict(row) for row in self.backend.approval_rows]
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.backend.reservation_rows[:] = self._reservation_snapshot
            self.backend.approval_rows[:] = self._approval_snapshot
        for lock in self.held_locks:
            lock.release()
        self.held_locks.clear()
        return False


def _factory(backend: _FakeBackend):
    def factory(*, commit: bool = False, database: str | None = None):
        return _FakeSession(backend)

    return factory


class TestApproveAndReserveHappyPath:
    def test_approves_and_creates_one_reservation(self) -> None:
        backend = _FakeBackend(available_quantity=Decimal("2.0"))
        repo = ManualExecutionGateRepository(cursor_factory=_factory(backend))
        request = _request(request_id=1, idempotency_key="req-atomic-0001")

        outcome = repo.approve_and_reserve(request)

        assert outcome.gate_result.decision_state == GATE_DECISION_EXECUTION_ALLOWED
        assert outcome.approval_id == 501
        assert backend.approval_rows[0]["approved_quantity_base"] == Decimal("2.0")
        assert backend.approval_rows[0]["expires_ts_utc"] > NOW
        assert len(backend.reservation_rows) == 1
        assert len(backend.approval_rows) == 1
        assert backend.approval_select_count == 1
        assert backend.reservation_rows[0]["manual_execution_request_id"] == 1

    @pytest.mark.parametrize(
        ("configuration", "message"),
        [
            ({"omit_approval_lastrowid": True}, "did not return"),
            ({"returned_approval_id_offset": 1}, "could not be re-read"),
            ({"approval_read_mode": "MISSING"}, "could not be re-read"),
            ({"approval_read_mode": "MISMATCHED_ID"}, "approval_id"),
            ({"approval_read_mode": "REPLACED_BINDING"}, "quote_asset"),
        ],
    )
    def test_create_result_identity_and_bindings_fail_closed(
        self,
        configuration: dict[str, object],
        message: str,
    ) -> None:
        backend = _FakeBackend(available_quantity=Decimal("2.0"))
        for name, value in configuration.items():
            setattr(backend, name, value)
        repo = ManualExecutionGateRepository(cursor_factory=_factory(backend))
        request = _request(request_id=1, idempotency_key=f"verify-{message}")

        with pytest.raises(RuntimeError, match=message):
            repo.approve_and_reserve(request)

        assert backend.reservation_rows == []
        assert backend.approval_rows == []


class TestApproveAndReserveIdempotentRetry:
    def test_retry_returns_same_approval_without_rederiving_decision(self) -> None:
        backend = _FakeBackend(available_quantity=Decimal("2.0"))
        repo = ManualExecutionGateRepository(cursor_factory=_factory(backend))
        request = _request(request_id=1, idempotency_key="req-atomic-retry-0001")

        first = repo.approve_and_reserve(request)

        # Simulate the wallet balance having since moved to zero; a naive
        # non-idempotent retry would see NO_FREE_BASE_QUANTITY here.
        backend.snapshot_rows[0]["available_quantity_base"] = Decimal("0")
        backend.snapshot_rows[0]["quantity_base"] = Decimal("0")

        second = repo.approve_and_reserve(request)

        assert second.gate_result.decision_state == GATE_DECISION_EXECUTION_ALLOWED
        assert second.approval_id == first.approval_id
        assert len(backend.reservation_rows) == 1
        assert len(backend.approval_rows) == 1


class TestApproveAndReserveRollback:
    def test_failed_insert_leaves_no_orphan_reservation_or_stuck_lock(self) -> None:
        backend = _FakeBackend(available_quantity=Decimal("2.0"))
        repo = ManualExecutionGateRepository(cursor_factory=_factory(backend))
        request = _request(request_id=1, idempotency_key="req-atomic-rollback-0001")

        backend.fail_on_insert = True
        with pytest.raises(RuntimeError):
            repo.approve_and_reserve(request)

        assert backend.reservation_rows == []

        # The lock must have been released despite the exception — a
        # subsequent call for the same key must not hang and must succeed.
        backend.fail_on_insert = False
        outcome = repo.approve_and_reserve(request)
        assert outcome.gate_result.decision_state == GATE_DECISION_EXECUTION_ALLOWED
        assert len(backend.reservation_rows) == 1
        assert len(backend.approval_rows) == 1

    def test_failed_approval_insert_rolls_back_reservation(self) -> None:
        backend = _FakeBackend(available_quantity=Decimal("2.0"))
        repo = ManualExecutionGateRepository(cursor_factory=_factory(backend))
        request = _request(request_id=1, idempotency_key="req-atomic-approval-rollback")

        backend.fail_on_approval_insert = True
        with pytest.raises(RuntimeError):
            repo.approve_and_reserve(request)

        assert backend.reservation_rows == []
        assert backend.approval_rows == []


class TestApproveAndReserveConcurrency:
    def test_two_concurrent_full_available_requests_cannot_both_reserve_it(self) -> None:
        backend = _FakeBackend(available_quantity=Decimal("10.0"))
        repo = ManualExecutionGateRepository(cursor_factory=_factory(backend))

        request_a = _request(
            request_id=1,
            idempotency_key="req-atomic-concurrent-a",
            quantity_policy=QUANTITY_POLICY_FIXED_BASE_QUANTITY,
            requested_base_quantity=Decimal("10.0"),
        )
        request_b = _request(
            request_id=2,
            idempotency_key="req-atomic-concurrent-b",
            quantity_policy=QUANTITY_POLICY_FIXED_BASE_QUANTITY,
            requested_base_quantity=Decimal("10.0"),
        )

        results: dict[str, Any] = {}

        def run(name: str, request) -> None:
            results[name] = repo.approve_and_reserve(request)

        thread_a = threading.Thread(target=run, args=("a", request_a), name="thread-a")
        thread_b = threading.Thread(target=run, args=("b", request_b), name="thread-b")

        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)

        assert not thread_a.is_alive() and not thread_b.is_alive()

        outcomes = [results["a"], results["b"]]
        allowed = [o for o in outcomes if o.gate_result.decision_state == GATE_DECISION_EXECUTION_ALLOWED]
        blocked = [o for o in outcomes if o.gate_result.decision_state == GATE_DECISION_BLOCKED]

        # Exactly one of the two competing requests may be approved for the
        # full 10.0 — the other must observe the first's reservation and be
        # blocked (no free quantity left), never both approved.
        assert len(allowed) == 1
        assert len(blocked) == 1
        assert allowed[0].approval_id is not None

        # The lock was genuinely contended, not skipped.
        assert len(backend.lock_acquired_events) == 2

        with backend._table_guard:
            total_reserved = sum(r["quantity_base"] for r in backend.reservation_rows)
        assert total_reserved == Decimal("10.0")
        assert len(backend.reservation_rows) == 1
