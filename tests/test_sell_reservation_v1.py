"""
Tests for src/decision_gate/sell_reservation_v1.py.

Uses an in-memory fake DB (no real MariaDB, no network) that implements
just the query shapes SellReservationRepository actually issues. This lets
the reservation lifecycle (create -> idempotent retry -> reconcile ->
terminal) be exercised end to end as an integration test against a
paper/fake broker-reconciliation snapshot, per the P0 task's requirement
for integration tests using paper/fake broker snapshots.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.decision_gate.sell_reservation_v1 import (
    STATE_APPROVED_NOT_SUBMITTED,
    STATE_CANCELLED,
    STATE_FILLED,
    STATE_OPEN,
    STATE_PARTIALLY_FILLED,
    STATE_SUBMITTED_AWAITING_RECONCILIATION,
    AmbiguousBrokerStateError,
    InvalidReservationTransitionError,
    SellReservationRepository,
)


class _FakeCursor:
    def __init__(self, table: list[dict]) -> None:
        self._table = table
        self._result: list[dict] | None = None
        self.lastrowid: int | None = None
        self.rowcount: int = 0

    def execute(self, sql: str, params: list) -> None:
        sql_norm = " ".join(sql.split())

        if sql_norm.startswith("SELECT * FROM execution_sell_reservation WHERE idempotency_key"):
            (idempotency_key,) = params
            self._result = [
                dict(r) for r in self._table if r["idempotency_key"] == idempotency_key
            ]
            return

        if sql_norm.startswith("INSERT INTO execution_sell_reservation"):
            (
                trading_account_id, venue, asset_id, symbol, idempotency_key,
                quantity_base, reservation_state, manual_execution_request_id,
                execution_plan_id, leg_number, notes,
            ) = params
            new_id = len(self._table) + 1
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
            self._table.append(row)
            self.lastrowid = new_id
            return

        if sql_norm.startswith("SELECT * FROM execution_sell_reservation WHERE reservation_id"):
            (reservation_id,) = params
            self._result = [
                dict(r) for r in self._table if r["reservation_id"] == reservation_id
            ]
            return

        if sql_norm.startswith("SELECT COALESCE(SUM(quantity_base)"):
            trading_account_id, venue, asset_id, state = params
            total = sum(
                (r["quantity_base"] for r in self._table
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
            n = sum(
                1 for r in self._table
                if r["trading_account_id"] == trading_account_id
                and r["venue"] == venue
                and r["asset_id"] == asset_id
                and r["reservation_state"] == state
            )
            self._result = [{"n": n}]
            return

        if sql_norm.startswith("UPDATE execution_sell_reservation"):
            new_state, broker_order_id, reservation_id = params
            is_terminal_update = "terminal_ts_utc = UTC_TIMESTAMP()" in sql_norm
            self.rowcount = 0
            for r in self._table:
                if r["reservation_id"] == reservation_id:
                    r["reservation_state"] = new_state
                    if broker_order_id is not None:
                        r["broker_order_id"] = broker_order_id
                    if is_terminal_update:
                        r["terminal_ts_utc"] = datetime.now(timezone.utc)
                    self.rowcount = 1
            return

        raise AssertionError(f"unhandled fake SQL: {sql_norm}")

    def fetchone(self):
        if not self._result:
            return None
        return self._result[0]

    def fetchall(self):
        return self._result or []


class _FakeDbContext:
    def __init__(self, table: list[dict]) -> None:
        self._cursor = _FakeCursor(table)

    def __enter__(self):
        return self._cursor

    def __exit__(self, *exc_info) -> bool:
        return False


def _make_repo() -> tuple[SellReservationRepository, list[dict]]:
    table: list[dict] = []

    def factory(*, commit: bool = False, database: str | None = None):
        return _FakeDbContext(table)

    return SellReservationRepository(cursor_factory=factory), table


class TestIdempotentCreate:
    def test_repeated_call_with_same_key_returns_same_row_not_a_duplicate(self) -> None:
        repo, table = _make_repo()
        first = repo.create_reservation_idempotent(
            trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
            idempotency_key="req-1-leg-1", quantity_base=Decimal("0.01"),
        )
        second = repo.create_reservation_idempotent(
            trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
            idempotency_key="req-1-leg-1", quantity_base=Decimal("0.01"),
        )
        assert first.reservation_id == second.reservation_id
        assert len(table) == 1

    def test_different_keys_create_separate_rows(self) -> None:
        repo, table = _make_repo()
        repo.create_reservation_idempotent(
            trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
            idempotency_key="req-1-leg-1", quantity_base=Decimal("0.01"),
        )
        repo.create_reservation_idempotent(
            trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
            idempotency_key="req-1-leg-2", quantity_base=Decimal("0.02"),
        )
        assert len(table) == 2

    def test_rejects_non_positive_quantity(self) -> None:
        repo, _ = _make_repo()
        with pytest.raises(ValueError):
            repo.create_reservation_idempotent(
                trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
                idempotency_key="req-1", quantity_base=Decimal("0"),
            )


class TestReservedOnceAndOnlyOnce:
    def test_sum_only_counts_approved_not_submitted(self) -> None:
        repo, _ = _make_repo()
        r1 = repo.create_reservation_idempotent(
            trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
            idempotency_key="leg-1", quantity_base=Decimal("0.01"),
        )
        repo.create_reservation_idempotent(
            trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
            idempotency_key="leg-2", quantity_base=Decimal("0.02"),
        )
        assert repo.sum_approved_not_submitted(
            trading_account_id=3, venue="bitvavo", asset_id=101
        ) == Decimal("0.03")

        repo.reconcile_reservation_state(
            reservation_id=r1.reservation_id,
            new_state=STATE_SUBMITTED_AWAITING_RECONCILIATION,
            broker_order_id=None,
            matching_broker_rows=1,
        )
        # once no longer APPROVED_NOT_SUBMITTED, it drops out of the sum —
        # it must not be double counted against the wallet-available figure.
        assert repo.sum_approved_not_submitted(
            trading_account_id=3, venue="bitvavo", asset_id=101
        ) == Decimal("0.02")


class TestReconciliationOwnsTransitions:
    def test_valid_transition_sequence(self) -> None:
        repo, _ = _make_repo()
        r = repo.create_reservation_idempotent(
            trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
            idempotency_key="leg-1", quantity_base=Decimal("0.01"),
        )
        r = repo.reconcile_reservation_state(
            reservation_id=r.reservation_id,
            new_state=STATE_SUBMITTED_AWAITING_RECONCILIATION,
            broker_order_id=None,
            matching_broker_rows=1,
        )
        assert r.reservation_state == STATE_SUBMITTED_AWAITING_RECONCILIATION

        r = repo.reconcile_reservation_state(
            reservation_id=r.reservation_id,
            new_state=STATE_OPEN,
            broker_order_id="bv-order-123",
            matching_broker_rows=1,
        )
        assert r.reservation_state == STATE_OPEN
        assert r.broker_order_id == "bv-order-123"

        r = repo.reconcile_reservation_state(
            reservation_id=r.reservation_id,
            new_state=STATE_PARTIALLY_FILLED,
            broker_order_id="bv-order-123",
            matching_broker_rows=1,
        )
        assert r.reservation_state == STATE_PARTIALLY_FILLED

        r = repo.reconcile_reservation_state(
            reservation_id=r.reservation_id,
            new_state=STATE_FILLED,
            broker_order_id="bv-order-123",
            matching_broker_rows=1,
        )
        assert r.reservation_state == STATE_FILLED
        assert r.terminal_ts_utc is not None

    def test_invalid_transition_rejected(self) -> None:
        repo, _ = _make_repo()
        r = repo.create_reservation_idempotent(
            trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
            idempotency_key="leg-1", quantity_base=Decimal("0.01"),
        )
        # APPROVED_NOT_SUBMITTED cannot jump straight to OPEN or PARTIALLY_FILLED.
        with pytest.raises(InvalidReservationTransitionError):
            repo.reconcile_reservation_state(
                reservation_id=r.reservation_id,
                new_state=STATE_OPEN,
                broker_order_id="bv-order-1",
                matching_broker_rows=1,
            )

    def test_partial_fill_then_cancel_is_allowed_and_terminal(self) -> None:
        repo, _ = _make_repo()
        r = repo.create_reservation_idempotent(
            trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
            idempotency_key="leg-1", quantity_base=Decimal("0.01"),
        )
        r = repo.reconcile_reservation_state(
            reservation_id=r.reservation_id, new_state=STATE_SUBMITTED_AWAITING_RECONCILIATION,
            broker_order_id=None, matching_broker_rows=1,
        )
        r = repo.reconcile_reservation_state(
            reservation_id=r.reservation_id, new_state=STATE_OPEN,
            broker_order_id="bv-1", matching_broker_rows=1,
        )
        r = repo.reconcile_reservation_state(
            reservation_id=r.reservation_id, new_state=STATE_PARTIALLY_FILLED,
            broker_order_id="bv-1", matching_broker_rows=1,
        )
        r = repo.reconcile_reservation_state(
            reservation_id=r.reservation_id, new_state=STATE_CANCELLED,
            broker_order_id="bv-1", matching_broker_rows=1,
        )
        assert r.reservation_state == STATE_CANCELLED
        assert r.terminal_ts_utc is not None


class TestAmbiguousBrokerStateFailsClosed:
    def test_zero_matching_rows_raises(self) -> None:
        repo, _ = _make_repo()
        r = repo.create_reservation_idempotent(
            trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
            idempotency_key="leg-1", quantity_base=Decimal("0.01"),
        )
        with pytest.raises(AmbiguousBrokerStateError):
            repo.reconcile_reservation_state(
                reservation_id=r.reservation_id,
                new_state=STATE_SUBMITTED_AWAITING_RECONCILIATION,
                broker_order_id=None,
                matching_broker_rows=0,
            )

    def test_multiple_matching_rows_raises(self) -> None:
        repo, _ = _make_repo()
        r = repo.create_reservation_idempotent(
            trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
            idempotency_key="leg-1", quantity_base=Decimal("0.01"),
        )
        with pytest.raises(AmbiguousBrokerStateError):
            repo.reconcile_reservation_state(
                reservation_id=r.reservation_id,
                new_state=STATE_SUBMITTED_AWAITING_RECONCILIATION,
                broker_order_id=None,
                matching_broker_rows=2,
            )

    def test_count_reconciliation_pending(self) -> None:
        repo, _ = _make_repo()
        r = repo.create_reservation_idempotent(
            trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
            idempotency_key="leg-1", quantity_base=Decimal("0.01"),
        )
        assert repo.count_reconciliation_pending(
            trading_account_id=3, venue="bitvavo", asset_id=101
        ) == 0
        repo.reconcile_reservation_state(
            reservation_id=r.reservation_id,
            new_state=STATE_SUBMITTED_AWAITING_RECONCILIATION,
            broker_order_id=None,
            matching_broker_rows=1,
        )
        assert repo.count_reconciliation_pending(
            trading_account_id=3, venue="bitvavo", asset_id=101
        ) == 1
