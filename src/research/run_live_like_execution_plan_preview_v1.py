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
    StrategyCandidate,
)


REPORT_NAME = "live_like_execution_plan_preview_v1"
REPORT_VERSION = "1.0"
DEFAULT_OUTPUT_ROOT = "data/research/live_like_execution_plan_preview_v1"
DEFAULT_RUN_DIR_PREFIX = "run_"

DECISION_PREVIEW_JSON = "decision_preview_v1.json"
DECISION_MANIFEST_JSON = "manifest_v1.json"
CANDIDATE_JSON = "strategy_candidate_v1.json"
EXECUTION_PLAN_JSON = "execution_plan_preview_v1.json"
EXECUTION_PLAN_JSONL = "execution_plan_preview_v1.jsonl"
MANIFEST_JSON = "manifest_v1.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a shadow-mode ExecutionPlanPreview from a file-based DecisionPreview "
            "artifact. This is a preview adapter, not the real execution_planner."
        )
    )
    parser.add_argument("--decision-run-dir", required=True)
    parser.add_argument("--candidate-run-dir", default=None)
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


def load_decision_preview(decision_run_dir: Path) -> DecisionPreview:
    payload = json.loads((decision_run_dir / DECISION_PREVIEW_JSON).read_text(encoding="utf-8"))
    return DecisionPreview(**payload)


def load_decision_manifest(decision_run_dir: Path) -> dict[str, Any]:
    return json.loads((decision_run_dir / DECISION_MANIFEST_JSON).read_text(encoding="utf-8"))


def load_candidate(candidate_run_dir: Path | None) -> StrategyCandidate | None:
    if candidate_run_dir is None:
        return None
    candidate_path = candidate_run_dir / CANDIDATE_JSON
    if not candidate_path.exists():
        return None
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    return StrategyCandidate(**payload)


def resolve_candidate_run_dir(*, args: argparse.Namespace, decision_manifest: dict[str, Any]) -> Path | None:
    if args.candidate_run_dir:
        return Path(str(args.candidate_run_dir))
    source_dir = decision_manifest.get("source_candidate_run_dir")
    if source_dir:
        return Path(str(source_dir))
    return None


def infer_side(candidate: StrategyCandidate | None) -> str:
    if candidate is None:
        return "NONE"
    if candidate.direction_pressure > 0:
        return "BUY"
    if candidate.direction_pressure < 0:
        return "SELL"
    return "NONE"


def infer_limit_price(candidate: StrategyCandidate | None) -> float | None:
    if candidate is None:
        return None
    observed = candidate.source_context.get("price_at_emit")
    if observed is None:
        return None
    try:
        return float(observed)
    except (TypeError, ValueError):
        return None


def build_execution_plan_preview(
    *,
    decision_preview: DecisionPreview,
    candidate: StrategyCandidate | None,
    run_id: str,
    mode: str,
) -> ExecutionPlanPreview:
    decision_preview_id = f"{decision_preview.strategy_candidate_id}__decision_preview__{run_id}"
    symbol = candidate.symbol if candidate is not None else "UNKNOWN"
    quote = candidate.quote if candidate is not None else ""
    execution_profile = (
        str(candidate.source_context.get("thresholds", {}).get("execution_profile"))
        if candidate is not None
        else "PREVIEW_ONLY"
    )
    if execution_profile in {"None", ""}:
        execution_profile = "PREVIEW_ONLY"

    decision_state = decision_preview.decision_state
    permission_state = decision_preview.permission_state
    block_reasons = tuple(decision_preview.block_reasons)

    if decision_state == "SHADOW_REVIEW" and permission_state == "PREVIEW_ONLY_NOT_PERMISSION":
        execution_plan_state = "PREVIEW_ONLY_BLOCKED"
        side = infer_side(candidate)
        max_notional_preview = None
        limit_price_preview = infer_limit_price(candidate)
        ladder_steps_preview: tuple[dict[str, Any], ...] = ()
        timeout_seconds = 0
        cancel_conditions = ("SHADOW_MODE_NO_PERMISSION",)
    elif decision_state == "WATCH_CANDIDATE":
        execution_plan_state = "WAIT_FOR_ENTRY_CONFIRMATION"
        side = "NONE"
        max_notional_preview = None
        limit_price_preview = None
        ladder_steps_preview = ()
        timeout_seconds = 0
        cancel_conditions = ("NOT_ENTRY_CANDIDATE_YET",)
    elif decision_state == "WAIT":
        execution_plan_state = "WAIT"
        side = "NONE"
        max_notional_preview = None
        limit_price_preview = None
        ladder_steps_preview = ()
        timeout_seconds = 0
        cancel_conditions = ("WAIT_RETEST",)
    else:
        execution_plan_state = "BLOCKED"
        side = "NONE"
        max_notional_preview = None
        limit_price_preview = None
        ladder_steps_preview = ()
        timeout_seconds = 0
        cancel_conditions = block_reasons if block_reasons else ("BLOCKED",)

    return ExecutionPlanPreview(
        decision_preview_id=decision_preview_id,
        execution_plan_state=execution_plan_state,
        execution_profile=execution_profile,
        side=side,
        symbol=symbol,
        quote=quote,
        max_notional_preview=max_notional_preview,
        limit_price_preview=limit_price_preview,
        ladder_steps_preview=ladder_steps_preview,
        timeout_seconds=timeout_seconds,
        cancel_conditions=cancel_conditions,
        mode=mode,
        executor_enabled=False,
        no_order_submission=True,
    )


def build_manifest(
    *,
    args: argparse.Namespace,
    run_id: str,
    output_dir: Path,
    decision_run_dir: Path,
    candidate_run_dir: Path | None,
    decision_preview: DecisionPreview,
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
        "decision_state": decision_preview.decision_state,
        "permission_state": decision_preview.permission_state,
        "execution_plan_state": execution_plan_preview.execution_plan_state,
        "side": execution_plan_preview.side,
        "db_writes": 0,
        "broker_private_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "decision_gate_changes": 0,
        "execution_planner_changes": 0,
        "executor": "none",
        "executor_enabled": False,
        "account_tables_used": False,
        "mode": str(args.mode),
        "source_decision_run_dir": str(decision_run_dir),
        "source_candidate_run_dir": str(candidate_run_dir) if candidate_run_dir is not None else None,
        "notes": [
            "This is not the real execution_planner.",
            "This preview adapter creates no executable intent and never enables the executor.",
            "Downstream path remains StrategyCandidate -> DecisionPreview -> ExecutionPlanPreview -> ShadowEvent.",
        ],
        "output_paths": {
            "execution_plan_preview_json": str(output_dir / EXECUTION_PLAN_JSON),
            "execution_plan_preview_jsonl": str(output_dir / EXECUTION_PLAN_JSONL),
            "manifest_json": str(output_dir / MANIFEST_JSON),
        },
    }


def print_summary(
    *,
    args: argparse.Namespace,
    decision_preview: DecisionPreview,
    execution_plan_preview: ExecutionPlanPreview,
    output_dir: Path | None,
) -> None:
    payload = {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "decision_state": decision_preview.decision_state,
        "permission_state": decision_preview.permission_state,
        "execution_plan_state": execution_plan_preview.execution_plan_state,
        "side": execution_plan_preview.side,
        "executor_enabled": False,
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
        f"decision_state={payload['decision_state']} "
        f"permission_state={payload['permission_state']}"
    )
    print(
        f"execution_plan_state={payload['execution_plan_state']} "
        f"side={payload['side']}"
    )
    if output_dir is not None:
        print(f"output_dir={output_dir}")
    print("executor_enabled=false")
    print("broker_writes=0 order_submission=0 executor=none")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_started_at = utc_now()
    run_id = utc_run_id(run_started_at)
    output_dir = resolve_output_dir(output_root=str(args.output_root), run_id=run_id)
    decision_run_dir = Path(str(args.decision_run_dir))

    decision_preview = load_decision_preview(decision_run_dir)
    decision_manifest = load_decision_manifest(decision_run_dir)
    candidate_run_dir = resolve_candidate_run_dir(args=args, decision_manifest=decision_manifest)
    candidate = load_candidate(candidate_run_dir)
    execution_plan_preview = build_execution_plan_preview(
        decision_preview=decision_preview,
        candidate=candidate,
        run_id=run_id,
        mode=str(args.mode),
    )

    execution_payload = asdict(execution_plan_preview)
    run_finished_at = utc_now()
    manifest = build_manifest(
        args=args,
        run_id=run_id,
        output_dir=output_dir,
        decision_run_dir=decision_run_dir,
        candidate_run_dir=candidate_run_dir,
        decision_preview=decision_preview,
        execution_plan_preview=execution_plan_preview,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
    )

    if args.write_files:
        write_json(output_dir / EXECUTION_PLAN_JSON, execution_payload)
        write_jsonl(output_dir / EXECUTION_PLAN_JSONL, execution_payload)
        write_json(output_dir / MANIFEST_JSON, manifest)

    print_summary(
        args=args,
        decision_preview=decision_preview,
        execution_plan_preview=execution_plan_preview,
        output_dir=output_dir if args.write_files else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
