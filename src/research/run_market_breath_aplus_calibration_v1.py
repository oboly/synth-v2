from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from src.common.db import get_connection
from src.research import run_market_breath_analysis_v1 as market_breath
from src.research.load_aplus_reports_to_db_v1 import collect_reports, normalized_table1_report
from src.research.market_breath_classifier_v1 import (
    DEFAULT_MARKET_BREATH_THRESHOLD_PROFILE_V1,
    MarketBreathThresholdProfileV1,
    classify_market_breath_phase_state_v1,
)


REPORT_NAME = "market_breath_aplus_calibration_v1"
REPORT_VERSION = "1.0"

DEFAULT_RAW_DIR = Path("data/aplus_raw")
DEFAULT_NORMALIZED_DIRS = (
    Path("data/research/aplus_canonical_table1_v1"),
    Path("data/research/aplus_table1_only_normalized_v1"),
)
DEFAULT_OUTPUT_DIR = Path("data/research/market_breath_aplus_calibration_v1")
DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL = "4h"
DEFAULT_LOOKBACK_CANDLES = 120
FULL_SNAPSHOT_MIN_ROWS = 40
MIN_CANDLE_COUNT_V1 = 24
ATR_WINDOW_V1 = 14
ATR_BASELINE_WINDOW_V1 = 60
RANGE_BASELINE_WINDOW_V1 = 30
SIGNED_SCORE_BOUNDS_V1 = {"min": -100.0, "max": 100.0}
CLAMPED_SCORE_BOUNDS_V1 = {"min": 0.0, "max": 100.0}

STATUS_BASELINE_RETAINED = "BASELINE_RETAINED"
STATUS_CALIBRATION_CANDIDATE = "CALIBRATION_CANDIDATE"
STATUS_INSUFFICIENT_TRAINING_DATA = "INSUFFICIENT_TRAINING_DATA"
WARNING_TRAINING_SAMPLE_SMALL = "TRAINING_SAMPLE_SMALL"
SEARCH_MODE = "SINGLE_AXIS"

SCORABLE_PHASES = (
    "COLLAPSE_RESET",
    "OVERBREATH_EXTENSION",
    "EXHALE_EXPANSION",
    "HOLD_COMPRESSION",
    "INHALE_ACCUMULATION",
    "NEUTRAL_TRANSITION",
)

FULL_CANONICAL_REPORT_TIMESTAMPS = {
    "2026-05-13T19:15:00Z",
    "2026-05-14T13:15:00Z",
    "2026-05-15T12:44:48Z",
    "2026-05-16T01:15:11Z",
    "2026-05-16T12:09:00Z",
}


@dataclass(frozen=True)
class CandidateProfileSpec:
    profile_id: str
    profile: MarketBreathThresholdProfileV1
    axis_name: str
    axis_value: float | None
    is_baseline: bool = False


@dataclass(frozen=True)
class TeacherReportSource:
    report_id: str
    prediction_ts_utc: datetime
    artifact_path: str
    source_file_path: str
    source_kind: str
    row_count: int
    artifact_hash_sha256: str
    source_hash_sha256: str | None
    rows: tuple[dict[str, Any], ...]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Research-only offline calibration of Market Breath against A+ Table 1 "
            "teacher labels using leave-one-report-out validation."
        )
    )
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument(
        "--normalized-dir",
        action="append",
        default=None,
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--lookback-candles", type=int, default=DEFAULT_LOOKBACK_CANDLES)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    args = parser.parse_args(argv)
    if args.normalized_dir is None:
        args.normalized_dir = [str(path) for path in DEFAULT_NORMALIZED_DIRS]
    return args


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profile_axis_values() -> dict[str, tuple[float, ...]]:
    return {
        "collapse_reset_momentum_lt": (-30.0, -25.0, -20.0),
        "collapse_reset_reversal_min": (40.0, 45.0, 50.0),
        "overbreath_expansion_min": (60.0, 65.0, 70.0),
        "overbreath_momentum_min": (50.0, 55.0, 60.0),
        "overbreath_reversal_min": (40.0, 45.0, 50.0),
        "exhale_expansion_min": (50.0, 55.0, 60.0),
        "exhale_momentum_gt": (15.0, 20.0, 25.0),
        "exhale_relative_strength_gt": (0.0, 5.0, 10.0),
        "exhale_confirmed_expansion_min": (65.0, 70.0, 75.0),
        "exhale_confirmed_momentum_min": (30.0, 35.0, 40.0),
        "hold_compression_min": (55.0, 60.0, 65.0),
        "hold_expansion_lt": (30.0, 35.0, 40.0),
        "hold_abs_momentum_max": (15.0, 20.0, 25.0),
        "hold_confirmed_compression_min": (70.0, 75.0, 80.0),
        "inhale_compression_min": (40.0, 45.0, 50.0),
        "inhale_momentum_min": (0.0, 5.0, 10.0),
        "inhale_momentum_max": (30.0, 35.0, 40.0),
        "inhale_relative_strength_gt": (0.0, 5.0, 10.0),
        "inhale_confirmed_momentum_min": (15.0, 20.0, 25.0),
    }


def baseline_profile_spec() -> CandidateProfileSpec:
    return CandidateProfileSpec(
        profile_id="BASELINE",
        profile=DEFAULT_MARKET_BREATH_THRESHOLD_PROFILE_V1,
        axis_name="BASELINE",
        axis_value=None,
        is_baseline=True,
    )


def build_single_axis_profiles() -> list[CandidateProfileSpec]:
    baseline = baseline_profile_spec()
    specs = [baseline]
    for axis_name, values in profile_axis_values().items():
        baseline_value = getattr(baseline.profile, axis_name)
        for value in values:
            if value == baseline_value:
                continue
            profile = replace(baseline.profile, **{axis_name: value})
            specs.append(
                CandidateProfileSpec(
                    profile_id=f"{axis_name}__{value:+g}".replace(".", "p").replace("+", "plus").replace("-", "minus"),
                    profile=profile,
                    axis_name=axis_name,
                    axis_value=value,
                    is_baseline=False,
                )
            )
    return specs


def normalized_artifact_index(normalized_dirs: list[Path]) -> dict[str, Path]:
    preferred: dict[str, Path] = {}
    for directory in normalized_dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.jsonl")):
            report = normalized_table1_report(path)
            if report is None:
                continue
            report_ts = market_breath.fmt_ts(report.prediction_ts_utc)
            current = preferred.get(report_ts)
            if current is None:
                preferred[report_ts] = path
                continue
            if path.name.startswith("table1_normalized_"):
                preferred[report_ts] = path
    return preferred


def report_id_for_ts(value: datetime) -> str:
    return market_breath.fmt_ts(value).replace(":", "").replace("-", "")


def discover_teacher_reports(
    *,
    raw_dir: Path,
    normalized_dirs: list[Path],
) -> tuple[list[TeacherReportSource], list[dict[str, Any]]]:
    reports, _skipped = collect_reports(raw_dir, normalized_dirs)
    artifact_by_ts = normalized_artifact_index(normalized_dirs)
    selected: list[TeacherReportSource] = []
    excluded: list[dict[str, Any]] = []

    for report in reports:
        if report.report_type != "TABLE1_BREATHLINE_VECTOR":
            continue
        report_ts = report.prediction_ts_utc
        report_ts_key = market_breath.fmt_ts(report_ts)
        artifact_path = artifact_by_ts.get(report_ts_key, Path(report.source_file_path))
        source_path = Path(report.source_file_path)
        row_count = len(report.rows)
        source_name = source_path.name.lower()

        if "prime17" in source_name:
            excluded.append(
                {
                    "prediction_ts_utc": report_ts_key,
                    "source_file_path": report.source_file_path,
                    "artifact_path": artifact_path.as_posix(),
                    "row_count": row_count,
                    "reason": "PRIME17_EXCLUDED_FROM_V1_TRAINING",
                }
            )
            continue

        if "partial" in source_name or "subset" in source_name:
            excluded.append(
                {
                    "prediction_ts_utc": report_ts_key,
                    "source_file_path": report.source_file_path,
                    "artifact_path": artifact_path.as_posix(),
                    "row_count": row_count,
                    "reason": "PARTIAL_OR_SUBSET_EXCLUDED_FROM_V1_TRAINING",
                }
            )
            continue

        if report_ts_key not in FULL_CANONICAL_REPORT_TIMESTAMPS:
            excluded.append(
                {
                    "prediction_ts_utc": report_ts_key,
                    "source_file_path": report.source_file_path,
                    "artifact_path": artifact_path.as_posix(),
                    "row_count": row_count,
                    "reason": "NOT_IN_V1_FULL_CANONICAL_REPORT_SET",
                }
            )
            continue

        if row_count < FULL_SNAPSHOT_MIN_ROWS:
            excluded.append(
                {
                    "prediction_ts_utc": report_ts_key,
                    "source_file_path": report.source_file_path,
                    "artifact_path": artifact_path.as_posix(),
                    "row_count": row_count,
                    "reason": "NON_FULL_REPORT_EXCLUDED_FROM_V1_TRAINING",
                }
            )
            continue

        selected.append(
            TeacherReportSource(
                report_id=report_id_for_ts(report_ts),
                prediction_ts_utc=report_ts,
                artifact_path=artifact_path.as_posix(),
                source_file_path=report.source_file_path,
                source_kind="normalized_primary" if artifact_path.suffix.lower() == ".jsonl" else "raw_fallback",
                row_count=row_count,
                artifact_hash_sha256=sha256_path(artifact_path),
                source_hash_sha256=sha256_path(source_path) if source_path.exists() else None,
                rows=tuple(dict(row) for row in report.rows),
            )
        )

    selected.sort(key=lambda item: item.prediction_ts_utc)
    return selected, excluded


def teacher_report_manifest_row(report: TeacherReportSource) -> dict[str, Any]:
    return {
        "report_id": report.report_id,
        "prediction_ts_utc": market_breath.fmt_ts(report.prediction_ts_utc),
        "artifact_path": report.artifact_path,
        "source_file_path": report.source_file_path,
        "source_kind": report.source_kind,
        "row_count": report.row_count,
        "artifact_hash_sha256": report.artifact_hash_sha256,
        "source_hash_sha256": report.source_hash_sha256,
    }


def row_value(row: dict[str, Any], key: str) -> str:
    raw = row.get(key)
    if raw is None:
        raw = row.get(f"table1_{key}")
    return str(raw or "").strip().lower()


def normalize_teacher_phase(row: dict[str, Any]) -> tuple[str, str]:
    phase = row_value(row, "phase")
    field = row_value(row, "field")
    strategic_bias = row_value(row, "strategic_bias")

    if phase == "reset":
        return "COLLAPSE_RESET", "phase=reset"
    if field == "expansion" and phase in {"late", "exhaustion"}:
        return "OVERBREATH_EXTENSION", "field=expansion and phase in {late,exhaustion}"
    if field == "expansion":
        return "EXHALE_EXPANSION", "field=expansion otherwise"
    if field == "compression" and strategic_bias == "accumulation":
        return "INHALE_ACCUMULATION", "field=compression and strategic_bias=accumulation"
    if field == "compression":
        return "HOLD_COMPRESSION", "field=compression otherwise"
    if field in {"transition", "neutral"}:
        return "NEUTRAL_TRANSITION", "field in {transition,neutral}"
    return "UNMAPPED", "no provisional v1 mapping"


def resolve_report_observations(
    conn: Any,
    *,
    report: TeacherReportSource,
    venue: str,
    interval: str,
    lookback_candles: int,
    asset_by_symbol: dict[str, market_breath.Asset],
) -> dict[str, dict[str, Any]]:
    btc_asset = asset_by_symbol.get("BTC")
    if btc_asset is None:
        raise RuntimeError("BTC asset not available; cannot resolve market breath observations")

    report_symbols = sorted({str(row.get("token") or "").strip().upper() for row in report.rows if row.get("token")})
    selected_assets = [asset_by_symbol[symbol] for symbol in report_symbols if symbol in asset_by_symbol]
    candle_assets = list(selected_assets)
    if all(asset.asset_id != btc_asset.asset_id for asset in candle_assets):
        candle_assets.append(btc_asset)

    candles_by_asset = market_breath.fetch_candles(
        conn,
        assets=candle_assets,
        venue=venue,
        interval_code=interval,
        asof_ts=report.prediction_ts_utc.replace(tzinfo=None),
        lookback_candles=lookback_candles,
    )

    report_naive_ts = report.prediction_ts_utc.replace(tzinfo=None)
    for candles in candles_by_asset.values():
        for candle in candles:
            if candle.close_ts_utc > report_naive_ts:
                raise ValueError("Future candle leaked into calibration observation set")

    btc_candles = candles_by_asset.get(btc_asset.asset_id, [])
    btc_r6 = market_breath.safe_return(btc_candles, 6) if btc_candles else None
    btc_r12 = market_breath.safe_return(btc_candles, 12) if btc_candles else None
    btc_resolved_ts = market_breath.fmt_ts(btc_candles[-1].close_ts_utc) if btc_candles else None

    base_rows = [
        market_breath.build_base_observation(
            asset=asset,
            candles=candles_by_asset.get(asset.asset_id, []),
            venue=venue,
            interval_code=interval,
            lookback_candles=lookback_candles,
            asof_ts=report_naive_ts,
            btc_r6=btc_r6,
            btc_r12=btc_r12,
        )
        for asset in selected_assets
    ]
    scored_rows = market_breath.add_breadth_and_scores(base_rows, lookback_candles)
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in scored_rows:
        symbol = str(row.get("symbol") or "").upper()
        asset = asset_by_symbol.get(symbol)
        symbol_candles = candles_by_asset.get(asset.asset_id, []) if asset else []
        hydrated = dict(row)
        hydrated["resolved_candle_ts_utc"] = (
            market_breath.fmt_ts(symbol_candles[-1].close_ts_utc)
            if symbol_candles
            else None
        )
        hydrated["resolved_btc_candle_ts_utc"] = btc_resolved_ts
        by_symbol[symbol] = hydrated
    return by_symbol


def hydrate_teacher_rows(
    *,
    reports: list[TeacherReportSource],
    venue: str,
    interval: str,
    lookback_candles: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    conn = get_connection()
    try:
        assets = market_breath.fetch_assets(conn)
        asset_by_symbol = {asset.symbol.upper(): asset for asset in assets}
        hydrated: list[dict[str, Any]] = []
        exclusions: list[dict[str, Any]] = []
        for report in reports:
            observations = resolve_report_observations(
                conn,
                report=report,
                venue=venue,
                interval=interval,
                lookback_candles=lookback_candles,
                asset_by_symbol=asset_by_symbol,
            )
            for raw_row in report.rows:
                token = str(raw_row.get("token") or "").strip().upper()
                teacher_phase, mapping_reason = normalize_teacher_phase(raw_row)
                observation = observations.get(token)
                if observation is None:
                    input_status = "MISSING_ASSET_OR_CANDLES"
                elif observation.get("market_breath_phase") == "INSUFFICIENT_DATA":
                    input_status = "INSUFFICIENT_DATA"
                else:
                    input_status = "OK"
                row = {
                    "report_id": report.report_id,
                    "prediction_ts_utc": market_breath.fmt_ts(report.prediction_ts_utc),
                    "report_source_kind": report.source_kind,
                    "report_artifact_path": report.artifact_path,
                    "report_source_file_path": report.source_file_path,
                    "report_artifact_hash_sha256": report.artifact_hash_sha256,
                    "report_source_hash_sha256": report.source_hash_sha256,
                    "token": token,
                    "teacher_phase": teacher_phase,
                    "teacher_mapping_reason": mapping_reason,
                    "teacher_phase_raw": row_value(raw_row, "phase"),
                    "teacher_coherence_raw": row_value(raw_row, "coherence"),
                    "teacher_field_raw": row_value(raw_row, "field"),
                    "teacher_geometry_raw": row_value(raw_row, "geometry"),
                    "teacher_structural_role_raw": row_value(raw_row, "structural_role"),
                    "teacher_expansion_quality_raw": row_value(raw_row, "expansion_quality"),
                    "teacher_anchor_strength_raw": row_value(raw_row, "anchor_strength"),
                    "teacher_strategic_bias_raw": row_value(raw_row, "strategic_bias"),
                    "teacher_notes_raw": str(raw_row.get("notes") or raw_row.get("table1_notes") or "").strip(),
                    "teacher_scoring_eligible": teacher_phase != "UNMAPPED",
                    "input_status": input_status,
                    "resolved_candle_ts_utc": None if observation is None else observation.get("resolved_candle_ts_utc"),
                    "resolved_btc_candle_ts_utc": None if observation is None else observation.get("resolved_btc_candle_ts_utc"),
                    "compression_score": None if observation is None else observation.get("compression_score"),
                    "expansion_score": None if observation is None else observation.get("expansion_score"),
                    "momentum_score": None if observation is None else observation.get("momentum_score"),
                    "reversal_pressure_score": None if observation is None else observation.get("reversal_pressure_score"),
                    "relative_strength_score": None if observation is None else observation.get("relative_strength_score"),
                    "btc_alignment_score": None if observation is None else observation.get("btc_alignment_score"),
                    "breadth_alignment_score": None if observation is None else observation.get("breadth_alignment_score"),
                    "baseline_phase": None if observation is None else observation.get("market_breath_phase"),
                    "baseline_state": None if observation is None else observation.get("market_breath_state"),
                }
                hydrated.append(row)
                if input_status != "OK":
                    exclusions.append(
                        {
                            "report_id": report.report_id,
                            "prediction_ts_utc": market_breath.fmt_ts(report.prediction_ts_utc),
                            "token": token,
                            "reason": input_status,
                        }
                    )
        return hydrated, exclusions
    finally:
        conn.rollback()
        conn.close()


def classify_hydrated_row(
    row: dict[str, Any],
    profile: MarketBreathThresholdProfileV1,
) -> tuple[str, str]:
    if row.get("input_status") != "OK":
        return "INSUFFICIENT_DATA", "UNKNOWN"
    return classify_market_breath_phase_state_v1(
        compression=float(row["compression_score"] or 0.0),
        expansion=float(row["expansion_score"] or 0.0),
        momentum=float(row["momentum_score"] or 0.0),
        reversal_pressure=float(row["reversal_pressure_score"] or 0.0),
        relative_strength=float(row["relative_strength_score"] or 0.0),
        profile=profile,
    )


def score_profile_against_teacher_rows(
    rows: list[dict[str, Any]],
    profile_spec: CandidateProfileSpec,
) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for row in rows:
        predicted_phase, predicted_state = classify_hydrated_row(row, profile_spec.profile)
        score_status = "SCORED"
        if row["teacher_phase"] == "UNMAPPED":
            score_status = "UNMAPPED"
        elif row["input_status"] != "OK":
            score_status = row["input_status"]
        scored.append(
            {
                **row,
                "profile_id": profile_spec.profile_id,
                "predicted_phase": predicted_phase,
                "predicted_state": predicted_state,
                "exact_phase_match": score_status == "SCORED" and predicted_phase == row["teacher_phase"],
                "score_status": score_status,
            }
        )
    return scored


def precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float | None, float | None, float | None]:
    precision = None if tp + fp == 0 else tp / (tp + fp)
    recall = None if tp + fn == 0 else tp / (tp + fn)
    if precision is None or recall is None or precision + recall == 0:
        f1 = None if precision is None and recall is None else 0.0
    else:
        f1 = (2.0 * precision * recall) / (precision + recall)
    return precision, recall, f1


def summarize_scored_rows(scored_rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_rows = len(scored_rows)
    eligible_rows = [row for row in scored_rows if row["score_status"] == "SCORED"]
    eligible_count = len(eligible_rows)
    exact_match_count = sum(1 for row in eligible_rows if row["exact_phase_match"])
    coverage = 0.0 if total_rows == 0 else eligible_count / total_rows

    confusion: dict[str, dict[str, int]] = {
        truth: {pred: 0 for pred in SCORABLE_PHASES}
        for truth in SCORABLE_PHASES
    }
    for row in eligible_rows:
        truth = str(row["teacher_phase"])
        pred = str(row["predicted_phase"])
        if truth in confusion and pred in confusion[truth]:
            confusion[truth][pred] += 1

    per_phase: dict[str, dict[str, Any]] = {}
    f1_values: list[float] = []
    for phase in SCORABLE_PHASES:
        tp = confusion[phase][phase]
        fp = sum(confusion[truth][phase] for truth in SCORABLE_PHASES if truth != phase)
        fn = sum(confusion[phase][pred] for pred in SCORABLE_PHASES if pred != phase)
        precision, recall, f1 = precision_recall_f1(tp, fp, fn)
        per_phase[phase] = {
            "support": sum(confusion[phase].values()),
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
        if f1 is not None and (tp + fp + fn) > 0:
            f1_values.append(f1)

    macro_f1 = None if not f1_values else mean(f1_values)
    exact_match_rate = None if eligible_count == 0 else exact_match_count / eligible_count

    return {
        "row_count": total_rows,
        "eligible_row_count": eligible_count,
        "exact_match_count": exact_match_count,
        "labeled_row_coverage": coverage,
        "exact_raw_phase_match_rate": exact_match_rate,
        "macro_f1": macro_f1,
        "per_phase": per_phase,
        "confusion_matrix": confusion,
    }


def build_leave_one_report_out_folds(report_ids: list[str]) -> list[dict[str, Any]]:
    folds: list[dict[str, Any]] = []
    for holdout_id in report_ids:
        train_ids = [report_id for report_id in report_ids if report_id != holdout_id]
        folds.append(
            {
                "holdout_report_id": holdout_id,
                "training_report_ids": train_ids,
            }
        )
    return folds


def fold_rows_for_profile(
    hydrated_rows: list[dict[str, Any]],
    profile_spec: CandidateProfileSpec,
    folds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_report: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in score_profile_against_teacher_rows(hydrated_rows, profile_spec):
        by_report[str(row["report_id"])].append(row)

    fold_rows: list[dict[str, Any]] = []
    for fold in folds:
        holdout_id = str(fold["holdout_report_id"])
        summary = summarize_scored_rows(by_report.get(holdout_id, []))
        fold_rows.append(
            {
                "profile_id": profile_spec.profile_id,
                "holdout_report_id": holdout_id,
                "training_report_ids": ",".join(fold["training_report_ids"]),
                "row_count": summary["row_count"],
                "eligible_row_count": summary["eligible_row_count"],
                "labeled_row_coverage": summary["labeled_row_coverage"],
                "exact_raw_phase_match_rate": summary["exact_raw_phase_match_rate"],
                "macro_f1": summary["macro_f1"],
            }
        )
    return fold_rows


def aggregate_profile_result(
    hydrated_rows: list[dict[str, Any]],
    profile_spec: CandidateProfileSpec,
    fold_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    overall_summary = summarize_scored_rows(score_profile_against_teacher_rows(hydrated_rows, profile_spec))
    fold_scores = [float(row["macro_f1"] or 0.0) for row in fold_rows]
    return {
        "profile_id": profile_spec.profile_id,
        "axis_name": profile_spec.axis_name,
        "axis_value": profile_spec.axis_value,
        "is_baseline": profile_spec.is_baseline,
        "profile": asdict(profile_spec.profile),
        "row_count": overall_summary["row_count"],
        "eligible_row_count": overall_summary["eligible_row_count"],
        "labeled_row_coverage": overall_summary["labeled_row_coverage"],
        "exact_raw_phase_match_rate": overall_summary["exact_raw_phase_match_rate"],
        "macro_f1": overall_summary["macro_f1"],
        "per_phase": overall_summary["per_phase"],
        "confusion_matrix": overall_summary["confusion_matrix"],
        "mean_fold_score": None if not fold_scores else mean(fold_scores),
        "worst_report_score": None if not fold_scores else min(fold_scores),
    }


def rank_profile_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        results,
        key=lambda row: (
            float(row["mean_fold_score"] or -1.0),
            float(row["worst_report_score"] or -1.0),
            float(row["macro_f1"] or -1.0),
            float(row["exact_raw_phase_match_rate"] or -1.0),
            float(row["labeled_row_coverage"] or -1.0),
            row["profile_id"],
        ),
        reverse=True,
    )
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return ranked


def select_result_status(
    *,
    ranked_results: list[dict[str, Any]],
    teacher_report_count: int,
    eligible_report_ids: list[str],
) -> tuple[str, dict[str, Any], list[str]]:
    baseline = next(row for row in ranked_results if row["is_baseline"])
    warnings: list[str] = []
    if teacher_report_count < 10:
        warnings.append(WARNING_TRAINING_SAMPLE_SMALL)
    if len(eligible_report_ids) < 2:
        return STATUS_INSUFFICIENT_TRAINING_DATA, baseline, warnings

    candidate_rows = [
        row
        for row in ranked_results
        if not row["is_baseline"]
        and float(row["labeled_row_coverage"] or 0.0) >= float(baseline["labeled_row_coverage"] or 0.0)
        and float(row["mean_fold_score"] or -1.0) > float(baseline["mean_fold_score"] or -1.0)
        and float(row["worst_report_score"] or -1.0) > float(baseline["worst_report_score"] or -1.0)
    ]
    if candidate_rows:
        return STATUS_CALIBRATION_CANDIDATE, candidate_rows[0], warnings
    return STATUS_BASELINE_RETAINED, baseline, warnings


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    flattened: list[dict[str, Any]] = []
    for row in rows:
        flat: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                flat[key] = json.dumps(value, sort_keys=True, ensure_ascii=True)
            else:
                flat[key] = value
        flattened.append(flat)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(flattened[0].keys()))
        writer.writeheader()
        writer.writerows(flattened)


def build_confusion_export(profile_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in profile_results:
        for truth, preds in result["confusion_matrix"].items():
            for pred, count in preds.items():
                rows.append(
                    {
                        "profile_id": result["profile_id"],
                        "teacher_phase": truth,
                        "predicted_phase": pred,
                        "count": count,
                    }
                )
    return rows


def teacher_report_timestamps(reports: list[TeacherReportSource]) -> list[str]:
    return [market_breath.fmt_ts(report.prediction_ts_utc) for report in reports]


def teacher_row_stats(hydrated_rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "teacher_row_count": len(hydrated_rows),
        "mapped_row_count": sum(1 for row in hydrated_rows if row["teacher_phase"] != "UNMAPPED"),
        "unmapped_row_count": sum(1 for row in hydrated_rows if row["teacher_phase"] == "UNMAPPED"),
        "insufficient_candle_row_count": sum(1 for row in hydrated_rows if row["input_status"] == "INSUFFICIENT_DATA"),
    }


def compact_profile_result(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "profile_id": row["profile_id"],
        "mean_fold_score": row["mean_fold_score"],
        "worst_report_score": row["worst_report_score"],
        "exact_raw_phase_match_rate": row["exact_raw_phase_match_rate"],
        "macro_f1": row["macro_f1"],
    }


def print_table_summary(payload: dict[str, Any]) -> None:
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print("scope=research-only offline A+ supervised calibration for Market Breath")
    print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
    print("selection_engine_changes=0 decision_gate_changes=0 execution_planner_changes=0 executor_changes=0")
    print(f"status={payload['result_status']}")
    if payload["warnings"]:
        print("warnings=" + ",".join(payload["warnings"]))
    print(f"teacher_reports={payload['teacher_report_count']}")
    print(f"eligible_reports={payload['eligible_report_count']}")
    print("approved_teacher_report_timestamps=" + ",".join(payload["approved_teacher_report_timestamps"]))
    print(f"profile_count={payload['profile_count']}")
    print(f"selected_profile_id={payload['selected_result']['profile_id']}")
    print(
        f"baseline_mean_fold_score={payload['baseline_result']['mean_fold_score']} "
        f"baseline_worst_report_score={payload['baseline_result']['worst_report_score']}"
    )
    print(
        f"selected_mean_fold_score={payload['selected_result_metrics']['mean_fold_score']} "
        f"selected_worst_report_score={payload['selected_result_metrics']['worst_report_score']}"
    )


def build_public_summary_payload(
    *,
    teacher_reports: list[TeacherReportSource],
    excluded_reports: list[dict[str, Any]],
    hydrated_rows: list[dict[str, Any]],
    folds: list[dict[str, Any]],
    result_status: str,
    warnings: list[str],
    baseline_result: dict[str, Any],
    best_candidate_result: dict[str, Any] | None,
    selected_profile: dict[str, Any],
    profile_count: int,
) -> dict[str, Any]:
    row_stats = teacher_row_stats(hydrated_rows)
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "result_status": result_status,
        "warnings": warnings,
        "teacher_report_count": len(teacher_reports),
        "eligible_report_count": len(folds),
        "approved_teacher_report_timestamps": teacher_report_timestamps(teacher_reports),
        "excluded_reports": excluded_reports,
        "teacher_row_count": row_stats["teacher_row_count"],
        "mapped_row_count": row_stats["mapped_row_count"],
        "unmapped_row_count": row_stats["unmapped_row_count"],
        "insufficient_candle_row_count": row_stats["insufficient_candle_row_count"],
        "fold_count": len(folds),
        "profile_count": profile_count,
        "baseline_result": baseline_result,
        "best_candidate_result": compact_profile_result(best_candidate_result),
        "selected_result": {
            "status": result_status,
            "profile_id": selected_profile["profile_id"],
            "is_baseline": bool(selected_profile["is_baseline"]),
            "is_calibration_candidate": result_status == STATUS_CALIBRATION_CANDIDATE,
        },
        "selected_result_metrics": compact_profile_result(selected_profile),
        "runtime_profile_written": False,
        "runtime_profile_selected": False,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    raw_dir = Path(args.raw_dir)
    normalized_dirs = [Path(path) for path in args.normalized_dir]
    teacher_reports, excluded_reports = discover_teacher_reports(
        raw_dir=raw_dir,
        normalized_dirs=normalized_dirs,
    )
    hydrated_rows, coverage_exclusions = hydrate_teacher_rows(
        reports=teacher_reports,
        venue=args.venue,
        interval=args.interval,
        lookback_candles=args.lookback_candles,
    )
    eligible_report_ids = sorted(
        {
            str(row["report_id"])
            for row in hydrated_rows
            if row["teacher_phase"] != "UNMAPPED" and row["input_status"] == "OK"
        }
    )
    folds = build_leave_one_report_out_folds(eligible_report_ids)
    profile_specs = build_single_axis_profiles()

    fold_rows: list[dict[str, Any]] = []
    profile_results: list[dict[str, Any]] = []
    for spec in profile_specs:
        current_fold_rows = fold_rows_for_profile(hydrated_rows, spec, folds)
        fold_rows.extend(current_fold_rows)
        profile_results.append(aggregate_profile_result(hydrated_rows, spec, current_fold_rows))

    ranked_results = rank_profile_results(profile_results)
    result_status, selected_profile, warnings = select_result_status(
        ranked_results=ranked_results,
        teacher_report_count=len(teacher_reports),
        eligible_report_ids=eligible_report_ids,
    )
    baseline_result = next(row for row in ranked_results if row["is_baseline"])
    best_candidate_result = next((row for row in ranked_results if not row["is_baseline"]), None)

    for row in ranked_results:
        row["delta_mean_fold_score_vs_baseline"] = None
        row["delta_worst_report_score_vs_baseline"] = None
        row["delta_macro_f1_vs_baseline"] = None
        row["delta_exact_match_rate_vs_baseline"] = None
        row["delta_labeled_coverage_vs_baseline"] = None
        for key, baseline_key in (
            ("mean_fold_score", "delta_mean_fold_score_vs_baseline"),
            ("worst_report_score", "delta_worst_report_score_vs_baseline"),
            ("macro_f1", "delta_macro_f1_vs_baseline"),
            ("exact_raw_phase_match_rate", "delta_exact_match_rate_vs_baseline"),
            ("labeled_row_coverage", "delta_labeled_coverage_vs_baseline"),
        ):
            if row[key] is None or baseline_result[key] is None:
                continue
            row[baseline_key] = float(row[key]) - float(baseline_result[key])

    manifest = {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "search_mode": SEARCH_MODE,
        "result_status": result_status,
        "warnings": warnings,
        "teacher_report_count": len(teacher_reports),
        "eligible_report_count": len(eligible_report_ids),
        "eligible_report_ids": eligible_report_ids,
        "teacher_reports": [teacher_report_manifest_row(report) for report in teacher_reports],
        "excluded_reports": excluded_reports,
        "coverage_exclusions": coverage_exclusions,
        "baseline_profile": asdict(DEFAULT_MARKET_BREATH_THRESHOLD_PROFILE_V1),
        "non_tuned_baseline_constants": {
            "minimum_candle_count": MIN_CANDLE_COUNT_V1,
            "expected_lookback_candles": args.lookback_candles,
            "atr_window": ATR_WINDOW_V1,
            "atr_baseline_window": ATR_BASELINE_WINDOW_V1,
            "range_baseline_window": RANGE_BASELINE_WINDOW_V1,
            "signed_score_bounds": SIGNED_SCORE_BOUNDS_V1,
            "clamped_score_bounds": CLAMPED_SCORE_BOUNDS_V1,
            "source_interval": args.interval,
        },
        "candidate_axis_values": profile_axis_values(),
        "output_dir": str(Path(args.output_dir)),
        "write_files": bool(args.write_files),
    }

    output_paths = {
        "manifest_json": str(Path(args.output_dir) / "manifest_v1.json"),
        "teacher_rows_jsonl": str(Path(args.output_dir) / "teacher_label_rows_v1.jsonl"),
        "score_table_csv": str(Path(args.output_dir) / "candidate_score_table_v1.csv"),
        "fold_summary_csv": str(Path(args.output_dir) / "per_report_fold_summary_v1.csv"),
        "selected_profile_json": str(Path(args.output_dir) / "calibration_candidate_profile_v1.json"),
        "confusion_matrix_csv": str(Path(args.output_dir) / "confusion_matrix_v1.csv"),
    }
    manifest["output_paths"] = output_paths

    selected_profile_payload = {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "result_status": result_status,
        "warnings": warnings,
        "selected_profile": selected_profile,
        "baseline_profile": baseline_result,
        "runtime_promotion_allowed": False,
        "runtime_dependency_on_aplus": False,
        "calibration_candidate_is_research_only": True,
    }

    summary_payload = build_public_summary_payload(
        teacher_reports=teacher_reports,
        excluded_reports=excluded_reports,
        hydrated_rows=hydrated_rows,
        folds=folds,
        result_status=result_status,
        warnings=warnings,
        baseline_result=baseline_result,
        best_candidate_result=best_candidate_result,
        selected_profile=selected_profile,
        profile_count=len(profile_specs),
    )

    if args.write_files:
        write_json(Path(output_paths["manifest_json"]), manifest)
        write_jsonl(Path(output_paths["teacher_rows_jsonl"]), hydrated_rows)
        write_csv(Path(output_paths["score_table_csv"]), ranked_results)
        write_csv(Path(output_paths["fold_summary_csv"]), fold_rows)
        write_json(Path(output_paths["selected_profile_json"]), selected_profile_payload)
        write_csv(Path(output_paths["confusion_matrix_csv"]), build_confusion_export(ranked_results))

    if args.output == "json":
        print(json.dumps(summary_payload, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print_table_summary(summary_payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
