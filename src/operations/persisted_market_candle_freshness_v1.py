from __future__ import annotations

"""Fail-closed validation of a persisted canonical candle boundary.

Two levels of freshness truth live here:

- ``classify_persisted_candle_boundary`` -- single (venue, interval) boundary
  check against one expected close. This is the existing per-market/per-call
  contract consumed by callers that already know which symbol they care
  about.
- ``classify_universe_candle_coverage`` -- aggregate, whole-universe view
  across every eligible symbol for one (venue, interval). This distinguishes
  an isolated per-symbol gap (``PARTIAL_COVERAGE``) from a systemic producer
  outage where every symbol stalled at the same boundary (``WRITER_FAILED``),
  which the per-symbol check alone cannot reveal (Issue #606: an ICP-EUR
  freshness gap traced back to a global writer stall was previously visible
  only market-by-market).
"""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping


PASS = "PASS"
BLOCKED = "BLOCKED"
FRESH = "FRESH"
MISSING = "MISSING"
MALFORMED = "MALFORMED"
FUTURE = "FUTURE"
STALE = "STALE"

# Universe-level coverage states (Issue #606 freshness contract).
CURRENT = "CURRENT"
PARTIAL_COVERAGE = "PARTIAL_COVERAGE"
WRITER_FAILED = "WRITER_FAILED"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"

# Default fraction of the non-current universe that must share one identical
# lagging close boundary before the gap is classified as a systemic writer
# outage rather than a set of unrelated per-symbol gaps.
DEFAULT_WRITER_FAILED_DOMINANCE_RATIO = 0.9


@dataclass(frozen=True)
class PersistedMarketCandleFreshness:
    validation_result: str
    freshness_classification: str
    reason: str
    expected_close_ts_utc: datetime
    latest_close_ts_utc: datetime | None
    expected_close_row_count: int

    @property
    def is_fresh(self) -> bool:
        return self.validation_result == PASS


def fetch_persisted_candle_boundary(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    expected_close_ts_utc: datetime,
) -> Mapping[str, Any]:
    """Use one SELECT to inspect the exact persisted close and newest close."""

    sql = """
        SELECT
            MAX(close_ts_utc) AS latest_close_ts_utc,
            COALESCE(SUM(CASE WHEN close_ts_utc = %s THEN 1 ELSE 0 END), 0)
                AS expected_close_row_count
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                expected_close_ts_utc.replace(tzinfo=None),
                venue.lower(),
                interval_code,
            ),
        )
        return cur.fetchone()


def _as_utc(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def classify_persisted_candle_boundary(
    row: Mapping[str, Any] | None,
    *,
    expected_close_ts_utc: datetime,
) -> PersistedMarketCandleFreshness:
    expected = expected_close_ts_utc.astimezone(UTC)
    if row is None:
        return PersistedMarketCandleFreshness(
            BLOCKED, MISSING, "NO_CANDLE_QUERY_RESULT", expected, None, 0
        )

    latest_raw = row.get("latest_close_ts_utc")
    latest = _as_utc(latest_raw)
    if latest_raw is not None and latest is None:
        return PersistedMarketCandleFreshness(
            BLOCKED, MALFORMED, "MALFORMED_LATEST_CLOSE", expected, None, 0
        )

    try:
        exact_count = int(row.get("expected_close_row_count") or 0)
    except (TypeError, ValueError):
        return PersistedMarketCandleFreshness(
            BLOCKED, MALFORMED, "MALFORMED_EXPECTED_CLOSE_ROW_COUNT", expected, latest, 0
        )

    if latest is None:
        return PersistedMarketCandleFreshness(
            BLOCKED, MISSING, "NO_PERSISTED_CANDLES", expected, None, 0
        )
    if latest > expected:
        return PersistedMarketCandleFreshness(
            BLOCKED, FUTURE, "LATEST_CLOSE_AFTER_EXPECTED_BOUNDARY", expected, latest, exact_count
        )
    if latest < expected or exact_count <= 0:
        return PersistedMarketCandleFreshness(
            BLOCKED, STALE, "EXPECTED_CLOSE_NOT_PERSISTED", expected, latest, exact_count
        )
    return PersistedMarketCandleFreshness(
        PASS, FRESH, "EXPECTED_CLOSE_PERSISTED", expected, latest, exact_count
    )


def fetch_universe_latest_close_by_symbol(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    symbols: list[str],
) -> Mapping[str, Any]:
    """One SELECT for the latest persisted close per symbol in ``symbols``.

    Callers pass the already-resolved eligible/enabled symbol universe (the
    same active-market filter the writer itself applies) so a delisted or
    disabled market never counts against coverage.
    """
    if not symbols:
        return {}

    placeholders = ", ".join(["%s"] * len(symbols))
    sql = f"""
        SELECT a.symbol AS symbol, MAX(c.close_ts_utc) AS latest_close_ts_utc
        FROM asset a
        LEFT JOIN obs_market_candle c
            ON c.asset_id = a.asset_id
            AND c.venue = %s
            AND c.interval_code = %s
        WHERE a.symbol IN ({placeholders})
        GROUP BY a.symbol
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue.lower(), interval_code, *symbols))
        rows = cur.fetchall()
    return {str(row["symbol"]): row.get("latest_close_ts_utc") for row in rows}


@dataclass(frozen=True)
class UniverseCandleCoverage:
    interval_code: str
    overall_state: str
    reason: str
    expected_close_ts_utc: datetime
    universe_size: int
    current_count: int
    stale_count: int
    missing_count: int
    dominant_lag_close_ts_utc: datetime | None
    dominant_lag_symbol_count: int


def classify_universe_candle_coverage(
    *,
    interval_code: str,
    expected_close_ts_utc: datetime,
    symbol_latest_close: Mapping[str, object],
    writer_failed_dominance_ratio: float = DEFAULT_WRITER_FAILED_DOMINANCE_RATIO,
) -> UniverseCandleCoverage:
    """Classify whole-universe coverage for one (venue, interval) boundary.

    ``symbol_latest_close`` maps every eligible symbol to its latest
    persisted ``close_ts_utc`` (``None``/missing entries count as no data).
    This function does no I/O and does not know about venues or SQL -- it is
    a pure classifier so it can be exercised with fixture data.
    """
    expected = expected_close_ts_utc.astimezone(UTC)
    universe_size = len(symbol_latest_close)

    if universe_size == 0:
        return UniverseCandleCoverage(
            interval_code, SOURCE_UNAVAILABLE, "NO_ELIGIBLE_SYMBOLS",
            expected, 0, 0, 0, 0, None, 0,
        )

    current_count = 0
    missing_count = 0
    lag_counts: Counter[datetime] = Counter()

    for raw_latest in symbol_latest_close.values():
        latest = _as_utc(raw_latest)
        if latest is None:
            missing_count += 1
            continue
        if latest >= expected:
            current_count += 1
            continue
        lag_counts[latest] += 1

    stale_count = universe_size - current_count - missing_count
    non_current_count = universe_size - current_count

    dominant_lag_ts: datetime | None = None
    dominant_lag_count = 0
    if lag_counts:
        dominant_lag_ts, dominant_lag_count = lag_counts.most_common(1)[0]

    if current_count == universe_size:
        return UniverseCandleCoverage(
            interval_code, CURRENT, "ALL_SYMBOLS_AT_EXPECTED_BOUNDARY",
            expected, universe_size, current_count, stale_count, missing_count,
            None, 0,
        )

    if missing_count == universe_size:
        return UniverseCandleCoverage(
            interval_code, MISSING, "NO_SYMBOL_HAS_ANY_PERSISTED_CANDLE",
            expected, universe_size, current_count, stale_count, missing_count,
            None, 0,
        )

    if current_count == 0 and dominant_lag_count / non_current_count >= writer_failed_dominance_ratio:
        return UniverseCandleCoverage(
            interval_code, WRITER_FAILED,
            f"DOMINANT_LAG_BOUNDARY_SHARED_BY_{dominant_lag_count}_OF_{universe_size}_SYMBOLS",
            expected, universe_size, current_count, stale_count, missing_count,
            dominant_lag_ts, dominant_lag_count,
        )

    if current_count == 0:
        return UniverseCandleCoverage(
            interval_code, STALE, "NO_SYMBOL_AT_EXPECTED_BOUNDARY_NO_DOMINANT_LAG",
            expected, universe_size, current_count, stale_count, missing_count,
            dominant_lag_ts, dominant_lag_count,
        )

    return UniverseCandleCoverage(
        interval_code, PARTIAL_COVERAGE,
        f"{current_count}_OF_{universe_size}_SYMBOLS_AT_EXPECTED_BOUNDARY",
        expected, universe_size, current_count, stale_count, missing_count,
        dominant_lag_ts, dominant_lag_count,
    )
