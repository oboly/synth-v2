from __future__ import annotations

"""CLI for the persisted market-only native SHORT context snapshot."""

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from src.common.db import get_connection
from src.market_data.native_short_fib_context_snapshot_v1 import (
    PRODUCER_NAME,
    PRODUCER_VERSION,
    SAFETY_MARKERS,
    build_snapshot,
    load_persisted_authorities,
    publish_snapshot,
)


DEFAULT_OUTPUT_DIR = Path(
    os.getenv(
        "SYNTH_NATIVE_SHORT_CONTEXT_SNAPSHOT_DIR",
        "/var/www/html/synth/_runtime/native_short_context_snapshot_v1",
    )
)


def _absolute_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed.astimezone(UTC)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build or publish the persisted native SHORT context snapshot.")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--quote-currency", default="EUR", choices=("EUR",))
    parser.add_argument("--fib-trading-horizon", default="SHORT", choices=("SHORT",))
    parser.add_argument("--primary-interval", default="4h", choices=("4h",))
    parser.add_argument("--supporting-interval", default="1h", choices=("1h",))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish filesystem artifacts. Omit for read-only dry-run.",
    )
    parser.add_argument("--generated-ts-utc", type=_absolute_utc)
    parser.add_argument("--publication-ts-utc", type=_absolute_utc)
    parser.add_argument("--output", choices=("jsonl", "summary"), default="jsonl")
    return parser.parse_args(argv)


def _emit(payload: dict[str, Any], output: str) -> None:
    if output == "jsonl":
        print(json.dumps(payload, sort_keys=True, default=str), flush=True)
    else:
        print(" ".join(f"{key}={value}" for key, value in payload.items()), flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.monotonic()
    generated_ts = args.generated_ts_utc or datetime.now(UTC)

    # Publication is a canonical artifact mutation owned by native_short_4h_chain.
    # Acquire and validate authorization BEFORE opening any DB connection,
    # loading persisted authorities, or building publication state. Dry-run
    # (read-only) needs no production authorization.
    publish_authorization = None
    if args.publish:
        from src.operations.writer_capability_authorization_v1 import (
            require_capability_write_authorization,
        )

        publish_authorization = require_capability_write_authorization(
            "native_short_4h_chain",
            service="synth-chain-4h.service",
        )
    _emit(
        {
            "event": "STARTED",
            "runner": PRODUCER_NAME,
            "version": PRODUCER_VERSION,
            "mode": "publish" if args.publish else "dry_run",
            "scope": f"{args.venue}/{args.quote_currency}/SHORT/4h/1h",
            "worker_count": 1,
            "output_dir": str(args.output_dir),
            **SAFETY_MARKERS,
        },
        args.output,
    )
    conn = None
    try:
        phase_started = time.monotonic()
        conn = get_connection()
        authorities = load_persisted_authorities(
            conn,
            venue=args.venue,
            quote_currency=args.quote_currency,
            fib_trading_horizon=args.fib_trading_horizon,
            primary_interval=args.primary_interval,
            supporting_interval=args.supporting_interval,
        )
        conn.rollback()
        _emit(
            {
                "event": "PHASE_FINISHED",
                "phase": "load_persisted_authorities",
                "scope_rows": len(authorities[0]),
                "map_rows": len(authorities[1]),
                "level_rows": sum(len(rows) for rows in authorities[2].values()),
                "elapsed_ms": round((time.monotonic() - phase_started) * 1000),
                "db_writes": 0,
            },
            args.output,
        )
        build = build_snapshot(
            scopes=authorities[0],
            maps_by_id=authorities[1],
            levels_by_map_id=authorities[2],
            generation_event_ts_by_id=authorities[3],
            lifecycle_event_ts_by_id=authorities[4],
        )
        result = "DRY_RUN"
        paths: dict[str, str] = {}
        if args.publish:
            publication_ts = args.publication_ts_utc or datetime.now(UTC)
            published = publish_snapshot(
                build,
                output_dir=args.output_dir,
                generated_ts_utc=generated_ts,
                publication_ts_utc=publication_ts,
                authorization=publish_authorization,
            )
            result = published.status
            paths = {
                "manifest_path": str(published.manifest_path),
                "rows_path": str(published.rows_path),
                "bundle_path": str(published.bundle_path),
            }
        _emit(
            {
                "event": "FINISHED",
                "result": result,
                "snapshot_id": build.snapshot_id,
                "content_digest": f"sha256:{build.content_digest}",
                "row_count": len(build.rows),
                "counts": build.counts,
                "overall_freshness_state": build.overall_freshness_state,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                **paths,
                **SAFETY_MARKERS,
            },
            args.output,
        )
        return 0
    except KeyboardInterrupt:
        _emit({"event": "INTERRUPTED", "exit_status": 130}, args.output)
        return 130
    except Exception as exc:
        _emit(
            {
                "event": "FAILED",
                "error_type": type(exc).__name__,
                "detail": str(exc),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                **SAFETY_MARKERS,
            },
            args.output,
        )
        return 1
    finally:
        if conn is not None:
            try:
                conn.rollback()
            finally:
                conn.close()


if __name__ == "__main__":
    sys.exit(main())
