"""
Tests for src/decision_gate/free_base_quantity_v1.py.

Pure Python — no DB, no broker, no network.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.manual_execution import _trusted_clock_v1 as trusted_clock
from src.decision_gate.free_base_quantity_v1 import (
    REASON_ACCOUNT_VENUE_ASSET_MISMATCH,
    REASON_CONTRADICTORY_WALLET_SNAPSHOT,
    REASON_INCOMPLETE_WALLET_SNAPSHOT,
    REASON_NEGATIVE_RESULT,
    REASON_RECONCILIATION_PENDING,
    REASON_STALE_WALLET_SNAPSHOT,
    STATUS_BLOCKED,
    STATUS_OK,
    WalletAvailableSnapshot,
    resolve_free_base_quantity,
    resolve_free_base_quantity_core_v1,
)


NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fixed_manual_execution_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trusted_clock, "utc_now", lambda: NOW)


def _snapshot(**overrides) -> WalletAvailableSnapshot:
    defaults = dict(
        trading_account_id=3,
        venue="bitvavo",
        asset_id=101,
        symbol="BTC",
        available_base_quantity=Decimal("1.5"),
        total_base_quantity=Decimal("2.0"),
        source_name="bitvavo_private_balance_read_v1",
        snapshot_ts_utc=NOW - timedelta(minutes=1),
    )
    defaults.update(overrides)
    return WalletAvailableSnapshot(**defaults)


class TestHappyPath:
    def test_explicit_time_core_is_deterministic(self) -> None:
        snapshot = _snapshot(snapshot_ts_utc=NOW - timedelta(minutes=1))
        first = resolve_free_base_quantity_core_v1(
            wallet_snapshot=snapshot,
            approved_not_submitted_reservation_base=Decimal("0.4"),
            reconciliation_pending_reservation_count=0,
            evaluation_ts_utc=NOW,
        )
        second = resolve_free_base_quantity_core_v1(
            wallet_snapshot=snapshot,
            approved_not_submitted_reservation_base=Decimal("0.4"),
            reconciliation_pending_reservation_count=0,
            evaluation_ts_utc=NOW,
        )
        assert first == second
        assert first.resolved_ts_utc == NOW

    def test_explicit_time_core_controls_freshness(self) -> None:
        result = resolve_free_base_quantity_core_v1(
            wallet_snapshot=_snapshot(snapshot_ts_utc=NOW),
            approved_not_submitted_reservation_base=Decimal("0"),
            reconciliation_pending_reservation_count=0,
            evaluation_ts_utc=NOW + timedelta(minutes=16),
        )
        assert result.status == STATUS_BLOCKED
        assert REASON_STALE_WALLET_SNAPSHOT in result.blocking_reasons

    def test_resolves_ok_with_no_local_reservations(self) -> None:
        result = resolve_free_base_quantity(
            wallet_snapshot=_snapshot(),
            approved_not_submitted_reservation_base=Decimal("0"),
            reconciliation_pending_reservation_count=0,
        )
        assert result.status == STATUS_OK
        assert result.free_base_quantity == Decimal("1.5")
        assert result.blocking_reasons == ()

    def test_subtracts_only_approved_not_submitted_reservations(self) -> None:
        result = resolve_free_base_quantity(
            wallet_snapshot=_snapshot(available_base_quantity=Decimal("1.5")),
            approved_not_submitted_reservation_base=Decimal("0.4"),
            reconciliation_pending_reservation_count=0,
        )
        assert result.status == STATUS_OK
        assert result.free_base_quantity == Decimal("1.1")


class TestDoubleSubtractionPrevention:
    def test_does_not_subtract_open_broker_orders_already_reflected(self) -> None:
        # available_base_quantity already excludes an open SELL order's
        # quantity (this is what the broker's own `available` field means).
        # No APPROVED_NOT_SUBMITTED reservation exists for it, so nothing
        # should be subtracted a second time.
        result = resolve_free_base_quantity(
            wallet_snapshot=_snapshot(available_base_quantity=Decimal("1.5")),
            approved_not_submitted_reservation_base=Decimal("0"),
            reconciliation_pending_reservation_count=0,
        )
        assert result.free_base_quantity == Decimal("1.5")

    def test_reconciliation_pending_blocks_rather_than_guessing(self) -> None:
        # A reservation mid-flight between "approved" and "confirmed open"
        # is ambiguous: we cannot know whether the broker's available
        # figure already reflects it. Fail closed instead of guessing
        # either direction.
        result = resolve_free_base_quantity(
            wallet_snapshot=_snapshot(),
            approved_not_submitted_reservation_base=Decimal("0"),
            reconciliation_pending_reservation_count=1,
        )
        assert result.status == STATUS_BLOCKED
        assert REASON_RECONCILIATION_PENDING in result.blocking_reasons
        assert result.free_base_quantity is None


class TestFailClosed:
    def test_stale_snapshot_blocks(self) -> None:
        result = resolve_free_base_quantity(
            wallet_snapshot=_snapshot(snapshot_ts_utc=NOW - timedelta(hours=2)),
            approved_not_submitted_reservation_base=Decimal("0"),
            reconciliation_pending_reservation_count=0,
            max_wallet_snapshot_age_seconds=900,
        )
        assert result.status == STATUS_BLOCKED
        assert REASON_STALE_WALLET_SNAPSHOT in result.blocking_reasons

    def test_future_snapshot_blocks(self) -> None:
        result = resolve_free_base_quantity(
            wallet_snapshot=_snapshot(snapshot_ts_utc=NOW + timedelta(minutes=5)),
            approved_not_submitted_reservation_base=Decimal("0"),
            reconciliation_pending_reservation_count=0,
        )
        assert result.status == STATUS_BLOCKED
        assert REASON_STALE_WALLET_SNAPSHOT in result.blocking_reasons

    def test_incomplete_snapshot_blocks(self) -> None:
        result = resolve_free_base_quantity(
            wallet_snapshot=_snapshot(available_base_quantity=None),
            approved_not_submitted_reservation_base=Decimal("0"),
            reconciliation_pending_reservation_count=0,
        )
        assert result.status == STATUS_BLOCKED
        assert REASON_INCOMPLETE_WALLET_SNAPSHOT in result.blocking_reasons

    def test_negative_available_is_contradictory(self) -> None:
        result = resolve_free_base_quantity(
            wallet_snapshot=_snapshot(available_base_quantity=Decimal("-1")),
            approved_not_submitted_reservation_base=Decimal("0"),
            reconciliation_pending_reservation_count=0,
        )
        assert result.status == STATUS_BLOCKED
        assert REASON_CONTRADICTORY_WALLET_SNAPSHOT in result.blocking_reasons

    def test_available_exceeding_total_is_contradictory(self) -> None:
        result = resolve_free_base_quantity(
            wallet_snapshot=_snapshot(
                available_base_quantity=Decimal("5"), total_base_quantity=Decimal("2")
            ),
            approved_not_submitted_reservation_base=Decimal("0"),
            reconciliation_pending_reservation_count=0,
        )
        assert result.status == STATUS_BLOCKED
        assert REASON_CONTRADICTORY_WALLET_SNAPSHOT in result.blocking_reasons

    def test_account_mismatch_blocks(self) -> None:
        result = resolve_free_base_quantity(
            wallet_snapshot=_snapshot(trading_account_id=3),
            approved_not_submitted_reservation_base=Decimal("0"),
            reconciliation_pending_reservation_count=0,
            expected_trading_account_id=99,
        )
        assert result.status == STATUS_BLOCKED
        assert REASON_ACCOUNT_VENUE_ASSET_MISMATCH in result.blocking_reasons

    def test_venue_mismatch_blocks(self) -> None:
        result = resolve_free_base_quantity(
            wallet_snapshot=_snapshot(venue="bitvavo"),
            approved_not_submitted_reservation_base=Decimal("0"),
            reconciliation_pending_reservation_count=0,
            expected_venue="kraken",
        )
        assert result.status == STATUS_BLOCKED
        assert REASON_ACCOUNT_VENUE_ASSET_MISMATCH in result.blocking_reasons

    def test_reservation_exceeding_available_yields_negative_result_blocked(self) -> None:
        result = resolve_free_base_quantity(
            wallet_snapshot=_snapshot(available_base_quantity=Decimal("1.0")),
            approved_not_submitted_reservation_base=Decimal("2.0"),
            reconciliation_pending_reservation_count=0,
        )
        assert result.status == STATUS_BLOCKED
        assert REASON_NEGATIVE_RESULT in result.blocking_reasons
        assert result.free_base_quantity is None

    def test_negative_reservation_input_is_contradictory(self) -> None:
        result = resolve_free_base_quantity(
            wallet_snapshot=_snapshot(),
            approved_not_submitted_reservation_base=Decimal("-1"),
            reconciliation_pending_reservation_count=0,
        )
        assert result.status == STATUS_BLOCKED
        assert REASON_CONTRADICTORY_WALLET_SNAPSHOT in result.blocking_reasons


class TestRecordedProvenance:
    def test_result_carries_source_account_venue_asset_and_semantics(self) -> None:
        result = resolve_free_base_quantity(
            wallet_snapshot=_snapshot(),
            approved_not_submitted_reservation_base=Decimal("0"),
            reconciliation_pending_reservation_count=0,
        )
        assert result.trading_account_id == 3
        assert result.venue == "bitvavo"
        assert result.asset_id == 101
        assert result.symbol == "BTC"
        assert result.source_name == "bitvavo_private_balance_read_v1"
        assert result.snapshot_ts_utc == NOW - timedelta(minutes=1)
        assert result.resolved_ts_utc == NOW
        assert "APPROVED_NOT_SUBMITTED" in result.reservation_semantics
        assert "not subtracted again" in result.reservation_semantics
