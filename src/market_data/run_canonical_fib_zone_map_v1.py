from __future__ import annotations

"""Publish the recurring canonical market-only 4h Fibonacci map."""

import argparse
import fcntl
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from src.common.db import get_connection
from src.market_data.canonical_fib_zone_map_v1 import (
    DEFAULT_INTERVAL,
    DEFAULT_LOOKBACK_CANDLES,
    PRODUCER_NAME,
    PRODUCER_VERSION,
    SAFETY_MARKERS,
    build_publication,
    fetch_latest_trend_rows,
    fetch_production_rows_before,
    fetch_recent_candles,
    fetch_tracked_symbols,
    publish,
    resolve_candidate_asof_ts_utc,
)


DEFAULT_LOCK_FILE = Path("/tmp/synth-canonical-fib-zone-map-v1.lock")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build or publish the canonical market-only Fibonacci map from persisted public "
            "candles and aligned deterministic trend features. "
            "No account, broker, decision, planning, execution, or research inputs."
        )
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--quote", default="EUR")
    parser.add_argument("--interval", default=DEFAULT_INTERVAL, choices=(DEFAULT_INTERVAL,))
    parser.add_argument("--lookback-candles", type=int, default=DEFAULT_LOOKBACK_CANDLES)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    return parser.parse_args(argv)


def _emit(payload: dict[str, Any], output: str) -> None:
    if output == "json":
        print(json.dumps(payload, sort_keys=True, default=str), flush=True)
    else:
        print(" ".join(f"{key}={value}" for key, value in payload.items()), flush=True)


def load_publication_inputs(
    conn: Any,
    *,
    venue: str,
    quote: str,
    interval: str,
    lookback_candles: int,
) -> tuple[list[str], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, int]]:
    """Load current public inputs for the normal recurring writer.

    Prior continuity is read via ``fetch_production_rows_before``, bound
    strictly before the candidate ``asof_ts_utc``. The candidate is not known
    in advance -- it is derived from live candles via
    ``resolve_candidate_asof_ts_utc`` *before* the prior-continuity read, so
    a rerun of the same asof can never read its own just-published cohort
    (or a later one) as prior context. This is the same
    ``fetch_production_rows_before`` bound used by the historical/operator
    repair path (``build_historical_publication``), so the two share prior-
    continuity semantics.

    Returns ``(symbols, candles, prior_rows, trend_rows, metrics)``.
    """
    symbols = fetch_tracked_symbols(conn, venue=venue, quote_currency=quote)
    candles = fetch_recent_candles(
        conn,
        venue=venue,
        interval_code=interval,
        symbols=symbols,
        lookback_candles=lookback_candles,
    )
    candidate_asof_ts_utc = resolve_candidate_asof_ts_utc(candles)
    prior_rows = (
        fetch_production_rows_before(
            conn,
            venue=venue,
            quote_currency=quote,
            interval_code=interval,
            before_asof_ts_utc=candidate_asof_ts_utc,
        )
        if candidate_asof_ts_utc is not None
        else {}
    )
    trend_rows = fetch_latest_trend_rows(
        conn,
        venue=venue,
        interval_code=interval,
        symbols=symbols,
    )
    metrics = {
        "tracked_symbols": len(symbols),
        "candle_rows": sum(len(rows) for rows in candles.values()),
        "prior_rows": len(prior_rows),
        "trend_rows": len(trend_rows),
    }
    return symbols, candles, prior_rows, trend_rows, metrics


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.lookback_candles < 10:
        raise SystemExit("--lookback-candles must be at least 10")
    started = time.monotonic()
    _emit(
        {
            "event": "STARTED",
            "runner": PRODUCER_NAME,
            "version": PRODUCER_VERSION,
            "mode": "publish" if args.publish else "dry_run",
            "scope": f"{args.venue}/{args.quote}/{args.interval}",
            "worker_count": 1,
            **SAFETY_MARKERS,
        },
        args.output,
    )
    args.lock_file.parent.mkdir(parents=True, exist_ok=True)
    with args.lock_file.open("a+b") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _emit({"event": "FAILED", "reason": "LOCK_HELD", **SAFETY_MARKERS}, args.output)
            return 75

        conn = None
        try:
            authorization = None
            if args.publish:
                from src.operations.writer_capability_authorization_v1 import (
                    require_capability_write_authorization,
                )

                authorization = require_capability_write_authorization(
                    "native_short_4h_chain",
                    service="synth-chain-4h.service",
                )
            conn = get_connection()
            phase = time.monotonic()
            symbols, candles, prior_rows, trend_rows, metrics = load_publication_inputs(
                conn,
                venue=args.venue,
                quote=args.quote,
                interval=args.interval,
                lookback_candles=args.lookback_candles,
            )
            conn.rollback()
            _emit(
                {
                    "event": "PHASE_FINISHED",
                    "phase": "load_public_inputs",
                    **metrics,
                    "elapsed_ms": round((time.monotonic() - phase) * 1000),
                    "database_writes": 0,
                },
                args.output,
            )
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
            result = None
            if args.publish:
                result = publish(conn, build, authorization=authorization)
                conn.commit()
            else:
                conn.rollback()
            _emit(
                {
                    "event": "FINISHED",
                    "result": result.status if result else "DRY_RUN",
                    "publication_id": result.publication_id if result else None,
                    "content_digest": build.content_digest,
                    "row_count": len(build.rows),
                    "available_count": build.available_count,
                    "unavailable_count": len(build.rows) - build.available_count,
                    "asof_ts_utc": build.asof_ts_utc.isoformat().replace("+00:00", "Z"),
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                    "database_writes": len(build.rows) + 1 if result and result.status == "PUBLISHED" else 0,
                    **SAFETY_MARKERS,
                },
                args.output,
            )
            return 0
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
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    sys.exit(main())
