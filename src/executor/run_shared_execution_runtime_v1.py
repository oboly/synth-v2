"""One bounded, side-neutral DRY_RUN shared-executor runtime cycle."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from collections import Counter
from datetime import UTC, datetime

from src.common.db_core_v1 import db_cursor
from src.executor.execution_handoff_v1 import ExecutionHandoffRepositoryV1
from src.executor.execution_leg_v1 import ExecutionLegRepositoryV1
from src.executor.run_shared_execution_consumer_once_v1 import (
    run_shared_execution_consumer_once_v1,
)
from src.executor.shared_execution_runtime_v1 import (
    DEFAULT_BATCH_LIMIT,
    DEFAULT_LEASE_SECONDS,
    SharedExecutorRuntimeConfigV1,
    build_runtime_adapter_factory_v1,
)


RUNNER_NAME = "run_shared_execution_runtime_v1"
SAFETY_MARKERS = (
    "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
    "decision_gate=none execution_planner=none executor=shared_persisted_consumer"
)
INCOMPLETE_REASONS = frozenset({
    "EXECUTION_HANDOFF_CLAIM_LOST",
    "SUBMISSION_UNCERTAIN",
    "RECONCILIATION_REQUIRED",
})


class RuntimeInterrupted(KeyboardInterrupt):
    pass


def _environment_text(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise ValueError(f"{name} required")
    return value


def _environment_positive_int(name: str, default: int | None = None) -> int:
    raw = os.getenv(name, str(default) if default is not None else None)
    if raw is None:
        raise ValueError(f"{name} required")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _require_not_granted(name: str) -> None:
    if os.getenv(name, "NOT_GRANTED") != "NOT_GRANTED":
        raise ValueError(f"{name} must remain NOT_GRANTED")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one generic persisted BUY/SELL shared executor cycle with explicit identity."
    )
    parser.add_argument("--executor-mode", default=os.getenv("SYNTH_SHARED_EXECUTOR_MODE"))
    parser.add_argument("--runtime-owner", default=os.getenv("SYNTH_SHARED_EXECUTOR_RUNTIME_OWNER"))
    parser.add_argument("--executor-identity", default=os.getenv("SYNTH_SHARED_EXECUTOR_IDENTITY"))
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--operator-id", type=int, default=None)
    parser.add_argument("--lease-seconds", type=int, default=None)
    parser.add_argument("--batch-limit", type=int, default=None)
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> SharedExecutorRuntimeConfigV1:
    _require_not_granted("SYNTH_LIVE_EXECUTION_PERMISSION")
    _require_not_granted("SYNTH_BROKER_WRITE_PERMISSION")
    worker_id = args.worker_id or os.getenv("SYNTH_SHARED_EXECUTOR_WORKER_ID")
    if worker_id is None:
        worker_id = f"shared-executor-v1:{socket.gethostname()}:{os.getpid()}"
    return SharedExecutorRuntimeConfigV1(
        executor_mode=args.executor_mode or _environment_text("SYNTH_SHARED_EXECUTOR_MODE"),
        runtime_owner=args.runtime_owner or _environment_text("SYNTH_SHARED_EXECUTOR_RUNTIME_OWNER"),
        executor_identity=args.executor_identity or _environment_text("SYNTH_SHARED_EXECUTOR_IDENTITY"),
        worker_id=worker_id,
        operator_id=args.operator_id if args.operator_id is not None else _environment_positive_int("SYNTH_SHARED_EXECUTOR_OPERATOR_ID"),
        lease_seconds=args.lease_seconds if args.lease_seconds is not None else _environment_positive_int("SYNTH_SHARED_EXECUTOR_LEASE_SECONDS", DEFAULT_LEASE_SECONDS),
        batch_limit=args.batch_limit if args.batch_limit is not None else _environment_positive_int("SYNTH_SHARED_EXECUTOR_BATCH_LIMIT", DEFAULT_BATCH_LIMIT),
    )


def run_one_cycle(config: SharedExecutorRuntimeConfigV1):
    """Consume a deterministic batch after validating its mode adapter locally."""
    adapter_factory = build_runtime_adapter_factory_v1(config)
    return run_shared_execution_consumer_once_v1(
        handoff_repository=ExecutionHandoffRepositoryV1(cursor_factory=db_cursor),
        leg_repository=ExecutionLegRepositoryV1(cursor_factory=db_cursor),
        adapter=None,
        adapter_factory=adapter_factory,
        operator_id=config.operator_id,
        worker_id=config.worker_id,
        runtime_owner=config.runtime_owner,
        executor_identity=config.executor_identity,
        executor_mode=config.executor_mode,
        limit=config.batch_limit,
        lease_seconds=config.lease_seconds,
    )


def run(
    config: SharedExecutorRuntimeConfigV1,
    *,
    run_cycle=run_one_cycle,
) -> int:
    started = datetime.now(UTC)
    print(
        f"STARTED runner={RUNNER_NAME} mode={config.executor_mode} scope=one_cycle worker_count=1 "
        f"runtime_owner={config.runtime_owner} executor_identity={config.executor_identity} "
        f"worker_id={config.worker_id} lease_seconds={config.lease_seconds} "
        f"batch_limit={config.batch_limit} started_ts_utc={started.isoformat()}",
        flush=True,
    )
    print(SAFETY_MARKERS, flush=True)
    try:
        outcomes = run_cycle(config)
    except (RuntimeInterrupted, KeyboardInterrupt):
        finished = datetime.now(UTC)
        print(
            f"INTERRUPTED runner={RUNNER_NAME} result=signal "
            f"finished_ts_utc={finished.isoformat()} "
            f"elapsed_seconds={(finished - started).total_seconds():.3f}",
            flush=True,
        )
        return 130
    except Exception as exc:
        finished = datetime.now(UTC)
        print(
            f"FAILED runner={RUNNER_NAME} result=cycle_failed detail={type(exc).__name__}:{exc} "
            f"finished_ts_utc={finished.isoformat()}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    finished = datetime.now(UTC)
    reason_counts = Counter(
        outcome.stopped_reason or "COMPLETED" for outcome in outcomes
    )
    for outcome in outcomes:
        print(
            f"OUTCOME runner={RUNNER_NAME} handoff_id={outcome.handoff_id} "
            f"reason={outcome.stopped_reason or 'COMPLETED'}",
            flush=True,
        )
    incomplete = any(
        outcome.stopped_reason in INCOMPLETE_REASONS for outcome in outcomes
    )
    print(
        f"FINISHED runner={RUNNER_NAME} result={'incomplete' if incomplete else 'ok'} "
        f"outcomes={len(outcomes)} reason_counts={json.dumps(dict(sorted(reason_counts.items())), sort_keys=True)} "
        f"finished_ts_utc={finished.isoformat()} "
        f"elapsed_seconds={(finished - started).total_seconds():.3f}",
        flush=True,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        config = config_from_args(parse_args(argv))
    except ValueError as exc:
        print(f"FAILED runner={RUNNER_NAME} result=invalid_configuration detail={exc}", file=sys.stderr, flush=True)
        return 2
    def _interrupt(_signum: int, _frame: object) -> None:
        raise RuntimeInterrupted

    import signal

    signal.signal(signal.SIGINT, _interrupt)
    signal.signal(signal.SIGTERM, _interrupt)
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
