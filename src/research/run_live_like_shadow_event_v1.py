from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.research.live_like_vertical_slice_contract_v1 import (
    DecisionPreview,
    ExecutionPlanPreview,
    ShadowEvent,
    StrategyCandidate,
)


REPORT_NAME = "live_like_shadow_event_v1"
REPORT_VERSION = "1.0"
DEFAULT_OUTPUT_ROOT = "data/research/live_like_shadow_event_v1"
DEFAULT_RUN_DIR_PREFIX = "run_"

CANDIDATE_JSON = "strategy_candidate_v1.json"
DECISION_JSON = "decision_preview_v1.json"
EXECUTION_PLAN_JSON = "execution_plan_preview_v1.json"
SHADOW_EVENT_JSON = "shadow_event_v1.json"
SHADOW_EVENT_JSONL = "shadow_event_v1.jsonl"
MANIFEST_JSON = "manifest_v1.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a shadow-mode ShadowEvent from file-based StrategyCandidate, "
            "DecisionPreview, and ExecutionPlanPreview artifacts."
        )
    )
    parser.add_argument("--candidate-run-dir", required=True)
    parser.add_argument("--decision-run-dir", required=True)
    parser.add_argument("--execution-plan-run-dir", required=True)
    parser.add_argument("--mode", default="shadow")
    parser.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def utc_now() -> datetime:
    return datetime.now(UTC)


def fmt_ts(value: datetime) -> str:
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def utc_run_id(now_utc: datetime) -> str:
    return now_utc.strftime("%Y%m%dT%H%M%SZ")


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return fmt_ts(value)
    return value


def resolve_output_dir(*, output_root: str, run_id: str) -> Path:
    return Path(output_root) / f"{DEFAULT_RUN_DIR_PREFIX}{run_id}"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(row, sort_keys=True, ensure_ascii=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def load_candidate(candidate_run_dir: Path) -> StrategyCandidate:
    payload = json.loads((candidate_run_dir / CANDIDATE_JSON).read_text(encoding="utf-8"))
    return StrategyCandidate(**payload)


def load_decision_preview(decision_run_dir: Path) -> DecisionPreview:
    payload = json.loads((decision_run_dir / DECISION_JSON).read_text(encoding="utf-8"))
    return DecisionPreview(**payload)


def load_execution_plan(execution_plan_run_dir: Path) -> ExecutionPlanPreview:
    payload = json.loads((execution_plan_run_dir / EXECUTION_PLAN_JSON).read_text(encoding="utf-8"))
    return ExecutionPlanPreview(**payload)


def resolve_observed_price(candidate: StrategyCandidate) -> float | None:
    source_context = candidate.source_context
    for key in ("current_price", "ticker_price", "observed_price", "price_at_emit"):
        value = source_context.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def build_shadow_event(
    *,
    candidate: StrategyCandidate,
    decision_preview: DecisionPreview,
    execution_plan_preview: ExecutionPlanPreview,
    event_ts_utc: datetime,
) -> ShadowEvent:
    return ShadowEvent(
        strategy_instance_id=candidate.strategy_instance_id,
        candidate_state=candidate.candidate_state,
        decision_state=decision_preview.decision_state,
        execution_plan_state=execution_plan_preview.execution_plan_state,
        observed_price=resolve_observed_price(candidate),
        event_ts_utc=fmt_ts(event_ts_utc),
        no_order_submitted=True,
    )


def build_manifest(
    *,
    args: argparse.Namespace,
    run_id: str,
    output_dir: Path,
    candidate_run_dir: Path,
    decision_run_dir: Path,
    execution_plan_run_dir: Path,
    shadow_event: ShadowEvent,
    execution_plan_preview: ExecutionPlanPreview,
    run_started_at: datetime,
    run_finished_at: datetime,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "run_started_at_utc": fmt_ts(run_started_at),
        "run_finished_at_utc": fmt_ts(run_finished_at),
        "run_duration_sec": round((run_finished_at - run_started_at).total_seconds(), 6),
        "candidate_state": shadow_event.candidate_state,
        "decision_state": shadow_event.decision_state,
        "execution_plan_state": shadow_event.execution_plan_state,
        "db_writes": 0,
        "broker_private_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "decision_gate_changes": 0,
        "execution_planner_changes": 0,
        "executor": "none",
        "executor_enabled": False,
        "no_order_submitted": True,
        "account_tables_used": False,
        "mode": str(args.mode),
        "source_candidate_run_dir": str(candidate_run_dir),
        "source_decision_run_dir": str(decision_run_dir),
        "source_execution_plan_run_dir": str(execution_plan_run_dir),
        "notes": [
            "This completes the shadow vertical slice.",
            "This is not execution, not paper trading, and not live trading.",
            "The next step is a chain runner or dashboard, not executor enablement.",
        ],
        "output_paths": {
            "shadow_event_json": str(output_dir / SHADOW_EVENT_JSON),
            "shadow_event_jsonl": str(output_dir / SHADOW_EVENT_JSONL),
            "manifest_json": str(output_dir / MANIFEST_JSON),
        },
        "execution_plan_preview_executor_enabled": execution_plan_preview.executor_enabled,
    }


def print_summary(
    *,
    args: argparse.Namespace,
    shadow_event: ShadowEvent,
    output_dir: Path | None,
) -> None:
    payload = {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "candidate_state": shadow_event.candidate_state,
        "decision_state": shadow_event.decision_state,
        "execution_plan_state": shadow_event.execution_plan_state,
        "no_order_submitted": True,
        "broker_writes": 0,
        "order_submission": 0,
        "executor": "none",
    }
    if output_dir is not None:
        payload["output_dir"] = str(output_dir)

    if args.output == "json":
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))
        return

    print(f"report={payload['report']} version={payload['version']}")
    print(
        f"candidate_state={payload['candidate_state']} "
        f"decision_state={payload['decision_state']}"
    )
    print(f"execution_plan_state={payload['execution_plan_state']}")
    if output_dir is not None:
        print(f"output_dir={output_dir}")
    print("no_order_submitted=true")
    print("broker_writes=0 order_submission=0 executor=none")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_started_at = utc_now()
    run_id = utc_run_id(run_started_at)
    output_dir = resolve_output_dir(output_root=str(args.output_root), run_id=run_id)

    candidate_run_dir = Path(str(args.candidate_run_dir))
    decision_run_dir = Path(str(args.decision_run_dir))
    execution_plan_run_dir = Path(str(args.execution_plan_run_dir))

    candidate = load_candidate(candidate_run_dir)
    decision_preview = load_decision_preview(decision_run_dir)
    execution_plan_preview = load_execution_plan(execution_plan_run_dir)
    shadow_event = build_shadow_event(
        candidate=candidate,
        decision_preview=decision_preview,
        execution_plan_preview=execution_plan_preview,
        event_ts_utc=run_started_at,
    )

    shadow_payload = asdict(shadow_event)
    run_finished_at = utc_now()
    manifest = build_manifest(
        args=args,
        run_id=run_id,
        output_dir=output_dir,
        candidate_run_dir=candidate_run_dir,
        decision_run_dir=decision_run_dir,
        execution_plan_run_dir=execution_plan_run_dir,
        shadow_event=shadow_event,
        execution_plan_preview=execution_plan_preview,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
    )

    if args.write_files:
        write_json(output_dir / SHADOW_EVENT_JSON, shadow_payload)
        write_jsonl(output_dir / SHADOW_EVENT_JSONL, shadow_payload)
        write_json(output_dir / MANIFEST_JSON, manifest)

    print_summary(args=args, shadow_event=shadow_event, output_dir=output_dir if args.write_files else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
