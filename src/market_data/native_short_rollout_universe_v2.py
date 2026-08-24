from __future__ import annotations

"""Deterministic Native SHORT bulk-rollout universe (v2).

Boundary: native SHORT market-data, read-only, market-only, account-agnostic.
This module performs no database I/O, no mutation, and no promotion. It is a
pure derivation over an already-computed
``native_short_multi_asset_audit_v1.AuditReport``.

Why this module exists
-----------------------
``native_short_scope_administration_rollout_v1.APPROVED_ROLLOUT_UNIVERSE_V1``
required one hand-written ``RolloutSymbolEntry``, one reviewed
``docs/ops/native_short_<symbol>_bootstrap_promotion_approval_v1.md`` document,
and one digested ``native_short_promotion_bootstrap_manifest_v1.json`` entry
per symbol. That per-symbol-approval-document model was deliberate while
``MULTI_SCOPE_FAILURE_ISOLATION_MISSING`` and ``BOOTSTRAP_ORCHESTRATION_BLOCKED``
were still hardcoded-active global blockers: individual bootstrap evidence was
the *only* way to narrow those two blockers for one named scope's first
promotion (see ``native_short_promotion_bootstrap_evidence_v1``).

Both of those blockers are now evidence-driven and, on current ``main``,
globally closed (Issue #276 / #298) -- so the per-symbol manifest/document
mechanism no longer changes ``decide_administration``'s outcome; the
canonical, unchanged ``native_short_multi_asset_audit_v1`` readiness gate
(market eligibility, ledger consistency, tick/execution-constraint
resolution, freshness, and any *currently* active global blocker) already
decides, deterministically and fail-closed, whether a scope is eligible.
Requiring a second, hand-maintained, per-symbol paper trail on top of that
adds administrative overhead without adding any additional safety the audit
does not already provide.

This module replaces "358 hand-written approval entries" with one
deterministic rule, re-derived fresh on every call from current market state
and the current audit's unchanged readiness classification:

    canonical Bitvavo EUR market universe   (CandidateResult.market_eligible)
    -> native SHORT readiness gate           (CandidateResult.readiness_status, unchanged)
    -> PROMOTE_SCOPE-applicable blockers     (applicable_active_global_blockers, unchanged)
    -> bulk PROMOTE_SCOPE entries            (this module)
    -> existing per-scope transaction         (native_short_scope_administration_transaction_v1,
                                                 unchanged, still the sole mutation owner)

No wildcard runtime input: nothing here accepts a CLI-supplied symbol list.
The universe is derived only from already-fetched canonical market metadata
and the existing readiness evaluator, both already covered by
``native_short_multi_asset_audit_v1``'s own tests and safety markers.

Deliberately not built on ``native_short_multi_asset_audit_v1.classify_rollout_status``:
that function's ``BLOCKED`` branch checks ``CandidateResult.global_rollout_status``,
which ``evaluate_candidate`` sets from *any* nonempty active-blocker tuple,
without filtering by operation applicability the way the real transaction
gate (``native_short_scope_administration_transaction_v1.decide_administration``
via ``applicable_active_global_blockers``) does. ``REMOVAL_CONTRACT_MISSING``
is permanently active by design (no removal-acceptance evidence source
exists yet) and never gates ``PROMOTE_SCOPE`` at the real transaction layer --
but it does make ``classify_rollout_status`` report ``BLOCKED`` for every
scope, always, since ``REMOVAL_CONTRACT_MISSING`` is never absent from
``active_global_blockers``. Reusing it here would make this module's
``READY`` set permanently empty in current production, contradicting the
transaction layer it is supposed to mirror. This module instead reuses the
same ``applicable_active_global_blockers`` the transaction layer itself
uses, so a scope is administratively blocked here if and only if it would
also be blocked by the actual ``PROMOTE_SCOPE`` gate.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
"""

from src.market_data.native_short_multi_asset_audit_v1 import (
    READY_EXISTING_CANARY,
    READY_FOR_SEQUENTIAL_CANARY_REVIEW,
    ROLLOUT_STATUS_ALREADY_SUPPORTED,
    ROLLOUT_STATUS_BLOCKED,
    ROLLOUT_STATUS_READY,
    ROLLOUT_STATUS_SKIPPED_NOT_READY,
    AuditReport,
    CandidateResult,
)
from src.market_data.native_short_scope_administration_rollout_v1 import (
    RolloutSymbolEntry,
)
from src.market_data.native_short_scope_administration_v1 import (
    NativeShortScopeAdministrationOperationType as OperationType,
)
from src.market_data.native_short_scope_administration_transaction_v1 import (
    applicable_active_global_blockers,
)


BULK_ROLLOUT_UNIVERSE_CONTRACT_VERSION = "native_short_rollout_universe_v2"

# Cited as the approval_reference for every entry this module derives, in
# place of a per-symbol docs/ops/*.md file: the "approval" is this module's
# deterministic rule plus the unchanged, already-reviewed
# native_short_multi_asset_audit_v1 readiness gate it reads, not a
# per-symbol human sign-off document.
APPROVAL_REFERENCE = "src/market_data/native_short_rollout_universe_v2.py"

_ENTRY_NOTE = (
    "Deterministic bulk-rollout universe (Issue #276 v2): admitted because "
    "it is a market-eligible canonical Bitvavo EUR scope that the unchanged "
    "native_short_multi_asset_audit_v1 readiness gate currently classifies "
    "READY -- not a manually reviewed per-symbol approval document."
)


def _classify_for_promotion(result: CandidateResult) -> str:
    """Operation-aware rollout classification for exactly ``PROMOTE_SCOPE``.
    See the module docstring for why this cannot reuse
    ``native_short_multi_asset_audit_v1.classify_rollout_status`` -- the
    precedence is otherwise identical: ``ALREADY_SUPPORTED`` wins outright,
    an applicable blocker outranks readiness, ``READY`` requires market and
    ledger readiness, everything else is ``SKIPPED_NOT_READY``."""
    if result.scope_states == ("SUPPORTED",) or result.readiness_status == READY_EXISTING_CANARY:
        return ROLLOUT_STATUS_ALREADY_SUPPORTED
    blocking = applicable_active_global_blockers(
        OperationType.PROMOTE_SCOPE, result.global_blocker_codes
    )
    if blocking:
        return ROLLOUT_STATUS_BLOCKED
    if result.readiness_status == READY_FOR_SEQUENTIAL_CANARY_REVIEW:
        return ROLLOUT_STATUS_READY
    return ROLLOUT_STATUS_SKIPPED_NOT_READY


def universe_market_symbols(report: AuditReport) -> tuple[str, ...]:
    """The canonical Bitvavo EUR native-SHORT market universe: every symbol
    in ``report`` that ``native_short_multi_asset_audit_v1.evaluate_candidate``
    already classifies market-eligible (single canonical market, asset
    enabled, market-data enabled, tradeable). Reads the one existing
    ``CandidateResult.market_eligible`` field; this is deliberately not a
    second, independent filter implementation."""
    return tuple(sorted(r.canonical_key.symbol for r in report.results if r.market_eligible))


def derive_bulk_rollout_entries(report: AuditReport) -> tuple[RolloutSymbolEntry, ...]:
    """Deterministically derive the ``PROMOTE_SCOPE`` entries for one bulk
    rollout run: every candidate in ``report`` that the existing, unchanged
    ``classify_rollout_status`` already classifies ``READY`` -- market-eligible,
    ledger-consistent, not already supported, and with no currently active
    global blocker applicable to ``PROMOTE_SCOPE``.

    Ordered by canonical symbol, matching ``report.results``' own
    deterministic ordering. A rerun against fresh market/ledger state may
    return a different set (a scope can newly qualify, or drop out on a
    regression) -- that is intended: eligibility always follows current
    state, never a frozen repository list.
    """
    ready = [r for r in report.results if _classify_for_promotion(r) == ROLLOUT_STATUS_READY]
    return tuple(
        RolloutSymbolEntry(
            symbol=result.canonical_key.symbol,
            operation_type=OperationType.PROMOTE_SCOPE,
            approval_reference=APPROVAL_REFERENCE,
            note=_ENTRY_NOTE,
        )
        for result in sorted(ready, key=lambda r: r.canonical_key.symbol)
    )


def is_symbol_bulk_rollout_eligible(report: AuditReport, symbol: str) -> tuple[bool, str]:
    """Single-scope eligibility check sharing exactly the same universe and
    readiness definition ``derive_bulk_rollout_entries`` uses, for CLI parity:
    the single-scope administration CLI must apply the identical gate a bulk
    run would, rather than accepting an arbitrary symbol unconditionally.

    Returns ``(eligible, reason)``. ``reason`` is ``"READY"`` when eligible,
    or the symbol's current ``_classify_for_promotion`` value (
    ``ALREADY_SUPPORTED`` / ``SKIPPED_NOT_READY`` / ``BLOCKED``) or
    ``"SYMBOL_NOT_IN_CANONICAL_MARKET_UNIVERSE"`` when not.
    """
    canonical_symbol = symbol.strip().upper()
    result: CandidateResult | None = next(
        (r for r in report.results if r.canonical_key.symbol == canonical_symbol), None
    )
    if result is None:
        return False, "SYMBOL_NOT_IN_CANONICAL_MARKET_UNIVERSE"
    status = _classify_for_promotion(result)
    if status == ROLLOUT_STATUS_READY:
        return True, "READY"
    return False, status


def classify_symbol_for_single_scope_promotion(
    report: AuditReport, symbol: str
) -> tuple[bool, str]:
    """Parity gate for the single-scope administration CLI's ``PROMOTE_SCOPE``
    operation. Deliberately wider than ``is_symbol_bulk_rollout_eligible``:
    it also permits ``ALREADY_SUPPORTED`` (an idempotent replay of an
    already-completed promotion, e.g. re-running the identical operation UUID
    for ops/test purposes -- the existing rollout orchestrator's own
    idempotent-rerun contract already relies on this being harmless), not
    only a fresh ``READY`` first promotion. Still rejects
    ``BLOCKED``/``SKIPPED_NOT_READY``/unknown-symbol exactly like the bulk
    gate: an unready or ineligible scope may never reach ``PROMOTE_SCOPE``
    through either path.
    """
    canonical_symbol = symbol.strip().upper()
    result: CandidateResult | None = next(
        (r for r in report.results if r.canonical_key.symbol == canonical_symbol), None
    )
    if result is None:
        return False, "SYMBOL_NOT_IN_CANONICAL_MARKET_UNIVERSE"
    status = _classify_for_promotion(result)
    if status in (ROLLOUT_STATUS_READY, ROLLOUT_STATUS_ALREADY_SUPPORTED):
        return True, status
    return False, status


__all__ = [
    "BULK_ROLLOUT_UNIVERSE_CONTRACT_VERSION",
    "APPROVAL_REFERENCE",
    "universe_market_symbols",
    "derive_bulk_rollout_entries",
    "is_symbol_bulk_rollout_eligible",
    "classify_symbol_for_single_scope_promotion",
]
