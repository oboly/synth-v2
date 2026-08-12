from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

from src.account.account_snapshot_models_v1 import MarketSyncResult, MarketSyncRow
from src.market.run_bitvavo_market_sync_v1 import (
    _build_asset_insert_payload,
    fetch_asset_columns,
    normalize_market_rows,
    print_summary,
    run_market_sync,
    upsert_asset,
    upsert_venue_market,
)


def _capture_print_summary(result: MarketSyncResult, *, write_db: bool) -> str:
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        print_summary(result, write_db=write_db)
    finally:
        sys.stdout = old
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _raw_markets() -> list[dict]:
    return [
        {
            "market": "BTC-EUR",
            "status": "trading",
            "base": "BTC",
            "quote": "EUR",
            "pricePrecision": 5,
        },
        {
            "market": "ETH-EUR",
            "status": "trading",
            "base": "ETH",
            "quote": "EUR",
            "pricePrecision": 4,
        },
        {
            "market": "WLD-EUR",
            "status": "halted",
            "base": "WLD",
            "quote": "EUR",
            "pricePrecision": 4,
        },
        {
            "market": "BTC-USDT",
            "status": "trading",
            "base": "BTC",
            "quote": "USDT",
            "pricePrecision": 2,
        },
        {
            "market": "UNKNOWN-EUR",
            "status": "trading",
            "base": "",
            "quote": "EUR",
        },
    ]


# ---------------------------------------------------------------------------
# normalize_market_rows
# ---------------------------------------------------------------------------

def test_normalize_filters_non_eur_markets():
    rows, unsupported = normalize_market_rows(_raw_markets(), quote_filter="EUR")
    markets = {r.market for r in rows}
    assert "BTC-USDT" not in markets


def test_normalize_non_eur_counted_as_unsupported():
    rows, unsupported = normalize_market_rows(_raw_markets(), quote_filter="EUR")
    # BTC-USDT + UNKNOWN-EUR (empty base) = 2 unsupported
    assert unsupported == 2


def test_normalize_eur_markets_included():
    rows, _ = normalize_market_rows(_raw_markets(), quote_filter="EUR")
    markets = {r.market for r in rows}
    assert "BTC-EUR" in markets
    assert "ETH-EUR" in markets


def test_normalize_halted_market_not_tradeable():
    rows, _ = normalize_market_rows(_raw_markets(), quote_filter="EUR")
    wld = next(r for r in rows if r.market == "WLD-EUR")
    assert wld.is_tradeable is False


def test_normalize_trading_market_is_tradeable():
    rows, _ = normalize_market_rows(_raw_markets(), quote_filter="EUR")
    btc = next(r for r in rows if r.market == "BTC-EUR")
    assert btc.is_tradeable is True


def test_normalize_price_precision_parsed():
    rows, _ = normalize_market_rows(_raw_markets(), quote_filter="EUR")
    btc = next(r for r in rows if r.market == "BTC-EUR")
    assert btc.price_precision == 5


def test_normalize_status_preserved():
    rows, _ = normalize_market_rows(_raw_markets(), quote_filter="EUR")
    wld = next(r for r in rows if r.market == "WLD-EUR")
    assert wld.status == "halted"


def test_normalize_empty_base_filtered():
    rows, _ = normalize_market_rows(_raw_markets(), quote_filter="EUR")
    bases = {r.base for r in rows}
    assert "" not in bases


def test_normalize_empty_input():
    rows, unsupported = normalize_market_rows([], quote_filter="EUR")
    assert rows == []
    assert unsupported == 0


# ---------------------------------------------------------------------------
# run_market_sync dry-run (no DB)
# ---------------------------------------------------------------------------

class _FakeConn:
    """Minimal fake connection that accepts cursor calls but records nothing."""
    def __init__(self):
        self.committed = 0
        self.executed: list[str] = []
        self.asset_schema: list[dict[str, object]] = []

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.committed += 1


class _FakeCursor:
    def __init__(self, conn: _FakeConn):
        self._conn = conn
        self.rowcount = 1
        self.lastrowid = 99
        self._rows: list[dict] = []

    def execute(self, sql: str, params=None):
        self._conn.executed.append(sql.strip())
        if "information_schema.COLUMNS" in sql:
            self._rows = list(self._conn.asset_schema)
            self.rowcount = len(self._rows)
            return

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _sample_rows() -> list[MarketSyncRow]:
    return [
        MarketSyncRow(
            market="BTC-EUR",
            base="BTC",
            quote="EUR",
            status="trading",
            is_tradeable=True,
            price_precision=5,
            qty_precision=None,
        ),
        MarketSyncRow(
            market="ETH-EUR",
            base="ETH",
            quote="EUR",
            status="trading",
            is_tradeable=True,
            price_precision=4,
            qty_precision=None,
        ),
    ]


def test_dry_run_returns_zero_db_counts():
    result = run_market_sync(
        _FakeConn(),
        venue="bitvavo",
        rows=_sample_rows(),
        unsupported_count=1,
        write_db=False,
    )
    assert result.asset_inserted == 0
    assert result.venue_market_inserted == 0


def test_dry_run_total_markets_correct():
    rows = _sample_rows()
    result = run_market_sync(
        _FakeConn(),
        venue="bitvavo",
        rows=rows,
        unsupported_count=1,
        write_db=False,
    )
    assert result.total_markets == len(rows)


def test_dry_run_no_commit():
    conn = _FakeConn()
    run_market_sync(conn, venue="bitvavo", rows=_sample_rows(), unsupported_count=0, write_db=False)
    assert conn.committed == 0


def test_dry_run_unsupported_count_preserved():
    result = run_market_sync(
        _FakeConn(),
        venue="bitvavo",
        rows=_sample_rows(),
        unsupported_count=7,
        write_db=False,
    )
    assert result.unsupported_count == 7


def _asset_schema_rows() -> list[dict[str, object]]:
    return [
        {
            "COLUMN_NAME": "asset_id",
            "DATA_TYPE": "int",
            "COLUMN_TYPE": "int(11)",
            "IS_NULLABLE": "NO",
            "COLUMN_DEFAULT": None,
            "EXTRA": "auto_increment",
        },
        {
            "COLUMN_NAME": "symbol",
            "DATA_TYPE": "varchar",
            "COLUMN_TYPE": "varchar(32)",
            "IS_NULLABLE": "NO",
            "COLUMN_DEFAULT": None,
            "EXTRA": "",
        },
        {
            "COLUMN_NAME": "name",
            "DATA_TYPE": "varchar",
            "COLUMN_TYPE": "varchar(255)",
            "IS_NULLABLE": "NO",
            "COLUMN_DEFAULT": None,
            "EXTRA": "",
        },
        {
            "COLUMN_NAME": "is_enabled",
            "DATA_TYPE": "tinyint",
            "COLUMN_TYPE": "tinyint(1)",
            "IS_NULLABLE": "NO",
            "COLUMN_DEFAULT": None,
            "EXTRA": "",
        },
        {
            "COLUMN_NAME": "is_tradeable",
            "DATA_TYPE": "tinyint",
            "COLUMN_TYPE": "tinyint(1)",
            "IS_NULLABLE": "NO",
            "COLUMN_DEFAULT": None,
            "EXTRA": "",
        },
        {
            "COLUMN_NAME": "is_portfolio",
            "DATA_TYPE": "tinyint",
            "COLUMN_TYPE": "tinyint(1)",
            "IS_NULLABLE": "NO",
            "COLUMN_DEFAULT": None,
            "EXTRA": "",
        },
        {
            "COLUMN_NAME": "is_hidden",
            "DATA_TYPE": "tinyint",
            "COLUMN_TYPE": "tinyint(1)",
            "IS_NULLABLE": "NO",
            "COLUMN_DEFAULT": None,
            "EXTRA": "",
        },
        {
            "COLUMN_NAME": "asset_class",
            "DATA_TYPE": "varchar",
            "COLUMN_TYPE": "varchar(32)",
            "IS_NULLABLE": "NO",
            "COLUMN_DEFAULT": None,
            "EXTRA": "",
        },
    ]


class _AssetSchemaConn:
    def __init__(self, *, insert_rowcount: int = 1):
        self.asset_schema = _asset_schema_rows()
        self.insert_rowcount = insert_rowcount
        self.executions: list[tuple[str, object]] = []

    def cursor(self):
        return _AssetSchemaCursor(self)


class _AssetSchemaCursor:
    def __init__(self, conn: _AssetSchemaConn):
        self._conn = conn
        self.rowcount = 0
        self._rows: list[dict[str, object]] = []

    def execute(self, sql: str, params=None):
        normalized = " ".join(sql.split())
        self._conn.executions.append((normalized, params))
        if "information_schema.COLUMNS" in sql:
            self._rows = list(self._conn.asset_schema)
            self.rowcount = len(self._rows)
            return
        if normalized.startswith("INSERT INTO asset"):
            self.rowcount = self._conn.insert_rowcount
            return
        raise AssertionError(f"Unexpected SQL in asset schema test: {normalized}")

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _parse_insert_columns(sql: str) -> list[str]:
    prefix = "INSERT INTO asset ("
    start = sql.index(prefix) + len(prefix)
    end = sql.index(")", start)
    return [part.strip() for part in sql[start:end].split(",")]


def test_asset_insert_payload_sets_legacy_required_booleans():
    columns, values = _build_asset_insert_payload(_asset_schema_rows(), symbol="TON")
    payload = dict(zip(columns, values))
    assert payload["symbol"] == "TON"
    assert payload["name"] == "TON"
    assert payload["is_enabled"] == 1
    assert payload["is_tradeable"] == 1
    assert payload["is_portfolio"] == 0
    assert payload["is_hidden"] == 0
    assert payload["asset_class"] == "CRYPTO"


def test_asset_insert_payload_sets_canonical_publication_cohort_when_present():
    columns = _asset_schema_rows() + [{
        "COLUMN_NAME": "is_publication_cohort", "DATA_TYPE": "tinyint",
        "COLUMN_TYPE": "tinyint(1)", "IS_NULLABLE": "NO", "COLUMN_DEFAULT": None, "EXTRA": "",
    }]
    insert_columns, values = _build_asset_insert_payload(columns, symbol="TON")
    payload = dict(zip(insert_columns, values))
    assert payload["is_portfolio"] == 0
    assert payload["is_publication_cohort"] == 0


def test_upsert_asset_existing_row_does_not_overwrite_is_portfolio():
    conn = _AssetSchemaConn(insert_rowcount=2)
    action = upsert_asset(conn, symbol="LINK", asset_columns=conn.asset_schema)
    assert action == "EXISTING"
    insert_sql, params = conn.executions[-1]
    payload = dict(zip(_parse_insert_columns(insert_sql), params))
    assert payload["is_portfolio"] == 0
    update_clause = insert_sql.split("ON DUPLICATE KEY UPDATE", 1)[1]
    assert "is_portfolio" not in update_clause
    assert "is_enabled" not in update_clause


def test_fetch_asset_columns_uses_information_schema():
    conn = _FakeConn()
    conn.asset_schema = _asset_schema_rows()
    rows = fetch_asset_columns(conn)
    assert [row["COLUMN_NAME"] for row in rows][:3] == ["asset_id", "symbol", "name"]


# ---------------------------------------------------------------------------
# print_summary output contains safety markers
# ---------------------------------------------------------------------------

def test_print_summary_contains_broker_writes_zero():
    result = MarketSyncResult(
        venue="bitvavo",
        total_markets=10,
        asset_inserted=2,
        asset_existing=8,
        venue_market_inserted=2,
        venue_market_updated=8,
        unsupported_count=3,
    )
    out = _capture_print_summary(result, write_db=True)
    assert "broker_writes=0" in out
    assert "order_submission=0" in out
    assert "executor=none" in out


def test_print_summary_dry_run_label():
    result = MarketSyncResult(
        venue="bitvavo",
        total_markets=5,
        asset_inserted=0,
        asset_existing=0,
        venue_market_inserted=0,
        venue_market_updated=0,
        unsupported_count=0,
    )
    out = _capture_print_summary(result, write_db=False)
    assert "DRY_RUN" in out


# ---------------------------------------------------------------------------
# AST safety: no broker writes in source
# ---------------------------------------------------------------------------

def test_market_sync_source_no_broker_writes():
    src = Path("src/market/run_bitvavo_market_sync_v1.py").read_text()
    tree = ast.parse(src)
    forbidden = {"place_order", "cancel_order", "BROKER_WRITE_PERMISSION"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in forbidden:
            raise AssertionError(f"Forbidden symbol {node.id!r} found in market sync source")
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            raise AssertionError(f"Forbidden attr {node.attr!r} found in market sync source")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for f in forbidden:
                if f in node.value:
                    raise AssertionError(
                        f"Forbidden string {f!r} in constant in market sync source"
                    )


def test_market_sync_source_no_place_order_import():
    src = Path("src/market/run_bitvavo_market_sync_v1.py").read_text()
    assert "place_order" not in src
    assert "cancel_order" not in src
    assert "BitvavoClient" not in src


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    test_normalize_filters_non_eur_markets()
    test_normalize_non_eur_counted_as_unsupported()
    test_normalize_eur_markets_included()
    test_normalize_halted_market_not_tradeable()
    test_normalize_trading_market_is_tradeable()
    test_normalize_price_precision_parsed()
    test_normalize_status_preserved()
    test_normalize_empty_base_filtered()
    test_normalize_empty_input()
    test_dry_run_returns_zero_db_counts()
    test_dry_run_total_markets_correct()
    test_dry_run_no_commit()
    test_dry_run_unsupported_count_preserved()
    test_asset_insert_payload_sets_legacy_required_booleans()
    test_upsert_asset_existing_row_does_not_overwrite_is_portfolio()
    test_fetch_asset_columns_uses_information_schema()
    test_print_summary_contains_broker_writes_zero()
    test_print_summary_dry_run_label()
    test_market_sync_source_no_broker_writes()
    test_market_sync_source_no_place_order_import()
    print("ok")


if __name__ == "__main__":
    main()
