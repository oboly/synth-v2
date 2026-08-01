from __future__ import annotations

"""CLI for the Odroid-side native SHORT context snapshot import.

Installs an already-fetched (staged) copy of gurkdb's canonical native SHORT
snapshot publication into the local canonical path Profit Plan reads. Never
fetches or transports anything itself (see
scripts/fetch_native_short_snapshot_from_gurkdb.sh for that bounded step),
never touches the database, never calls a broker, and never mutates account,
decision, execution, or order state.

Deterministic exit codes:
  0  success (INSTALLED or UNCHANGED)
  2  staged snapshot is older than the installed one (stale, rejected)
  3  staged or installed bundle failed schema/digest/identity validation
  4  wrong host (--expected-host did not match this host)
  1  any other failure
"""

import argparse
import json
import socket
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from src.market_data.native_short_context_snapshot_import_v1 import (
    IMPORTER_NAME,
    IMPORTER_VERSION,
    SAFETY_MARKERS,
    SnapshotImportError,
    StaleSnapshotError,
    WrongHostError,
    import_snapshot,
)
from src.market_data.native_short_fib_context_snapshot_v1 import SnapshotContractError


DEFAULT_CANONICAL_DIR = Path("/var/www/html/synth/_runtime/native_short_context_snapshot_v1")

EXIT_OK = 0
EXIT_GENERIC_FAILURE = 1
EXIT_STALE = 2
EXIT_VALIDATION_FAILED = 3
EXIT_WRONG_HOST = 4


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and atomically install a staged native SHORT context snapshot."
    )
    parser.add_argument(
        "--staged-dir",
        type=Path,
        required=True,
        help="Local directory already containing the fetched manifest/snapshots bundle.",
    )
    parser.add_argument("--canonical-dir", type=Path, default=DEFAULT_CANONICAL_DIR)
    parser.add_argument(
        "--expected-host",
        required=True,
        help="This import runs only when it matches the local hostname. Fails closed otherwise.",
    )
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
    actual_host = socket.gethostname()
    _emit(
        {
            "event": "STARTED",
            "runner": IMPORTER_NAME,
            "version": IMPORTER_VERSION,
            "staged_dir": str(args.staged_dir),
            "canonical_dir": str(args.canonical_dir),
            "expected_host": args.expected_host,
            "actual_host": actual_host,
            **SAFETY_MARKERS,
        },
        args.output,
    )
    try:
        result = import_snapshot(
            staged_root=args.staged_dir,
            canonical_root=args.canonical_dir,
            expected_host=args.expected_host,
            actual_host=actual_host,
        )
        _emit(
            {
                "event": "FINISHED",
                "result": result.result,
                "snapshot_id": result.snapshot_id,
                "content_digest": result.content_digest,
                "publication_ts_utc": result.publication_ts_utc,
                "row_count": result.row_count,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                **SAFETY_MARKERS,
            },
            args.output,
        )
        return EXIT_OK
    except KeyboardInterrupt:
        _emit({"event": "INTERRUPTED", "exit_status": 130}, args.output)
        return 130
    except WrongHostError as exc:
        _emit(
            {
                "event": "FAILED",
                "error_type": "WrongHostError",
                "detail": str(exc),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                **SAFETY_MARKERS,
            },
            args.output,
        )
        return EXIT_WRONG_HOST
    except StaleSnapshotError as exc:
        _emit(
            {
                "event": "FAILED",
                "error_type": "StaleSnapshotError",
                "detail": str(exc),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                **SAFETY_MARKERS,
            },
            args.output,
        )
        return EXIT_STALE
    except (SnapshotContractError, SnapshotImportError) as exc:
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
        return EXIT_VALIDATION_FAILED
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
        return EXIT_GENERIC_FAILURE


if __name__ == "__main__":
    sys.exit(main())
