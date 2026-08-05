from __future__ import annotations

"""Regression tests for the 20:00Z canonical Fib publication collision.

Root cause: canonical_fib_zone_map_v1.asof_ts_utc was written as the row's own
source-candle timestamp (input_latest_candle_ts_utc) instead of the
publication's own asof_ts_utc, so a symbol whose source candle stayed stale
across two consecutive, legitimate publication cohorts (NOT still sourced from
16:00 data at a 20:00 publication) produced the same
(venue, symbol, interval_code, asof_ts_utc, map_version) tuple twice and hit
uq_canonical_fib_zone_map_v1.

Intended model (see db/migrations/20260806_canonical_fib_zone_map_publication_identity_v1.sql):
every publication is an immutable cohort with exactly one row per symbol;
row.asof_ts_utc always equals the publication's build asof;
input_latest_candle_ts_utc remains the source freshness timestamp; child-row
identity is (venue, symbol, interval_code, publication_id, map_version).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from src.market_data.canonical_fib_zone_map_v1 import (
    CanonicalFibMapError,
    PublicationBuild,
    build_publication,
    insert_publication_cohort,
    publish,
)
from src.market_data.fib_navigation_map_v1 import FibNavCandle
from src.operations.writer_capability_authorization_v1 import (
    ExecutionMode,
    _mint_authorization,
)


LOWS = ("100", "98", "95", "90", "94", "99", "104", "108", "106", "109", "111", "112")
HIGHS = ("105", "103", "100", "95", "100", "106", "112", "120", "116", "119", "121", "122")


def bullish_candles(end_ts: datetime) -> list[FibNavCandle]:
    start = end_ts - timedelta(hours=4 * (len(LOWS) - 1))
    return [
        FibNavCandle(
            close_ts_utc=start + timedelta(hours=4 * index),
            open_price=(Decimal(low) + Decimal(high)) / 2,
            high_price=Decimal(high),
            low_price=Decimal(low),
            close_price=(Decimal(low) + Decimal(high)) / 2,
            volume=Decimal("1000"),
        )
        for index, (low, high) in enumerate(zip(LOWS, HIGHS, strict=True))
    ]


def trend_row(source: list[FibNavCandle]) -> dict[str, object]:
    return {
        "close_ts_utc": source[-1].close_ts_utc,
        "price_vs_ema20": Decimal("0.03"),
        "price_vs_ema50": Decimal("0.04"),
        "ema_spread_pct": Decimal("0.02"),
    }


def _authorization() -> Any:
    return _mint_authorization(
        capability_id="native_short_4h_chain",
        execution_mode=ExecutionMode.PRODUCTION,
        validated_host="test-host",
        validated_commit="0" * 40,
        authorization_or_permit_id="test-authorization",
    )


class _IntegrityError(Exception):
    """Stand-in for the pymysql/MariaDB 1062 duplicate-key error."""


class _FakeCursor:
    def __init__(self, script: dict) -> None:
        self._script = script
        self._result: Any = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: Any = ()) -> None:
        stripped = sql.strip()
        if stripped.startswith("SELECT") and "canonical_fib_zone_map_publication_v1" in sql:
            venue, quote, interval, asof = params[0], params[1], params[2], params[3]
            match = None
            for row in self._script["publications"].values():
                if (
                    row["venue"] == venue
                    and row["quote_currency"] == quote
                    and row["interval_code"] == interval
                    and row["asof_ts_utc"] == asof
                ):
                    match = row
                    break
            self._result = match
        elif stripped.startswith("INSERT INTO canonical_fib_zone_map_publication_v1"):
            (
                publication_id,
                venue,
                quote,
                interval,
                asof,
                map_version,
                digest,
                row_count,
                available_count,
                producer_name,
                producer_version,
            ) = params
            self._script["publications"][publication_id] = {
                "publication_id": publication_id,
                "venue": venue,
                "quote_currency": quote,
                "interval_code": interval,
                "asof_ts_utc": asof,
                "map_version": map_version,
                "content_digest": digest,
                "row_count": row_count,
                "available_count": available_count,
            }
        elif stripped.startswith("INSERT INTO canonical_fib_zone_map_v1"):
            row = dict(params)
            # Enforce the migrated uq_canonical_fib_zone_map_v1:
            # (venue, symbol, interval_code, publication_id, map_version).
            key = (
                row["venue"],
                row["symbol"],
                row["interval_code"],
                row["publication_id"],
                row["map_version"],
            )
            if key in self._script["map_keys"]:
                raise _IntegrityError(
                    "Duplicate entry for key 'uq_canonical_fib_zone_map_v1'"
                )
            self._script["map_keys"].add(key)
            self._script["map_rows"].append(row)
        else:
            raise AssertionError(f"unexpected SQL in fake cursor: {sql[:120]}")

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._result or []


class _FakeConn:
    def __init__(self) -> None:
        self.script: dict = {"publications": {}, "map_rows": [], "map_keys": set()}
        self.committed = 0
        self.rolled_back = 0

    def cursor(self):
        return _FakeCursor(self.script)

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def rows_for(self, symbol: str) -> list[dict]:
        return [row for row in self.script["map_rows"] if row["symbol"] == symbol]


def _build(
    *,
    symbols_and_end_ts: dict[str, datetime],
    now_utc: datetime,
) -> PublicationBuild:
    candles_by_symbol = {
        symbol: bullish_candles(end_ts) for symbol, end_ts in symbols_and_end_ts.items()
    }
    trend_rows_by_symbol = {
        symbol: trend_row(candles) for symbol, candles in candles_by_symbol.items()
    }
    return build_publication(
        venue="bitvavo",
        quote_currency="EUR",
        interval_code="4h",
        symbols=list(symbols_and_end_ts),
        candles_by_symbol=candles_by_symbol,
        trend_rows_by_symbol=trend_rows_by_symbol,
        now_utc=now_utc,
    )


T_1600 = datetime(2026, 8, 5, 16, 0, tzinfo=UTC)
T_2000 = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
# insert_publication_cohort writes naive UTC via _db_ts; DB-row assertions
# below compare against these naive equivalents.
DB_1600 = T_1600.replace(tzinfo=None)
DB_2000 = T_2000.replace(tzinfo=None)


def test_1600_publication_contains_not_at_source_1600() -> None:
    build = _build(symbols_and_end_ts={"NOT": T_1600}, now_utc=T_1600 + timedelta(minutes=5))
    assert build.asof_ts_utc == T_1600

    conn = _FakeConn()
    result = publish(conn, build, authorization=_authorization())
    assert result.status == "PUBLISHED"
    [row] = conn.rows_for("NOT")
    assert row["asof_ts_utc"] == DB_1600
    assert row["input_latest_candle_ts_utc"] == DB_1600


def test_2000_publication_may_still_source_not_from_1600() -> None:
    """NOT's source candle is unchanged since the 16:00 cohort; BTC is fresh at
    20:00. The publication asof is the max across symbols (20:00), and NOT's
    row must carry that publication asof even though its source data is 16:00.
    """
    build = _build(
        symbols_and_end_ts={"NOT": T_1600, "BTC": T_2000},
        now_utc=T_2000 + timedelta(minutes=5),
    )
    assert build.asof_ts_utc == T_2000

    conn = _FakeConn()
    result = publish(conn, build, authorization=_authorization())
    assert result.status == "PUBLISHED"
    [not_row] = conn.rows_for("NOT")
    assert not_row["asof_ts_utc"] == DB_2000, "row identity must be the publication asof"
    assert not_row["input_latest_candle_ts_utc"] == DB_1600, "source freshness must stay 16:00"
    [btc_row] = conn.rows_for("BTC")
    assert btc_row["asof_ts_utc"] == DB_2000
    assert btc_row["input_latest_candle_ts_utc"] == DB_2000


def test_1600_and_2000_cohorts_coexist_without_collision() -> None:
    conn = _FakeConn()
    first = _build(symbols_and_end_ts={"NOT": T_1600}, now_utc=T_1600 + timedelta(minutes=5))
    publish(conn, first, authorization=_authorization())

    second = _build(
        symbols_and_end_ts={"NOT": T_1600, "BTC": T_2000},
        now_utc=T_2000 + timedelta(minutes=5),
    )
    result = publish(conn, second, authorization=_authorization())

    assert result.status == "PUBLISHED"
    not_rows = conn.rows_for("NOT")
    assert len(not_rows) == 2
    assert {row["publication_id"] for row in not_rows} == {
        f"fibnav-{first.content_digest[:32]}",
        f"fibnav-{second.content_digest[:32]}",
    }
    assert {row["asof_ts_utc"] for row in not_rows} == {DB_1600, DB_2000}
    assert all(row["input_latest_candle_ts_utc"] == DB_1600 for row in not_rows)


def test_each_publication_has_exactly_one_row_per_symbol() -> None:
    build = _build(
        symbols_and_end_ts={"NOT": T_1600, "BTC": T_2000},
        now_utc=T_2000 + timedelta(minutes=5),
    )
    conn = _FakeConn()
    publish(conn, build, authorization=_authorization())
    assert len(conn.rows_for("NOT")) == 1
    assert len(conn.rows_for("BTC")) == 1
    assert len(conn.script["map_rows"]) == 2


def test_duplicate_symbol_within_same_publication_still_fails() -> None:
    """build_publication already de-duplicates symbols via a set, so this
    exercises the DB-level guard directly: two rows for the same symbol under
    the same publication_id must still be rejected by the unique key.
    """
    build = _build(symbols_and_end_ts={"NOT": T_1600}, now_utc=T_1600 + timedelta(minutes=5))
    conn = _FakeConn()
    with conn.cursor() as cur:
        publication_id = "fibnav-duplicate-test"
        doubled = PublicationBuild(
            venue=build.venue,
            quote_currency=build.quote_currency,
            interval_code=build.interval_code,
            asof_ts_utc=build.asof_ts_utc,
            rows=build.rows + build.rows,
            content_digest=build.content_digest,
            available_count=build.available_count,
        )
        with pytest.raises(_IntegrityError, match="uq_canonical_fib_zone_map_v1"):
            insert_publication_cohort(cur, doubled, publication_id)


def test_same_publication_retry_remains_idempotent() -> None:
    build = _build(symbols_and_end_ts={"NOT": T_1600}, now_utc=T_1600 + timedelta(minutes=5))
    conn = _FakeConn()
    first = publish(conn, build, authorization=_authorization())
    second = publish(conn, build, authorization=_authorization())
    assert first.status == "PUBLISHED"
    assert second.status == "UNCHANGED"
    assert second.publication_id == first.publication_id
    assert len(conn.rows_for("NOT")) == 1


def test_different_content_at_same_identity_still_fails_closed() -> None:
    """Ordinary nondeterminism at the same publication asof must still be
    rejected by ``publish`` -- this collision fix must not weaken that guard.
    """
    build = _build(symbols_and_end_ts={"NOT": T_1600}, now_utc=T_1600 + timedelta(minutes=5))
    conn = _FakeConn()
    publish(conn, build, authorization=_authorization())

    other = _build(symbols_and_end_ts={"NOT": T_1600}, now_utc=T_1600 + timedelta(minutes=5))
    mutated_rows = tuple({**row, "reference_price": row["reference_price"] * 2} for row in other.rows)
    mutated = PublicationBuild(
        venue=other.venue,
        quote_currency=other.quote_currency,
        interval_code=other.interval_code,
        asof_ts_utc=other.asof_ts_utc,
        rows=mutated_rows,
        content_digest="f" * 64,
        available_count=other.available_count,
    )
    with pytest.raises(CanonicalFibMapError, match="publication identity collision"):
        publish(conn, mutated, authorization=_authorization())
