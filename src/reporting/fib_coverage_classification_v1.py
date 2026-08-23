"""Per-symbol Fib coverage classification for Profit Plan (Issue #489).

The #486 production audit found that "no Fib authority row for this symbol"
was reported with a single generic reason (``FIB_MAP_SYMBOL_MISSING``) that
does not distinguish an expected-but-broken publication from a symbol that
was never enrolled in the canonical publication cohort and is only rendered
through an account overlay (held asset / open order / manual asset config).

This module is read-only, market/account-fact classification only. It does
not compute, mutate, or promote publication-cohort membership, native SHORT
scope, or account overlay state -- it consumes those already-resolved facts
(``is_market_selected`` / ``is_core_sensor`` from
``asset.is_publication_cohort`` / core-sensor enrollment, ``is_wallet_held`` /
``is_portfolio_asset`` / open-order presence from the rendered account scope,
and ``native_short_scope_support_state`` from the native SHORT scope-status
projection) and derives one explicit, stable, per-symbol classification.

Reason vocabulary is intentionally compact and mutually exclusive per card:

    FIB_MAP_AVAILABLE               -- an authority (canonical 4h or native
                                        SHORT) is usable for this symbol.
    FIB_MAP_STALE                   -- canonical row exists but is stale.
    FIB_MAP_UNAVAILABLE             -- canonical row exists but is not usable
                                        (bad map_status / missing timestamp).
    FIB_MAP_EXPECTED_BUT_MISSING    -- canonical publication cohort/core
                                        sensor enrolled, but no row exists.
    ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE -- not enrolled in the canonical
                                        publication cohort; rendered only
                                        through an account overlay (held
                                        asset, open order, or manual asset
                                        config).
    FIB_MAP_NOT_ENROLLED            -- not enrolled and no known account
                                        overlay origin (fallback; should be
                                        rare given the account-scoped market
                                        universe).
    NOT_APPLICABLE                  -- native SHORT or legacy 1d context
                                        already supplies authority for this
                                        symbol; canonical-row absence is not
                                        the operative reason.
    FIB_MAP_SOURCE_UNAVAILABLE      -- the whole canonical Fib source failed
                                        to load. Distinct from
                                        FIB_MAP_EXPECTED_BUT_MISSING /
                                        ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE /
                                        FIB_MAP_NOT_ENROLLED: when the source
                                        itself is unreadable, no per-symbol
                                        enrollment or absence conclusion is
                                        truthful for anyone in that render.

Native SHORT scope/row state are tracked as two independent fields so that
"unsupported/not enrolled" never collapses into the same bucket as
"supported but the row is missing" (#489 items E/F).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


CANONICAL_SCOPE_ENROLLED = "ENROLLED"
CANONICAL_SCOPE_NOT_ENROLLED = "NOT_ENROLLED"

CANONICAL_ROW_AVAILABLE = "AVAILABLE"
CANONICAL_ROW_STALE = "STALE"
CANONICAL_ROW_UNAVAILABLE = "UNAVAILABLE"
CANONICAL_ROW_ABSENT = "ABSENT"
CANONICAL_ROW_NOT_APPLICABLE = "NOT_APPLICABLE"
# The whole canonical Fib source (not just this symbol's row) is unavailable.
# Distinct from ABSENT: ABSENT means the source was readable and this symbol
# has no row in it, which is meaningful evidence for an enrollment
# conclusion. SOURCE_UNAVAILABLE means the source could not be read at all,
# so no per-symbol enrollment/absence conclusion is truthful.
CANONICAL_ROW_SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"

# Native SHORT scope vocabulary matches
# src.market_data.native_short_scope_status_v1.NativeShortScopeSupportEventState.
NATIVE_SCOPE_SUPPORTED = "SUPPORTED"
NATIVE_SCOPE_NOT_APPLICABLE = "NOT_APPLICABLE"
NATIVE_SCOPE_UNKNOWN = "UNKNOWN"

NATIVE_ROW_AVAILABLE = "AVAILABLE"
NATIVE_ROW_PARTIAL = "PARTIAL"
NATIVE_ROW_ABSENT = "ABSENT"

ORIGIN_GLOBAL_PUBLICATION_COHORT = "GLOBAL_PUBLICATION_COHORT"
ORIGIN_ACCOUNT_POSITION_HELD = "ACCOUNT_POSITION_HELD"
ORIGIN_ACCOUNT_OPEN_ORDER = "ACCOUNT_OPEN_ORDER"
ORIGIN_ACCOUNT_ASSET_CONFIG = "ACCOUNT_ASSET_CONFIG"
ORIGIN_UNKNOWN = "UNKNOWN"

_ACCOUNT_OVERLAY_ORIGINS = frozenset({
    ORIGIN_ACCOUNT_POSITION_HELD,
    ORIGIN_ACCOUNT_OPEN_ORDER,
    ORIGIN_ACCOUNT_ASSET_CONFIG,
})

REASON_FIB_MAP_AVAILABLE = "FIB_MAP_AVAILABLE"
REASON_FIB_MAP_STALE = "FIB_MAP_STALE"
REASON_FIB_MAP_UNAVAILABLE = "FIB_MAP_UNAVAILABLE"
REASON_FIB_MAP_EXPECTED_BUT_MISSING = "FIB_MAP_EXPECTED_BUT_MISSING"
REASON_ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE = "ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE"
REASON_FIB_MAP_NOT_ENROLLED = "FIB_MAP_NOT_ENROLLED"
REASON_NOT_APPLICABLE = "NOT_APPLICABLE"
# Whole-source unavailability. Never combined with an enrollment/scope
# conclusion (FIB_MAP_EXPECTED_BUT_MISSING / ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE
# / FIB_MAP_NOT_ENROLLED) -- the source could not be read, so this symbol's
# per-row truth (and therefore any enrollment-relative conclusion) is
# unknown, not "missing" or "out of scope".
REASON_FIB_MAP_SOURCE_UNAVAILABLE = "FIB_MAP_SOURCE_UNAVAILABLE"

# Reasons that already carry usable/expected Fib authority — never appended
# as a supplemental card reason and never counted as a coverage gap.
_NON_GAP_REASONS = frozenset({REASON_FIB_MAP_AVAILABLE, REASON_NOT_APPLICABLE})

# short_context_coverage_status / short_context_input_status values (defined in
# src.reporting.run_manual_short_trader_profit_plan_v1) that this module maps
# into a canonical_fib_row_state without re-deriving canonical-row truth.
_COVERAGE_STATUS_CANONICAL_AVAILABLE = "CANONICAL_4H_CONTEXT_AVAILABLE"
_INPUT_STATUS_CANONICAL_STALE = "CANONICAL_4H_CONTEXT_STALE"
_INPUT_STATUS_CANONICAL_UNAVAILABLE = "CANONICAL_4H_CONTEXT_UNAVAILABLE"
_COVERAGE_STATUS_FIB_MAP_SYMBOL_MISSING = "FIB_MAP_SYMBOL_MISSING"
_COVERAGE_STATUS_FIB_MAP_SOURCE_MISSING = "FIB_MAP_SOURCE_MISSING"
_COVERAGE_STATUS_NATIVE_SHORT_AVAILABLE = "NATIVE_SHORT_CONTEXT_AVAILABLE"
_INPUT_STATUS_NATIVE_SHORT_AVAILABLE = "NATIVE_SHORT_CONTEXT_AVAILABLE"
_PARTIAL_NATIVE_COVERAGE_STATUSES = frozenset({
    "INSUFFICIENT_4H_HISTORY",
    "INSUFFICIENT_1H_HISTORY",
    "MARKET_DATA_MISSING",
    "CONTEXT_INVALID_OR_STALE",
    "TRANSIENT_NON_CANONICAL_CONTEXT_AVAILABLE",
})


@dataclass(frozen=True)
class FibCoverageClassification:
    """Immutable, read-only per-symbol Fib coverage classification."""

    canonical_fib_scope_state: str
    canonical_fib_row_state: str
    native_short_scope_state: str
    native_short_row_state: str
    rendered_scope_origin: str
    fib_coverage_reason: str

    def to_json(self) -> dict[str, str]:
        return {
            "canonical_fib_scope_state": self.canonical_fib_scope_state,
            "canonical_fib_row_state": self.canonical_fib_row_state,
            "native_short_scope_state": self.native_short_scope_state,
            "native_short_row_state": self.native_short_row_state,
            "rendered_scope_origin": self.rendered_scope_origin,
            "fib_coverage_reason": self.fib_coverage_reason,
        }


def classify_fib_coverage(
    *,
    short_context_coverage_status: str,
    short_context_input_status: str,
    is_market_selected: bool,
    is_core_sensor: bool,
    is_wallet_held: bool,
    is_portfolio_asset: bool,
    has_open_order: bool,
    native_short_scope_state: str = NATIVE_SCOPE_UNKNOWN,
) -> FibCoverageClassification:
    """Classify one symbol's Fib coverage from already-resolved canonical facts.

    This never infers enrollment from row presence/absence, and never treats
    absence of a row as proof of "unsupported" -- ``canonical_fib_scope_state``
    and ``native_short_scope_state`` are taken from separately-resolved
    enrollment facts (publication cohort / core sensor / native SHORT scope
    status), independent of whether a row happens to exist.
    """
    canonical_fib_scope_state = (
        CANONICAL_SCOPE_ENROLLED if (is_market_selected or is_core_sensor) else CANONICAL_SCOPE_NOT_ENROLLED
    )

    if short_context_coverage_status == _COVERAGE_STATUS_CANONICAL_AVAILABLE:
        canonical_fib_row_state = CANONICAL_ROW_AVAILABLE
    elif short_context_input_status == _INPUT_STATUS_CANONICAL_STALE:
        canonical_fib_row_state = CANONICAL_ROW_STALE
    elif short_context_input_status == _INPUT_STATUS_CANONICAL_UNAVAILABLE:
        canonical_fib_row_state = CANONICAL_ROW_UNAVAILABLE
    elif short_context_coverage_status == _COVERAGE_STATUS_FIB_MAP_SYMBOL_MISSING:
        canonical_fib_row_state = CANONICAL_ROW_ABSENT
    elif short_context_coverage_status == _COVERAGE_STATUS_FIB_MAP_SOURCE_MISSING:
        # The whole source failed to load -- this is not evidence that *this*
        # symbol's row is absent, only that nothing could be read for anyone.
        canonical_fib_row_state = CANONICAL_ROW_SOURCE_UNAVAILABLE
    else:
        # Native SHORT or legacy 1d context already supplies authority for
        # this symbol -- canonical-row absence is not the operative reason.
        canonical_fib_row_state = CANONICAL_ROW_NOT_APPLICABLE

    if (
        short_context_coverage_status == _COVERAGE_STATUS_NATIVE_SHORT_AVAILABLE
        or short_context_input_status == _INPUT_STATUS_NATIVE_SHORT_AVAILABLE
    ):
        native_short_row_state = NATIVE_ROW_AVAILABLE
    elif (
        short_context_coverage_status in _PARTIAL_NATIVE_COVERAGE_STATUSES
        and native_short_scope_state == NATIVE_SCOPE_SUPPORTED
    ):
        native_short_row_state = NATIVE_ROW_PARTIAL
    else:
        native_short_row_state = NATIVE_ROW_ABSENT

    if is_market_selected or is_core_sensor:
        rendered_scope_origin = ORIGIN_GLOBAL_PUBLICATION_COHORT
    elif is_wallet_held:
        rendered_scope_origin = ORIGIN_ACCOUNT_POSITION_HELD
    elif has_open_order:
        rendered_scope_origin = ORIGIN_ACCOUNT_OPEN_ORDER
    elif is_portfolio_asset:
        rendered_scope_origin = ORIGIN_ACCOUNT_ASSET_CONFIG
    else:
        rendered_scope_origin = ORIGIN_UNKNOWN

    if canonical_fib_row_state == CANONICAL_ROW_AVAILABLE or native_short_row_state == NATIVE_ROW_AVAILABLE:
        fib_coverage_reason = REASON_FIB_MAP_AVAILABLE
    elif canonical_fib_row_state == CANONICAL_ROW_STALE:
        fib_coverage_reason = REASON_FIB_MAP_STALE
    elif canonical_fib_row_state == CANONICAL_ROW_UNAVAILABLE:
        fib_coverage_reason = REASON_FIB_MAP_UNAVAILABLE
    elif canonical_fib_row_state == CANONICAL_ROW_SOURCE_UNAVAILABLE:
        # The source itself could not be read -- never draw a per-symbol
        # enrollment/absence conclusion (EXPECTED_BUT_MISSING /
        # ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE / NOT_ENROLLED) from that.
        fib_coverage_reason = REASON_FIB_MAP_SOURCE_UNAVAILABLE
    elif canonical_fib_row_state == CANONICAL_ROW_ABSENT:
        if canonical_fib_scope_state == CANONICAL_SCOPE_ENROLLED:
            fib_coverage_reason = REASON_FIB_MAP_EXPECTED_BUT_MISSING
        elif rendered_scope_origin in _ACCOUNT_OVERLAY_ORIGINS:
            fib_coverage_reason = REASON_ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE
        else:
            fib_coverage_reason = REASON_FIB_MAP_NOT_ENROLLED
    else:
        fib_coverage_reason = REASON_NOT_APPLICABLE

    return FibCoverageClassification(
        canonical_fib_scope_state=canonical_fib_scope_state,
        canonical_fib_row_state=canonical_fib_row_state,
        native_short_scope_state=native_short_scope_state,
        native_short_row_state=native_short_row_state,
        rendered_scope_origin=rendered_scope_origin,
        fib_coverage_reason=fib_coverage_reason,
    )


_REASON_DISPLAY_TEXT: dict[str, str] = {
    REASON_FIB_MAP_EXPECTED_BUT_MISSING: (
        "Canonical 4h publication cohort/core-sensor enrolled, but no canonical "
        "Fib map row is published for this symbol yet."
    ),
    REASON_ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE: (
        "Not enrolled in the canonical 4h publication cohort or core-sensor scope; "
        "rendered only because of an account overlay (held asset, open order, or "
        "manual asset config)."
    ),
    REASON_FIB_MAP_NOT_ENROLLED: (
        "Not enrolled in the canonical 4h publication cohort or core-sensor scope."
    ),
    REASON_FIB_MAP_STALE: "Canonical Fib map row exists but is stale.",
    REASON_FIB_MAP_UNAVAILABLE: "Canonical Fib map row exists but is not usable.",
    REASON_FIB_MAP_SOURCE_UNAVAILABLE: (
        "The canonical Fib map source could not be read at all, so whether this "
        "symbol is enrolled or has a row is currently unknown -- not missing, not "
        "out of scope."
    ),
}


def fib_coverage_reason_text(classification: FibCoverageClassification) -> str | None:
    """Human-readable supplemental reason, or None when there is no gap to explain."""
    if classification.fib_coverage_reason in _NON_GAP_REASONS:
        return None
    return _REASON_DISPLAY_TEXT.get(classification.fib_coverage_reason)


def summarize_fib_coverage_reasons(
    classifications: Iterable[FibCoverageClassification],
) -> dict[str, int]:
    """Per-reason counts, computed from the same per-symbol classification exposed
    in JSON/HTML. Callers must sum this dict to exactly the classified symbol
    count -- it is not an independently-derived aggregate."""
    summary: dict[str, int] = {
        REASON_FIB_MAP_AVAILABLE: 0,
        REASON_FIB_MAP_STALE: 0,
        REASON_FIB_MAP_UNAVAILABLE: 0,
        REASON_FIB_MAP_EXPECTED_BUT_MISSING: 0,
        REASON_ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE: 0,
        REASON_FIB_MAP_NOT_ENROLLED: 0,
        REASON_FIB_MAP_SOURCE_UNAVAILABLE: 0,
        REASON_NOT_APPLICABLE: 0,
    }
    for classification in classifications:
        reason = classification.fib_coverage_reason
        summary[reason] = summary.get(reason, 0) + 1
    return summary
