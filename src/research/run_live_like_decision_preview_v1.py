from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.research.live_like_vertical_slice_contract_v1 import DecisionPreview, StrategyCandidate


REPORT_NAME = "live_like_decision_preview_v1"
REPORT_VERSION = "1.0"
DEFAULT_OUTPUT_ROOT = "data/research/live_like_decision_preview_v1"
DEFAULT_RUN_DIR_PREFIX = "run_"

CANDIDATE_JSON = "strategy_candidate_v1.json"
DECISION_PREVIEW_JSON = "decision_preview_v1.json"
DECISION_PREVIEW_JSONL = "decision_preview_v1.jsonl"
MANIFEST_JSON = "manifest_v1.json"

ENTRY_REVIEW_STATES = {"SHALLOW_RETEST_ACTIVE", "NORMAL_RETEST_ACTIVE", "DEEP_RETEST_ACTIVE"}
WAIT_STATES = {"IMPULSE_ACTIVE", "WAIT_RETEST"}
BLOCKED_STATES = {"NO_CANDIDATE", "INVALIDATED", "STALE"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a shadow-mode DecisionPreview from a file-based StrategyCandidate "
            "artifact. This is a preview adapter, not the real decision_gate."
        )
    )
    parser.add_argument("--candidate-run-dir", required=True)
    parser.add_argument("--trading-account-id", type=int, default=None)
    parser.add_argument("--mode", default="shadow")
    parser.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def fmt_ts(value: datetime) -> str:
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_run_id(now_utc: datetime) -> str:
    return now_utc.strftime("%Y%m%dT%H%M%SZ")


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return fmt_ts(value)
    return value


def resolve_output_dir(*, output_root: str, run_id: str) -> Path:
    return Path(output_root) / f"{DEFAULT_RUN_DIR_PREFIX}{run_id}"


def load_candidate(candidate_run_dir: Path) -> tuple[StrategyCandidate, dict[str, Any]]:
    candidate_path = candidate_run_dir / CANDIDATE_JSON
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate = StrategyCandidate(**payload)
    return candidate, payload


def decision_from_candidate(
    *,
    candidate: StrategyCandidate,
    trading_account_id: int | None,
) -> DecisionPreview:
    candidate_state = candidate.candidate_state
    block_reasons: tuple[str, ...]

    if candidate_state == "ENTRY_CANDIDATE":
        decision_state = "SHADOW_REVIEW"
        permission_state = "PREVIEW_ONLY_NOT_PERMISSION"
        block_reasons = ("SHADOW_MODE_NO_PERMISSION",)
    elif candidate_state in ENTRY_REVIEW_STATES:
        decision_state = "WATCH_CANDIDATE"
        permission_state = "WAIT_FOR_ENTRY_CONFIRMATION"
        block_reasons = ("NOT_ENTRY_CANDIDATE_YET",)
    elif candidate_state in WAIT_STATES:
        decision_state = "WAIT"
        permission_state = "NO_PERMISSION"
        block_reasons = ("WAIT_RETEST",)
    elif candidate_state in BLOCKED_STATES:
        decision_state = "BLOCKED"
        permission_state = "NO_PERMISSION"
        block_reasons = (candidate_state,)
    else:
        decision_state = "BLOCKED"
        permission_state = "NO_PERMISSION"
        block_reasons = ("UNKNOWN_CANDIDATE_STATE", candidate_state)

    account_awareness = "none" if trading_account_id is None else "configured_id_only"
    notes = (
        "Preview-only adapter. This is not the real decision_gate and does not grant "
        "trade or order permission. Real account-aware permissions remain downstream."
    )
    return DecisionPreview(
        strategy_candidate_id=candidate.strategy_candidate_id,
        trading_account_id=trading_account_id,
        decision_state=decision_state,
        permission_state=permission_state,
        block_reasons=block_reasons,
        account_awareness=account_awareness,
        live_trading_enabled=False,
        broker_write_permission=False,
        notes=notes,
    )


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


def build_manifest(
    *,
    args: argparse.Namespace,
    run_id: str,
    output_dir: Path,
    candidate_run_dir: Path,
    candidate: StrategyCandidate,
    decision_preview: DecisionPreview,
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
        "source_candidate_run_dir": str(candidate_run_dir),
        "mode": str(args.mode),
        "candidate_state": candidate.candidate_state,
        "decision_state": decision_preview.decision_state,
        "permission_state": decision_preview.permission_state,
        "block_reasons": list(decision_preview.block_reasons),
        "db_writes": 0,
        "broker_private_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "decision_gate_changes": 0,
        "execution_planner_changes": 0,
        "executor": "none",
        "account_tables_used": False,
        "notes": [
            "This is not the real decision_gate.",
            "This is a contract adapter for shadow-mode preview only.",
            "Downstream path remains StrategyCandidate -> DecisionPreview -> ExecutionPlanPreview -> ShadowEvent.",
        ],
        "output_paths": {
            "decision_preview_json": str(output_dir / DECISION_PREVIEW_JSON),
            "decision_preview_jsonl": str(output_dir / DECISION_PREVIEW_JSONL),
            "manifest_json": str(output_dir / MANIFEST_JSON),
        },
    }


def print_summary(
    *,
    args: argparse.Namespace,
    candidate: StrategyCandidate,
    decision_preview: DecisionPreview,
    output_dir: Path | None,
) -> None:
    payload = {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "candidate_state": candidate.candidate_state,
        "decision_state": decision_preview.decision_state,
        "permission_state": decision_preview.permission_state,
        "block_reasons": list(decision_preview.block_reasons),
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
    print(
        f"permission_state={payload['permission_state']} "
        f"block_reasons={','.join(payload['block_reasons'])}"
    )
    if output_dir is not None:
        print(f"output_dir={output_dir}")
    print("broker_writes=0 order_submission=0 executor=none")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_started_at = utc_now()
    run_id = utc_run_id(run_started_at)
    output_dir = resolve_output_dir(output_root=str(args.output_root), run_id=run_id)
    candidate_run_dir = Path(args.candidate_run_dir)

    candidate, _candidate_payload = load_candidate(candidate_run_dir)
    decision_preview = decision_from_candidate(
        candidate=candidate,
        trading_account_id=args.trading_account_id,
    )

    decision_payload = asdict(decision_preview)
    run_finished_at = utc_now()
    manifest = build_manifest(
        args=args,
        run_id=run_id,
        output_dir=output_dir,
        candidate_run_dir=candidate_run_dir,
        candidate=candidate,
        decision_preview=decision_preview,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
    )

    if args.write_files:
        write_json(output_dir / DECISION_PREVIEW_JSON, decision_payload)
        write_jsonl(output_dir / DECISION_PREVIEW_JSONL, decision_payload)
        write_json(output_dir / MANIFEST_JSON, manifest)

    print_summary(
        args=args,
        candidate=candidate,
        decision_preview=decision_preview,
        output_dir=output_dir if args.write_files else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
