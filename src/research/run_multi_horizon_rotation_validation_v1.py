from __future__ import annotations

"""Holdout-safe artifact evaluator for Issue #593.

Reads research JSONL only. It has no DB access and exposes discovery/validation only;
final-holdout evaluation is intentionally unavailable in this runner version.
"""

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any

from src.research.multi_horizon_rotation_validation_temporal_v1 import (
    all_candidate_lead_lag,
    regime_stability,
)
from src.research.multi_horizon_rotation_validation_v1 import (
    ValidationRow,
    derive_chronological_split,
    ensure_utc,
    is_on_15m_grid,
    serializable_validation_summary,
)


RUNNER_NAME = "run_multi_horizon_rotation_validation_v1"
RUNNER_VERSION = "1.0.0"
ALLOWED_PHASES = ("discovery", "validation")
FORWARD_HORIZONS = {
    "forward_15m": timedelta(minutes=15),
    "forward_1h": timedelta(hours=1),
    "forward_4h": timedelta(hours=4),
    "forward_24h": timedelta(hours=24),
}


def emit(message: str) -> None:
    print(message, flush=True)


def parse_ts(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_optional_finite_float(value: Any, *, field: str, line_number: int) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError(f"JSONL line {line_number} {field} must be finite when present")
    return parsed


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

    expected = derive_chronological_split(
        start=parsed["discovery"][0],
        end=parsed["final_holdout"][1],
    )
    if parsed != expected:
        raise ValueError("split manifest does not match frozen 60/20/20 15m-grid contract")
    return raw


def load_rows(path: Path) -> list[ValidationRow]:
    rows: list[ValidationRow] = []
    identities: set[tuple[str, int, str, datetime]] = set()
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
            venue = str(raw["venue"])
            asset_id = int(raw["asset_id"])
            candidate_id = str(raw["candidate_id"])
            identity = (venue, asset_id, candidate_id, asof_ts)
            if identity in identities:
                raise ValueError(f"JSONL line {line_number} duplicate validation row identity")
            identities.add(identity)
            rows.append(
                ValidationRow(
                    venue=venue,
                    asset_id=asset_id,
                    asof_ts=asof_ts,
                    candidate_id=candidate_id,
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
            )
    return rows


def validate_phase_scoped_rows(rows: list[ValidationRow], manifest: dict[str, Any], phase: str) -> list[ValidationRow]:
    if phase not in ALLOWED_PHASES:
        raise ValueError("final holdout is not available in validation runner v1")
    split = manifest["splits"][phase]
    start = parse_ts(split["start"])
    end = parse_ts(split["end"])
    holdout_start = parse_ts(manifest["splits"]["final_holdout"]["start"])
    if end > holdout_start:
        raise ValueError("requested phase overlaps final holdout")
    outside = [row for row in rows if not (start <= ensure_utc(row.asof_ts) < end)]
    if outside:
        raise ValueError(
            f"input artifact is not phase-scoped: {len(outside)} row(s) outside requested {phase} interval"
        )
    for row in rows:
        asof = ensure_utc(row.asof_ts)
        for field, horizon in FORWARD_HORIZONS.items():
            value = getattr(row, field)
            if value is not None and asof + horizon >= end:
                raise ValueError(
                    f"{field} outcome boundary reaches next phase for "
                    f"asset_id={row.asset_id} candidate_id={row.candidate_id} asof={asof.isoformat()}"
                )
    return rows


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
        rows = load_rows(Path(args.input_jsonl))
        validate_phase_scoped_rows(rows, manifest, args.phase)
        emit(
            f"PHASE_FINISHED name=load_validation_rows phase_rows={len(rows)} "
            f"elapsed_s={time.perf_counter() - load_started:.3f}"
        )

        eval_started = time.perf_counter()
        emit("PHASE_STARTED name=evaluate_validation_metrics")
        summary = serializable_validation_summary(rows)
        summary["lead_lag_vs_b1"] = all_candidate_lead_lag(rows)
        summary["regime_stability"] = regime_stability(rows)
        emit(
            f"PHASE_FINISHED name=evaluate_validation_metrics rows={len(rows)} "
            f"elapsed_s={time.perf_counter() - eval_started:.3f}"
        )

        output = {
            "runner": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "phase": args.phase,
            "final_holdout_access": "DENY",
            "input_artifact_scope": "REQUESTED_PHASE_ONLY",
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
