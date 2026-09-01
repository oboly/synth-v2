from __future__ import annotations

"""Bounded, C1-only final-holdout evaluator for Issue #593."""

import argparse
import json
import os
import signal
import time
from pathlib import Path
from typing import Any

from src.research.multi_horizon_rotation_validation_streaming_v1 import (
    StreamingValidationAccumulator,
    serializable_streaming_summary,
)
from src.research.run_multi_horizon_rotation_validation_streaming_v1 import parse_row


RUNNER_NAME = "run_multi_horizon_rotation_c1_final_holdout_evaluator_v1"
RUNNER_VERSION = "1.0.0"
CANDIDATE_ID = "C1"
INPUT_BASENAME = "final_holdout_c1_rows_v1.jsonl"

class RunnerInterrupted(Exception):
    def __init__(self, signum: int) -> None:
        self.signum = signum


def emit(message: str) -> None:
    print(message, flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="#593 bounded C1-only final-holdout evaluator"
    )
    parser.add_argument("--input-jsonl", required=True)
    parser.add_argument("--output-json", required=True)
    return parser.parse_args(argv)


def require_c1_row(raw: Any, *, line_number: int) -> None:
    """Reject outside scope before parsing a row's outcome fields."""
    if not isinstance(raw, dict):
        raise ValueError(f"JSONL line {line_number} must be an object")
    if raw.get("candidate_id") != CANDIDATE_ID:
        raise ValueError(
            f"JSONL line {line_number} candidate_id must be {CANDIDATE_ID}"
        )


def c1_holdout_summary(accumulator: StreamingValidationAccumulator) -> dict[str, object]:
    """Expose C1 only while retaining the frozen 12-test inference family."""
    frozen = serializable_streaming_summary(accumulator)
    candidates = frozen["candidate_summaries"]
    lead_lag = frozen["lead_lag_vs_b1"]
    regime_stability = frozen["regime_stability"]
    holm = frozen["holm_bonferroni_family"]
    assert isinstance(candidates, dict)
    assert isinstance(lead_lag, dict)
    assert isinstance(regime_stability, dict)
    assert isinstance(holm, dict)
    return {
        "candidate_id": CANDIDATE_ID,
        "metrics": candidates[CANDIDATE_ID],
        "lead_lag_vs_b1": lead_lag[CANDIDATE_ID],
        "b0_regime_stability": regime_stability[CANDIDATE_ID],
        "forward_ic_holm_bonferroni": {
            horizon: holm[f"{CANDIDATE_ID}:{horizon}"]
            for horizon in ("15m", "1h", "4h", "24h")
        },
        "holm_family_size": frozen["holm_family_size"],
    }


def evaluate_streaming(path: Path) -> tuple[dict[str, object], int]:
    if path.name != INPUT_BASENAME:
        raise ValueError(f"input JSONL must be named {INPUT_BASENAME}")
    accumulator = StreamingValidationAccumulator()
    row_count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            require_c1_row(raw, line_number=line_number)
            accumulator.add(parse_row(raw, line_number=line_number))
            row_count += 1
            if row_count % 250000 == 0:
                emit(f"HEARTBEAT phase=final_holdout candidate=C1 rows={row_count}")
    return c1_holdout_summary(accumulator), row_count


def install_interrupt_handlers() -> dict[int, Any]:
    def handle_interrupt(signum: int, _frame: Any) -> None:
        raise RunnerInterrupted(signum)

    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    for signum in previous:
        signal.signal(signum, handle_interrupt)
    return previous


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    previous_handlers = install_interrupt_handlers()
    temporary_output_path: Path | None = None
    emit(
        f"STARTED runner={RUNNER_NAME} version={RUNNER_VERSION} phase=final_holdout "
        "candidate=C1 workers=1"
    )
    emit(
        "SAFETY research_only=1 market_only=1 database_reads=0 database_writes=0 "
        "account_awareness=0 decision_gate=none execution_planner=none executor=none "
        "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0"
    )
    try:
        evaluation_started = time.perf_counter()
        emit("PHASE_STARTED name=stream_final_holdout_c1_rows_and_metrics")
        summary, row_count = evaluate_streaming(Path(args.input_jsonl))
        emit(
            "PHASE_FINISHED name=stream_final_holdout_c1_rows_and_metrics "
            f"rows={row_count} elapsed_s={time.perf_counter() - evaluation_started:.3f}"
        )
        output = {
            "runner": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "phase": "final_holdout",
            "candidate_id": CANDIDATE_ID,
            "input_artifact_scope": "FINAL_HOLDOUT_C1_ONLY",
            "memory_mode": "BOUNDED_STREAMING_CANONICAL_ASOF_ORDER",
            "summary": summary,
            "safety": {
                "research_only": 1, "market_only": 1, "database_reads": 0,
                "database_writes": 0, "account_awareness": 0, "decision_gate": "none",
                "execution_planner": "none", "executor": "none", "broker_private_calls": 0,
                "broker_writes": 0, "order_submission": 0, "live_orders": 0,
            },
        }
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_output_path = output_path.with_suffix(output_path.suffix + ".partial")
        with temporary_output_path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(output, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_output_path.replace(output_path)
        temporary_output_path = None
        emit(f"OUTPUT_WRITTEN path={output_path} rows={row_count}")
        emit(
            f"FINISHED runner={RUNNER_NAME} result=PASS phase=final_holdout candidate=C1 "
            f"rows={row_count} elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 0
    except RunnerInterrupted as exc:
        if temporary_output_path is not None:
            temporary_output_path.unlink(missing_ok=True)
        emit(
            f"INTERRUPTED runner={RUNNER_NAME} signal={signal.Signals(exc.signum).name} "
            f"elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 128 + exc.signum
    except Exception as exc:
        emit(
            f"FAILED runner={RUNNER_NAME} error={exc.__class__.__name__}:{exc} "
            f"elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 1
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
