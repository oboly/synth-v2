"""
Tests for src/decision_gate/manual_execution_gate_v1.py.

evaluate_manual_execution_request() is pure (no DB) — tested directly here.
ManualExecutionGateRepository is tested against an in-memory fake DB, same
pattern as tests/test_sell_reservation_v1.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.manual_execution import _trusted_clock_v1 as trusted_clock
from src.decision_gate.free_base_quantity_v1 import WalletAvailableSnapshot
from src.decision_gate.manual_execution_gate_v1 import (
    GATE_DECISION_BLOCKED,
    GATE_DECISION_EXECUTION_ALLOWED,
    REASON_ACCOUNT_DISABLED,
    REASON_ACCOUNT_LIVE_TRADING_ENABLED,
    REASON_ACCOUNT_NOT_PAPER_MODE,
    REASON_LIVE_TRADING_NOT_GRANTED,
    REASON_MANUAL_BUY_GATE_NOT_YET_IMPLEMENTED,
    REASON_QUANTITY_POLICY_NOT_YET_SUPPORTED,
    REASON_WALLET_SNAPSHOT_UNAVAILABLE,
    ManualExecutionGateInput,
    ManualExecutionGateRepository,
    evaluate_manual_execution_request,
)
from src.manual_execution.manual_execution_request_v1 import (
    MODE_LIVE,
    MODE_PAPER,
    QUANTITY_POLICY_FIXED_BASE_QUANTITY,
    QUANTITY_POLICY_FIXED_QUOTE_NOTIONAL,
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


def _request(**overrides):
    defaults = dict(
        idempotency_key="req-gate-0001",
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
    return build_manual_execution_request(**defaults)


def _wallet_snapshot(**overrides) -> WalletAvailableSnapshot:
    defaults = dict(
        trading_account_id=TRADING_ACCOUNT_ID,
        venue=VENUE,
        asset_id=ASSET_ID,
        symbol="BTC",
        available_base_quantity=Decimal("2.0"),
        total_base_quantity=Decimal("2.0"),
        source_name="account_position_snapshot",
        snapshot_ts_utc=NOW - timedelta(minutes=1),
    )
    defaults.update(overrides)
    return WalletAvailableSnapshot(**defaults)


def _gate_input(**overrides) -> ManualExecutionGateInput:
    defaults = dict(
        wallet_snapshot=_wallet_snapshot(),
        approved_not_submitted_reservation_base=Decimal("0"),
        reconciliation_pending_count=0,
        account_enabled=True,
        account_live_trading_enabled=False,
        account_mode="paper",
    )
    defaults.update(overrides)
    return ManualExecutionGateInput(**defaults)


class TestEvaluateManualExecutionRequest:
    def test_full_available_base_approved(self) -> None:
        result = evaluate_manual_execution_request(_request(), _gate_input())
        assert result.decision_state == GATE_DECISION_EXECUTION_ALLOWED
        assert result.approved_quantity_base == Decimal("2.0")
        assert result.free_base_quantity_result is not None

    def test_fixed_base_quantity_under_free_uses_requested(self) -> None:
        request = _request(
            quantity_policy=QUANTITY_POLICY_FIXED_BASE_QUANTITY,
            requested_base_quantity=Decimal("0.5"),
        )
        result = evaluate_manual_execution_request(request, _gate_input())
        assert result.decision_state == GATE_DECISION_EXECUTION_ALLOWED
        assert result.approved_quantity_base == Decimal("0.5")

    def test_fixed_base_quantity_over_free_is_capped(self) -> None:
        request = _request(
            quantity_policy=QUANTITY_POLICY_FIXED_BASE_QUANTITY,
            requested_base_quantity=Decimal("999"),
        )
        result = evaluate_manual_execution_request(request, _gate_input())
        assert result.decision_state == GATE_DECISION_EXECUTION_ALLOWED
        assert result.approved_quantity_base == Decimal("2.0")

    def test_live_mode_blocked_before_anything_else(self) -> None:
        request = _request(mode=MODE_LIVE)
        result = evaluate_manual_execution_request(
            request, _gate_input(wallet_snapshot=None, account_enabled=False)
        )
        assert result.decision_state == GATE_DECISION_BLOCKED
        assert result.decision_reason == REASON_LIVE_TRADING_NOT_GRANTED
        assert result.approved_quantity_base is None

    def test_buy_side_blocked(self) -> None:
        request = _request(side="BUY")
        result = evaluate_manual_execution_request(request, _gate_input())
        assert result.decision_state == GATE_DECISION_BLOCKED
        assert result.decision_reason == REASON_MANUAL_BUY_GATE_NOT_YET_IMPLEMENTED

    def test_fixed_quote_notional_policy_blocked(self) -> None:
        request = _request(
            quantity_policy=QUANTITY_POLICY_FIXED_QUOTE_NOTIONAL,
            requested_quote_notional=Decimal("100"),
        )
        result = evaluate_manual_execution_request(request, _gate_input())
        assert result.decision_state == GATE_DECISION_BLOCKED
        assert result.decision_reason == REASON_QUANTITY_POLICY_NOT_YET_SUPPORTED

    def test_account_disabled_blocked(self) -> None:
        result = evaluate_manual_execution_request(
            _request(), _gate_input(account_enabled=False)
        )
        assert result.decision_reason == REASON_ACCOUNT_DISABLED

    def test_account_live_trading_enabled_blocked(self) -> None:
        result = evaluate_manual_execution_request(
            _request(), _gate_input(account_live_trading_enabled=True)
        )
        assert result.decision_reason == REASON_ACCOUNT_LIVE_TRADING_ENABLED

    def test_account_not_paper_mode_blocked(self) -> None:
        result = evaluate_manual_execution_request(
            _request(), _gate_input(account_mode="live")
        )
        assert result.decision_reason == REASON_ACCOUNT_NOT_PAPER_MODE

    def test_wallet_snapshot_missing_blocked(self) -> None:
        result = evaluate_manual_execution_request(
            _request(), _gate_input(wallet_snapshot=None)
        )
        assert result.decision_reason == REASON_WALLET_SNAPSHOT_UNAVAILABLE

    def test_stale_wallet_snapshot_blocks_via_free_base_quantity_resolver(self) -> None:
        stale_snapshot = _wallet_snapshot(snapshot_ts_utc=NOW - timedelta(hours=2))
        result = evaluate_manual_execution_request(
            _request(), _gate_input(wallet_snapshot=stale_snapshot)
        )
        assert result.decision_state == GATE_DECISION_BLOCKED
        assert "STALE_WALLET_SNAPSHOT" in result.blocking_reasons

    def test_reconciliation_pending_blocks(self) -> None:
        result = evaluate_manual_execution_request(
            _request(), _gate_input(reconciliation_pending_count=1)
        )
        assert result.decision_state == GATE_DECISION_BLOCKED
        assert "RECONCILIATION_PENDING" in result.blocking_reasons

    def test_reservations_reduce_free_quantity(self) -> None:
        result = evaluate_manual_execution_request(
            _request(),
            _gate_input(approved_not_submitted_reservation_base=Decimal("1.9")),
        )
        assert result.decision_state == GATE_DECISION_EXECUTION_ALLOWED
        assert result.approved_quantity_base == Decimal("0.1")

    def test_zero_free_quantity_blocks(self) -> None:
        result = evaluate_manual_execution_request(
            _request(),
            _gate_input(approved_not_submitted_reservation_base=Decimal("2.0")),
        )
        assert result.decision_state == GATE_DECISION_BLOCKED


class _FakeCursor:
    def __init__(self, account_rows: list[dict], snapshot_rows: list[dict], reservation_rows: list[dict]) -> None:
        self._account_rows = account_rows
        self._snapshot_rows = snapshot_rows
        self._reservation_rows = reservation_rows
        self._result = None

    def execute(self, sql: str, params: list) -> None:
        sql_norm = " ".join(sql.split())

        if sql_norm.startswith("SELECT enabled, live_trading_enabled, account_mode"):
            (trading_account_id,) = params
            self._result = [r for r in self._account_rows if r["trading_account_id"] == trading_account_id]
            return

        if sql_norm.startswith("SELECT account_position_snapshot_id, available_quantity_base, quantity_base"):
            trading_account_id, venue, asset_id = params
            matches = [
                r for r in self._snapshot_rows
                if r["trading_account_id"] == trading_account_id
                and r["venue"] == venue
                and r["asset_id"] == asset_id
            ]
            matches.sort(key=lambda r: r["snapshot_ts_utc"], reverse=True)
            self._result = matches[:1]
            return

        if sql_norm.startswith("SELECT COALESCE(SUM(quantity_base)"):
            trading_account_id, venue, asset_id, state = params
            total = sum(
                (r["quantity_base"] for r in self._reservation_rows
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
                1 for r in self._reservation_rows
                if r["trading_account_id"] == trading_account_id
                and r["venue"] == venue
                and r["asset_id"] == asset_id
                and r["reservation_state"] == state
            )
            self._result = [{"n": n}]
            return

        raise AssertionError(f"unexpected SQL in fake cursor: {sql_norm}")

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestManualExecutionGateRepository:
    def test_load_gate_input_from_fake_db(self) -> None:
        account_rows = [
            {"trading_account_id": TRADING_ACCOUNT_ID, "enabled": 1, "live_trading_enabled": 0, "account_mode": "paper"}
        ]
        snapshot_rows = [
            {
                "account_position_snapshot_id": 9001,
                "trading_account_id": TRADING_ACCOUNT_ID,
                "venue": VENUE,
                "asset_id": ASSET_ID,
                "available_quantity_base": Decimal("2.0"),
                "quantity_base": Decimal("2.0"),
                "snapshot_ts_utc": NOW - timedelta(minutes=1),
                "source_name": "account_position_snapshot",
            }
        ]
        reservation_rows: list[dict] = []

        def factory(*, commit: bool = False, database: str | None = None):
            return _FakeCursor(account_rows, snapshot_rows, reservation_rows)

        repo = ManualExecutionGateRepository(cursor_factory=factory)
        gate_input = repo.load_gate_input(_request())

        assert gate_input.account_enabled is True
        assert gate_input.account_live_trading_enabled is False
        assert gate_input.account_mode == "paper"
        assert gate_input.wallet_snapshot is not None
        assert gate_input.wallet_snapshot.available_base_quantity == Decimal("2.0")
        assert gate_input.approved_not_submitted_reservation_base == Decimal("0")
        assert gate_input.reconciliation_pending_count == 0

    def test_load_gate_input_unknown_account_fails_closed(self) -> None:
        def factory(*, commit: bool = False, database: str | None = None):
            return _FakeCursor([], [], [])

        repo = ManualExecutionGateRepository(cursor_factory=factory)
        gate_input = repo.load_gate_input(_request())

        assert gate_input.account_enabled is False
        assert gate_input.account_live_trading_enabled is True
        assert gate_input.wallet_snapshot is None
