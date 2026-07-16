from __future__ import annotations

"""CLI for the bounded native SHORT multi-asset readiness audit."""

import argparse
import json
import signal
import sys
import threading
import time
from datetime import UTC, datetime
from typing import Any, Sequence

from src.common.db import get_connection
from src.market_data.native_short_multi_asset_audit_v1 import run_audit


RUNNER_NAME = "run_native_short_multi_asset_audit_v1"
HEARTBEAT_SECONDS = 15.0
SAFETY_MARKERS: dict[str, int | str] = {
    "db_writes": 0,
    "scope_seeding": 0,
    "materializer_calls": 0,
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
}


def _parse_as_of(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--as-of-utc must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("--as-of-utc must include a UTC offset")
    return parsed.astimezone(UTC)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit public-market readiness for canonical native SHORT expansion "
            "without changing runtime state."
        )
    )
    parser.add_argument("--as-of-utc", type=_parse_as_of, help="Audit cutoff; defaults to current UTC time.")
    parser.add_argument("--output", choices=("summary", "jsonl"), default="summary")
    return parser.parse_args(argv)


class Heartbeat:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.started = time.monotonic()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self._stop.wait(HEARTBEAT_SECONDS):
            print(f"HEARTBEAT runner={RUNNER_NAME} elapsed_s={time.monotonic() - self.started:.1f}", flush=True)


def _progress(phase: str, rows: int, elapsed_s: float) -> None:
    print(f"PHASE_FINISHED phase={phase} rows={rows} elapsed_s={elapsed_s:.3f}", flush=True)


def _begin_read_only(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("START TRANSACTION READ ONLY")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    as_of = args.as_of_utc or datetime.now(UTC)
    marker_text = " ".join(f"{key}={value}" for key, value in SAFETY_MARKERS.items())
    print(
        f"STARTED runner={RUNNER_NAME} mode=read_only scope=bitvavo/*-EUR/SHORT/4h/1h workers=1 {marker_text}",
        flush=True,
    )
    heartbeat = Heartbeat()
    heartbeat.start()
    conn = None
    started = time.monotonic()
    try:
        conn = get_connection()
        _begin_read_only(conn)
        report = run_audit(conn, as_of_utc=as_of, progress=_progress)
        payload = report.to_dict()
        if args.output == "jsonl":
            header = {key: value for key, value in payload.items() if key != "results"}
            print(json.dumps({"record_type": "summary", **header}, sort_keys=True), flush=True)
            for result in payload["results"]:
                print(json.dumps({"record_type": "candidate", **result}, sort_keys=True), flush=True)
        else:
            summary = {key: value for key, value in payload.items() if key != "results"}
            print(json.dumps(summary, sort_keys=True), flush=True)
        print(
            f"FINISHED runner={RUNNER_NAME} candidates={report.counts['candidate_count']} "
            f"qualified={report.counts['readiness_qualified_count']} "
            f"elapsed_s={time.monotonic() - started:.3f} {marker_text}",
            flush=True,
        )
        return 0
    except KeyboardInterrupt:
        print(f"INTERRUPTED runner={RUNNER_NAME} elapsed_s={time.monotonic() - started:.3f} {marker_text}", flush=True)
        return 130
    except Exception as exc:
        print(
            f"FAILED runner={RUNNER_NAME} error={type(exc).__name__} detail={str(exc)!r} "
            f"elapsed_s={time.monotonic() - started:.3f} {marker_text}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    finally:
        heartbeat.stop()
        if conn is not None:
            conn.rollback()
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
