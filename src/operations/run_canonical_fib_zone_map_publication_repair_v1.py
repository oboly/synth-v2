from __future__ import annotations

"""Operator-invoked CLI for repairing exactly one confirmed-invalid
canonical_fib_zone_map_publication_v1 cohort.

Not part of scripts/run_chain_4h.sh and not invoked by any automated timer.
Run manually, by an operator, against a DBA-authorized connection that is not
the least-privilege synth_chain_4h_writer identity (that identity has no
UPDATE/DELETE grant on these tables by design -- see
db/dba/synth_chain_4h_writer_v1.sql -- and this script must not be used to
argue for widening it).

Dry run by default. Mutation requires --confirm-old-digest exactly matching
the digest currently stored for the exact (venue, quote, interval, asof)
identity, plus --operator and --reason. Any mismatch fails closed with no
database write.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from typing import Any, Sequence

from src.common.db import get_connection
from src.market_data.canonical_fib_zone_map_v1 import (
    DEFAULT_INTERVAL,
    DEFAULT_LOOKBACK_CANDLES,
    CanonicalFibMapError,
    SAFETY_MARKERS,
    build_publication,
    fetch_latest_production_rows,
    fetch_latest_trend_rows,
    fetch_recent_candles,
    fetch_tracked_symbols,
)
from src.operations.canonical_fib_zone_map_publication_repair_v1 import (
    repair_publication_identity,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Repair exactly one canonical_fib_zone_map_publication_v1 identity after a "
            "confirmed upstream data defect. Recomputes the cohort from current public "
            "candles/features, then replaces the one exact (venue, quote, interval, asof) "
            "publication -- only if its currently stored digest matches --confirm-old-digest."
        )
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--quote", default="EUR")
    parser.add_argument("--interval", default=DEFAULT_INTERVAL, choices=(DEFAULT_INTERVAL,))
    parser.add_argument("--asof", required=True, help="Exact asof_ts_utc, e.g. 2026-08-05T16:00:00Z")
    parser.add_argument("--lookback-candles", type=int, default=DEFAULT_LOOKBACK_CANDLES)
    parser.add_argument(
        "--confirm-old-digest",
        default=None,
        help="Exact content_digest currently stored for this identity. Required to mutate.",
    )
    parser.add_argument("--operator", default=None)
    parser.add_argument("--reason", default=None)
    parser.add_argument("--repair", action="store_true", help="Perform the repair. Default is dry-run.")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    return parser.parse_args(argv)


def _emit(payload: dict[str, Any], output: str) -> None:
    if output == "json":
        print(json.dumps(payload, sort_keys=True, default=str), flush=True)
    else:
        print(" ".join(f"{key}={value}" for key, value in payload.items()), flush=True)


def _parse_asof(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise SystemExit("--asof must be an explicit UTC timestamp (e.g. ...Z or +00:00)")
    return parsed.astimezone(UTC)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.lookback_candles < 10:
        raise SystemExit("--lookback-candles must be at least 10")
    asof_ts_utc = _parse_asof(args.asof)
    if args.repair and not (args.confirm_old_digest and args.operator and args.reason):
        raise SystemExit("--repair requires --confirm-old-digest, --operator, and --reason")

    started = time.monotonic()
    _emit(
        {
            "event": "STARTED",
            "runner": "canonical_fib_zone_map_publication_repair_v1",
            "mode": "repair" if args.repair else "dry_run",
            "scope": f"{args.venue}/{args.quote}/{args.interval}@{asof_ts_utc.isoformat()}",
            "worker_count": 1,
            **SAFETY_MARKERS,
        },
        args.output,
    )

    conn = None
    try:
        conn = get_connection()
        symbols = fetch_tracked_symbols(conn, venue=args.venue, quote_currency=args.quote)
        prior_rows = fetch_latest_production_rows(
            conn, venue=args.venue, quote_currency=args.quote, interval_code=args.interval
        )
        candles = fetch_recent_candles(
            conn,
            venue=args.venue,
            interval_code=args.interval,
            symbols=symbols,
            lookback_candles=args.lookback_candles,
        )
        trend_rows = fetch_latest_trend_rows(
            conn, venue=args.venue, interval_code=args.interval, symbols=symbols
        )
        conn.rollback()

        build = build_publication(
            venue=args.venue,
            quote_currency=args.quote,
            interval_code=args.interval,
            symbols=symbols,
            candles_by_symbol=candles,
            trend_rows_by_symbol=trend_rows,
            now_utc=datetime.now(UTC),
            prior_rows_by_symbol=prior_rows,
        )
        if build.asof_ts_utc != asof_ts_utc:
            conn.rollback()
            _emit(
                {
                    "event": "FAILED",
                    "reason": "RECOMPUTED_ASOF_DOES_NOT_MATCH_REQUESTED_ASOF",
                    "requested_asof_ts_utc": asof_ts_utc.isoformat(),
                    "recomputed_asof_ts_utc": build.asof_ts_utc.isoformat(),
                    "database_writes": 0,
                    **SAFETY_MARKERS,
                },
                args.output,
            )
            return 1

        if not args.repair:
            conn.rollback()
            _emit(
                {
                    "event": "FINISHED",
                    "result": "DRY_RUN",
                    "recomputed_content_digest": build.content_digest,
                    "row_count": len(build.rows),
                    "available_count": build.available_count,
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                    "database_writes": 0,
                    **SAFETY_MARKERS,
                },
                args.output,
            )
            return 0

        result = repair_publication_identity(
            conn,
            venue=args.venue,
            quote_currency=args.quote,
            interval_code=args.interval,
            asof_ts_utc=asof_ts_utc,
            expected_old_digest=args.confirm_old_digest,
            new_build=build,
            operator=args.operator,
            reason=args.reason,
        )
        conn.commit()
        _emit(
            {
                "event": "FINISHED",
                "result": result.status,
                "old_publication_id": result.old_publication_id,
                "old_content_digest": result.old_content_digest,
                "new_publication_id": result.new_publication_id,
                "new_content_digest": result.new_content_digest,
                "row_count": result.row_count,
                "available_count": result.available_count,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "database_writes": result.row_count + 3,
                **SAFETY_MARKERS,
            },
            args.output,
        )
        return 0
    except CanonicalFibMapError as exc:
        if conn is not None:
            conn.rollback()
        _emit(
            {
                "event": "FAILED",
                "error_type": type(exc).__name__,
                "detail": str(exc),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "database_writes": 0,
                **SAFETY_MARKERS,
            },
            args.output,
        )
        return 1
    except KeyboardInterrupt:
        if conn is not None:
            conn.rollback()
        _emit({"event": "INTERRUPTED", "exit_status": 130, **SAFETY_MARKERS}, args.output)
        return 130
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        _emit(
            {
                "event": "FAILED",
                "error_type": type(exc).__name__,
                "detail": str(exc),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "database_writes": 0,
                **SAFETY_MARKERS,
            },
            args.output,
        )
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
