"""
Breathline V1 recovery deterministic campaign matrix.

Arm A canonical jobs plus Arm B B.2a integer-day phase-null controls only.
Pure functions: no subprocess execution, no filesystem I/O, no manifest
validation (that belongs to breathline_v1_recovery_cohort_manifest_v1).

Safety markers:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.research.breathline_v1_recovery_cohort_manifest_v1 import CohortPayload

ARM_A = "ARM_A"
ARM_B = "ARM_B"
CANONICAL_CONTROL_ID = "CANONICAL"
ARM_A_RUN_ID_PREFIX = "arm_a"
ARM_B_RUN_ID_PREFIX = "arm_b"

# B.2a INTEGER_DAY_PHASE_NULL_CONTROL: 20 distinct non-zero integer-day
# displacements. No two values in this set are modulo-21 aliases of each
# other, so phase_class_mod_21_days equals anchor_displacement_days here.
B2A_DISPLACEMENTS: tuple[int, ...] = tuple(range(-10, 0)) + tuple(range(1, 11))


@dataclass(frozen=True)
class CampaignJob:
    job_id: str
    arm_id: str
    control_id: str
    run_id_prefix: str
    symbol: str
    base_anchor_ts_utc: str
    physical_anchor_ts_utc: str
    anchor_displacement_days: int
    phase_class_mod_21_days: int


def _b2a_control_id(displacement_days: int) -> str:
    sign = "M" if displacement_days < 0 else "P"
    return f"B2A_{sign}{abs(displacement_days):02d}"


def _filesystem_safe_anchor(anchor_ts_utc: str) -> str:
    return anchor_ts_utc.replace(":", "-")


def _parse_anchor(anchor_ts_utc: str) -> tuple[datetime, bool]:
    is_date_only = (
        len(anchor_ts_utc) == 10 and anchor_ts_utc.count("-") == 2 and "T" not in anchor_ts_utc
    )
    if is_date_only:
        return datetime.strptime(anchor_ts_utc, "%Y-%m-%d").replace(tzinfo=timezone.utc), True
    value = anchor_ts_utc.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc), False


def _format_anchor(moment: datetime, is_date_only: bool) -> str:
    if is_date_only:
        return moment.strftime("%Y-%m-%d")
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _physical_anchor(base_anchor_ts_utc: str, displacement_days: int) -> str:
    parsed, is_date_only = _parse_anchor(base_anchor_ts_utc)
    shifted = parsed + timedelta(days=displacement_days)
    return _format_anchor(shifted, is_date_only)


def _build_arm_a_job(symbol: str, base_anchor_ts_utc: str) -> CampaignJob:
    safe_anchor = _filesystem_safe_anchor(base_anchor_ts_utc)
    return CampaignJob(
        job_id=f"{ARM_A}_{CANONICAL_CONTROL_ID}_{symbol}_{safe_anchor}",
        arm_id=ARM_A,
        control_id=CANONICAL_CONTROL_ID,
        run_id_prefix=ARM_A_RUN_ID_PREFIX,
        symbol=symbol,
        base_anchor_ts_utc=base_anchor_ts_utc,
        physical_anchor_ts_utc=base_anchor_ts_utc,
        anchor_displacement_days=0,
        phase_class_mod_21_days=0,
    )


def _build_b2a_job(symbol: str, base_anchor_ts_utc: str, displacement_days: int) -> CampaignJob:
    control_id = _b2a_control_id(displacement_days)
    safe_anchor = _filesystem_safe_anchor(base_anchor_ts_utc)
    return CampaignJob(
        job_id=f"{ARM_B}_{control_id}_{symbol}_{safe_anchor}",
        arm_id=ARM_B,
        control_id=control_id,
        run_id_prefix=ARM_B_RUN_ID_PREFIX,
        symbol=symbol,
        base_anchor_ts_utc=base_anchor_ts_utc,
        physical_anchor_ts_utc=_physical_anchor(base_anchor_ts_utc, displacement_days),
        anchor_displacement_days=displacement_days,
        phase_class_mod_21_days=displacement_days,
    )


def _control_sort_key(control_id: str) -> tuple[int, int]:
    if control_id == CANONICAL_CONTROL_ID:
        return (0, 0)
    token = control_id.removeprefix("B2A_")
    sign = -1 if token.startswith("M") else 1
    magnitude = int(token[1:])
    return (1, sign * magnitude)


def build_campaign_jobs(payload: CohortPayload) -> list[CampaignJob]:
    """Enumerate the deterministic Arm A + B.2a job matrix for a cohort.

    Ordering: all Arm A canonical jobs first, then all B.2a controls in
    numeric displacement order (-10 ... -1, +1 ... +10); within each tier,
    canonical symbol order, then canonical base-anchor order.
    """
    symbol_order = {symbol: index for index, symbol in enumerate(payload.canonical_symbols)}
    anchor_order = {anchor: index for index, anchor in enumerate(payload.canonical_base_anchors)}

    jobs: list[CampaignJob] = []
    for symbol in payload.canonical_symbols:
        for base_anchor in payload.canonical_base_anchors:
            jobs.append(_build_arm_a_job(symbol, base_anchor))
            for displacement_days in B2A_DISPLACEMENTS:
                jobs.append(_build_b2a_job(symbol, base_anchor, displacement_days))

    def sort_key(job: CampaignJob) -> tuple:
        return (
            0 if job.arm_id == ARM_A else 1,
            _control_sort_key(job.control_id),
            symbol_order[job.symbol],
            anchor_order[job.base_anchor_ts_utc],
        )

    return sorted(jobs, key=sort_key)
