from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from src.common.db import get_connection
from src.research.market_observer_evidence_preview_v1 import (
    MarketObserverEvidencePreviewAmbiguityError,
    MarketObserverEvidencePreviewMalformedTagsError,
    MarketObserverEvidencePreviewNoSourceError,
    build_market_observer_evidence_preview,
)
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
MARKET_OBSERVER_EVIDENCE_PREVIEW_JSON = "market_observer_evidence_preview_v1.json"

MARKET_OBSERVER_EVIDENCE_STATUS = Literal[
    "DISABLED",
    "AVAILABLE",
    "NO_SOURCE",
    "AMBIGUOUS",
    "MALFORMED_TAGS",
    "DB_READ_ERROR",
    "UNEXPECTED_ERROR",
]

_STRICT_UTC_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")


@dataclass(frozen=True)
class MarketObserverEvidenceSidecar:
    enabled: bool
    status: MARKET_OBSERVER_EVIDENCE_STATUS
    requested_inputs: dict[str, Any]
    db_reads: int
    db_writes: int = 0
    warnings: tuple[str, ...] = ()
    exception_class: str | None = None
    preview: dict[str, Any] | None = None
    source_locator: dict[str, Any] | None = None
    path: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "enabled": self.enabled,
            "status": self.status,
            "requested_inputs": self.requested_inputs,
            "warnings": list(self.warnings),
            "db_reads": self.db_reads,
            "db_writes": self.db_writes,
        }
        if self.exception_class is not None:
            payload["exception_class"] = self.exception_class
        if self.preview is not None:
            payload["preview"] = self.preview
        if self.source_locator is not None:
            payload["source_locator"] = self.source_locator
        return payload

    def to_compact_summary(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "warnings": list(self.warnings),
        }
        if self.exception_class is not None:
            payload["exception_class"] = self.exception_class
        if self.preview is not None:
            payload.update(
                {
                    "requested_event_ts_utc": self.preview["requested_event_ts_utc"],
                    "canonical_global_regime": self.preview["canonical_global_regime"],
                    "canonical_asset_class": self.preview["canonical_asset_class"],
                    "canonical_asset_class_regime": self.preview["canonical_asset_class_regime"],
                    "validation_status": self.preview["validation_status"],
                }
            )
        return payload


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
    parser.add_argument("--include-market-observer-evidence-preview", action="store_true")
    parser.add_argument("--canonical-asset-class", default=None)
    parser.add_argument("--canonical-regime-interval", default="4h")
    args = parser.parse_args(argv)
    if args.include_market_observer_evidence_preview and not args.canonical_asset_class:
        parser.error(
            "--canonical-asset-class is required when "
            "--include-market-observer-evidence-preview is enabled."
        )
    return args


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
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return value


def parse_strategy_candidate_created_at_utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("StrategyCandidate.created_at_utc must be a string.")
    if not _STRICT_UTC_Z_RE.fullmatch(value):
        raise ValueError(
            "StrategyCandidate.created_at_utc must be an explicit UTC Z timestamp."
        )
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def build_market_observer_requested_inputs(
    *,
    args: argparse.Namespace,
    candidate: Any,
) -> dict[str, Any]:
    return {
        "venue": str(args.venue),
        "canonical_asset_class": args.canonical_asset_class,
        "canonical_regime_interval": str(args.canonical_regime_interval),
        "strategy_candidate_created_at_utc": candidate.created_at_utc,
    }


def resolve_market_observer_evidence_sidecar(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    candidate: Any,
) -> MarketObserverEvidenceSidecar:
    sidecar_path = output_dir / MARKET_OBSERVER_EVIDENCE_PREVIEW_JSON
    requested_inputs = build_market_observer_requested_inputs(args=args, candidate=candidate)
    if not args.include_market_observer_evidence_preview:
        return MarketObserverEvidenceSidecar(
            enabled=False,
            status="DISABLED",
            requested_inputs=requested_inputs,
            db_reads=0,
        )

    try:
        event_ts_utc = parse_strategy_candidate_created_at_utc(candidate.created_at_utc)
    except Exception as exc:
        return MarketObserverEvidenceSidecar(
            enabled=True,
            status="UNEXPECTED_ERROR",
            requested_inputs=requested_inputs,
            db_reads=0,
            warnings=(
                "MarketObserverEvidencePreview was not attached because "
                "StrategyCandidate.created_at_utc was not an explicit UTC Z timestamp.",
            ),
            exception_class=exc.__class__.__name__,
            path=str(sidecar_path),
        )

    conn = None
    try:
        conn = get_connection()
        preview = build_market_observer_evidence_preview(
            conn=conn,
            venue=str(args.venue),
            interval_code=str(args.canonical_regime_interval),
            asset_class=str(args.canonical_asset_class),
            event_ts_utc=event_ts_utc,
        )
        preview_payload = asdict(preview)
        source_locator = dict(preview_payload["source_locator"])
        return MarketObserverEvidenceSidecar(
            enabled=True,
            status="AVAILABLE",
            requested_inputs=requested_inputs,
            db_reads=1,
            warnings=tuple(str(value) for value in preview_payload.get("warnings", ())),
            preview=preview_payload,
            source_locator=source_locator,
            path=str(sidecar_path),
        )
    except MarketObserverEvidencePreviewNoSourceError:
        return MarketObserverEvidenceSidecar(
            enabled=True,
            status="NO_SOURCE",
            requested_inputs=requested_inputs,
            db_reads=1,
            warnings=(
                "No canonical active_regime_observation row was available at-or-before the "
                "candidate event timestamp.",
            ),
            path=str(sidecar_path),
        )
    except MarketObserverEvidencePreviewAmbiguityError:
        return MarketObserverEvidenceSidecar(
            enabled=True,
            status="AMBIGUOUS",
            requested_inputs=requested_inputs,
            db_reads=1,
            warnings=(
                "Multiple canonical active_regime_observation rows matched the selected "
                "event timestamp.",
            ),
            path=str(sidecar_path),
        )
    except MarketObserverEvidencePreviewMalformedTagsError:
        return MarketObserverEvidenceSidecar(
            enabled=True,
            status="MALFORMED_TAGS",
            requested_inputs=requested_inputs,
            db_reads=1,
            warnings=(
                "Canonical active_regime_observation tags could not be decoded safely for "
                "the evidence sidecar.",
            ),
            path=str(sidecar_path),
        )
    except Exception as exc:
        return MarketObserverEvidenceSidecar(
            enabled=True,
            status="DB_READ_ERROR",
            requested_inputs=requested_inputs,
            db_reads=1,
            warnings=(
                "Read-only canonical active_regime_observation lookup failed. "
                "The four-stage shadow chain continued unchanged.",
            ),
            exception_class=exc.__class__.__name__,
            path=str(sidecar_path),
        )
    finally:
        if conn is not None:
            conn.close()


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
    market_observer_sidecar: MarketObserverEvidenceSidecar,
) -> dict[str, Any]:
    summary = {
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
        "market_observer_evidence_preview_enabled": market_observer_sidecar.enabled,
        "market_observer_evidence_preview_status": market_observer_sidecar.status,
        "market_observer_evidence_preview_path": market_observer_sidecar.path,
        "market_observer_canonical_asset_class": args.canonical_asset_class,
        "market_observer_canonical_regime_interval": str(args.canonical_regime_interval),
        "market_observer_db_reads": market_observer_sidecar.db_reads,
        "market_observer_db_writes": market_observer_sidecar.db_writes,
        "market_observer_evidence_preview": market_observer_sidecar.to_compact_summary(),
    }
    if market_observer_sidecar.source_locator is not None:
        summary["market_observer_evidence_preview_source_locator"] = market_observer_sidecar.source_locator
    return summary


def build_chain_manifest(
    *,
    args: argparse.Namespace,
    run_id: str,
    output_dir: Path,
    chain_summary: dict[str, Any],
    market_observer_sidecar: MarketObserverEvidenceSidecar,
    run_started_at: datetime,
    run_finished_at: datetime,
) -> dict[str, Any]:
    manifest = {
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
    if market_observer_sidecar.path is not None:
        manifest["output_paths"]["market_observer_evidence_preview_json"] = market_observer_sidecar.path
    return manifest


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
    if chain_summary["market_observer_evidence_preview_enabled"]:
        payload["market_observer_evidence_preview_status"] = chain_summary["market_observer_evidence_preview_status"]
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
    if "market_observer_evidence_preview_status" in payload:
        print(
            "market_observer_evidence_preview_status="
            f"{payload['market_observer_evidence_preview_status']}"
        )
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
    market_observer_sidecar = resolve_market_observer_evidence_sidecar(
        args=args,
        output_dir=output_dir,
        candidate=candidate,
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
        market_observer_sidecar=market_observer_sidecar,
    )
    run_finished_at = candidate_runner.utc_now()
    manifest = build_chain_manifest(
        args=args,
        run_id=run_id,
        output_dir=output_dir,
        chain_summary=chain_summary,
        market_observer_sidecar=market_observer_sidecar,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
    )

    if args.write_files:
        if market_observer_sidecar.enabled and market_observer_sidecar.path is not None:
            write_json(output_dir / MARKET_OBSERVER_EVIDENCE_PREVIEW_JSON, market_observer_sidecar.to_payload())
        write_json(output_dir / CHAIN_SUMMARY_JSON, chain_summary)
        write_jsonl(output_dir / CHAIN_SUMMARY_JSONL, chain_summary)
        write_json(output_dir / MANIFEST_JSON, manifest)

    print_summary(args=args, chain_summary=chain_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
