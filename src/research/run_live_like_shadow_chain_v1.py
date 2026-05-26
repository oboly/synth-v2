from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.research import run_intraday_retest_reclaim_candidate_v1 as candidate_runner
from src.research import run_live_like_decision_preview_v1 as decision_runner
from src.research import run_live_like_execution_plan_preview_v1 as execution_runner
from src.research import run_live_like_shadow_event_v1 as shadow_runner


REPORT_NAME = "live_like_shadow_chain_v1"
REPORT_VERSION = "1.0"
DEFAULT_OUTPUT_ROOT = "data/research/live_like_shadow_chain_v1"
DEFAULT_RUN_DIR_PREFIX = "run_"

CHAIN_SUMMARY_JSON = "chain_summary_v1.json"
CHAIN_SUMMARY_JSONL = "chain_summary_v1.jsonl"
MANIFEST_JSON = "manifest_v1.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the full live-like shadow vertical slice: "
            "StrategyCandidate -> DecisionPreview -> ExecutionPlanPreview -> ShadowEvent."
        )
    )
    parser.add_argument("--market", default="NEAR-EUR")
    parser.add_argument("--symbol", default="NEAR")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--quote", default="EUR")
    parser.add_argument("--strategy-instance-id", default="near_intraday_retest_reclaim_v1")
    parser.add_argument("--mode", default="shadow")
    parser.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def resolve_output_dir(*, output_root: str, run_id: str) -> Path:
    return Path(output_root) / f"{DEFAULT_RUN_DIR_PREFIX}{run_id}"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=chain_json_default) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(row, sort_keys=True, ensure_ascii=True, default=chain_json_default) + "\n",
        encoding="utf-8",
    )


def chain_json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return candidate_runner.fmt_ts(value)
    return value


def run_candidate_stage(args: argparse.Namespace) -> tuple[Path, Any, dict[str, Any]]:
    run_started_at = candidate_runner.utc_now()
    run_id = candidate_runner.utc_run_id(run_started_at)
    output_dir = candidate_runner.resolve_output_dir(
        output_root=str(candidate_runner.DEFAULT_OUTPUT_ROOT),
        run_id=run_id,
    )
    output_paths = candidate_runner.output_paths(output_dir)
    base_url = str(candidate_runner.DEFAULT_BASE_URL).rstrip("/")
    market = str(args.market).upper()
    instance_config = candidate_runner.resolve_instance_config(args)
    current_price = candidate_runner.fetch_price(base_url=base_url, market=market)
    candles_15m = candidate_runner.fetch_candles(base_url=base_url, market=market, interval="15m", limit=64)
    candles_1h = candidate_runner.fetch_candles(base_url=base_url, market=market, interval="1h", limit=64)
    context_15m = candidate_runner.classify_timeframe("15m", candles_15m, current_price)
    context_1h = candidate_runner.classify_timeframe("1h", candles_1h, current_price)
    candidate = candidate_runner.build_candidate(
        instance_config=instance_config,
        market=market,
        current_price=current_price,
        context_15m=context_15m,
        context_1h=context_1h,
        now_utc=run_started_at,
    )
    run_finished_at = candidate_runner.utc_now()
    manifest = candidate_runner.build_manifest(
        args=args,
        run_id=run_id,
        output_dir=output_dir,
        instance_config=instance_config,
        candidate=candidate,
        output_paths_map=output_paths,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
    )
    if args.write_files:
        payload = asdict(candidate)
        candidate_runner.write_json(output_paths.strategy_candidate_json, payload)
        candidate_runner.write_jsonl(output_paths.strategy_candidate_jsonl, payload)
        candidate_runner.write_json(output_paths.manifest_json, manifest)
    return output_dir, candidate, manifest


def run_decision_stage(args: argparse.Namespace, candidate_run_dir: Path) -> tuple[Path, Any, dict[str, Any]]:
    run_started_at = decision_runner.utc_now()
    run_id = decision_runner.utc_run_id(run_started_at)
    output_dir = decision_runner.resolve_output_dir(
        output_root=str(decision_runner.DEFAULT_OUTPUT_ROOT),
        run_id=run_id,
    )
    candidate, _payload = decision_runner.load_candidate(candidate_run_dir)
    decision_preview = decision_runner.decision_from_candidate(
        candidate=candidate,
        trading_account_id=None,
    )
    run_finished_at = decision_runner.utc_now()
    manifest = decision_runner.build_manifest(
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
        payload = asdict(decision_preview)
        decision_runner.write_json(output_dir / decision_runner.DECISION_PREVIEW_JSON, payload)
        decision_runner.write_jsonl(output_dir / decision_runner.DECISION_PREVIEW_JSONL, payload)
        decision_runner.write_json(output_dir / decision_runner.MANIFEST_JSON, manifest)
    return output_dir, decision_preview, manifest


def run_execution_plan_stage(args: argparse.Namespace, decision_run_dir: Path) -> tuple[Path, Any, dict[str, Any]]:
    run_started_at = execution_runner.utc_now()
    run_id = execution_runner.utc_run_id(run_started_at)
    output_dir = execution_runner.resolve_output_dir(
        output_root=str(execution_runner.DEFAULT_OUTPUT_ROOT),
        run_id=run_id,
    )
    decision_preview = execution_runner.load_decision_preview(decision_run_dir)
    decision_manifest = execution_runner.load_decision_manifest(decision_run_dir)
    candidate_run_dir_value = decision_manifest.get("source_candidate_run_dir")
    candidate_run_dir = Path(str(candidate_run_dir_value)) if candidate_run_dir_value else None
    candidate = execution_runner.load_candidate(candidate_run_dir)
    execution_plan_preview = execution_runner.build_execution_plan_preview(
        decision_preview=decision_preview,
        candidate=candidate,
        run_id=run_id,
        mode=str(args.mode),
    )
    run_finished_at = execution_runner.utc_now()
    manifest = execution_runner.build_manifest(
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
        payload = asdict(execution_plan_preview)
        execution_runner.write_json(output_dir / execution_runner.EXECUTION_PLAN_JSON, payload)
        execution_runner.write_jsonl(output_dir / execution_runner.EXECUTION_PLAN_JSONL, payload)
        execution_runner.write_json(output_dir / execution_runner.MANIFEST_JSON, manifest)
    return output_dir, execution_plan_preview, manifest


def run_shadow_event_stage(
    args: argparse.Namespace,
    candidate_run_dir: Path,
    decision_run_dir: Path,
    execution_plan_run_dir: Path,
) -> tuple[Path, Any, dict[str, Any]]:
    run_started_at = shadow_runner.utc_now()
    run_id = shadow_runner.utc_run_id(run_started_at)
    output_dir = shadow_runner.resolve_output_dir(
        output_root=str(shadow_runner.DEFAULT_OUTPUT_ROOT),
        run_id=run_id,
    )
    candidate = shadow_runner.load_candidate(candidate_run_dir)
    decision_preview = shadow_runner.load_decision_preview(decision_run_dir)
    execution_plan_preview = shadow_runner.load_execution_plan(execution_plan_run_dir)
    shadow_event = shadow_runner.build_shadow_event(
        candidate=candidate,
        decision_preview=decision_preview,
        execution_plan_preview=execution_plan_preview,
        event_ts_utc=run_started_at,
    )
    run_finished_at = shadow_runner.utc_now()
    manifest = shadow_runner.build_manifest(
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
        payload = asdict(shadow_event)
        shadow_runner.write_json(output_dir / shadow_runner.SHADOW_EVENT_JSON, payload)
        shadow_runner.write_jsonl(output_dir / shadow_runner.SHADOW_EVENT_JSONL, payload)
        shadow_runner.write_json(output_dir / shadow_runner.MANIFEST_JSON, manifest)
    return output_dir, shadow_event, manifest


def build_chain_summary(
    *,
    args: argparse.Namespace,
    candidate_run_dir: Path,
    decision_run_dir: Path,
    execution_plan_run_dir: Path,
    shadow_event_run_dir: Path,
    candidate: Any,
    decision_preview: Any,
    execution_plan_preview: Any,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "mode": str(args.mode),
        "market": str(args.market).upper(),
        "symbol": str(args.symbol).upper(),
        "candidate_run_dir": str(candidate_run_dir),
        "decision_run_dir": str(decision_run_dir),
        "execution_plan_run_dir": str(execution_plan_run_dir),
        "shadow_event_run_dir": str(shadow_event_run_dir),
        "candidate_state": candidate.candidate_state,
        "decision_state": decision_preview.decision_state,
        "execution_plan_state": execution_plan_preview.execution_plan_state,
        "no_order_submitted": True,
        "db_writes": 0,
        "broker_private_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "decision_gate_changes": 0,
        "execution_planner_changes": 0,
        "executor": "none",
        "executor_enabled": False,
        "account_tables_used": False,
    }


def build_chain_manifest(
    *,
    args: argparse.Namespace,
    run_id: str,
    output_dir: Path,
    chain_summary: dict[str, Any],
    run_started_at: datetime,
    run_finished_at: datetime,
) -> dict[str, Any]:
    return {
        **chain_summary,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "run_started_at_utc": candidate_runner.fmt_ts(run_started_at),
        "run_finished_at_utc": candidate_runner.fmt_ts(run_finished_at),
        "run_duration_sec": round((run_finished_at - run_started_at).total_seconds(), 6),
        "notes": [
            "This completes the live-like shadow chain.",
            "This is not paper trading and not live trading.",
            "The next step is a static shadow dashboard or report, not executor enablement.",
        ],
        "output_paths": {
            "chain_summary_json": str(output_dir / CHAIN_SUMMARY_JSON),
            "chain_summary_jsonl": str(output_dir / CHAIN_SUMMARY_JSONL),
            "manifest_json": str(output_dir / MANIFEST_JSON),
        },
    }


def print_summary(*, args: argparse.Namespace, chain_summary: dict[str, Any]) -> None:
    payload = {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "market": chain_summary["market"],
        "symbol": chain_summary["symbol"],
        "candidate_state": chain_summary["candidate_state"],
        "decision_state": chain_summary["decision_state"],
        "execution_plan_state": chain_summary["execution_plan_state"],
        "shadow_event_run_dir": chain_summary["shadow_event_run_dir"],
        "broker_writes": 0,
        "order_submission": 0,
        "executor": "none",
        "no_order_submitted": True,
    }
    if args.output == "json":
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))
        return
    print(f"report={payload['report']} version={payload['version']}")
    print(f"market={payload['market']} symbol={payload['symbol']}")
    print(
        f"candidate_state={payload['candidate_state']} "
        f"decision_state={payload['decision_state']}"
    )
    print(f"execution_plan_state={payload['execution_plan_state']}")
    print(f"shadow_event_run_dir={payload['shadow_event_run_dir']}")
    print("broker_writes=0 order_submission=0 executor=none")
    print("no_order_submitted=true")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_started_at = candidate_runner.utc_now()
    run_id = candidate_runner.utc_run_id(run_started_at)
    output_dir = resolve_output_dir(output_root=str(args.output_root), run_id=run_id)

    candidate_run_dir, candidate, _candidate_manifest = run_candidate_stage(args)
    decision_run_dir, decision_preview, _decision_manifest = run_decision_stage(args, candidate_run_dir)
    execution_plan_run_dir, execution_plan_preview, _execution_manifest = run_execution_plan_stage(args, decision_run_dir)
    shadow_event_run_dir, _shadow_event, _shadow_manifest = run_shadow_event_stage(
        args,
        candidate_run_dir,
        decision_run_dir,
        execution_plan_run_dir,
    )

    chain_summary = build_chain_summary(
        args=args,
        candidate_run_dir=candidate_run_dir,
        decision_run_dir=decision_run_dir,
        execution_plan_run_dir=execution_plan_run_dir,
        shadow_event_run_dir=shadow_event_run_dir,
        candidate=candidate,
        decision_preview=decision_preview,
        execution_plan_preview=execution_plan_preview,
    )
    run_finished_at = candidate_runner.utc_now()
    manifest = build_chain_manifest(
        args=args,
        run_id=run_id,
        output_dir=output_dir,
        chain_summary=chain_summary,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
    )

    if args.write_files:
        write_json(output_dir / CHAIN_SUMMARY_JSON, chain_summary)
        write_jsonl(output_dir / CHAIN_SUMMARY_JSONL, chain_summary)
        write_json(output_dir / MANIFEST_JSON, manifest)

    print_summary(args=args, chain_summary=chain_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
