from __future__ import annotations

import pytest

from src.execution_capability.execution_capability_v1 import ExecutionCapabilityError
from src.reporting.execution_capability_reporting_adapter_v1 import fetch_execution_mode_by_symbol


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, rows):
        self.cursor_obj = _Cursor(rows)

    def cursor(self):
        return self.cursor_obj


def test_empty_symbols_performs_no_query() -> None:
    conn = _Conn([])
    assert fetch_execution_mode_by_symbol(conn, symbols=[]) == {}
    assert conn.cursor_obj.sql is None


def test_reads_generic_modes_without_symbol_specific_logic() -> None:
    conn = _Conn([
        {"symbol": "MDT", "execution_mode": "MANUAL_RFQ"},
        {"symbol": "BOND10Y", "execution_mode": "MANUAL"},
        {"symbol": "BTC", "execution_mode": "AUTOMATED"},
    ])
    result = fetch_execution_mode_by_symbol(conn, symbols=["btc", "MDT", "BOND10Y", "btc"])
    assert result == {
        "BTC": "AUTOMATED",
        "MDT": "MANUAL_RFQ",
        "BOND10Y": "MANUAL",
    }
    assert "SELECT symbol, execution_mode" in conn.cursor_obj.sql
    assert "UPDATE " not in conn.cursor_obj.sql.upper()
    assert "INSERT " not in conn.cursor_obj.sql.upper()
    assert "DELETE " not in conn.cursor_obj.sql.upper()


def test_unsupported_canonical_mode_fails_closed() -> None:
    conn = _Conn([{"symbol": "XYZ", "execution_mode": "MAGIC"}])
    with pytest.raises(ExecutionCapabilityError):
        fetch_execution_mode_by_symbol(conn, symbols=["XYZ"])
