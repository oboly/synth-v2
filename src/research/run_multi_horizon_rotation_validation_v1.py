from __future__ import annotations

"""Holdout-safe artifact evaluator for Issue #593.

Reads research JSONL only. It has no DB access and exposes discovery/validation only;
final-holdout evaluation is intentionally unavailable in this runner version.
"""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.research.multi_horizon_rotation_validation_v1 import (
    ValidationRow,
    ensure_utc,
    is_on_15m_grid,
    serializable_validation_summary,
)


RUNNER_NAME = "run_multi_horizon_rotation_validation_v1"
RUNNER_VERSION = "1.0.0"
ALLOWED_PHASES = ("discovery", "validation")


def emit(message: str) -> None:
    print(message, flush=True)


def parse_ts(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate #593 discovery/validation artifacts without holdout access")
    parser.add_argument("--input-jsonl", required=True)
    parser.add_argument("--split-manifest", required=True)
    parser.add_argument("--phase", required=True, choices=ALLOWED_PHASES)
    parser.add_argument("--output-json", required=True)
    return parser.parse_args(argv)


def load_split_manifest(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("manifest_version") != "1.0.0":
        raise ValueError("split manifest_version must be 1.0.0")
    if raw.get("final_holdout_inspected") is not False:
        raise ValueError("split manifest must assert final_holdout_inspected=false")
    splits = raw.get("splits")
    if not isinstance(splits, dict):
        raise ValueError("split manifest requires splits object")

    parsed: dict[str, tuple[datetime, datetime]] = {}
    for phase in ("discovery", "validation", "final_holdout"):
        values = splits.get(phase)
        if not isinstance(values, dict) or "start" not in values or "end" not in values:
            raise ValueError(f"split manifest missing {phase} start/end")
        start = parse_ts(values["start"])
        end = parse_ts(values["end"])
        if not is_on_15m_grid(start) or not is_on_15m_grid(end):
            raise ValueError(f"split manifest {phase} boundaries must be on 15m grid")
        if end <= start:
            raise ValueError(f"split manifest {phase} end must be after start")
        parsed[phase] = (start, end)

    if parsed["discovery"][1] != parsed["validation"][0]:
        raise ValueError("split manifest discovery/validation must be contiguous")
    if parsed["validation"][1] != parsed["final_holdout"][0]:
        raise ValueError("split manifest validation/holdout must be contiguous")
    if not (
        parsed["discovery"][0]
        < parsed["discovery"][1]
        < parsed["validation"][1]
        < parsed["final_holdout"][1]
    ):
        raise ValueError("split manifest phases must be strictly chronological")
    return raw


def load_rows(path: Path) -> list[ValidationRow]:
    rows: list[ValidationRow] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            if not isinstance(raw, dict):
                raise ValueError(f"JSONL line {line_number} must be an object")
            asof_ts = parse_ts(raw["asof_ts"])
            if not is_on_15m_grid(asof_ts):
                raise ValueError(f"JSONL line {line_number} asof_ts must be on 15m grid")
            rows.append(
                ValidationRow(
                    venue=str(raw["venue"]),
                    asset_id=int(raw["asset_id"]),
                    asof_ts=asof_ts,
                    candidate_id=str(raw["candidate_id"]),
                    candidate_score=(None if raw.get("candidate_score") is None else float(raw["candidate_score"])),
                    b0_score=(None if raw.get("b0_score") is None else float(raw["b0_score"])),
                    b0_pressure_state=(None if raw.get("b0_pressure_state") is None else str(raw["b0_pressure_state"])),
                    b1_return=(None if raw.get("b1_return") is None else float(raw["b1_return"])),
                    forward_15m=(None if raw.get("forward_15m") is None else float(raw["forward_15m"])),
                    forward_1h=(None if raw.get("forward_1h") is None else float(raw["forward_1h"])),
                    forward_4h=(None if raw.get("forward_4h") is None else float(raw["forward_4h"])),
                    forward_24h=(None if raw.get("forward_24h") is None else float(raw["forward_24h"])),
                )
            )
    return rows


def select_phase_rows(rows: list[ValidationRow], manifest: dict[str, Any], phase: str) -> list[ValidationRow]:
    if phase not in ALLOWED_PHASES:
        raise ValueError("final holdout is not available in validation runner v1")
    split = manifest["splits"][phase]
    start = parse_ts(split["start"])
    end = parse_ts(split["end"])
    holdout_start = parse_ts(manifest["splits"]["final_holdout"]["start"])
    if end > holdout_start:
        raise ValueError("requested phase overlaps final holdout")
    return [row for row in rows if start <= ensure_utc(row.asof_ts) < end]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    emit(
        f"STARTED runner={RUNNER_NAME} version={RUNNER_VERSION} mode=research-artifact-only "
        f"workers=1 phase={args.phase} final_holdout_access=DENY"
    )
    try:
        manifest_started = time.perf_counter()
        emit("PHASE_STARTED name=load_split_manifest")
        manifest = load_split_manifest(Path(args.split_manifest))
        emit(
            f"PHASE_FINISHED name=load_split_manifest elapsed_s={time.perf_counter() - manifest_started:.3f}"
        )

        load_started = time.perf_counter()
        emit("PHASE_STARTED name=load_validation_rows")
        all_rows = load_rows(Path(args.input_jsonl))
        rows = select_phase_rows(all_rows, manifest, args.phase)
        emit(
            f"PHASE_FINISHED name=load_validation_rows input_rows={len(all_rows)} phase_rows={len(rows)} "
            f"elapsed_s={time.perf_counter() - load_started:.3f}"
        )

        eval_started = time.perf_counter()
        emit("PHASE_STARTED name=evaluate_validation_metrics")
        summary = serializable_validation_summary(rows)
        emit(
            f"PHASE_FINISHED name=evaluate_validation_metrics rows={len(rows)} "
            f"elapsed_s={time.perf_counter() - eval_started:.3f}"
        )

        output = {
            "runner": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "phase": args.phase,
            "final_holdout_access": "DENY",
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
            f"FINISHED runner={RUNNER_NAME} result=PASS phase={args.phase} rows={len(rows)} "
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
