from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.operations.freshness_status_v1 import (
    FRESH,
    MISSING,
    REASON_EXCEEDS_THRESHOLD,
    REASON_FUTURE_TIMESTAMP,
    STALE,
    UNAVAILABLE,
)
from src.operations.persisted_market_price_freshness_v1 import (
    BLOCKED,
    PASS,
    REASON_MALFORMED_OBSERVATION_TIMESTAMP,
    REASON_MALFORMED_SNAPSHOT_ROW_COUNT,
    classify_persisted_price_batch,
    fetch_latest_persisted_price_batch,
)


NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
STALE_AFTER = timedelta(minutes=15)


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row):
        self.cursor_instance = FakeCursor(row)

    def cursor(self):
        return self.cursor_instance


def test_current_persisted_price_passes() -> None:
    result = classify_persisted_price_batch(
        {"observed_ts_utc": NOW - timedelta(minutes=5), "snapshot_row_count": 42},
        now_utc=NOW,
        stale_after=STALE_AFTER,
    )
    assert result.public_price_validation_result == PASS
    assert result.freshness_classification == FRESH
    assert result.is_fresh
    assert result.persisted_public_price_age_seconds == 300.0


def test_stale_persisted_price_blocks() -> None:
    result = classify_persisted_price_batch(
        {"observed_ts_utc": NOW - timedelta(minutes=16), "snapshot_row_count": 42},
        now_utc=NOW,
        stale_after=STALE_AFTER,
    )
    assert result.public_price_validation_result == BLOCKED
    assert result.freshness_classification == STALE
    assert result.reason == REASON_EXCEEDS_THRESHOLD


def test_missing_persisted_price_blocks() -> None:
    result = classify_persisted_price_batch(None, now_utc=NOW, stale_after=STALE_AFTER)
    assert result.public_price_validation_result == BLOCKED
    assert result.freshness_classification == MISSING


def test_malformed_timestamp_blocks() -> None:
    result = classify_persisted_price_batch(
        {"observed_ts_utc": "not-a-timestamp", "snapshot_row_count": 42},
        now_utc=NOW,
        stale_after=STALE_AFTER,
    )
    assert result.freshness_classification == UNAVAILABLE
    assert result.reason == REASON_MALFORMED_OBSERVATION_TIMESTAMP


def test_malformed_row_count_blocks() -> None:
    result = classify_persisted_price_batch(
        {"observed_ts_utc": NOW, "snapshot_row_count": 0},
        now_utc=NOW,
        stale_after=STALE_AFTER,
    )
    assert result.freshness_classification == UNAVAILABLE
    assert result.reason == REASON_MALFORMED_SNAPSHOT_ROW_COUNT


def test_future_timestamp_blocks() -> None:
    result = classify_persisted_price_batch(
        {"observed_ts_utc": NOW + timedelta(minutes=2), "snapshot_row_count": 42},
        now_utc=NOW,
        stale_after=STALE_AFTER,
        max_future_skew=timedelta(seconds=30),
    )
    assert result.public_price_validation_result == BLOCKED
    assert result.reason == REASON_FUTURE_TIMESTAMP


def test_mariadb_naive_timestamp_is_typed_as_utc_at_boundary() -> None:
    result = classify_persisted_price_batch(
        {"observed_ts_utc": datetime(2026, 7, 18, 11, 55), "snapshot_row_count": 42},
        now_utc=NOW,
        stale_after=STALE_AFTER,
    )
    assert result.is_fresh
    assert result.persisted_public_price_as_of_utc == datetime(2026, 7, 18, 11, 55, tzinfo=UTC)


def test_persisted_price_repository_is_select_only() -> None:
    conn = FakeConnection({"observed_ts_utc": NOW, "snapshot_row_count": 42})
    row = fetch_latest_persisted_price_batch(conn, venue="bitvavo", quote_currency="eur")
    assert row is not None
    assert len(conn.cursor_instance.calls) == 1
    sql, params = conn.cursor_instance.calls[0]
    normalized = " ".join(sql.split()).upper()
    assert normalized.startswith("SELECT ")
    assert all(token not in normalized for token in (" INSERT ", " UPDATE ", " DELETE ", " REPLACE "))
    assert params == ("bitvavo", "EUR")
