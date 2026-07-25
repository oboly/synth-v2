"""
Tests for src/market_rules/venue_execution_constraints_v1.py.

Pure Python — no DB, no broker, no network. Missing/stale metadata tests
prove the fail-closed contract required by the P0 remediation task.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.market_rules.venue_execution_constraints_v1 import (
    STATUS_FRESH,
    STATUS_MISSING,
    STATUS_STALE,
    VenueExecutionConstraints,
    is_usable,
    resolve_venue_execution_constraints,
)


NOW = datetime(2026, 7, 25, 20, 0, 0, tzinfo=timezone.utc)


def _fresh_row(market: str, *, synced: datetime) -> VenueExecutionConstraints:
    return VenueExecutionConstraints(
        venue="bitvavo",
        market=market,
        tick_size=Decimal("0.01"),
        qty_step_size=Decimal("0.00000001"),
        min_base_quantity=Decimal("0.001"),
        min_quote_notional=Decimal("5.00"),
        supported_order_types=("market", "limit"),
        supported_time_in_force=("GTC", "IOC", "FOK"),
        source_provenance="BITVAVO_PUBLIC_MARKETS_API_V2",
        metadata_synced_ts_utc=synced,
        status=STATUS_FRESH,
    )


class TestMissingFailsClosed:
    def test_no_row_returns_missing(self) -> None:
        result = resolve_venue_execution_constraints(
            venue="bitvavo", market="ZZZ-EUR", db_rows={}, now=NOW,
        )
        assert result.status == STATUS_MISSING
        assert not is_usable(result)
        assert result.tick_size == Decimal("0")

    def test_absent_market_among_others_still_missing(self) -> None:
        db_rows = {"BTC-EUR": _fresh_row("BTC-EUR", synced=NOW - timedelta(hours=1))}
        result = resolve_venue_execution_constraints(
            venue="bitvavo", market="DEEP-EUR", db_rows=db_rows, now=NOW,
        )
        assert result.status == STATUS_MISSING


class TestStaleFailsClosed:
    def test_row_older_than_max_age_is_stale(self) -> None:
        db_rows = {"BTC-EUR": _fresh_row("BTC-EUR", synced=NOW - timedelta(days=10))}
        result = resolve_venue_execution_constraints(
            venue="bitvavo", market="BTC-EUR", db_rows=db_rows, now=NOW,
            max_age_seconds=7 * 24 * 3600,
        )
        assert result.status == STATUS_STALE
        assert not is_usable(result)

    def test_row_from_the_future_is_treated_as_stale_not_trusted(self) -> None:
        db_rows = {"BTC-EUR": _fresh_row("BTC-EUR", synced=NOW + timedelta(hours=1))}
        result = resolve_venue_execution_constraints(
            venue="bitvavo", market="BTC-EUR", db_rows=db_rows, now=NOW,
        )
        assert result.status == STATUS_STALE


class TestFreshIsUsable:
    def test_recent_row_is_fresh_and_usable(self) -> None:
        db_rows = {"BTC-EUR": _fresh_row("BTC-EUR", synced=NOW - timedelta(hours=1))}
        result = resolve_venue_execution_constraints(
            venue="bitvavo", market="BTC-EUR", db_rows=db_rows, now=NOW,
        )
        assert result.status == STATUS_FRESH
        assert is_usable(result)
        assert result.tick_size == Decimal("0.01")
