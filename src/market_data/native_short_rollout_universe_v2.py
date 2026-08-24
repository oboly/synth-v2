from __future__ import annotations

"""Native SHORT bulk PROMOTE_SCOPE readiness derivation (v2).

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
per symbol. That per-symbol-approval-document model was necessary while
``MULTI_SCOPE_FAILURE_ISOLATION_MISSING`` and ``BOOTSTRAP_ORCHESTRATION_BLOCKED``
were hardcoded-active global blockers: individual bootstrap evidence was the
only way to narrow those two blockers for one named scope's first promotion.

Both are now evidence-driven and, on current ``main``, globally closed
(#276/#298) -- so the per-symbol manifest/document mechanism no longer
changes ``decide_administration``'s outcome. The unchanged, already-reviewed
``native_short_multi_asset_audit_v1`` readiness gate already decides
eligibility deterministically and fail-closed on its own; a second,
hand-maintained per-symbol approval layer on top of it adds no safety this
module's two checks below don't already provide.

Target flow (Issue #276):

    canonical Bitvavo EUR market            (venue_market / asset, unchanged)
    -> native SHORT readiness                (CandidateResult.readiness_status, unchanged)
    -> PROMOTE_SCOPE-applicable blockers      (applicable_active_global_blockers, unchanged)
    -> per-scope PROMOTE_SCOPE transaction    (native_short_scope_administration_transaction_v1, unchanged)

No new classification vocabulary and no approval/universe concept: this
module reads ``CandidateResult.readiness_status`` and
``CandidateResult.global_blocker_codes`` directly and calls the existing
``applicable_active_global_blockers`` -- it does not reimplement, wrap, or
duplicate blocker-precedence logic. It is deliberately NOT built on
``native_short_multi_asset_audit_v1.classify_rollout_status``: that
function's ``BLOCKED`` branch treats *any* active global blocker as
blocking, without filtering by operation applicability, so with
``REMOVAL_CONTRACT_MISSING`` permanently active (it never gates
``PROMOTE_SCOPE``) it reports every scope ``BLOCKED``, always. Fixing
``classify_rollout_status`` itself belongs to its owning module and is
intentionally out of scope here (tracked separately) -- this module simply
does not route through it.

No wildcard runtime input: nothing here accepts a CLI-supplied symbol list.
Eligibility is derived only from already-fetched canonical market metadata
and the existing readiness evaluator, both already covered by
``native_short_multi_asset_audit_v1``'s own tests and safety markers.

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
    READY_FOR_SEQUENTIAL_CANARY_REVIEW,
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


def _find_result(report: AuditReport, symbol: str) -> CandidateResult | None:
    canonical_symbol = symbol.strip().upper()
    return next(
        (r for r in report.results if r.canonical_key.symbol == canonical_symbol), None
    )


def ready_symbols(report: AuditReport) -> tuple[str, ...]:
    """Every canonical symbol in ``report`` currently eligible for a first
    ``PROMOTE_SCOPE``: market-eligible, ledger-consistent, and
    market/ledger-ready per the unchanged
    ``native_short_multi_asset_audit_v1`` readiness gate
    (``readiness_status == READY_FOR_SEQUENTIAL_CANARY_REVIEW``), with no
    currently active global blocker applicable to ``PROMOTE_SCOPE``
    (``applicable_active_global_blockers``, unchanged). Not already
    supported.

    Sorted by canonical symbol. A rerun against fresh market/ledger state may
    return a different set -- that is intended: eligibility always follows
    current state, never a frozen repository list.
    """
    ready = []
    for result in report.results:
        if result.readiness_status != READY_FOR_SEQUENTIAL_CANARY_REVIEW:
            continue
        if applicable_active_global_blockers(
            OperationType.PROMOTE_SCOPE, result.global_blocker_codes
        ):
            continue
        ready.append(result.canonical_key.symbol)
    return tuple(sorted(ready))


def derive_bulk_rollout_entries(report: AuditReport) -> tuple[RolloutSymbolEntry, ...]:
    """One ``PROMOTE_SCOPE`` entry per ``ready_symbols(report)`` symbol, for
    the existing rollout orchestrator (``native_short_scope_administration_rollout_v1``)
    to process unchanged -- same per-scope transaction, isolation, and
    idempotent-rerun contract as any other entry. No approval reference and
    no note: nothing here stands in for a human sign-off document."""
    return tuple(
        RolloutSymbolEntry(symbol=symbol, operation_type=OperationType.PROMOTE_SCOPE)
        for symbol in ready_symbols(report)
    )


def is_symbol_promote_scope_ready(report: AuditReport, symbol: str) -> tuple[bool, str]:
    """Single-scope guard sharing exactly the same two facts
    ``ready_symbols`` checks, for CLI parity: the single-scope administration
    CLI must apply the identical gate a bulk run would, rather than accepting
    an arbitrary symbol unconditionally.

    Also permits an already-``SUPPORTED`` scope (raw ``scope_states``, not a
    derived status) -- an idempotent replay of an already-completed
    promotion, e.g. re-running the identical operation UUID for ops/test
    purposes, which the existing rollout orchestrator's own idempotent-rerun
    contract already relies on being harmless.

    Returns ``(eligible, reason)``. ``reason`` is ``"READY"`` or
    ``"ALREADY_SUPPORTED"`` when eligible; otherwise the failing
    ``readiness_status``, ``"BLOCKED"``, or
    ``"SYMBOL_NOT_IN_CANONICAL_MARKET_UNIVERSE"``.
    """
    result = _find_result(report, symbol)
    if result is None:
        return False, "SYMBOL_NOT_IN_CANONICAL_MARKET_UNIVERSE"
    if result.scope_states == ("SUPPORTED",):
        return True, "ALREADY_SUPPORTED"
    if result.readiness_status != READY_FOR_SEQUENTIAL_CANARY_REVIEW:
        return False, result.readiness_status
    if applicable_active_global_blockers(
        OperationType.PROMOTE_SCOPE, result.global_blocker_codes
    ):
        return False, "BLOCKED"
    return True, "READY"


__all__ = [
    "ready_symbols",
    "derive_bulk_rollout_entries",
    "is_symbol_promote_scope_ready",
]
