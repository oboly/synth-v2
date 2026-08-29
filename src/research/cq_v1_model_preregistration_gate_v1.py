from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

RUNNER_NAME = "cq_v1_pit_extractor_v1"
READY_STATE = "READY_FOR_MODEL_FREEZE"
BLOCKED_STATE = "BLOCKED_INVALID_COVERAGE_ARTIFACT"


@dataclass(frozen=True)
class CoverageGateResult:
    state: str
    artifact_sha256: str | None
    reasons: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.state == READY_STATE


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_coverage_summary(payload: Mapping[str, Any]) -> CoverageGateResult:
    reasons: list[str] = []

    if payload.get("runner") != RUNNER_NAME:
        reasons.append("RUNNER_MISMATCH")
    if payload.get("terminal_state") != "FINISHED":
        reasons.append("TERMINAL_STATE_NOT_FINISHED")

    try:
        sample_count = int(payload["sample_count"])
        mrp_count = int(payload["mrp_available_count"])
        sector_count = int(payload["sector_available_count"])
        joint_count = int(payload["joint_available_count"])
    except (KeyError, TypeError, ValueError):
        return CoverageGateResult(BLOCKED_STATE, None, tuple(reasons + ["INVALID_OR_MISSING_COUNTS"]))

    if sample_count <= 0:
        reasons.append("EMPTY_SAMPLE")
    if sample_count > 0 and payload.get("last_shadow_id") is None:
        reasons.append("LAST_SHADOW_ID_REQUIRED")

    for name, value in (
        ("MRP_COUNT", mrp_count),
        ("SECTOR_COUNT", sector_count),
        ("JOINT_COUNT", joint_count),
    ):
        if value < 0 or value > sample_count:
            reasons.append(f"{name}_OUT_OF_RANGE")

    if joint_count > mrp_count or joint_count > sector_count:
        reasons.append("JOINT_COUNT_EXCEEDS_FAMILY_COUNT")

    if payload.get("weights_assigned") != 0:
        reasons.append("WEIGHTS_ALREADY_ASSIGNED")
    if payload.get("cq_v1_scores_emitted") != 0:
        reasons.append("CQ_V1_SCORES_ALREADY_EMITTED")

    if sample_count > 0:
        expected = {
            "mrp_coverage": round(mrp_count / sample_count, 6),
            "sector_coverage": round(sector_count / sample_count, 6),
            "joint_coverage": round(joint_count / sample_count, 6),
        }
        for key, value in expected.items():
            try:
                observed = float(payload[key])
            except (KeyError, TypeError, ValueError):
                reasons.append(f"{key.upper()}_INVALID_OR_MISSING")
                continue
            if observed != value:
                reasons.append(f"{key.upper()}_MISMATCH")

    if reasons:
        return CoverageGateResult(BLOCKED_STATE, None, tuple(reasons))

    return CoverageGateResult(READY_STATE, _canonical_sha256(payload), ())
