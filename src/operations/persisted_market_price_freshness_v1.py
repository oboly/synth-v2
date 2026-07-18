from __future__ import annotations

"""Read-only persisted public-price freshness validation.

This module is an operations boundary used by persisted-state consumers.  It
never calls an exchange and never writes the database.  Freshness semantics
delegate to the canonical pure classifier in ``freshness_status_v1``.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from src.operations.freshness_status_v1 import (
    FRESH,
    MISSING,
    UNAVAILABLE,
    evaluate_freshness,
)


PASS = "PASS"
BLOCKED = "BLOCKED"
REASON_MALFORMED_OBSERVATION_TIMESTAMP = "MALFORMED_OBSERVATION_TIMESTAMP"
REASON_MALFORMED_SNAPSHOT_ROW_COUNT = "MALFORMED_SNAPSHOT_ROW_COUNT"
REASON_QUERY_FAILED = "QUERY_FAILED"


@dataclass(frozen=True)
class PersistedMarketPriceFreshness:
    public_price_validation_result: str
    freshness_classification: str
    reason: str
    persisted_public_price_as_of_utc: datetime | None
    persisted_public_price_age_seconds: float | None
    stale_after_seconds: float
    snapshot_row_count: int

    @property
    def is_fresh(self) -> bool:
        return self.public_price_validation_result == PASS


def fetch_latest_persisted_price_batch(
    conn: Any,
    *,
    venue: str,
    quote_currency: str,
) -> Mapping[str, Any] | None:
    """Return the newest persisted batch identity using exactly one SELECT."""

    sql = """
        SELECT observed_ts_utc, COUNT(*) AS snapshot_row_count
        FROM market_price_snapshot
        WHERE venue = %s
          AND quote_currency = %s
        GROUP BY observed_ts_utc
        ORDER BY observed_ts_utc DESC
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue.lower(), quote_currency.upper()))
        return cur.fetchone()


def _blocked(
    *,
    classification: str,
    reason: str,
    stale_after: timedelta,
    as_of_utc: datetime | None = None,
    age_seconds: float | None = None,
    snapshot_row_count: int = 0,
) -> PersistedMarketPriceFreshness:
    return PersistedMarketPriceFreshness(
        public_price_validation_result=BLOCKED,
        freshness_classification=classification,
        reason=reason,
        persisted_public_price_as_of_utc=as_of_utc,
        persisted_public_price_age_seconds=age_seconds,
        stale_after_seconds=stale_after.total_seconds(),
        snapshot_row_count=snapshot_row_count,
    )


def classify_persisted_price_batch(
    row: Mapping[str, Any] | None,
    *,
    now_utc: datetime,
    stale_after: timedelta,
    max_future_skew: timedelta = timedelta(seconds=30),
) -> PersistedMarketPriceFreshness:
    """Classify a persisted batch; malformed input always fails closed."""

    if row is None:
        result = evaluate_freshness(None, now_utc, stale_after)
        return _blocked(
            classification=MISSING,
            reason=result.reason,
            stale_after=stale_after,
        )

    observed = row.get("observed_ts_utc")
    if not isinstance(observed, datetime):
        return _blocked(
            classification=UNAVAILABLE,
            reason=REASON_MALFORMED_OBSERVATION_TIMESTAMP,
            stale_after=stale_after,
        )
    # MariaDB DATETIME values are UTC by schema contract but are returned as
    # naive datetimes by the driver.  Attach UTC at this DB boundary only.
    observed_utc = observed.replace(tzinfo=UTC) if observed.tzinfo is None else observed.astimezone(UTC)

    raw_count = row.get("snapshot_row_count")
    try:
        snapshot_row_count = int(raw_count)
    except (TypeError, ValueError):
        snapshot_row_count = 0
    if snapshot_row_count <= 0:
        return _blocked(
            classification=UNAVAILABLE,
            reason=REASON_MALFORMED_SNAPSHOT_ROW_COUNT,
            stale_after=stale_after,
            as_of_utc=observed_utc,
        )

    result = evaluate_freshness(
        observed_utc,
        now_utc,
        stale_after,
        max_future_skew=max_future_skew,
    )
    return PersistedMarketPriceFreshness(
        public_price_validation_result=PASS if result.status == FRESH else BLOCKED,
        freshness_classification=result.status,
        reason=result.reason,
        persisted_public_price_as_of_utc=result.observed_ts_utc,
        persisted_public_price_age_seconds=result.age_seconds,
        stale_after_seconds=result.stale_after_seconds,
        snapshot_row_count=snapshot_row_count,
    )


def query_failed_result(*, stale_after: timedelta) -> PersistedMarketPriceFreshness:
    return _blocked(
        classification=UNAVAILABLE,
        reason=REASON_QUERY_FAILED,
        stale_after=stale_after,
    )
