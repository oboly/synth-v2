from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.research.breathline_v1_recovery_campaign_matrix_v1 import (
    ARM_A,
    ARM_B,
    B2A_DISPLACEMENTS,
    CANONICAL_CONTROL_ID,
    build_campaign_jobs,
)
from src.research.breathline_v1_recovery_cohort_manifest_v1 import (
    V1_CHECKPOINT_RATIOS,
    V1_CYCLE_DAYS,
    V1_OFFSET_GRID,
    CohortPayload,
)


def make_payload(
    *,
    symbols: tuple[str, ...] = ("BTC", "ETH"),
    anchors: tuple[str, ...] = ("2025-01-01", "2025-02-15"),
) -> CohortPayload:
    return CohortPayload(
        canonical_symbols=symbols,
        canonical_base_anchors=anchors,
        checkpoint_ratios=V1_CHECKPOINT_RATIOS,
        cycle_days=V1_CYCLE_DAYS,
        offset_grid=V1_OFFSET_GRID,
        cohort_source={"note": "synthetic"},
        payload_sha256="deadbeef",
    )


def test_arm_a_job_count_matches_formula() -> None:
    payload = make_payload(symbols=("BTC", "ETH", "TAO"), anchors=("2025-01-01", "2025-02-15"))
    jobs = build_campaign_jobs(payload)
    arm_a_jobs = [job for job in jobs if job.arm_id == ARM_A]
    assert len(arm_a_jobs) == len(payload.canonical_symbols) * len(payload.canonical_base_anchors)
    assert all(job.control_id == CANONICAL_CONTROL_ID for job in arm_a_jobs)


def test_b2a_job_count_is_twenty_per_symbol_anchor_pair() -> None:
    payload = make_payload(symbols=("BTC", "ETH"), anchors=("2025-01-01",))
    jobs = build_campaign_jobs(payload)
    arm_b_jobs = [job for job in jobs if job.arm_id == ARM_B]
    assert len(arm_b_jobs) == 20 * len(payload.canonical_symbols) * len(payload.canonical_base_anchors)
    for symbol in payload.canonical_symbols:
        for anchor in payload.canonical_base_anchors:
            matching = [
                job for job in arm_b_jobs if job.symbol == symbol and job.base_anchor_ts_utc == anchor
            ]
            assert len(matching) == 20


def test_b2a_displacement_set_is_exact() -> None:
    payload = make_payload(symbols=("BTC",), anchors=("2025-01-01",))
    jobs = build_campaign_jobs(payload)
    displacements = {job.anchor_displacement_days for job in jobs if job.arm_id == ARM_B}
    assert displacements == set(range(-10, 0)) | set(range(1, 11))
    assert len(displacements) == 20


def test_b2a_excludes_zero_displacement() -> None:
    payload = make_payload(symbols=("BTC",), anchors=("2025-01-01",))
    jobs = build_campaign_jobs(payload)
    assert 0 not in {job.anchor_displacement_days for job in jobs if job.arm_id == ARM_B}
    assert B2A_DISPLACEMENTS == tuple(range(-10, 0)) + tuple(range(1, 11))
    assert 0 not in B2A_DISPLACEMENTS
    assert len(B2A_DISPLACEMENTS) == 20


def test_no_b1_jobs_produced() -> None:
    payload = make_payload(symbols=("BTC",), anchors=("2025-01-01",))
    jobs = build_campaign_jobs(payload)
    for job in jobs:
        assert "10.5" not in job.control_id
        assert job.anchor_displacement_days != 10.5
        assert job.anchor_displacement_days != -10.5
        assert job.phase_class_mod_21_days != 10.5


def test_phase_class_mod_21_days_equals_signed_displacement() -> None:
    payload = make_payload(symbols=("BTC",), anchors=("2025-01-01",))
    jobs = build_campaign_jobs(payload)
    for job in jobs:
        if job.arm_id == ARM_B:
            assert job.phase_class_mod_21_days == job.anchor_displacement_days


def test_physical_anchor_equals_base_anchor_plus_displacement_days() -> None:
    payload = make_payload(symbols=("BTC",), anchors=("2025-01-15",))
    jobs = build_campaign_jobs(payload)
    by_control = {job.control_id: job for job in jobs}
    assert by_control["CANONICAL"].physical_anchor_ts_utc == "2025-01-15"
    assert by_control["B2A_M10"].physical_anchor_ts_utc == "2025-01-05"
    assert by_control["B2A_P10"].physical_anchor_ts_utc == "2025-01-25"
    assert by_control["B2A_M01"].physical_anchor_ts_utc == "2025-01-14"
    assert by_control["B2A_P01"].physical_anchor_ts_utc == "2025-01-16"


def test_deterministic_ordering_stable_across_calls() -> None:
    payload = make_payload(symbols=("ETH", "BTC"), anchors=("2025-02-15", "2025-01-01"))
    first = [job.job_id for job in build_campaign_jobs(payload)]
    second = [job.job_id for job in build_campaign_jobs(payload)]
    assert first == second


def test_ordering_arm_a_first_then_b2a_by_numeric_displacement() -> None:
    payload = make_payload(symbols=("BTC",), anchors=("2025-01-01",))
    jobs = build_campaign_jobs(payload)
    assert jobs[0].arm_id == ARM_A
    assert jobs[0].control_id == CANONICAL_CONTROL_ID
    arm_b_jobs = jobs[1:]
    assert [job.arm_id for job in arm_b_jobs] == [ARM_B] * 20
    assert [job.anchor_displacement_days for job in arm_b_jobs] == list(range(-10, 0)) + list(
        range(1, 11)
    )


def test_ordering_groups_by_symbol_then_anchor_within_each_tier() -> None:
    payload = make_payload(symbols=("ETH", "BTC"), anchors=("2025-02-15", "2025-01-01"))
    jobs = build_campaign_jobs(payload)
    arm_a_jobs = [job for job in jobs if job.arm_id == ARM_A]
    assert [(job.symbol, job.base_anchor_ts_utc) for job in arm_a_jobs] == [
        ("ETH", "2025-02-15"),
        ("ETH", "2025-01-01"),
        ("BTC", "2025-02-15"),
        ("BTC", "2025-01-01"),
    ]


def test_job_ids_are_filesystem_safe() -> None:
    payload = make_payload(
        symbols=("BTC",),
        anchors=("2025-01-15T00:00:00Z",),
    )
    jobs = build_campaign_jobs(payload)
    for job in jobs:
        assert ":" not in job.job_id
        assert "+" not in job.job_id
        assert "-" not in job.control_id
        assert job.job_id == f"{job.arm_id}_{job.control_id}_{job.symbol}_2025-01-15T00-00-00Z"


def test_job_ids_match_required_naming_examples() -> None:
    payload = make_payload(symbols=("BTC",), anchors=("2025-01-15",))
    jobs = build_campaign_jobs(payload)
    job_ids = {job.job_id for job in jobs}
    assert "ARM_A_CANONICAL_BTC_2025-01-15" in job_ids
    assert "ARM_B_B2A_M10_BTC_2025-01-15" in job_ids
    assert "ARM_B_B2A_P10_BTC_2025-01-15" in job_ids
