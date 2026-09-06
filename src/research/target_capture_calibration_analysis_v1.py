from __future__ import annotations

"""Deterministic research-only target-capture calibration for issue #559."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Final, Iterable, Mapping, Sequence

from src.market_data.fib_navigation_map_v1 import DIRECTION_BEARISH, DIRECTION_BULLISH
from src.research.execution_offset_replay_report_v1 import build_replay_dataset
from src.research.execution_offset_replay_v1 import (
    ExecutionOffsetEpisodeV1,
    ExecutionOffsetPolicyV1,
    ExecutionOffsetReplayRowV1,
    POLICY_EXACT_LEVEL,
    POLICY_STATIC_BUFFER,
    ReplayCandle,
    SIDE_BUY,
    SIDE_SELL,
    policy_fingerprint,
)
from src.research.target_capture_calibration_adapter_v1 import TargetEpisodeAnalysisContextV1

VERSION: Final[str] = "target_capture_calibration_analysis_v1"
MIN_SAMPLE_THRESHOLD: Final[int] = 30
CONFIDENCE_SUFFICIENT: Final[str] = "SUFFICIENT_SAMPLE"
CONFIDENCE_INSUFFICIENT: Final[str] = "INSUFFICIENT_SAMPLE"
DISPOSITION_REJECT: Final[str] = "REJECT"
DISPOSITION_RESEARCH_ONLY: Final[str] = "RESEARCH_ONLY"
DISPOSITION_EXECUTION_PLANNER_CANDIDATE: Final[str] = "EXECUTION_PLANNER_CANDIDATE"

CANDIDATE_BUFFER_PCTS: Final[tuple[Decimal, ...]] = (
    Decimal("0"),
    Decimal("0.005"),
    Decimal("0.0075"),
    Decimal("0.01"),
    Decimal("0.0125"),
    Decimal("0.015"),
)
QUANTILES: Final[tuple[tuple[str, Decimal], ...]] = (
    ("p50", Decimal("0.50")),
    ("p75", Decimal("0.75")),
    ("p80", Decimal("0.80")),
    ("p90", Decimal("0.90")),
)


class TargetCaptureCalibrationError(ValueError):
    pass


@dataclass(frozen=True)
class CalibrationInputV1:
    episode: ExecutionOffsetEpisodeV1
    context: TargetEpisodeAnalysisContextV1
    candles: tuple[ReplayCandle, ...]


def candidate_policies() -> tuple[ExecutionOffsetPolicyV1, ...]:
    policies: list[ExecutionOffsetPolicyV1] = []
    for buffer_pct in CANDIDATE_BUFFER_PCTS:
        if buffer_pct == 0:
            policies.append(ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "559-v1"))
        else:
            policies.append(
                ExecutionOffsetPolicyV1(
                    POLICY_STATIC_BUFFER,
                    "559-v1",
                    buffer_pct=buffer_pct,
                )
            )
    return tuple(policies)


def _validate_threshold(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TargetCaptureCalibrationError("INVALID_MIN_SAMPLE_THRESHOLD")


def _validate_input(item: CalibrationInputV1) -> None:
    episode = item.episode
    context = item.context
    if episode.episode_id != context.episode_id:
        raise TargetCaptureCalibrationError("EPISODE_CONTEXT_IDENTITY_CONFLICT")
    if episode.source_map_id != context.source_map_id:
        raise TargetCaptureCalibrationError("SOURCE_MAP_IDENTITY_CONFLICT")
    if context.reference_price <= 0:
        raise TargetCaptureCalibrationError("NON_POSITIVE_REFERENCE_PRICE")
    if context.direction == DIRECTION_BULLISH and episode.side != SIDE_SELL:
        raise TargetCaptureCalibrationError("DIRECTION_SIDE_CONFLICT")
    if context.direction == DIRECTION_BEARISH and episode.side != SIDE_BUY:
        raise TargetCaptureCalibrationError("DIRECTION_SIDE_CONFLICT")
    if context.direction not in {DIRECTION_BULLISH, DIRECTION_BEARISH}:
        raise TargetCaptureCalibrationError("UNSUPPORTED_DIRECTION")


def _ordered_inputs(inputs: Iterable[CalibrationInputV1]) -> list[CalibrationInputV1]:
    items = list(inputs)
    if not items:
        raise TargetCaptureCalibrationError("NO_CALIBRATION_INPUTS")
    for item in items:
        _validate_input(item)
    ordered = sorted(items, key=lambda item: item.episode.episode_id)
    ids = [item.episode.episode_id for item in ordered]
    if len(ids) != len(set(ids)):
        raise TargetCaptureCalibrationError("DUPLICATE_EPISODE_IDENTITY")
    return ordered


def _nearest_rank(values: Sequence[Decimal], quantile: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(float(quantile * Decimal(len(ordered)))))
    return ordered[rank - 1]


def _rate_pct(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return Decimal(numerator) / Decimal(denominator) * Decimal("100")


def _avg(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def _expected_return_pct(
    row: ExecutionOffsetReplayRowV1,
    context: TargetEpisodeAnalysisContextV1,
) -> Decimal:
    if not row.filled:
        return Decimal("0")
    if context.direction == DIRECTION_BULLISH:
        return (row.execution_price - context.reference_price) / context.reference_price * Decimal("100")
    if context.direction == DIRECTION_BEARISH:
        return (context.reference_price - row.execution_price) / context.reference_price * Decimal("100")
    raise TargetCaptureCalibrationError("UNSUPPORTED_DIRECTION")


def _foregone_upside_pct(row: ExecutionOffsetReplayRowV1) -> Decimal:
    return abs(row.execution_price - row.canonical_level) / row.canonical_level * Decimal("100")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _segment_key(item: CalibrationInputV1, dimension: str) -> str:
    if dimension == "overall":
        return "ALL"
    if dimension == "fib_level_id":
        return item.episode.fib_level_id
    if dimension == "horizon":
        return item.episode.horizon
    if dimension == "direction":
        return item.context.direction
    raise TargetCaptureCalibrationError("UNSUPPORTED_SEGMENT_DIMENSION")


def _analyze_segment(
    items: Sequence[CalibrationInputV1],
    rows_by_identity: Mapping[tuple[str, str], ExecutionOffsetReplayRowV1],
    policies: Sequence[ExecutionOffsetPolicyV1],
    min_sample_threshold: int,
) -> dict[str, Any]:
    exact_policy = policies[0]
    exact_fp = policy_fingerprint(exact_policy)
    exact_rows = [rows_by_identity[(item.episode.episode_id, exact_fp)] for item in items]

    exact_ambiguous_ids = {
        row.episode_id for row in exact_rows if row.same_candle_fill_invalidation_ambiguous
    }
    required_buffers: list[Decimal] = []
    unresolved_without_distance = 0
    for row in exact_rows:
        if row.episode_id in exact_ambiguous_ids:
            continue
        if row.filled or row.touched or row.canonical_level_touched:
            required_buffers.append(Decimal("0"))
        elif row.near_miss_distance_pct is not None:
            required_buffers.append(row.near_miss_distance_pct)
        else:
            unresolved_without_distance += 1

    exact_resolved_ids = {
        row.episode_id
        for row in exact_rows
        if row.episode_id not in exact_ambiguous_ids
        and (row.filled or row.touched or row.canonical_level_touched or row.near_miss_distance_pct is not None)
    }
    context_by_id = {item.episode.episode_id: item.context for item in items}

    candidate_results: list[dict[str, Any]] = []
    exact_expected_return: Decimal | None = None
    exact_capture_rate: Decimal | None = None
    for policy in policies:
        fingerprint = policy_fingerprint(policy)
        rows = [rows_by_identity[(item.episode.episode_id, fingerprint)] for item in items]
        candidate_ambiguous_ids = {
            row.episode_id
            for row in rows
            if row.episode_id in exact_resolved_ids and row.same_candle_fill_invalidation_ambiguous
        }
        resolved_rows = [
            row
            for row in rows
            if row.episode_id in exact_resolved_ids and row.episode_id not in candidate_ambiguous_ids
        ]
        filled_rows = [row for row in resolved_rows if row.filled]
        capture_rate = _rate_pct(len(filled_rows), len(resolved_rows))
        expected_returns = [
            _expected_return_pct(row, context_by_id[row.episode_id]) for row in resolved_rows
        ]
        expected_return = _avg(expected_returns)
        foregone_on_fills = [_foregone_upside_pct(row) for row in filled_rows]
        foregone_contributions = [
            _foregone_upside_pct(row) if row.filled else Decimal("0") for row in resolved_rows
        ]
        if policy.policy_id == POLICY_EXACT_LEVEL:
            exact_expected_return = expected_return
            exact_capture_rate = capture_rate
        candidate_results.append(
            {
                "policy_id": policy.policy_id,
                "policy_fingerprint": fingerprint,
                "buffer_pct_fraction": policy.buffer_pct,
                "buffer_pct_points": policy.buffer_pct * Decimal("100"),
                "resolved_sample_count": len(resolved_rows),
                "candidate_ambiguity_count": len(candidate_ambiguous_ids),
                "candidate_ambiguity_rate_pct": _rate_pct(len(candidate_ambiguous_ids), len(exact_resolved_ids)),
                "filled_count": len(filled_rows),
                "capture_rate_pct": capture_rate,
                "avg_foregone_upside_pct_on_fills": _avg(foregone_on_fills),
                "expected_foregone_upside_contribution_pct": _avg(foregone_contributions),
                "expected_captured_return_proxy_pct": expected_return,
            }
        )

    assert exact_capture_rate is not None or not exact_resolved_ids
    assert exact_expected_return is not None or not exact_resolved_ids
    for result in candidate_results:
        result["capture_rate_uplift_pct_points"] = (
            None
            if result["capture_rate_pct"] is None or exact_capture_rate is None
            else result["capture_rate_pct"] - exact_capture_rate
        )
        result["expected_return_delta_vs_exact_pct_points"] = (
            None
            if result["expected_captured_return_proxy_pct"] is None or exact_expected_return is None
            else result["expected_captured_return_proxy_pct"] - exact_expected_return
        )

    confidence = (
        CONFIDENCE_SUFFICIENT
        if len(exact_resolved_ids) >= min_sample_threshold
        else CONFIDENCE_INSUFFICIENT
    )
    return {
        "input_episode_count": len(items),
        "resolved_sample_count": len(exact_resolved_ids),
        "exact_ambiguity_count": len(exact_ambiguous_ids),
        "exact_ambiguity_rate_pct": _rate_pct(len(exact_ambiguous_ids), len(items)),
        "unresolved_without_distance_count": unresolved_without_distance,
        "min_sample_threshold": min_sample_threshold,
        "confidence_state": confidence,
        "atr_available_count": sum(1 for item in items if item.episode.atr_at_issue is not None),
        "atr_available_rate_pct": _rate_pct(
            sum(1 for item in items if item.episode.atr_at_issue is not None), len(items)
        ),
        "required_buffer_quantiles_pct_points": {
            name: _nearest_rank(required_buffers, quantile) for name, quantile in QUANTILES
        },
        "candidates": candidate_results,
    }


def _candidate_by_buffer(segment: Mapping[str, Any], buffer_pct: Decimal) -> Mapping[str, Any]:
    for candidate in segment["candidates"]:
        if candidate["buffer_pct_fraction"] == buffer_pct:
            return candidate
    raise TargetCaptureCalibrationError("CANDIDATE_BUFFER_NOT_FOUND")


def _choose_disposition(
    overall: Mapping[str, Any],
    subgroup_segments: Sequence[Mapping[str, Any]],
    min_sample_threshold: int,
) -> tuple[str, Decimal | None, str]:
    if overall["resolved_sample_count"] < min_sample_threshold:
        return DISPOSITION_RESEARCH_ONLY, None, "OVERALL_SAMPLE_INSUFFICIENT"

    viable: list[Mapping[str, Any]] = []
    for candidate in overall["candidates"]:
        if candidate["buffer_pct_fraction"] == 0:
            continue
        uplift = candidate["capture_rate_uplift_pct_points"]
        delta = candidate["expected_return_delta_vs_exact_pct_points"]
        if uplift is not None and delta is not None and uplift > 0 and delta > 0:
            viable.append(candidate)
    if not viable:
        return DISPOSITION_REJECT, None, "NO_NONZERO_CANDIDATE_IMPROVES_CAPTURE_AND_RETURN"

    viable.sort(
        key=lambda candidate: (
            -candidate["expected_captured_return_proxy_pct"],
            candidate["buffer_pct_fraction"],
        )
    )
    selected = viable[0]
    selected_buffer = selected["buffer_pct_fraction"]

    for subgroup in subgroup_segments:
        if subgroup["resolved_sample_count"] < min_sample_threshold:
            continue
        candidate = _candidate_by_buffer(subgroup, selected_buffer)
        delta = candidate["expected_return_delta_vs_exact_pct_points"]
        if delta is not None and delta < 0:
            return DISPOSITION_RESEARCH_ONLY, selected_buffer, "SUFFICIENT_SUBGROUP_CONTRADICTION"

    return DISPOSITION_EXECUTION_PLANNER_CANDIDATE, selected_buffer, "STABLE_POSITIVE_CAPTURE_ECONOMICS"


def build_calibration_report(
    inputs: Iterable[CalibrationInputV1],
    *,
    min_sample_threshold: int = MIN_SAMPLE_THRESHOLD,
) -> dict[str, Any]:
    _validate_threshold(min_sample_threshold)
    ordered = _ordered_inputs(inputs)
    policies = candidate_policies()
    episodes = [item.episode for item in ordered]
    candles_by_episode = {item.episode.episode_id: item.candles for item in ordered}
    rows = build_replay_dataset(episodes, candles_by_episode, policies)
    rows_by_identity = {(row.episode_id, row.policy_fingerprint): row for row in rows}

    overall = _analyze_segment(ordered, rows_by_identity, policies, min_sample_threshold)
    segment_groups: dict[str, list[dict[str, Any]]] = {}
    subgroup_segments: list[dict[str, Any]] = []
    for dimension in ("fib_level_id", "horizon", "direction"):
        values: dict[str, list[CalibrationInputV1]] = {}
        for item in ordered:
            values.setdefault(_segment_key(item, dimension), []).append(item)
        output: list[dict[str, Any]] = []
        for value in sorted(values):
            summary = _analyze_segment(values[value], rows_by_identity, policies, min_sample_threshold)
            summary = {"segment_value": value, **summary}
            output.append(summary)
            subgroup_segments.append(summary)
        segment_groups[dimension] = output

    disposition, selected_buffer, reason = _choose_disposition(
        overall, subgroup_segments, min_sample_threshold
    )
    evidence_rows = [
        {
            "episode_id": row.episode_id,
            "policy_fingerprint": row.policy_fingerprint,
            "policy_id": row.policy_id,
            "buffer_pct_fraction": row.policy_buffer_pct,
            "raw_canonical_level": row.canonical_level,
            "executable_level": row.execution_price,
            "filled": row.filled,
            "ambiguous": row.same_candle_fill_invalidation_ambiguous,
        }
        for row in sorted(rows, key=lambda r: (r.episode_id, r.policy_fingerprint))
    ]
    report = {
        "version": VERSION,
        "candidate_buffer_pcts_fraction": CANDIDATE_BUFFER_PCTS,
        "volatility_segmentation_state": "NOT_DEFINED_CANONICALLY",
        "overall": overall,
        "segments": segment_groups,
        "disposition": disposition,
        "disposition_reason": reason,
        "selected_buffer_pct_fraction": selected_buffer,
        "evidence_rows": evidence_rows,
    }
    canonical = _canonical_json(report)
    report["report_fingerprint"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return report


def render_calibration_report_json(report: Mapping[str, Any]) -> str:
    return json.dumps(_json_safe(dict(report)), sort_keys=True, indent=2, ensure_ascii=True) + "\n"
