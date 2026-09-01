from __future__ import annotations

"""Bounded-memory holdout-safe evaluator for Issue #593.

Reads canonical phase-scoped JSONL in nondecreasing as-of order, performs no DB
or network access, and exposes discovery/validation only.
"""

import argparse
import json
import time
from pathlib import Path
from typing import Any

from src.research.multi_horizon_rotation_validation_streaming_v1 import (
    StreamingValidationAccumulator,
    serializable_streaming_summary,
)
from src.research.run_multi_horizon_rotation_validation_v1 import (
    ALLOWED_PHASES,
    FORWARD_HORIZONS,
    load_split_manifest,
    parse_optional_finite_float,
    parse_ts,
)
from src.research.multi_horizon_rotation_validation_v1 import (
    ValidationRow,
    ensure_utc,
    is_on_15m_grid,
)


RUNNER_NAME = "run_multi_horizon_rotation_validation_streaming_v1"
RUNNER_VERSION = "1.0.0"


def emit(message: str) -> None:
    print(message, flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded-memory evaluation of #593 discovery/validation artifacts without holdout access"
    )
    parser.add_argument("--input-jsonl", required=True)
    parser.add_argument("--split-manifest", required=True)
    parser.add_argument("--phase", required=True, choices=ALLOWED_PHASES)
    parser.add_argument("--output-json", required=True)
    return parser.parse_args(argv)


def parse_row(raw: Any, *, line_number: int) -> ValidationRow:
    if not isinstance(raw, dict):
        raise ValueError(f"JSONL line {line_number} must be an object")
    asof_ts = parse_ts(raw["asof_ts"])
    if not is_on_15m_grid(asof_ts):
        raise ValueError(f"JSONL line {line_number} asof_ts must be on 15m grid")
    return ValidationRow(
        venue=str(raw["venue"]),
        asset_id=int(raw["asset_id"]),
        asof_ts=asof_ts,
        candidate_id=str(raw["candidate_id"]),
        candidate_score=parse_optional_finite_float(
            raw.get("candidate_score"), field="candidate_score", line_number=line_number
        ),
        b0_score=parse_optional_finite_float(
            raw.get("b0_score"), field="b0_score", line_number=line_number
        ),
        b0_pressure_state=(None if raw.get("b0_pressure_state") is None else str(raw["b0_pressure_state"])),
        b1_return=parse_optional_finite_float(
            raw.get("b1_return"), field="b1_return", line_number=line_number
        ),
        forward_15m=parse_optional_finite_float(
            raw.get("forward_15m"), field="forward_15m", line_number=line_number
        ),
        forward_1h=parse_optional_finite_float(
            raw.get("forward_1h"), field="forward_1h", line_number=line_number
        ),
        forward_4h=parse_optional_finite_float(
            raw.get("forward_4h"), field="forward_4h", line_number=line_number
        ),
        forward_24h=parse_optional_finite_float(
            raw.get("forward_24h"), field="forward_24h", line_number=line_number
        ),
    )


def validate_row_phase(row: ValidationRow, *, manifest: dict[str, Any], phase: str) -> None:
    if phase not in ALLOWED_PHASES:
        raise ValueError("final holdout is not available in streaming validation runner v1")
    split = manifest["splits"][phase]
    start = parse_ts(split["start"])
    end = parse_ts(split["end"])
    holdout_start = parse_ts(manifest["splits"]["final_holdout"]["start"])
    if end > holdout_start:
        raise ValueError("requested phase overlaps final holdout")
    asof = ensure_utc(row.asof_ts)
    if not (start <= asof < end):
        raise ValueError(
            f"input artifact is not phase-scoped: row outside requested {phase} interval "
            f"asset_id={row.asset_id} candidate_id={row.candidate_id} asof={asof.isoformat()}"
        )
    for field, horizon in FORWARD_HORIZONS.items():
        value = getattr(row, field)
        if value is not None and asof + horizon >= end:
            raise ValueError(
                f"{field} outcome boundary reaches next phase for "
                f"asset_id={row.asset_id} candidate_id={row.candidate_id} asof={asof.isoformat()}"
            )


def evaluate_streaming(path: Path, *, manifest: dict[str, Any], phase: str) -> tuple[dict[str, object], int]:
    accumulator = StreamingValidationAccumulator()
    row_count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            row = parse_row(json.loads(line), line_number=line_number)
            validate_row_phase(row, manifest=manifest, phase=phase)
            accumulator.add(row)
            row_count += 1
            if row_count % 250000 == 0:
                emit(f"HEARTBEAT phase={phase} rows={row_count}")
    return serializable_streaming_summary(accumulator), row_count


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    emit(
        f"STARTED runner={RUNNER_NAME} version={RUNNER_VERSION} mode=research-artifact-streaming "
        f"workers=1 phase={args.phase} final_holdout_access=DENY"
    )
    try:
        manifest_started = time.perf_counter()
        emit("PHASE_STARTED name=load_split_manifest")
        manifest = load_split_manifest(Path(args.split_manifest))
        emit(
            f"PHASE_FINISHED name=load_split_manifest elapsed_s={time.perf_counter() - manifest_started:.3f}"
        )

        eval_started = time.perf_counter()
        emit("PHASE_STARTED name=stream_validation_rows_and_metrics")
        summary, row_count = evaluate_streaming(
            Path(args.input_jsonl), manifest=manifest, phase=args.phase
        )
        emit(
            f"PHASE_FINISHED name=stream_validation_rows_and_metrics rows={row_count} "
            f"elapsed_s={time.perf_counter() - eval_started:.3f}"
        )

        output = {
            "runner": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "phase": args.phase,
            "final_holdout_access": "DENY",
            "input_artifact_scope": "REQUESTED_PHASE_ONLY",
            "memory_mode": "BOUNDED_STREAMING_CANONICAL_ASOF_ORDER",
            "split_manifest": manifest,
            "summary": summary,
            "safety": {
                "database_reads": 0,
                "database_writes": 0,
                "account_awareness": 0,
                "broker_private_calls": 0,
                "broker_writes": 0,
                "order_submission": 0,
            },
        }
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        emit(
            f"FINISHED runner={RUNNER_NAME} result=PASS phase={args.phase} rows={row_count} "
            f"final_holdout_access=DENY elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 0
    except KeyboardInterrupt:
        emit(
            f"INTERRUPTED runner={RUNNER_NAME} final_holdout_access=DENY "
            f"elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 130
    except Exception as exc:
        emit(
            f"FAILED runner={RUNNER_NAME} error={exc.__class__.__name__}:{exc} "
            f"final_holdout_access=DENY elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
