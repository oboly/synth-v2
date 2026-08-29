from copy import deepcopy

from src.research.cq_v1_model_preregistration_gate_v1 import (
    BLOCKED_STATE,
    READY_STATE,
    validate_coverage_summary,
)


def valid_payload() -> dict:
    return {
        "runner": "cq_v1_pit_extractor_v1",
        "sample_count": 100,
        "mrp_available_count": 80,
        "sector_available_count": 70,
        "joint_available_count": 60,
        "mrp_coverage": 0.8,
        "sector_coverage": 0.7,
        "joint_coverage": 0.6,
        "last_shadow_id": 1234,
        "terminal_state": "FINISHED",
        "weights_assigned": 0,
        "cq_v1_scores_emitted": 0,
    }


def test_valid_coverage_artifact_is_ready_and_hashed_deterministically() -> None:
    payload = valid_payload()
    first = validate_coverage_summary(payload)
    second = validate_coverage_summary(dict(reversed(list(payload.items()))))
    assert first.state == READY_STATE
    assert first.ready is True
    assert first.reasons == ()
    assert first.artifact_sha256 is not None
    assert first.artifact_sha256 == second.artifact_sha256


def test_gate_rejects_wrong_runner_or_nonfinished_artifact() -> None:
    payload = valid_payload()
    payload["runner"] = "other_runner"
    payload["terminal_state"] = "INTERRUPTED"
    result = validate_coverage_summary(payload)
    assert result.state == BLOCKED_STATE
    assert "RUNNER_MISMATCH" in result.reasons
    assert "TERMINAL_STATE_NOT_FINISHED" in result.reasons
    assert result.artifact_sha256 is None


def test_gate_rejects_empty_or_inconsistent_counts() -> None:
    payload = valid_payload()
    payload.update(sample_count=0, mrp_available_count=1, sector_available_count=0, joint_available_count=1)
    result = validate_coverage_summary(payload)
    assert result.state == BLOCKED_STATE
    assert "EMPTY_SAMPLE" in result.reasons
    assert "MRP_COUNT_OUT_OF_RANGE" in result.reasons
    assert "JOINT_COUNT_OUT_OF_RANGE" in result.reasons


def test_gate_rejects_fractional_or_boolean_count_values() -> None:
    for key, bad_value in (
        ("sample_count", 100.0),
        ("mrp_available_count", 79.9),
        ("sector_available_count", True),
        ("joint_available_count", False),
    ):
        payload = valid_payload()
        payload[key] = bad_value
        result = validate_coverage_summary(payload)
        assert result.state == BLOCKED_STATE
        assert "INVALID_OR_MISSING_COUNTS" in result.reasons
        assert result.artifact_sha256 is None


def test_gate_rejects_zero_fractional_boolean_or_missing_last_shadow_id() -> None:
    for bad_value in (0, -1, 1.5, True, None):
        payload = valid_payload()
        payload["last_shadow_id"] = bad_value
        result = validate_coverage_summary(payload)
        assert result.state == BLOCKED_STATE
        assert "LAST_SHADOW_ID_INVALID_OR_MISSING" in result.reasons
        assert result.artifact_sha256 is None

    payload = valid_payload()
    del payload["last_shadow_id"]
    result = validate_coverage_summary(payload)
    assert result.state == BLOCKED_STATE
    assert "LAST_SHADOW_ID_INVALID_OR_MISSING" in result.reasons


def test_gate_rejects_coverage_not_recomputed_from_same_population() -> None:
    payload = valid_payload()
    payload["joint_coverage"] = 0.61
    result = validate_coverage_summary(payload)
    assert result.state == BLOCKED_STATE
    assert "JOINT_COVERAGE_MISMATCH" in result.reasons


def test_gate_rejects_boolean_string_or_nonfinite_coverage_values() -> None:
    for key, bad_value in (
        ("mrp_coverage", True),
        ("sector_coverage", "0.7"),
        ("joint_coverage", float("nan")),
        ("joint_coverage", float("inf")),
    ):
        payload = valid_payload()
        payload[key] = bad_value
        result = validate_coverage_summary(payload)
        assert result.state == BLOCKED_STATE
        assert f"{key.upper()}_INVALID_OR_MISSING" in result.reasons
        assert result.artifact_sha256 is None


def test_gate_rejects_preassigned_weights_or_scores() -> None:
    payload = valid_payload()
    payload["weights_assigned"] = 1
    payload["cq_v1_scores_emitted"] = 1
    result = validate_coverage_summary(payload)
    assert result.state == BLOCKED_STATE
    assert "WEIGHTS_ALREADY_ASSIGNED" in result.reasons
    assert "CQ_V1_SCORES_ALREADY_EMITTED" in result.reasons


def test_artifact_digest_changes_when_coverage_changes() -> None:
    original = validate_coverage_summary(valid_payload())
    changed_payload = deepcopy(valid_payload())
    changed_payload["mrp_available_count"] = 79
    changed_payload["mrp_coverage"] = 0.79
    changed = validate_coverage_summary(changed_payload)
    assert original.ready and changed.ready
    assert original.artifact_sha256 != changed.artifact_sha256
