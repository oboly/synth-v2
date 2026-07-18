from __future__ import annotations

"""Fail-closed validation of a persisted canonical candle boundary."""

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
