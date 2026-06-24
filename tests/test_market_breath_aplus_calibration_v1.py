from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path

from src.research.market_breath_classifier_v1 import (
    DEFAULT_MARKET_BREATH_THRESHOLD_PROFILE_V1,
    classify_market_breath_phase_state_v1,
)
from src.research.run_market_breath_aplus_calibration_v1 import (
    DEFAULT_LOOKBACK_CANDLES,
    FULL_CANONICAL_REPORT_TIMESTAMPS,
    SEARCH_MODE,
    STATUS_BASELINE_RETAINED,
    STATUS_INSUFFICIENT_TRAINING_DATA,
    WARNING_TRAINING_SAMPLE_SMALL,
    TeacherReportSource,
    baseline_profile_spec,
    build_public_summary_payload,
    build_leave_one_report_out_folds,
    build_single_axis_profiles,
    compact_profile_result,
    discover_teacher_reports,
    normalize_teacher_phase,
    rank_profile_results,
    select_result_status,
    teacher_report_manifest_row,
    teacher_row_stats,
)


MODULE_PATH = Path("src/research/run_market_breath_aplus_calibration_v1.py")

_CANONICAL_TS_LIST = sorted(FULL_CANONICAL_REPORT_TIMESTAMPS)


def _write_table1_jsonl(path: Path, prediction_ts_utc: str, row_count: int = 40) -> None:
    rows: list[dict] = [{"prediction_ts_utc": prediction_ts_utc, "token": "BTC"}]
    for i in range(1, row_count):
        rows.append({"token": f"TOK{i:02d}"})
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _make_teacher_report(ts_str: str) -> TeacherReportSource:
    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    safe = ts_str.replace(":", "").replace("-", "").replace("Z", "")
    return TeacherReportSource(
        report_id=safe,
        prediction_ts_utc=ts,
        artifact_path=f"data/test_{safe}.jsonl",
        source_file_path=f"data/test_{safe}.jsonl",
        source_kind="normalized_primary",
        row_count=41,
        artifact_hash_sha256="abc123",
        source_hash_sha256=None,
        rows=tuple(),
    )


def test_teacher_label_mappings_cover_required_cases():
    assert normalize_teacher_phase({"phase": "reset", "field": "compression", "strategic_bias": "avoid"})[0] == "COLLAPSE_RESET"
    assert normalize_teacher_phase({"phase": "late", "field": "expansion", "strategic_bias": "continuation"})[0] == "OVERBREATH_EXTENSION"
    assert normalize_teacher_phase({"phase": "forming", "field": "expansion", "strategic_bias": "continuation"})[0] == "EXHALE_EXPANSION"
    assert normalize_teacher_phase({"phase": "forming", "field": "compression", "strategic_bias": "accumulation"})[0] == "INHALE_ACCUMULATION"
    assert normalize_teacher_phase({"phase": "forming", "field": "compression", "strategic_bias": "avoid"})[0] == "HOLD_COMPRESSION"
    assert normalize_teacher_phase({"phase": "confirmed", "field": "transition", "strategic_bias": "neutral"})[0] == "NEUTRAL_TRANSITION"


def test_unmapped_teacher_labels_are_explicit():
    teacher_phase, reason = normalize_teacher_phase({"phase": "confirmed", "field": "unknown", "strategic_bias": "neutral"})
    assert teacher_phase == "UNMAPPED"
    assert "no provisional" in reason


def test_baseline_profile_reproduces_shared_classifier_behavior():
    profile = baseline_profile_spec().profile
    features = dict(
        compression=50.0,
        expansion=20.0,
        momentum=25.0,
        reversal_pressure=0.0,
        relative_strength=10.0,
    )
    assert classify_market_breath_phase_state_v1(**features, profile=profile) == classify_market_breath_phase_state_v1(**features, profile=DEFAULT_MARKET_BREATH_THRESHOLD_PROFILE_V1)


def test_single_axis_candidate_generation_only():
    specs = build_single_axis_profiles()
    baseline = specs[0]
    assert baseline.is_baseline is True
    assert SEARCH_MODE == "SINGLE_AXIS"
    diffs = []
    baseline_values = baseline.profile
    for spec in specs[1:]:
        changed = [
            field
            for field in baseline_values.__dataclass_fields__
            if getattr(spec.profile, field) != getattr(baseline_values, field)
        ]
        diffs.append(changed)
        assert len(changed) == 1
    assert diffs


def test_deterministic_candidate_ranking():
    ranked = rank_profile_results(
        [
            {
                "profile_id": "B",
                "mean_fold_score": 0.5,
                "worst_report_score": 0.2,
                "macro_f1": 0.6,
                "exact_raw_phase_match_rate": 0.4,
                "labeled_row_coverage": 0.9,
                "is_baseline": False,
            },
            {
                "profile_id": "A",
                "mean_fold_score": 0.5,
                "worst_report_score": 0.2,
                "macro_f1": 0.6,
                "exact_raw_phase_match_rate": 0.4,
                "labeled_row_coverage": 0.9,
                "is_baseline": False,
            },
        ]
    )
    assert [row["profile_id"] for row in ranked] == ["B", "A"]


def test_leave_one_report_out_separation():
    folds = build_leave_one_report_out_folds(["r1", "r2", "r3"])
    assert len(folds) == 3
    assert folds[0]["holdout_report_id"] == "r1"
    assert folds[0]["training_report_ids"] == ["r2", "r3"]


def test_baseline_fallback_when_no_candidate_beats_it():
    baseline = {
        "profile_id": "BASELINE",
        "is_baseline": True,
        "labeled_row_coverage": 0.8,
        "mean_fold_score": 0.5,
        "worst_report_score": 0.4,
    }
    weaker = {
        "profile_id": "candidate",
        "is_baseline": False,
        "labeled_row_coverage": 0.8,
        "mean_fold_score": 0.5,
        "worst_report_score": 0.39,
    }
    status, selected, warnings = select_result_status(
        ranked_results=[baseline, weaker],
        teacher_report_count=5,
        eligible_report_ids=["r1", "r2", "r3"],
    )
    assert status == STATUS_BASELINE_RETAINED
    assert selected["profile_id"] == "BASELINE"
    assert WARNING_TRAINING_SAMPLE_SMALL in warnings


def test_insufficient_training_data_when_fewer_than_two_eligible_reports():
    baseline = {
        "profile_id": "BASELINE",
        "is_baseline": True,
        "labeled_row_coverage": 0.8,
        "mean_fold_score": 0.5,
        "worst_report_score": 0.4,
    }
    status, selected, warnings = select_result_status(
        ranked_results=[baseline],
        teacher_report_count=5,
        eligible_report_ids=["r1"],
    )
    assert status == STATUS_INSUFFICIENT_TRAINING_DATA
    assert selected["profile_id"] == "BASELINE"
    assert WARNING_TRAINING_SAMPLE_SMALL in warnings


def test_v1_teacher_report_filter_keeps_only_five_full_reports(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    norm_dir = tmp_path / "norm"
    norm_dir.mkdir()
    for ts in _CANONICAL_TS_LIST:
        safe = ts.replace(":", "").replace("-", "").replace("Z", "")
        _write_table1_jsonl(norm_dir / f"table1_normalized_{safe}.jsonl", ts)
    _write_table1_jsonl(norm_dir / "table1_normalized_prime17_extra.jsonl", "2026-01-01T00:00:00Z")
    _write_table1_jsonl(norm_dir / "table1_normalized_partial_extra.jsonl", "2026-01-02T00:00:00Z")
    reports, excluded = discover_teacher_reports(raw_dir=raw_dir, normalized_dirs=[norm_dir])
    assert len(reports) == 5
    assert {
        r.prediction_ts_utc.isoformat().replace("+00:00", "Z") for r in reports
    } == FULL_CANONICAL_REPORT_TIMESTAMPS
    reasons = {row["reason"] for row in excluded}
    assert "PRIME17_EXCLUDED_FROM_V1_TRAINING" in reasons
    assert "PARTIAL_OR_SUBSET_EXCLUDED_FROM_V1_TRAINING" in reasons


def test_prime17_with_canonical_timestamp_still_excluded(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    norm_dir = tmp_path / "norm"
    norm_dir.mkdir()
    for ts in _CANONICAL_TS_LIST[:4]:
        safe = ts.replace(":", "").replace("-", "").replace("Z", "")
        _write_table1_jsonl(norm_dir / f"table1_normalized_{safe}.jsonl", ts)
    ts5 = _CANONICAL_TS_LIST[4]
    _write_table1_jsonl(norm_dir / "table1_normalized_prime17_ts5.jsonl", ts5)
    reports, excluded = discover_teacher_reports(raw_dir=raw_dir, normalized_dirs=[norm_dir])
    assert len(reports) == 4
    prime17_ex = [r for r in excluded if r["reason"] == "PRIME17_EXCLUDED_FROM_V1_TRAINING"]
    assert len(prime17_ex) == 1
    assert prime17_ex[0]["prediction_ts_utc"] == ts5


def test_no_future_candle_enforcement_plan_uses_report_timestamp_only():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "Future candle leaked into calibration observation set" in source
    assert "resolved_candle_ts_utc" in source


def test_static_boundary_guard_against_forbidden_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    joined = "\n".join(imports)
    for forbidden in ("decision_gate", "execution_planner", "executor", "broker", "reporting", "dashboard", "account", "order", "ui"):
        assert forbidden not in joined


def test_existing_classifier_is_reused_rather_than_copied():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "from src.research.market_breath_classifier_v1 import" in source
    assert "classify_market_breath_phase_state_v1(" in source
    assert "market_breath.build_base_observation(" in source
    assert "market_breath.add_breadth_and_scores(" in source
    assert "def phase_and_state(" not in source


def test_baseline_constant_manifest_plan_is_present():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "minimum_candle_count" in source
    assert str(DEFAULT_LOOKBACK_CANDLES) in source


def test_training_sample_small_is_based_on_teacher_report_count():
    baseline = {
        "profile_id": "BASELINE",
        "is_baseline": True,
        "labeled_row_coverage": 0.8,
        "mean_fold_score": 0.5,
        "worst_report_score": 0.4,
    }
    status, selected, warnings = select_result_status(
        ranked_results=[baseline],
        teacher_report_count=5,
        eligible_report_ids=["r1", "r2"],
    )
    assert status == STATUS_BASELINE_RETAINED
    assert selected["profile_id"] == "BASELINE"
    assert WARNING_TRAINING_SAMPLE_SMALL in warnings


def test_teacher_report_manifest_rows_are_json_serializable():
    report = _make_teacher_report(_CANONICAL_TS_LIST[0])
    row = teacher_report_manifest_row(report)
    assert row["prediction_ts_utc"].endswith("Z")
    assert "row_count" in row


def test_public_summary_payload_includes_required_cli_fields():
    reports = [_make_teacher_report(ts) for ts in _CANONICAL_TS_LIST]
    hydrated_rows = [
        {"teacher_phase": "EXHALE_EXPANSION", "input_status": "OK"},
        {"teacher_phase": "UNMAPPED", "input_status": "OK"},
        {"teacher_phase": "HOLD_COMPRESSION", "input_status": "INSUFFICIENT_DATA"},
    ]
    baseline_result = {
        "profile_id": "BASELINE",
        "is_baseline": True,
        "mean_fold_score": 0.5,
        "worst_report_score": 0.4,
        "exact_raw_phase_match_rate": 0.3,
        "macro_f1": 0.2,
    }
    best_candidate_result = {
        "profile_id": "candidate",
        "is_baseline": False,
        "mean_fold_score": 0.6,
        "worst_report_score": 0.5,
        "exact_raw_phase_match_rate": 0.4,
        "macro_f1": 0.3,
    }
    payload = build_public_summary_payload(
        teacher_reports=reports,
        excluded_reports=[],
        hydrated_rows=hydrated_rows,
        folds=build_leave_one_report_out_folds(["r1", "r2", "r3", "r4", "r5"]),
        result_status=STATUS_BASELINE_RETAINED,
        warnings=[WARNING_TRAINING_SAMPLE_SMALL],
        baseline_result=baseline_result,
        best_candidate_result=best_candidate_result,
        selected_profile=baseline_result,
        profile_count=39,
    )
    assert payload["result_status"] == STATUS_BASELINE_RETAINED
    assert payload["warnings"] == [WARNING_TRAINING_SAMPLE_SMALL]
    assert payload["teacher_report_count"] == 5
    assert payload["approved_teacher_report_timestamps"] == sorted(FULL_CANONICAL_REPORT_TIMESTAMPS)
    assert payload["teacher_row_count"] == 3
    assert payload["mapped_row_count"] == 2
    assert payload["unmapped_row_count"] == 1
    assert payload["insufficient_candle_row_count"] == 1
    assert payload["fold_count"] == 5
    assert payload["best_candidate_result"]["profile_id"] == "candidate"
    assert payload["selected_result"]["profile_id"] == "BASELINE"
    assert payload["runtime_profile_written"] is False
    assert payload["runtime_profile_selected"] is False


def test_teacher_row_stats_counts_mapped_unmapped_and_insufficient():
    stats = teacher_row_stats(
        [
            {"teacher_phase": "EXHALE_EXPANSION", "input_status": "OK"},
            {"teacher_phase": "UNMAPPED", "input_status": "OK"},
            {"teacher_phase": "HOLD_COMPRESSION", "input_status": "INSUFFICIENT_DATA"},
        ]
    )
    assert stats == {
        "teacher_row_count": 3,
        "mapped_row_count": 2,
        "unmapped_row_count": 1,
        "insufficient_candle_row_count": 1,
    }


def test_compact_profile_result_returns_public_metric_subset():
    compact = compact_profile_result(
        {
            "profile_id": "candidate",
            "mean_fold_score": 0.6,
            "worst_report_score": 0.5,
            "exact_raw_phase_match_rate": 0.4,
            "macro_f1": 0.3,
            "extra": "ignored",
        }
    )
    assert compact == {
        "profile_id": "candidate",
        "mean_fold_score": 0.6,
        "worst_report_score": 0.5,
        "exact_raw_phase_match_rate": 0.4,
        "macro_f1": 0.3,
    }
