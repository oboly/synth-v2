"""
Tests for src/market/run_bitvavo_venue_execution_constraint_sync_v1.py.

No network call, no real DB. `_FakeConn`/`_FakeCursor` simulate MariaDB's
`INSERT ... ON DUPLICATE KEY UPDATE` rowcount convention (1=insert,
2=changed update, 0=matched-but-identical) against an in-memory dict keyed
on the table's real (venue, market) unique key, so idempotency and
insert/update/unchanged counting are exercised without a live database.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from src.market.run_bitvavo_venue_execution_constraint_sync_v1 import (
    DEFAULT_QUOTE_FILTER,
    DEFAULT_VENUE,
    build_constraint_rows,
    fetch_bitvavo_markets,
    run_constraint_sync,
)
from src.market_rules.venue_execution_constraints_v1 import (
    STATUS_FRESH,
    SOURCE_BITVAVO_PUBLIC_MARKETS_API_V2,
    resolve_venue_execution_constraints,
)


TS = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)


def _row(market: str, base: str, quote: str = "EUR", *, status: str = "trading", **overrides) -> dict[str, Any]:
    row = {
        "market": market,
        "base": base,
        "quote": quote,
        "status": status,
        "tickSize": "0.01",
        "quantityDecimals": 8,
        "minOrderInBaseAsset": "0.001",
        "minOrderInQuoteAsset": "5.00",
        "orderTypes": ["market", "limit"],
        "pricePrecision": None,
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# fetch_bitvavo_markets — malformed payload fails closed
# ---------------------------------------------------------------------------

class _BadShapeClient:
    def get_markets(self) -> Any:
        return {"not": "a list"}


class _GoodClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def get_markets(self) -> list[dict[str, Any]]:
        return self._rows


def test_fetch_rejects_non_list_response() -> None:
    with pytest.raises(RuntimeError):
        fetch_bitvavo_markets(_BadShapeClient())


def test_fetch_returns_rows_for_list_response() -> None:
    rows = [_row("BTC-EUR", "BTC")]
    assert fetch_bitvavo_markets(_GoodClient(rows)) == rows


# ---------------------------------------------------------------------------
# build_constraint_rows — mapping, filtering, fail-closed skips, ordering
# ---------------------------------------------------------------------------

def test_representative_eur_market_maps_all_fields() -> None:
    raw = [_row("BTC-EUR", "BTC", tickSize="1.00", quantityDecimals=8,
                 minOrderInBaseAsset="0.00008817", minOrderInQuoteAsset="5.00")]
    build = build_constraint_rows(raw, synced_ts_utc=TS)
    assert build.eur_market_count == 1
    assert len(build.rows) == 1
    row = build.rows[0]
    assert row.venue == DEFAULT_VENUE
    assert row.market == "BTC-EUR"
    assert row.tick_size == Decimal("1.00")
    assert row.qty_step_size == Decimal("1").scaleb(-8)
    assert row.min_base_quantity == Decimal("0.00008817")
    assert row.min_quote_notional == Decimal("5.00")
    assert row.status == STATUS_FRESH
    assert row.source_provenance == SOURCE_BITVAVO_PUBLIC_MARKETS_API_V2
    assert row.metadata_synced_ts_utc == TS


def test_quantity_decimals_drive_qty_step_size() -> None:
    raw = [_row("NOT-EUR", "NOT", quantityDecimals=3)]
    build = build_constraint_rows(raw, synced_ts_utc=TS)
    assert build.rows[0].qty_step_size == Decimal("0.001")


def test_non_eur_market_excluded_from_universe() -> None:
    raw = [_row("BTC-USDT", "BTC", quote="USDT")]
    build = build_constraint_rows(raw, synced_ts_utc=TS)
    assert build.eur_market_count == 0
    assert build.rows == ()


def test_quote_filter_is_case_insensitive_and_configurable() -> None:
    raw = [_row("BTC-USD", "BTC", quote="usd")]
    build = build_constraint_rows(raw, quote_filter="USD", synced_ts_utc=TS)
    assert build.eur_market_count == 1
    assert build.rows[0].market == "BTC-USD"


def test_missing_required_field_fails_closed_not_written_not_defaulted() -> None:
    raw = [_row("XYZ-EUR", "XYZ", tickSize=None)]
    build = build_constraint_rows(raw, synced_ts_utc=TS)
    assert build.eur_market_count == 1
    assert build.rows == ()
    assert build.skipped_markets == ("XYZ-EUR",)


def test_malformed_payload_missing_multiple_fields_all_fail_closed() -> None:
    raw = [
        _row("A-EUR", "A", tickSize=None),
        _row("B-EUR", "B", minOrderInBaseAsset=None),
        _row("C-EUR", "C", orderTypes=None),
    ]
    build = build_constraint_rows(raw, synced_ts_utc=TS)
    assert build.rows == ()
    assert set(build.skipped_markets) == {"A-EUR", "B-EUR", "C-EUR"}


def test_inactive_market_status_excluded_per_existing_contract() -> None:
    raw = [_row("DORMANT-EUR", "DORMANT", status="halted")]
    build = build_constraint_rows(raw, synced_ts_utc=TS)
    assert build.eur_market_count == 1
    assert build.rows == ()
    assert build.skipped_markets == ("DORMANT-EUR",)


def test_multi_market_deterministic_ordering_independent_of_input_order() -> None:
    raw = [
        _row("ZZZ-EUR", "ZZZ"),
        _row("AAA-EUR", "AAA"),
        _row("MMM-EUR", "MMM"),
    ]
    build = build_constraint_rows(raw, synced_ts_utc=TS)
    assert [row.market for row in build.rows] == ["AAA-EUR", "MMM-EUR", "ZZZ-EUR"]

    build_reordered = build_constraint_rows(list(reversed(raw)), synced_ts_utc=TS)
    assert [row.market for row in build_reordered.rows] == ["AAA-EUR", "MMM-EUR", "ZZZ-EUR"]


def test_no_account_inputs_in_build_signature() -> None:
    params = set(inspect.signature(build_constraint_rows).parameters)
    assert not params & {"account_id", "trading_account_id", "holdings", "positions"}


# ---------------------------------------------------------------------------
# run_constraint_sync — idempotent upsert against a simulated table
# ---------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, store: dict[tuple[str, str], tuple]) -> None:
        self._store = store
        self.rowcount = 0

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_args) -> bool:
        return False

    def execute(self, sql: str, params: tuple) -> None:
        assert "ON DUPLICATE KEY UPDATE" in sql
        venue, market = params[0], params[1]
        key = (venue, market)
        existing = self._store.get(key)
        if existing is None:
            self._store[key] = params
            self.rowcount = 1
        elif existing == params:
            self.rowcount = 0
        else:
            self._store[key] = params
            self.rowcount = 2


class _FakeConn:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], tuple] = {}
        self.committed = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.store)

    def commit(self) -> None:
        self.committed += 1


def test_first_run_inserts_every_resolved_market() -> None:
    raw = [_row("BTC-EUR", "BTC"), _row("ETH-EUR", "ETH")]
    build = build_constraint_rows(raw, synced_ts_utc=TS)
    conn = _FakeConn()
    result = run_constraint_sync(conn, venue=DEFAULT_VENUE, build=build, write_db=True)
    assert result.inserted == 2
    assert result.updated == 0
    assert result.unchanged == 0
    assert conn.committed == 1
    assert len(conn.store) == 2


def test_rerun_with_identical_source_state_is_a_pure_noop() -> None:
    raw = [_row("BTC-EUR", "BTC"), _row("ETH-EUR", "ETH")]
    build = build_constraint_rows(raw, synced_ts_utc=TS)
    conn = _FakeConn()
    run_constraint_sync(conn, venue=DEFAULT_VENUE, build=build, write_db=True)

    result_2 = run_constraint_sync(conn, venue=DEFAULT_VENUE, build=build, write_db=True)
    assert result_2.inserted == 0
    assert result_2.updated == 0
    assert result_2.unchanged == 2
    assert len(conn.store) == 2


def test_rerun_with_changed_tick_size_updates_in_place_not_duplicates() -> None:
    raw_v1 = [_row("BTC-EUR", "BTC", tickSize="1.00")]
    conn = _FakeConn()
    run_constraint_sync(conn, venue=DEFAULT_VENUE, build=build_constraint_rows(raw_v1, synced_ts_utc=TS), write_db=True)

    raw_v2 = [_row("BTC-EUR", "BTC", tickSize="0.50")]
    later = TS.replace(hour=13)
    result_2 = run_constraint_sync(
        conn, venue=DEFAULT_VENUE, build=build_constraint_rows(raw_v2, synced_ts_utc=later), write_db=True,
    )
    assert result_2.inserted == 0
    assert result_2.updated == 1
    assert len(conn.store) == 1


def test_dry_run_performs_no_writes_and_no_commit() -> None:
    raw = [_row("BTC-EUR", "BTC")]
    build = build_constraint_rows(raw, synced_ts_utc=TS)
    conn = _FakeConn()
    result = run_constraint_sync(conn, venue=DEFAULT_VENUE, build=build, write_db=False)
    assert result.inserted == 0
    assert conn.committed == 0
    assert conn.store == {}


def test_skipped_and_resolved_counts_reported() -> None:
    raw = [_row("BTC-EUR", "BTC"), _row("BAD-EUR", "BAD", tickSize=None)]
    build = build_constraint_rows(raw, synced_ts_utc=TS)
    conn = _FakeConn()
    result = run_constraint_sync(conn, venue=DEFAULT_VENUE, build=build, write_db=True)
    assert result.eur_market_count == 2
    assert result.resolved_count == 1
    assert result.skipped_count == 1


# ---------------------------------------------------------------------------
# Compatibility with the existing fail-closed reader contract
# ---------------------------------------------------------------------------

def test_freshly_built_row_resolves_fresh_for_existing_automatic_buy_reader() -> None:
    raw = [_row("BTC-EUR", "BTC")]
    build = build_constraint_rows(raw, synced_ts_utc=TS)
    db_rows = {row.market: row for row in build.rows}
    resolved = resolve_venue_execution_constraints(
        venue=DEFAULT_VENUE, market="BTC-EUR", db_rows=db_rows, now=TS,
    )
    assert resolved.status == STATUS_FRESH
    assert resolved.tick_size == Decimal("0.01")


def test_default_quote_filter_matches_module_constant() -> None:
    assert DEFAULT_QUOTE_FILTER == "EUR"


# ---------------------------------------------------------------------------
# Structural boundary checks: public-only, no account/broker-write coupling
# ---------------------------------------------------------------------------

def test_module_uses_public_client_only() -> None:
    import src.market.run_bitvavo_venue_execution_constraint_sync_v1 as module

    source = inspect.getsource(module)
    assert "BitvavoClient.for_public" in source
    assert "for_private" not in source
    assert "place_order" not in source
    assert "api_key=" not in source
    assert "api_secret=" not in source


def test_module_has_no_account_or_execution_layer_imports() -> None:
    import src.market.run_bitvavo_venue_execution_constraint_sync_v1 as module

    source = inspect.getsource(module)
    for forbidden in ("import src.decision_gate", "import src.execution_planner", "import src.executor", "import src.account"):
        assert forbidden not in source
