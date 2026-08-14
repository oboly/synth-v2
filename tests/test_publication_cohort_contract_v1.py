from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.market.run_bitvavo_market_sync_v1 import _build_asset_insert_payload
from src.market_data.canonical_fib_zone_map_v1 import fetch_tracked_symbols
from src.market_data.publication_cohort_contract_v1 import (
    CANONICAL_COLUMN,
    LEGACY_COLUMN,
    PublicationCohortDriftError,
    fetch_publication_cohort_contract,
)


class _Cursor:
    def __init__(self, conn: "_Conn") -> None:
        self.conn = conn
        self.rows: list[dict[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.conn.sql.append(" ".join(sql.split()))
        if "information_schema.COLUMNS" in sql:
            self.rows = [{"COLUMN_NAME": name} for name in self.conn.columns]
        elif "COALESCE(is_portfolio, 0) <>" in sql:
            self.rows = [self.conn.drift] if self.conn.drift else []
        elif "SELECT DISTINCT a.symbol" in sql:
            self.rows = [{"symbol": symbol} for symbol in self.conn.symbols]
        else:
            raise AssertionError(sql)

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self.rows)

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _Conn:
    def __init__(
        self,
        columns: tuple[str, ...],
        *,
        symbols: tuple[str, ...] = ("BTC", "ETH"),
        drift: dict[str, Any] | None = None,
    ) -> None:
        self.columns = columns
        self.symbols = symbols
        self.drift = drift
        self.sql: list[str] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self)


def _column(name: str) -> dict[str, object]:
    return {
        "COLUMN_NAME": name,
        "DATA_TYPE": "tinyint",
        "COLUMN_TYPE": "tinyint(1)",
        "IS_NULLABLE": "NO",
        "COLUMN_DEFAULT": None,
        "EXTRA": "",
    }


def test_old_only_schema_reads_legacy_cohort() -> None:
    contract = fetch_publication_cohort_contract(_Conn((LEGACY_COLUMN,)))
    assert contract.read_column == LEGACY_COLUMN
    assert contract.write_columns == (LEGACY_COLUMN,)


def test_dual_schema_uses_canonical_after_drift_check() -> None:
    conn = _Conn((LEGACY_COLUMN, CANONICAL_COLUMN))
    contract = fetch_publication_cohort_contract(conn)
    assert contract.read_column == CANONICAL_COLUMN
    assert contract.write_columns == (LEGACY_COLUMN, CANONICAL_COLUMN)
    assert any("COALESCE(is_portfolio, 0) <>" in sql for sql in conn.sql)


def test_dual_schema_disagreement_fails_closed() -> None:
    conn = _Conn(
        (LEGACY_COLUMN, CANONICAL_COLUMN),
        drift={"asset_id": 7, "symbol": "ARB", "is_portfolio": 1, "is_publication_cohort": 0},
    )
    with pytest.raises(PublicationCohortDriftError, match="asset_id=7 symbol=ARB"):
        fetch_publication_cohort_contract(conn)


def test_bitvavo_sync_explicitly_seeds_every_present_cohort_column() -> None:
    common = [_column("symbol"), _column("name"), _column("is_enabled"), _column("is_tradeable")]
    cases = (
        ((LEGACY_COLUMN,), {LEGACY_COLUMN}),
        ((CANONICAL_COLUMN,), {CANONICAL_COLUMN}),
        ((LEGACY_COLUMN, CANONICAL_COLUMN), {LEGACY_COLUMN, CANONICAL_COLUMN}),
    )
    for names, expected in cases:
        columns, values = _build_asset_insert_payload(
            [*common, *[_column(name) for name in names]], symbol="TON"
        )
        payload = dict(zip(columns, values, strict=True))
        assert {name for name in payload if name in {LEGACY_COLUMN, CANONICAL_COLUMN}} == expected
        assert all(payload[name] == 0 for name in expected)


def test_tracked_symbol_identity_is_unchanged_for_old_and_cutover_schemas_per_venue_quote() -> None:
    pairs = {("bitvavo", "EUR"): ("BTC", "ETH"), ("other", "USD"): ("SOL",)}
    for (venue, quote), symbols in pairs.items():
        old = fetch_tracked_symbols(
            _Conn((LEGACY_COLUMN,), symbols=symbols), venue=venue, quote_currency=quote
        )
        cutover = fetch_tracked_symbols(
            _Conn((CANONICAL_COLUMN,), symbols=symbols), venue=venue, quote_currency=quote
        )
        assert old == cutover == sorted(symbols)


def test_backfill_contract_is_exact_value_copy_not_account_membership() -> None:
    migration = Path("db/migrations/20260814_backfill_asset_publication_cohort_v1.sql").read_text(
        encoding="utf-8"
    )
    assert "SET is_publication_cohort = is_portfolio" in migration
    assert "account_asset" not in migration
