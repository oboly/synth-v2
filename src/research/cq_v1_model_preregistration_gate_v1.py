from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

RUNNER_NAME = "cq_v1_pit_extractor_v1"
CONTRACT_NAME = "cq_v1_pit_extractor_v1"
CONTRACT_VERSION = "1.0.0"
READY_STATE = "READY_FOR_MODEL_FREEZE"
BLOCKED_STATE = "BLOCKED_INVALID_COVERAGE_ARTIFACT"

ALLOWED_FIELDS = frozenset(
    {
        "runner",
        "contract_name",
        "contract_version",
        "sample_count",
        "observations_in_this_invocation",
        "mrp_available_count",
        "sector_available_count",
        "joint_available_count",
        "mrp_coverage",
        "sector_coverage",
        "joint_coverage",
        "last_shadow_id",
        "terminal_state",
        "weights_assigned",
        "cq_v1_scores_emitted",
    }
)


@dataclass(frozen=True)
class CoverageGateResult:
    state: str
    artifact_sha256: str | None
    reasons: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.state == READY_STATE


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_json_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(key)
    return value


def _required_finite_json_number(payload: Mapping[str, Any], key: str) -> float:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(key)
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(key)
    return numeric


def _validate_exact_json_schema(payload: Mapping[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []
    keys = set(payload.keys())
    if keys != ALLOWED_FIELDS:
        reasons.append("ARTIFACT_SCHEMA_MISMATCH")
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError):
        reasons.append("ARTIFACT_NOT_STRICT_JSON")
    return tuple(reasons)


def validate_coverage_summary(payload: Mapping[str, Any]) -> CoverageGateResult:
    reasons = list(_validate_exact_json_schema(payload))

    if payload.get("runner") != RUNNER_NAME:
        reasons.append("RUNNER_MISMATCH")
    if payload.get("contract_name") != CONTRACT_NAME:
        reasons.append("CONTRACT_NAME_MISMATCH")
    if payload.get("contract_version") != CONTRACT_VERSION:
        reasons.append("CONTRACT_VERSION_MISMATCH")
    if payload.get("terminal_state") != "FINISHED":
        reasons.append("TERMINAL_STATE_NOT_FINISHED")

    try:
        sample_count = _required_json_int(payload, "sample_count")
        invocation_count = _required_json_int(payload, "observations_in_this_invocation")
        mrp_count = _required_json_int(payload, "mrp_available_count")
        sector_count = _required_json_int(payload, "sector_available_count")
        joint_count = _required_json_int(payload, "joint_available_count")
    except (KeyError, TypeError):
        return CoverageGateResult(BLOCKED_STATE, None, tuple(reasons + ["INVALID_OR_MISSING_COUNTS"]))

    if sample_count <= 0:
        reasons.append("EMPTY_SAMPLE")
    if invocation_count < 0 or invocation_count > sample_count:
        reasons.append("INVOCATION_COUNT_OUT_OF_RANGE")

    if sample_count > 0:
        try:
            last_shadow_id = _required_json_int(payload, "last_shadow_id")
        except (KeyError, TypeError):
            reasons.append("LAST_SHADOW_ID_INVALID_OR_MISSING")
        else:
            if last_shadow_id <= 0:
                reasons.append("LAST_SHADOW_ID_INVALID_OR_MISSING")

    for name, value in (
        ("MRP_COUNT", mrp_count),
        ("SECTOR_COUNT", sector_count),
        ("JOINT_COUNT", joint_count),
    ):
        if value < 0 or value > sample_count:
            reasons.append(f"{name}_OUT_OF_RANGE")

    if joint_count > mrp_count or joint_count > sector_count:
        reasons.append("JOINT_COUNT_EXCEEDS_FAMILY_COUNT")

    try:
        weights_assigned = _required_json_int(payload, "weights_assigned")
    except (KeyError, TypeError):
        reasons.append("WEIGHTS_ASSIGNED_INVALID_OR_MISSING")
    else:
        if weights_assigned != 0:
            reasons.append("WEIGHTS_ALREADY_ASSIGNED")

    try:
        scores_emitted = _required_json_int(payload, "cq_v1_scores_emitted")
    except (KeyError, TypeError):
        reasons.append("CQ_V1_SCORES_EMITTED_INVALID_OR_MISSING")
    else:
        if scores_emitted != 0:
            reasons.append("CQ_V1_SCORES_ALREADY_EMITTED")

    if sample_count > 0:
        expected = {
            "mrp_coverage": round(mrp_count / sample_count, 6),
            "sector_coverage": round(sector_count / sample_count, 6),
            "joint_coverage": round(joint_count / sample_count, 6),
        }
        for key, value in expected.items():
            try:
                observed = _required_finite_json_number(payload, key)
            except (KeyError, TypeError, ValueError):
                reasons.append(f"{key.upper()}_INVALID_OR_MISSING")
                continue
            if observed != value:
                reasons.append(f"{key.upper()}_MISMATCH")

    if reasons:
        return CoverageGateResult(BLOCKED_STATE, None, tuple(reasons))

    return CoverageGateResult(READY_STATE, _canonical_sha256(payload), ())
