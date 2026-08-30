from __future__ import annotations

"""Whole-universe public candle coverage health check (Issue #606).

Answers a question the per-symbol freshness check in
``persisted_market_candle_freshness_v1.py`` cannot: is a gap isolated to a
handful of symbols/markets, or is it systemic across the writer-eligible
Bitvavo universe (a stalled/failed writer)? The 2026-08-29/30 incident
(ICP-EUR 1h/4h reported stale) turned out to be the latter -- every eligible
market on every interval stalled at the same boundary because the canonical
writer checkout failed its authorization guard, not an ICP-specific or
aggregation-specific bug.

Universe ownership is intentionally identical to the writer:

```
enabled DB assets
INTERSECT
Bitvavo GET /v2/markets rows with status=trading
```

The exchange call is public market metadata only. Database access remains
SELECT-only. There are no account/private/broker/order calls and no writes.

database_writes=0 public_exchange_calls=1 broker_private_calls=0
broker_writes=0 order_submission=0 live_orders=0 decision_gate=none
execution_planner=none executor=none
"""

import argparse
from datetime import UTC, datetime
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_connection
from src.common.utc import utc_now
from src.etl.bitvavo.etl_bitvavo_candles import (
    build_requests_session,
    fetch_active_bitvavo_markets,
    floor_to_interval,
)
from src.operations.persisted_market_candle_freshness_v1 import (
    CURRENT,
    SOURCE_UNAVAILABLE,
    UniverseCandleCoverage,
    classify_universe_candle_coverage,
    fetch_universe_latest_close_by_symbol,
)

RUNNER_NAME = "run_public_candle_coverage_health_check_v1"
RUNNER_VERSION = "0.2"
DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE_ASSET = "EUR"
DEFAULT_INTERVALS = ["1h", "4h"]
DEFAULT_TIMEOUT_SECONDS = 20


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Whole-universe candle coverage check using the writer's exact active-market "
            "eligibility: distinguishes CURRENT / PARTIAL_COVERAGE / STALE / MISSING / "
            "WRITER_FAILED / SOURCE_UNAVAILABLE."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote-asset", default=DEFAULT_QUOTE_ASSET)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--interval",
        action="append",
        dest="intervals",
        default=None,
        help="Repeatable. Defaults to 1h and 4h.",
    )
    return parser.parse_args(argv)


def fetch_enabled_symbols(conn: Any) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT symbol FROM asset WHERE is_enabled = 1 ORDER BY symbol")
        rows = cur.fetchall()
    return [str(row["symbol"]).upper() for row in rows]


def filter_enabled_symbols_to_active_markets(
    *,
    enabled_symbols: list[str],
    active_markets: set[str],
    quote_asset: str,
) -> list[str]:
    """Apply the same market eligibility predicate as ``run_candles_etl``.

    The writer constructs ``SYMBOL-QUOTE`` and retains only markets returned
    by ``fetch_active_bitvavo_markets``. Keep output deterministic for logs and
    tests regardless of the exchange payload order.
    """
    quote = quote_asset.upper()
    return sorted(
        symbol
        for symbol in {value.upper() for value in enabled_symbols}
        if f"{symbol}-{quote}" in active_markets
    )


def _format_utc_z(value: datetime | None) -> str:
    if value is None:
        return "not_available"
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit_coverage(coverage: UniverseCandleCoverage) -> None:
    print(
        f"interval={coverage.interval_code} overall_state={coverage.overall_state} "
        f"reason={coverage.reason} "
        f"expected_close_ts_utc={_format_utc_z(coverage.expected_close_ts_utc)} "
        f"universe_size={coverage.universe_size} "
        f"current_count={coverage.current_count} "
        f"stale_count={coverage.stale_count} "
        f"missing_count={coverage.missing_count} "
        f"dominant_lag_close_ts_utc={_format_utc_z(coverage.dominant_lag_close_ts_utc)} "
        f"dominant_lag_symbol_count={coverage.dominant_lag_symbol_count}"
    )


def emit_source_unavailable(interval_code: str, reason: str) -> None:
    print(
        f"interval={interval_code} overall_state={SOURCE_UNAVAILABLE} reason={reason} "
        "expected_close_ts_utc=not_available universe_size=0 current_count=0 "
        "stale_count=0 missing_count=0 dominant_lag_close_ts_utc=not_available "
        "dominant_lag_symbol_count=0"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(dotenv_path=".env", override=False)
    intervals = args.intervals or DEFAULT_INTERVALS
    now = utc_now().astimezone(UTC)

    print(
        f"runner={RUNNER_NAME} version={RUNNER_VERSION} mode=select_plus_public_market_metadata "
        f"venue={args.venue} intervals={','.join(intervals)} now_utc={_format_utc_z(now)}"
    )

    conn = None
    overall_states: list[str] = []
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("START TRANSACTION READ ONLY")

        enabled_symbols = fetch_enabled_symbols(conn)
        if not enabled_symbols:
            emit_source_unavailable("ALL", "NO_ENABLED_ASSETS")
            print("database_writes=0 public_exchange_calls=1 broker_private_calls=0 broker_writes=0")
            return 1

        session = build_requests_session()
        active_markets = fetch_active_bitvavo_markets(
            session=session,
            timeout_seconds=args.timeout_seconds,
        )
        symbols = filter_enabled_symbols_to_active_markets(
            enabled_symbols=enabled_symbols,
            active_markets=active_markets,
            quote_asset=args.quote_asset,
        )
        if not symbols:
            emit_source_unavailable("ALL", "NO_WRITER_ELIGIBLE_ACTIVE_MARKETS")
            print("database_writes=0 public_exchange_calls=1 broker_private_calls=0 broker_writes=0")
            return 1

        print(
            f"universe_enabled_count={len(enabled_symbols)} "
            f"active_market_count={len(active_markets)} "
            f"writer_eligible_symbol_count={len(symbols)}"
        )

        for interval_code in intervals:
            expected_close_ts_utc = floor_to_interval(now, interval_code)
            symbol_latest_close = fetch_universe_latest_close_by_symbol(
                conn,
                venue=args.venue,
                interval_code=interval_code,
                symbols=symbols,
            )
            coverage = classify_universe_candle_coverage(
                interval_code=interval_code,
                expected_close_ts_utc=expected_close_ts_utc,
                symbol_latest_close=symbol_latest_close,
            )
            emit_coverage(coverage)
            overall_states.append(coverage.overall_state)
    except Exception as exc:
        for interval_code in intervals:
            emit_source_unavailable(interval_code, f"{exc.__class__.__name__}:{exc}")
        overall_states = [SOURCE_UNAVAILABLE]
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()

    print("database_writes=0 public_exchange_calls=1 broker_private_calls=0 broker_writes=0")
    return 0 if overall_states and all(state == CURRENT for state in overall_states) else 1


if __name__ == "__main__":
    raise SystemExit(main())
