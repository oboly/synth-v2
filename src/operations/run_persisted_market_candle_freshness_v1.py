from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime

from dotenv import load_dotenv

from src.common.db import get_connection
from src.operations.persisted_market_candle_freshness_v1 import (
    BLOCKED,
    PersistedMarketCandleFreshness,
    classify_persisted_candle_boundary,
    fetch_persisted_candle_boundary,
)


RUNNER_NAME = "run_persisted_market_candle_freshness_v1"
RUNNER_VERSION = "0.1"

# Canonical literal-UTC only: YYYY-MM-DDTHH:MM:SS(.frac)?Z. Offsets and
# timezone-less values are rejected; impossible calendar dates are rejected by
# the real datetime parse below.
_UTC_LITERAL_Z_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$"
)


def _utc_timestamp(value: str) -> datetime:
    if not _UTC_LITERAL_Z_RE.match(value):
        raise argparse.ArgumentTypeError(
            "timestamp must be canonical literal UTC (YYYY-MM-DDTHH:MM:SSZ)"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid calendar date/time: {value}") from exc
    return parsed.astimezone(UTC)


def _format_utc_z(value: datetime | None) -> str:
    """Format a UTC datetime as canonical literal Z (never +00:00)."""
    if value is None:
        return "not_available"
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SELECT-only validation of a persisted canonical candle close."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", required=True, dest="interval_code")
    parser.add_argument("--expected-close-ts", required=True, type=_utc_timestamp)
    return parser.parse_args()


def _blocked(expected: datetime) -> PersistedMarketCandleFreshness:
    return PersistedMarketCandleFreshness(
        validation_result=BLOCKED,
        freshness_classification="UNAVAILABLE",
        reason="QUERY_FAILED",
        expected_close_ts_utc=expected,
        latest_close_ts_utc=None,
        expected_close_row_count=0,
    )


def main() -> int:
    args = parse_args()
    load_dotenv(dotenv_path=".env", override=False)
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("START TRANSACTION READ ONLY")
        row = fetch_persisted_candle_boundary(
            conn,
            venue=args.venue,
            interval_code=args.interval_code,
            expected_close_ts_utc=args.expected_close_ts,
        )
        result = classify_persisted_candle_boundary(
            row,
            expected_close_ts_utc=args.expected_close_ts,
        )
    except Exception:
        result = _blocked(args.expected_close_ts)
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()

    print(f"runner={RUNNER_NAME} version={RUNNER_VERSION} mode=select_only")
    print(f"validation_result={result.validation_result}")
    print(f"freshness_classification={result.freshness_classification}")
    print(f"reason={result.reason}")
    print(f"expected_close_ts_utc={_format_utc_z(result.expected_close_ts_utc)}")
    print(f"latest_close_ts_utc={_format_utc_z(result.latest_close_ts_utc)}")
    print(f"expected_close_row_count={result.expected_close_row_count}")
    print("database_writes=0 public_exchange_calls=0 broker_private_calls=0 broker_writes=0")
    return 0 if result.is_fresh else 1


if __name__ == "__main__":
    raise SystemExit(main())
