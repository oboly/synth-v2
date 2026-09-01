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

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
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

# The five assets the frozen 2021 Fib Exit Ladder V1 findings actually
# bucketed (docs/research/fib_exit_ladder_v1_findings.md). HBAR/SUI have no
# original bucket and are out of scope for an overall Phase A disposition
# per the contract's § 5/§ 9 (Asset universe handling / Missing-data
# handling); an overall disposition may only be computed once every one of
# these five is represented exactly once.
REQUIRED_ASSET_UNIVERSE = ("LINK", "XLM", "SOL", "XRP", "HOT")

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
class OriginalAssetConfig:
    """One asset's full published 2021 configuration, frozen verbatim from
    the "Key sensitivity result" table in
    docs/research/fib_exit_ladder_v1_findings.md.

    `max_ladder_sell_fraction` is per asset, not a single global value:
    HOT's published EXPLOSIVE_SUPERCYCLE config used 0.40 (large moonbag
    reserve for an explosive mover), while LINK/XLM/SOL/XRP all used 0.80.
    Reproducing "the baseline" means reproducing this full tuple for the
    asset under evaluation, not just its target family — running HOT with
    the other four assets' 0.80 fraction is not a reproduction of the
    published HOT baseline even though the target family would still match.
    """

    symbol: str
    target_family: str
    max_ladder_sell_fraction: Decimal


ORIGINAL_ASSET_CONFIG: dict[str, OriginalAssetConfig] = {
    "LINK": OriginalAssetConfig("LINK", "PRO_3X4X", Decimal("0.80")),
    "XLM": OriginalAssetConfig("XLM", "PRO_3X4X", Decimal("0.80")),
    "SOL": OriginalAssetConfig("SOL", "SUPERCYCLE", Decimal("0.80")),
    "XRP": OriginalAssetConfig("XRP", "SUPERCYCLE", Decimal("0.80")),
    "HOT": OriginalAssetConfig("HOT", "EXPLOSIVE_SUPERCYCLE", Decimal("0.40")),
}


def original_config_for_asset(symbol: str) -> OriginalAssetConfig:
    """The frozen published config for one of the five originally-bucketed
    assets. Raises `KeyError` for any symbol outside `REQUIRED_ASSET_UNIVERSE`
    (including HBAR/SUI, which have no original bucket) rather than
    returning a default or guessed config."""
    return ORIGINAL_ASSET_CONFIG[symbol]


def baseline_config_matches_published(
    *, symbol: str, target_family: str, max_ladder_sell_fraction: Decimal
) -> bool:
    """Whether an evaluated baseline run used this asset's exact published
    original configuration: target family AND max_ladder_sell_fraction
    together. A target-family match alone is not sufficient — e.g. HOT
    evaluated under EXPLOSIVE_SUPERCYCLE at max_ladder_sell_fraction=0.80
    (the other four assets' value) does not match HOT's published 0.40 and
    must return False, forcing a BASELINE_REPRODUCTION_FAILED disposition
    rather than being silently accepted as a reproduction."""
    expected = original_config_for_asset(symbol)
    return (
        target_family == expected.target_family
        and max_ladder_sell_fraction == expected.max_ladder_sell_fraction
    )


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
    alpha_positive_ok_window_count: int,
    bucket_sign_agreement: Optional[bool],
    bucket_rank_agreement_all_ok_windows: Optional[bool],
) -> AssetDisposition:
    """Deterministic per-asset disposition per the frozen Phase A contract.

    `alpha_positive_ok_window_count` is how many of the `validation_windows_ok`
    status=OK validation windows have `alpha_vs_hold_pct > 0`. It must satisfy
    `0 <= alpha_positive_ok_window_count <= validation_windows_ok`. Per
    contract § Acceptance thresholds rule 3, VALIDATED requires
    `alpha_vs_hold_pct > 0` in *every* OK window, not merely a majority — a
    mixed OK-window set (some windows positive, some not) must never resolve
    to VALIDATED even if `bucket_rank_agreement_all_ok_windows` is True.

    Fail-closed: any ambiguous or unreproducible input maps to
    INSUFFICIENT_DATA or REJECTED, never to VALIDATED/REVISED. Malformed
    window counts (`validation_windows_total != 2`, or
    `validation_windows_ok` outside `[0, validation_windows_total]`) raise
    `ValueError` rather than silently coercing into a disposition — the
    frozen contract (§ New validation window(s)) always defines exactly two
    validation windows, so any other total means the caller itself violated
    the contract, and this must never be papered over by returning
    VALIDATED (or any other outcome) from bad input.

    `baseline_reproduced` must be an actual `bool` (`True`/`False`) or
    `None` — any other value (`0`, `1`, a string, etc.) raises `TypeError`
    rather than being coerced by truthiness, since `bool` is an `int`
    subclass and an int/string could otherwise slip past the `is False`
    check and be treated as a successful reproduction.
    """
    if validation_windows_total != 2:
        raise ValueError(
            "validation_windows_total must be exactly 2, per the frozen "
            "contract's two validation windows (§ New validation window(s)); "
            f"got {validation_windows_total}."
        )

    if not (0 <= validation_windows_ok <= validation_windows_total):
        raise ValueError(
            "validation_windows_ok must be between 0 and "
            "validation_windows_total inclusive; got "
            f"{validation_windows_ok} of {validation_windows_total}."
        )

    if baseline_reproduced is not None and not isinstance(baseline_reproduced, bool):
        # `bool` is a subclass of `int` in Python, so `baseline_reproduced is
        # False` below only matches the literal singleton `False` — an int
        # `0` (or `1`, or a truthy/falsy string, or any other non-bool
        # value) is neither `is False` nor `is None`, so it would otherwise
        # silently fall through past the reproduction-failure check below
        # and reach the VALIDATED/REVISED logic as if reproduction had
        # succeeded. Reject any non-bool, non-None value outright instead.
        raise TypeError(
            "baseline_reproduced must be True, False, or None; got "
            f"{baseline_reproduced!r} of type {type(baseline_reproduced).__name__}."
        )

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

    if not (0 <= alpha_positive_ok_window_count <= validation_windows_ok):
        raise ValueError(
            "alpha_positive_ok_window_count must be between 0 and "
            "validation_windows_ok inclusive; got "
            f"{alpha_positive_ok_window_count} of {validation_windows_ok}."
        )

    all_ok_windows_alpha_positive = alpha_positive_ok_window_count == validation_windows_ok
    no_ok_windows_alpha_positive = alpha_positive_ok_window_count == 0

    if all_ok_windows_alpha_positive:
        if bucket_rank_agreement_all_ok_windows is True:
            return AssetDisposition(symbol, OUTCOME_VALIDATED, None)
        if bucket_rank_agreement_all_ok_windows is None:
            # Every OK window is alpha-positive, but whether the originally
            # assigned family remains the best-scoring one was never
            # evaluated. This is missing evidence, not a known disagreement
            # (that would be explicit False) — it must never be inferred as
            # REVISED, and INSUFFICIENT_DATA (missing/unevaluable evidence)
            # is preferred over REJECTED (a contradictory finding) here.
            return AssetDisposition(symbol, OUTCOME_INSUFFICIENT_DATA, None)
        # bucket_rank_agreement_all_ok_windows is False here: falls through
        # to the sign-agreement routing below, same as the mixed-alpha case.

    elif no_ok_windows_alpha_positive:
        # alpha_vs_hold_pct <= 0 in every OK validation window: the ladder
        # never beat holding outside the original window. Reproduction
        # succeeded (rules 0/1 above did not fire), so this is a REJECTED
        # verdict from the methodology itself, distinct from
        # BASELINE_REPRODUCTION_FAILED. This does not depend on rank/sign
        # agreement, so it is unaffected by either being None.
        return AssetDisposition(symbol, OUTCOME_REJECTED, None)

    # Mixed OK-window set (>=1 window positive and >=1 window non-positive),
    # or every OK window positive but rank agreement is known to fail in
    # >=1 of them: not defensible as-is (cannot be VALIDATED), but the
    # ladder still beats hold often enough that it is not automatically a
    # clean REJECTED either. Route on majority sign agreement across the
    # three windows (original + both validation windows), per contract
    # rule 4/5. `bucket_sign_agreement is None` is missing evidence, not a
    # known disagreement, and must never be inferred as REVISED (True) or
    # silently treated as REJECTED (False) — it fails closed to
    # INSUFFICIENT_DATA instead.
    if bucket_sign_agreement is True:
        return AssetDisposition(symbol, OUTCOME_REVISED, None)
    if bucket_sign_agreement is False:
        return AssetDisposition(symbol, OUTCOME_REJECTED, None)
    return AssetDisposition(symbol, OUTCOME_INSUFFICIENT_DATA, None)


def overall_disposition(asset_dispositions: list[AssetDisposition]) -> str:
    """Overall Phase A outcome is the least favorable outcome across the
    complete frozen five-asset universe (`REQUIRED_ASSET_UNIVERSE`:
    LINK, XLM, SOL, XRP, HOT).

    Fails closed:
    - A duplicate symbol, or any asset outside the required five, raises
      `ValueError` — an ambiguous or unexpected identity must never be
      silently included in (or excluded from) the outcome, in either
      direction, since that could make an otherwise-unfavorable result look
      more favorable (e.g. dropping a REJECTED duplicate) or vice versa.
    - A missing required asset is treated exactly as if that asset had
      independently returned INSUFFICIENT_DATA: it can never be omitted to
      obtain a more favorable overall result than the evidence actually
      supports, so an incomplete universe can never yield VALIDATED (or
      anything more favorable than INSUFFICIENT_DATA).
    """
    symbols = [disposition.symbol for disposition in asset_dispositions]

    counts = Counter(symbols)
    duplicated = sorted(symbol for symbol, count in counts.items() if count > 1)
    if duplicated:
        raise ValueError(
            f"overall_disposition received duplicate asset entries: {duplicated}; "
            "each asset must appear at most once."
        )

    unexpected = sorted(set(symbols) - set(REQUIRED_ASSET_UNIVERSE))
    if unexpected:
        raise ValueError(
            "overall_disposition received asset(s) outside the frozen "
            f"five-asset universe {REQUIRED_ASSET_UNIVERSE}: {unexpected}."
        )

    missing = sorted(set(REQUIRED_ASSET_UNIVERSE) - set(symbols))
    effective_dispositions = list(asset_dispositions) + [
        AssetDisposition(symbol, OUTCOME_INSUFFICIENT_DATA, None) for symbol in missing
    ]

    worst_index = min(
        OUTCOME_ORDER.index(disposition.outcome) for disposition in effective_dispositions
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
