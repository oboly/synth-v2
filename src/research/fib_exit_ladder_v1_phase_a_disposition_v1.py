"""
Synth v2.6 research helper: FIB_EXIT_LADDER_V1_PHASE_A_DISPOSITION_V1.

Layer:
    research only. Pure functions, no DB access, no I/O.

Purpose:
    Formalize the deterministic per-asset and overall Phase A disposition
    rules frozen in
    docs/research/fib_exit_ladder_v1_phase_a_validation_contract_v1.md,
    so the outcome enum is exhaustive and fail-closed rather than left to
    ad hoc prose judgement when a findings report is written.

Outcome categories (mutually exclusive):
    VALIDATED, REVISED, REJECTED, INSUFFICIENT_DATA, BLOCKED

REJECTED carries an optional machine-readable `reason`. The only reason
defined so far is BASELINE_REPRODUCTION_FAILED (original/baseline window is
evaluable but does not reproduce the published 2021 findings under the
frozen methodology) — this is distinct from a REJECTED verdict reached by
actually reproducing the methodology and finding it does not beat holding.

Promotion-grade gating (`is_promotion_eligible`) is independent of the
disposition outcome: even a VALIDATED disposition under the current
future-aware anchor detector (see `METHODOLOGY_FUTURE_AWARE` /
FUTURE_AWARE_RESEARCH) can never satisfy #657 Phase B's point-in-time
promotion evidence requirement
(docs/architecture/automatic_exit_profile_promotion_v1.md Section 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

OUTCOME_VALIDATED = "VALIDATED"
OUTCOME_REVISED = "REVISED"
OUTCOME_REJECTED = "REJECTED"
OUTCOME_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
OUTCOME_BLOCKED = "BLOCKED"

OUTCOME_ORDER = (
    OUTCOME_BLOCKED,
    OUTCOME_INSUFFICIENT_DATA,
    OUTCOME_REJECTED,
    OUTCOME_REVISED,
    OUTCOME_VALIDATED,
)

REASON_BASELINE_REPRODUCTION_FAILED = "BASELINE_REPRODUCTION_FAILED"

# The frozen Fib Exit Ladder V1 anchor detector (`find_anchor_set` in
# run_fib_exit_ladder_backtest_v1.py) selects among candidate anchors using
# `future_high`, the max high of candles strictly *after* the candidate
# wave2_low (entry) index, and requires future_high > wave1_high before a
# candidate is even eligible. It therefore cannot confirm an entry using
# only data available at the entry point itself. This is a structural
# property of the frozen methodology (see the Phase A contract's "Look-ahead
# / promotion-grade classification" section and the accompanying test
# `test_anchor_detector_requires_future_data_after_its_own_entry_point`),
# not a per-run condition, so it is a module constant rather than a
# parameter.
METHODOLOGY_FUTURE_AWARE = True
METHODOLOGY_CLASSIFICATION = "FUTURE_AWARE_RESEARCH"


@dataclass(frozen=True)
class AssetDisposition:
    symbol: str
    outcome: str
    reason: Optional[str]


def classify_asset_disposition(
    *,
    symbol: str,
    baseline_evaluable: bool,
    baseline_reproduced: Optional[bool],
    has_original_bucket: bool,
    validation_windows_ok: int,
    validation_windows_total: int,
    bucket_sign_agreement: Optional[bool],
    bucket_rank_agreement_all_ok_windows: Optional[bool],
) -> AssetDisposition:
    """Deterministic per-asset disposition per the frozen Phase A contract.

    Fail-closed: any ambiguous or unreproducible input maps to
    INSUFFICIENT_DATA or REJECTED, never to VALIDATED/REVISED.
    """
    if not has_original_bucket:
        return AssetDisposition(symbol, OUTCOME_INSUFFICIENT_DATA, None)

    if not baseline_evaluable:
        # The original 2020-01-01..2022-01-01 window itself does not
        # reproduce a usable anchor under the frozen methodology; there is
        # no baseline to validate against at all.
        return AssetDisposition(symbol, OUTCOME_INSUFFICIENT_DATA, None)

    if baseline_reproduced is False:
        # Baseline window is evaluable (an anchor was found) but its
        # numbers do not match the published 2021 findings within the
        # contract's rounding tolerance. This must never be treated as
        # promotion evidence and must never resolve to VALIDATED/REVISED,
        # regardless of how the validation windows scored, because Phase A
        # cannot state confidently that the frozen methodology was actually
        # reproduced.
        return AssetDisposition(symbol, OUTCOME_REJECTED, REASON_BASELINE_REPRODUCTION_FAILED)

    if baseline_reproduced is None:
        raise ValueError(
            "baseline_reproduced must be explicitly True or False once "
            "baseline_evaluable is True; ambiguity is not permitted."
        )

    if validation_windows_ok == 0:
        return AssetDisposition(symbol, OUTCOME_INSUFFICIENT_DATA, None)

    if bucket_sign_agreement is False:
        return AssetDisposition(symbol, OUTCOME_REJECTED, None)

    if bucket_rank_agreement_all_ok_windows is True:
        return AssetDisposition(symbol, OUTCOME_VALIDATED, None)

    return AssetDisposition(symbol, OUTCOME_REVISED, None)


def overall_disposition(asset_dispositions: list[AssetDisposition]) -> str:
    """Overall Phase A outcome is the least favorable per-asset outcome."""
    if not asset_dispositions:
        return OUTCOME_INSUFFICIENT_DATA

    worst_index = min(
        OUTCOME_ORDER.index(disposition.outcome) for disposition in asset_dispositions
    )
    return OUTCOME_ORDER[worst_index]


def is_promotion_eligible(*, disposition_outcome: str, methodology_future_aware: bool = METHODOLOGY_FUTURE_AWARE) -> bool:
    """Whether a disposition may back a #657 Phase B promotion evidence claim.

    Always False while the frozen methodology is future-aware, independent
    of how favorable the disposition outcome itself is. A VALIDATED result
    from future-aware research is retrospective bucket-stability evidence
    only; it is not point-in-time promotion-grade evidence per
    docs/architecture/automatic_exit_profile_promotion_v1.md Section 2.
    """
    if methodology_future_aware:
        return False
    return disposition_outcome == OUTCOME_VALIDATED
