from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.research.live_like_vertical_slice_contract_v1 import (
    DecisionPreview,
    ExecutionPlanPreview,
    ShadowEvent,
    StrategyCandidate,
)
from src.research.market_observer_evidence_preview_v1 import (
    ActiveRegimeObservationLocator,
    MarketObserverEvidencePreview,
    MarketObserverEvidencePreviewAmbiguityError,
    MarketObserverEvidencePreviewMalformedTagsError,
    MarketObserverEvidencePreviewNoSourceError,
)
from src.research import run_live_like_shadow_chain_v1 as chain


MODULE_PATH = Path("src/research/run_live_like_shadow_chain_v1.py")
FIXED_CHAIN_RUN_ID = "20260707T120000Z"
FIXED_CHAIN_NOW = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
FIXED_CANDIDATE_CREATED_AT = "2026-07-07T11:22:33Z"


def _json_ready(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, default=chain.chain_json_default))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fixed_candidate(*, created_at_utc: str = FIXED_CANDIDATE_CREATED_AT) -> StrategyCandidate:
    return StrategyCandidate(
        strategy_candidate_id="cand-001",
        strategy_instance_id="near_intraday_retest_reclaim_v1",
        strategy_family="INTRADAY_RETEST_RECLAIM_V1",
        symbol="NEAR",
        venue="bitvavo",
        quote="EUR",
        horizon_bucket="INTRADAY",
        primary_timeframe="1h",
        entry_timeframe="15m",
        candidate_state="ENTRY_CANDIDATE",
        entry_state="READY",
        direction_pressure=0.72,
        exposure_delta_pressure=0.14,
        entry_quality_score=0.81,
        risk_severity_score=0.19,
        confidence_score=0.78,
        freshness_state="FRESH",
        created_at_utc=created_at_utc,
        source_context={"current_price": 5.25, "ticker_price": 5.25},
        safety_markers={"db_writes": 0, "order_submission": 0, "broker_writes": 0},
    )


def _fixed_decision() -> DecisionPreview:
    return DecisionPreview(
        strategy_candidate_id="cand-001",
        trading_account_id=None,
        decision_state="SHADOW_REVIEW",
        permission_state="PREVIEW_ONLY_NOT_PERMISSION",
        block_reasons=("SHADOW_MODE_NO_PERMISSION",),
        account_awareness="none",
        live_trading_enabled=False,
        broker_write_permission=False,
        notes="Preview-only decision fixture.",
    )


def _fixed_execution() -> ExecutionPlanPreview:
    return ExecutionPlanPreview(
        decision_preview_id="dec-001",
        execution_plan_state="PLAN_READY",
        execution_profile="PASSIVE_LIMIT_RETEST",
        side="BUY",
        symbol="NEAR",
        quote="EUR",
        max_notional_preview=100.0,
        limit_price_preview=5.10,
        ladder_steps_preview=({"level": 1, "limit_price": 5.1},),
        timeout_seconds=900,
        cancel_conditions=("STALE_SIGNAL",),
        mode="shadow",
        executor_enabled=False,
        no_order_submission=True,
    )


def _fixed_shadow() -> ShadowEvent:
    return ShadowEvent(
        strategy_instance_id="near_intraday_retest_reclaim_v1",
        candidate_state="ENTRY_CANDIDATE",
        decision_state="SHADOW_REVIEW",
        execution_plan_state="PLAN_READY",
        observed_price=5.25,
        event_ts_utc="2026-07-07T12:00:00Z",
        no_order_submitted=True,
    )


def _install_fixed_stage_stubs(
    monkeypatch: pytest.MonkeyPatch,
    case_root: Path,
    *,
    candidate_created_at_utc: str = FIXED_CANDIDATE_CREATED_AT,
) -> dict[str, Path]:
    candidate = _fixed_candidate(created_at_utc=candidate_created_at_utc)
    decision = _fixed_decision()
    execution = _fixed_execution()
    shadow = _fixed_shadow()

    stage_dirs = {
        "candidate": case_root / "candidate_stage",
        "decision": case_root / "decision_stage",
        "execution": case_root / "execution_stage",
        "shadow": case_root / "shadow_stage",
    }

    def run_candidate_stage(args: Any) -> tuple[Path, StrategyCandidate, dict[str, Any]]:
        output_dir = stage_dirs["candidate"]
        _write_json(output_dir / chain.candidate_runner.STRATEGY_CANDIDATE_JSON, asdict(candidate))
        _write_json(output_dir / chain.candidate_runner.MANIFEST_JSON, {"report": "candidate"})
        return output_dir, candidate, {"report": "candidate"}

    def run_decision_stage(args: Any, candidate_run_dir: Path) -> tuple[Path, DecisionPreview, dict[str, Any]]:
        output_dir = stage_dirs["decision"]
        _write_json(output_dir / chain.decision_runner.DECISION_PREVIEW_JSON, asdict(decision))
        _write_json(
            output_dir / chain.decision_runner.MANIFEST_JSON,
            {"source_candidate_run_dir": str(candidate_run_dir)},
        )
        return output_dir, decision, {"source_candidate_run_dir": str(candidate_run_dir)}

    def run_execution_plan_stage(
        args: Any,
        decision_run_dir: Path,
    ) -> tuple[Path, ExecutionPlanPreview, dict[str, Any]]:
        output_dir = stage_dirs["execution"]
        _write_json(output_dir / chain.execution_runner.EXECUTION_PLAN_JSON, asdict(execution))
        _write_json(
            output_dir / chain.execution_runner.MANIFEST_JSON,
            {"source_decision_run_dir": str(decision_run_dir)},
        )
        return output_dir, execution, {"source_decision_run_dir": str(decision_run_dir)}

    def run_shadow_event_stage(
        args: Any,
        candidate_run_dir: Path,
        decision_run_dir: Path,
        execution_plan_run_dir: Path,
    ) -> tuple[Path, ShadowEvent, dict[str, Any]]:
        output_dir = stage_dirs["shadow"]
        _write_json(output_dir / chain.shadow_runner.SHADOW_EVENT_JSON, asdict(shadow))
        _write_json(
            output_dir / chain.shadow_runner.MANIFEST_JSON,
            {
                "source_candidate_run_dir": str(candidate_run_dir),
                "source_decision_run_dir": str(decision_run_dir),
                "source_execution_plan_run_dir": str(execution_plan_run_dir),
            },
        )
        return output_dir, shadow, {"report": "shadow"}

    monkeypatch.setattr(chain, "run_candidate_stage", run_candidate_stage)
    monkeypatch.setattr(chain, "run_decision_stage", run_decision_stage)
    monkeypatch.setattr(chain, "run_execution_plan_stage", run_execution_plan_stage)
    monkeypatch.setattr(chain, "run_shadow_event_stage", run_shadow_event_stage)
    monkeypatch.setattr(chain.candidate_runner, "utc_now", lambda: FIXED_CHAIN_NOW)
    monkeypatch.setattr(chain.candidate_runner, "utc_run_id", lambda now_utc: FIXED_CHAIN_RUN_ID)
    return stage_dirs


class _FakeConnection:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


def _run_chain_case(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    case_name: str,
    cli_args: list[str],
    candidate_created_at_utc: str = FIXED_CANDIDATE_CREATED_AT,
    build_preview: Any = None,
    get_connection_impl: Any = None,
) -> dict[str, Any]:
    case_root = tmp_path / case_name
    stage_dirs = _install_fixed_stage_stubs(
        monkeypatch,
        case_root,
        candidate_created_at_utc=candidate_created_at_utc,
    )

    counts = {"get_connection": 0, "build_preview": 0}

    def wrapped_get_connection() -> Any:
        counts["get_connection"] += 1
        if get_connection_impl is None:
            return _FakeConnection()
        return get_connection_impl()

    def wrapped_build_preview(**kwargs: Any) -> Any:
        counts["build_preview"] += 1
        if build_preview is None:
            raise AssertionError("build_market_observer_evidence_preview should not have been called")
        return build_preview(**kwargs)

    monkeypatch.setattr(chain, "get_connection", wrapped_get_connection)
    monkeypatch.setattr(chain, "build_market_observer_evidence_preview", wrapped_build_preview)

    output_root = case_root / "chain_output"
    exit_code = chain.main([*cli_args, "--output-root", str(output_root), "--output", "json"])
    chain_dir = output_root / f"run_{FIXED_CHAIN_RUN_ID}"
    summary = json.loads((chain_dir / chain.CHAIN_SUMMARY_JSON).read_text(encoding="utf-8"))
    manifest = json.loads((chain_dir / chain.MANIFEST_JSON).read_text(encoding="utf-8"))
    sidecar_path = chain_dir / chain.MARKET_OBSERVER_EVIDENCE_PREVIEW_JSON
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8")) if sidecar_path.exists() else None
    return {
        "exit_code": exit_code,
        "summary": summary,
        "manifest": manifest,
        "sidecar": sidecar,
        "sidecar_path": sidecar_path,
        "chain_dir": chain_dir,
        "stage_dirs": stage_dirs,
        "counts": counts,
    }


def test_default_run_does_not_open_db_connection_or_invoke_evidence_preview_logic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _run_chain_case(
        monkeypatch,
        tmp_path,
        case_name="default_disabled",
        cli_args=[],
    )

    assert result["exit_code"] == 0
    assert result["counts"] == {"get_connection": 0, "build_preview": 0}
    assert result["summary"]["market_observer_evidence_preview_enabled"] is False
    assert result["summary"]["market_observer_evidence_preview_status"] == "DISABLED"
    assert result["summary"]["market_observer_db_reads"] == 0
    assert result["summary"]["market_observer_db_writes"] == 0
    assert result["summary"]["db_writes"] == 0
    assert result["sidecar"] is None
    assert not result["sidecar_path"].exists()


def test_enabled_available_sidecar_preserves_exact_preview_values_and_event_timestamp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_conn = _FakeConnection()
    captured_event_ts: dict[str, datetime] = {}
    preview = MarketObserverEvidencePreview(
        schema_version="1.0",
        requested_event_ts_utc=datetime(2026, 7, 7, 11, 22, 33, tzinfo=UTC),
        canonical_global_regime="GLOBAL_ROTATION_WINDOW",
        global_regime_version="1.1",
        canonical_asset_class="L1_L2",
        canonical_asset_class_regime="CLASS_LEADERSHIP",
        asset_class_regime_version="1.1",
        canonical_global_class_regime="GLOBAL_ROTATION_WINDOW|CLASS_LEADERSHIP",
        validation_status="H1_CONTEXT_VALIDATED",
        validated_hypothesis_tags=("H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT",),
        source_locator=ActiveRegimeObservationLocator(
            active_regime_observation_id=901,
            venue="bitvavo",
            interval_code="4h",
            asof_ts_utc=datetime(2026, 7, 7, 8, 0, 0, tzinfo=UTC),
            asset_class="L1_L2",
            global_regime_version="1.1",
            asset_class_regime_version="1.1",
            source_candle_ts_utc=datetime(2026, 7, 7, 8, 0, 0, tzinfo=UTC),
        ),
        warnings=(),
    )
    expected_preview = _json_ready(asdict(preview))

    def get_connection_impl() -> _FakeConnection:
        return fake_conn

    def build_preview(**kwargs: Any) -> MarketObserverEvidencePreview:
        captured_event_ts["value"] = kwargs["event_ts_utc"]
        assert kwargs["venue"] == "bitvavo"
        assert kwargs["interval_code"] == "4h"
        assert kwargs["asset_class"] == "L1_L2"
        return preview

    result = _run_chain_case(
        monkeypatch,
        tmp_path,
        case_name="available",
        cli_args=[
            "--include-market-observer-evidence-preview",
            "--canonical-asset-class",
            "L1_L2",
            "--canonical-regime-interval",
            "4h",
        ],
        build_preview=build_preview,
        get_connection_impl=get_connection_impl,
    )

    assert result["exit_code"] == 0
    assert result["counts"] == {"get_connection": 1, "build_preview": 1}
    assert fake_conn.closed == 1
    assert captured_event_ts["value"] == datetime(2026, 7, 7, 11, 22, 33, tzinfo=UTC)
    assert result["summary"]["market_observer_evidence_preview_status"] == "AVAILABLE"
    assert result["summary"]["market_observer_db_reads"] == 1
    assert result["summary"]["market_observer_db_writes"] == 0
    assert result["sidecar"] is not None
    assert result["sidecar"]["status"] == "AVAILABLE"
    assert result["sidecar"]["preview"] == expected_preview
    assert result["sidecar"]["source_locator"] == expected_preview["source_locator"]
    assert result["sidecar"]["preview"]["requested_event_ts_utc"] == FIXED_CANDIDATE_CREATED_AT
    assert result["summary"]["market_observer_evidence_preview_source_locator"] == expected_preview["source_locator"]
    assert result["summary"]["market_observer_evidence_preview"]["requested_event_ts_utc"] == FIXED_CANDIDATE_CREATED_AT
    assert result["summary"]["market_observer_evidence_preview_path"] == str(result["sidecar_path"])
    assert result["manifest"]["output_paths"]["market_observer_evidence_preview_json"] == str(result["sidecar_path"])
    assert result["summary"]["db_writes"] == 0
    assert result["summary"]["broker_writes"] == 0
    assert result["summary"]["order_submission"] == 0
    assert result["summary"]["no_order_submitted"] is True


@pytest.mark.parametrize(
    ("case_name", "exception_factory", "expected_status"),
    [
        ("no_source", MarketObserverEvidencePreviewNoSourceError, "NO_SOURCE"),
        ("ambiguous", MarketObserverEvidencePreviewAmbiguityError, "AMBIGUOUS"),
        ("malformed_tags", MarketObserverEvidencePreviewMalformedTagsError, "MALFORMED_TAGS"),
        ("db_read_error", RuntimeError, "DB_READ_ERROR"),
    ],
)
def test_unavailable_evidence_statuses_continue_chain_and_emit_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case_name: str,
    exception_factory: Any,
    expected_status: str,
) -> None:
    def build_preview(**kwargs: Any) -> Any:
        raise exception_factory("fixture error")

    result = _run_chain_case(
        monkeypatch,
        tmp_path,
        case_name=case_name,
        cli_args=[
            "--include-market-observer-evidence-preview",
            "--canonical-asset-class",
            "L1_L2",
        ],
        build_preview=build_preview,
    )

    assert result["exit_code"] == 0
    assert result["summary"]["candidate_state"] == "ENTRY_CANDIDATE"
    assert result["summary"]["decision_state"] == "SHADOW_REVIEW"
    assert result["summary"]["execution_plan_state"] == "PLAN_READY"
    assert result["summary"]["market_observer_evidence_preview_status"] == expected_status
    assert result["summary"]["market_observer_db_reads"] == 1
    assert result["summary"]["market_observer_db_writes"] == 0
    assert result["sidecar"] is not None
    assert result["sidecar"]["status"] == expected_status
    assert result["sidecar"]["requested_inputs"]["strategy_candidate_created_at_utc"] == FIXED_CANDIDATE_CREATED_AT
    assert "preview" not in result["sidecar"]


def test_malformed_candidate_timestamp_records_unexpected_error_without_db_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _run_chain_case(
        monkeypatch,
        tmp_path,
        case_name="malformed_timestamp",
        cli_args=[
            "--include-market-observer-evidence-preview",
            "--canonical-asset-class",
            "L1_L2",
        ],
        candidate_created_at_utc="2026-07-07T11:22:33+02:00",
    )

    assert result["exit_code"] == 0
    assert result["counts"] == {"get_connection": 0, "build_preview": 0}
    assert result["summary"]["market_observer_evidence_preview_status"] == "UNEXPECTED_ERROR"
    assert result["summary"]["market_observer_db_reads"] == 0
    assert result["sidecar"] is not None
    assert result["sidecar"]["status"] == "UNEXPECTED_ERROR"
    assert result["sidecar"]["exception_class"] == "ValueError"


def test_enabled_without_canonical_asset_class_fails_before_chain_execution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_run_candidate_stage(args: Any) -> Any:
        raise AssertionError("chain stages must not run when configuration is invalid")

    monkeypatch.setattr(chain, "run_candidate_stage", fail_run_candidate_stage)

    with pytest.raises(SystemExit) as excinfo:
        chain.main(["--include-market-observer-evidence-preview"])

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "--canonical-asset-class is required" in captured.err


def test_chain_state_artifacts_remain_unchanged_between_available_and_unavailable_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    available_conn = _FakeConnection()
    preview = MarketObserverEvidencePreview(
        schema_version="1.0",
        requested_event_ts_utc=datetime(2026, 7, 7, 11, 22, 33, tzinfo=UTC),
        canonical_global_regime="GLOBAL_ROTATION_WINDOW",
        global_regime_version="1.1",
        canonical_asset_class="L1_L2",
        canonical_asset_class_regime="CLASS_LEADERSHIP",
        asset_class_regime_version="1.1",
        canonical_global_class_regime="GLOBAL_ROTATION_WINDOW|CLASS_LEADERSHIP",
        validation_status="H1_CONTEXT_VALIDATED",
        validated_hypothesis_tags=("H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT",),
        source_locator=ActiveRegimeObservationLocator(
            active_regime_observation_id=901,
            venue="bitvavo",
            interval_code="4h",
            asof_ts_utc=datetime(2026, 7, 7, 8, 0, 0, tzinfo=UTC),
            asset_class="L1_L2",
            global_regime_version="1.1",
            asset_class_regime_version="1.1",
            source_candle_ts_utc=datetime(2026, 7, 7, 8, 0, 0, tzinfo=UTC),
        ),
        warnings=(),
    )

    available_result = _run_chain_case(
        monkeypatch,
        tmp_path,
        case_name="state_available",
        cli_args=[
            "--include-market-observer-evidence-preview",
            "--canonical-asset-class",
            "L1_L2",
        ],
        build_preview=lambda **kwargs: preview,
        get_connection_impl=lambda: available_conn,
    )

    unavailable_result = _run_chain_case(
        monkeypatch,
        tmp_path,
        case_name="state_unavailable",
        cli_args=[
            "--include-market-observer-evidence-preview",
            "--canonical-asset-class",
            "L1_L2",
        ],
        build_preview=lambda **kwargs: (_ for _ in ()).throw(
            MarketObserverEvidencePreviewNoSourceError("missing")
        ),
    )

    artifact_names = (
        ("candidate", chain.candidate_runner.STRATEGY_CANDIDATE_JSON),
        ("decision", chain.decision_runner.DECISION_PREVIEW_JSON),
        ("execution", chain.execution_runner.EXECUTION_PLAN_JSON),
        ("shadow", chain.shadow_runner.SHADOW_EVENT_JSON),
    )
    for stage_name, artifact_name in artifact_names:
        available_artifact = (
            available_result["stage_dirs"][stage_name] / artifact_name
        ).read_text(encoding="utf-8")
        unavailable_artifact = (
            unavailable_result["stage_dirs"][stage_name] / artifact_name
        ).read_text(encoding="utf-8")
        assert available_artifact == unavailable_artifact

    assert available_result["summary"]["market_observer_evidence_preview_status"] == "AVAILABLE"
    assert unavailable_result["summary"]["market_observer_evidence_preview_status"] == "NO_SOURCE"
    assert available_result["summary"]["candidate_state"] == unavailable_result["summary"]["candidate_state"]
    assert available_result["summary"]["decision_state"] == unavailable_result["summary"]["decision_state"]
    assert (
        available_result["summary"]["execution_plan_state"]
        == unavailable_result["summary"]["execution_plan_state"]
    )


def test_boundary_scan_blocks_forbidden_sidecar_imports_and_write_sql() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    upper_source = source.upper()
    import_lines = [
        line.strip()
        for line in source.splitlines()
        if line.startswith("from ") or line.startswith("import ")
    ]

    forbidden_import_fragments = (
        "src.executor",
        "src.execution_planner",
        "src.account",
        "src.portfolio",
        "broker",
        "dashboard",
        "systemd",
        "odroid",
    )
    for forbidden in forbidden_import_fragments:
        assert all(forbidden not in line for line in import_lines)

    forbidden_write_sql = (
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "REPLACE ",
        "CREATE TABLE",
        "ALTER TABLE",
        "DROP TABLE",
        "TRUNCATE ",
        "COMMIT(",
        ".COMMIT(",
    )
    for forbidden in forbidden_write_sql:
        assert forbidden not in upper_source
