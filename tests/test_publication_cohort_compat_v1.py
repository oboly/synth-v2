from __future__ import annotations

from pathlib import Path

import pytest

from src.market_data.canonical_fib_zone_map_v1 import fetch_tracked_symbols
from src.market_data.publication_cohort_compat_v1 import (
    PublicationCohortCompatibilityError,
    assert_no_publication_cohort_drift,
)


class _Cursor:
    def __init__(self, conn: "_Conn") -> None:
        self.conn = conn
        self.rows: list[dict[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, sql: str, params=None) -> None:
        self.conn.sql.append(" ".join(sql.split()))
        if "information_schema.COLUMNS" in sql:
            self.rows = [{"COLUMN_NAME": column} for column in self.conn.columns]
        elif "WHERE NOT (is_portfolio <=> is_publication_cohort)" in sql:
            self.rows = list(self.conn.drift_rows[:1])
        elif "SELECT DISTINCT a.symbol" in sql:
            self.rows = [{"symbol": symbol} for symbol in self.conn.symbols]
        else:
            raise AssertionError(sql)

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Conn:
    def __init__(self, *, columns: tuple[str, ...], symbols=("BTC", "ETH"), drift_rows=()) -> None:
        self.columns = columns
        self.symbols = symbols
        self.drift_rows = list(drift_rows)
        self.sql: list[str] = []

    def cursor(self):
        return _Cursor(self)


def test_old_column_only_schema_is_supported() -> None:
    conn = _Conn(columns=("is_portfolio",))
    assert assert_no_publication_cohort_drift(conn) == "is_portfolio"


def test_dual_schema_uses_canonical_column_after_verified_backfill() -> None:
    conn = _Conn(columns=("is_portfolio", "is_publication_cohort"))
    assert assert_no_publication_cohort_drift(conn) == "is_publication_cohort"


def test_new_column_only_schema_is_the_removable_cutover_target() -> None:
    conn = _Conn(columns=("is_publication_cohort",))
    assert assert_no_publication_cohort_drift(conn) == "is_publication_cohort"


def test_dual_schema_disagreement_fails_closed_with_deterministic_evidence() -> None:
    conn = _Conn(
        columns=("is_portfolio", "is_publication_cohort"),
        drift_rows=({"asset_id": 12, "symbol": "XLM"},),
    )
    with pytest.raises(PublicationCohortCompatibilityError, match="asset_id=12 symbol=XLM"):
        assert_no_publication_cohort_drift(conn)


@pytest.mark.parametrize("venue,quote", [("bitvavo", "EUR"), ("kraken", "USD")])
def test_tracked_symbols_keep_exact_identity_across_old_and_canonical_cutover(venue: str, quote: str) -> None:
    old = _Conn(columns=("is_portfolio",), symbols=("BTC", "ETH", "XLM"))
    cutover = _Conn(columns=("is_portfolio", "is_publication_cohort"), symbols=("BTC", "ETH", "XLM"))
    assert fetch_tracked_symbols(old, venue=venue, quote_currency=quote) == fetch_tracked_symbols(
        cutover, venue=venue, quote_currency=quote
    )
    assert any("a.is_portfolio" in sql for sql in old.sql)
    assert any("a.is_publication_cohort" in sql for sql in cutover.sql)


def test_backfill_migration_copies_only_the_legacy_global_field() -> None:
    source = Path("db/migrations/20260812_asset_publication_cohort_backfill_v1.sql").read_text(encoding="utf-8")
    assert "SET is_publication_cohort = is_portfolio" in source
    assert "UPDATE account_asset" not in source


def test_historical_rebuild_guard_remains_verbatim() -> None:
    source = Path("src/market_data/canonical_fib_zone_map_v1.py").read_text(encoding="utf-8")
    expected = (
        'so they are not historical truth for\n'
        '    an old asof and must never be used to decide which symbols an old\n'
        '    publication "should" have contained. Callers must supply the exact\n'
    )
    assert expected in source
