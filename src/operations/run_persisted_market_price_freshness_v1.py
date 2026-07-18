from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv

from src.common.db import get_connection
from src.operations.persisted_market_price_freshness_v1 import (
    PersistedMarketPriceFreshness,
    classify_persisted_price_batch,
    fetch_latest_persisted_price_batch,
    query_failed_result,
)


RUNNER_NAME = "run_persisted_market_price_freshness_v1"
RUNNER_VERSION = "0.1"
DEFAULT_MAX_AGE_SECONDS = 900
DEFAULT_MAX_FUTURE_SKEW_SECONDS = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SELECT-only freshness validation for persisted public market prices."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--quote", default="EUR")
    parser.add_argument("--max-age-seconds", type=int, default=DEFAULT_MAX_AGE_SECONDS)
    parser.add_argument(
        "--max-future-skew-seconds",
        type=int,
        default=DEFAULT_MAX_FUTURE_SKEW_SECONDS,
    )
    parser.add_argument("--output", choices=("table", "json", "tsv"), default="table")
    return parser.parse_args()


def _serialize(result: PersistedMarketPriceFreshness) -> dict[str, object]:
    payload = asdict(result)
    as_of = result.persisted_public_price_as_of_utc
    payload["persisted_public_price_as_of_utc"] = None if as_of is None else as_of.isoformat()
    return payload


def _print(result: PersistedMarketPriceFreshness, output: str) -> None:
    payload = _serialize(result)
    if output == "json":
        print(json.dumps(payload, sort_keys=True))
        return
    if output == "tsv":
        values = (
            result.public_price_validation_result,
            result.freshness_classification,
            result.reason,
            str(payload["persisted_public_price_as_of_utc"] or "not_available"),
            "not_available" if result.persisted_public_price_age_seconds is None else f"{result.persisted_public_price_age_seconds:.6f}",
            str(result.snapshot_row_count),
        )
        print("\t".join(values))
        return
    print(f"runner={RUNNER_NAME} version={RUNNER_VERSION} mode=select_only")
    for key, value in payload.items():
        print(f"{key}={value if value is not None else 'not_available'}")
    print("database_writes=0 public_exchange_calls=0 broker_private_calls=0 broker_writes=0")


def main() -> int:
    args = parse_args()
    if args.max_age_seconds < 0 or args.max_future_skew_seconds < 0:
        raise SystemExit("freshness thresholds must be non-negative")

    stale_after = timedelta(seconds=args.max_age_seconds)
    load_dotenv(dotenv_path=".env", override=False)
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("START TRANSACTION READ ONLY")
        row = fetch_latest_persisted_price_batch(
            conn,
            venue=args.venue,
            quote_currency=args.quote,
        )
        result = classify_persisted_price_batch(
            row,
            now_utc=datetime.now(UTC),
            stale_after=stale_after,
            max_future_skew=timedelta(seconds=args.max_future_skew_seconds),
        )
    except Exception:
        result = query_failed_result(stale_after=stale_after)
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()

    _print(result, args.output)
    return 0 if result.is_fresh else 1


if __name__ == "__main__":
    raise SystemExit(main())
