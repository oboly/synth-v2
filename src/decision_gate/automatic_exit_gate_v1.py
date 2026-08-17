"""Pure account-permission gate for :class:`AutomaticExitCandidateV1`.

This is deliberately a bounded permission layer.  It consumes account and
position evidence assembled by a caller, never fetches it, and does not
create reservations, plans, orders, or broker payloads.  In particular it
does not re-evaluate target/invalidation conditions or change the policy's
REDUCE/EXIT choice.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from src.decision_gate.account_protection_contract_v1 import (
    AccountProtectionContractError,
    AccountProtectionEvaluationV1,
    STATE_BLOCKED as PROTECTION_STATE_BLOCKED,
    validate_account_protection_evaluation_binding_v1,
)
from src.exit_policy import POLICY_NAME, POLICY_VERSION
from src.exit_policy.automatic_exit_candidate_v1 import AutomaticExitCandidateV1


STATE_APPROVED: Final[str] = "APPROVED"
STATE_DENIED: Final[str] = "DENIED"
STATE_NON_ACTIONABLE: Final[str] = "NON_ACTIONABLE"

REASON_OK: Final[str] = "OK"
REASON_INVALID_CANDIDATE: Final[str] = "INVALID_AUTOMATIC_EXIT_CANDIDATE"
REASON_UNSUPPORTED_POLICY_CONTRACT: Final[str] = "UNSUPPORTED_AUTOMATIC_EXIT_POLICY_CONTRACT"
REASON_IDENTITY_MISMATCH: Final[str] = "CANDIDATE_ACCOUNT_POSITION_IDENTITY_MISMATCH"
REASON_ACCOUNT_EVIDENCE_STALE: Final[str] = "ACCOUNT_EVIDENCE_STALE"
REASON_CANDIDATE_EVIDENCE_STALE: Final[str] = "CANDIDATE_EVIDENCE_STALE"
REASON_POSITION_EVIDENCE_STALE: Final[str] = "POSITION_EVIDENCE_STALE"
REASON_FREE_QUANTITY_EVIDENCE_STALE: Final[str] = "FREE_QUANTITY_EVIDENCE_STALE"
REASON_INVALID_TIMESTAMP: Final[str] = "NAIVE_OR_INVALID_TIMESTAMP"
REASON_INVALID_ACCOUNT_EVIDENCE: Final[str] = "INVALID_ACCOUNT_EVIDENCE"
REASON_INVALID_POSITION_EVIDENCE: Final[str] = "INVALID_POSITION_EVIDENCE"
REASON_ACCOUNT_DISABLED: Final[str] = "ACCOUNT_DISABLED"
REASON_EXECUTION_PERMISSION_DISABLED: Final[str] = "AUTOMATIC_EXIT_EXECUTION_PERMISSION_DISABLED"
REASON_LIVE_EXECUTION_NOT_GRANTED: Final[str] = "LIVE_EXECUTION_NOT_GRANTED"
REASON_BLOCKING_CONFLICT: Final[str] = "BLOCKING_SELL_RESERVATION_OR_ORDER_CONFLICT"
REASON_NO_FREE_QUANTITY: Final[str] = "NO_FREE_UNRESERVED_QUANTITY"
REASON_RISK_BOUND_UNRESOLVED: Final[str] = "AUTOMATIC_EXIT_RISK_BOUND_UNRESOLVED"


@dataclass(frozen=True)
class AutomaticExitGateContextV1:
    """Fresh, account-owned facts for one exact automatic-exit candidate.

    ``automatic_exit_execution_enabled`` is an explicit permission for this
    lane.  ``live_trading_enabled`` must remain false in Phase 2: this pure
    contract grants no LIVE authority.  ``blocking_conflict`` represents any
    active reservation/open-order state which cannot safely coexist with the
    proposed SELL.
    """

    trading_account_id: int
    position_reference: str
    venue: str
    asset_id: int
    market: str
    position_snapshot_id: str
    held_quantity_base: Decimal
    free_quantity_base: Decimal
    account_observed_ts_utc: datetime
    position_observed_ts_utc: datetime
    free_quantity_observed_ts_utc: datetime
    account_enabled: bool
    account_mode: str
    automatic_exit_execution_enabled: bool
    live_trading_enabled: bool
    blocking_conflict: bool
    evaluation_ts_utc: datetime
    max_account_age_seconds: int = 15 * 60
    max_candidate_age_seconds: int = 15 * 60
    max_position_age_seconds: int = 15 * 60
    max_free_quantity_age_seconds: int = 15 * 60
    # A caller may supply a stricter account risk ceiling.  None means the
    # account evidence has no additional cap, not that planner may bypass
    # the candidate/free-quantity bounds.
    max_automatic_exit_quantity_base: Decimal | None = None
    # P2 supplies an action-aware evaluation from decision_gate. Exit policy
    # remains unaware of protection internals.
    account_protection_evaluation: AccountProtectionEvaluationV1 | None = None


@dataclass(frozen=True)
class AutomaticExitGateDecisionV1:
    state: str  # APPROVED | DENIED | NON_ACTIONABLE
    reason_code: str
    candidate: AutomaticExitCandidateV1
    approved_fraction_candidate: Decimal | None
    approved_quantity_ceiling_base: Decimal | None
    protection_reason_code: str | None = None
    protection_code: str | None = None


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _stale(observed: datetime, evaluation: datetime, max_age_seconds: int) -> bool:
    age = evaluation - observed
    return age < timedelta(0) or age > timedelta(seconds=max_age_seconds)


def _decision(state: str, reason: str, candidate: AutomaticExitCandidateV1, *, ceiling: Decimal | None = None) -> AutomaticExitGateDecisionV1:
    return AutomaticExitGateDecisionV1(
        state=state,
        reason_code=reason,
        candidate=candidate,
        approved_fraction_candidate=(candidate.reduction_fraction_candidate if state == STATE_APPROVED else None),
        approved_quantity_ceiling_base=ceiling if state == STATE_APPROVED else None,
    )


def _evaluate_automatic_exit_candidate_permission_base_v1(
    *, candidate: AutomaticExitCandidateV1, context: AutomaticExitGateContextV1
) -> AutomaticExitGateDecisionV1:
    """Fail-closed permission decision for an already-selected exit candidate.

    The approved ceiling is account safety data, not a strategy quantity: it
    is the candidate's fraction of fresh held quantity, bounded by fresh free
    quantity and (if supplied) an account risk cap.  Downstream planning must
    not exceed it.
    """
    if (
        candidate.trading_account_id <= 0
        or not _is_nonempty_string(candidate.position_reference)
        or not _is_nonempty_string(candidate.venue)
        or candidate.asset_id <= 0
        or not _is_nonempty_string(candidate.market)
        or candidate.reduction_fraction_candidate <= 0
        or candidate.reduction_fraction_candidate > 1
        or candidate.candidate_action not in {"REDUCE", "EXIT"}
        or not _is_nonempty_string(candidate.evidence_id)
        or not _is_nonempty_string(candidate.exit_profile_id)
        or not _is_nonempty_string(candidate.exit_profile_version)
    ):
        return _decision(STATE_NON_ACTIONABLE, REASON_INVALID_CANDIDATE, candidate)
    if candidate.policy_name != POLICY_NAME or candidate.policy_version != POLICY_VERSION:
        return _decision(STATE_NON_ACTIONABLE, REASON_UNSUPPORTED_POLICY_CONTRACT, candidate)

    if not all(_is_aware(value) for value in (
        candidate.observed_ts_utc, context.account_observed_ts_utc,
        context.position_observed_ts_utc, context.free_quantity_observed_ts_utc,
        context.evaluation_ts_utc,
    )):
        return _decision(STATE_NON_ACTIONABLE, REASON_INVALID_TIMESTAMP, candidate)

    if (
        context.trading_account_id <= 0 or not _is_nonempty_string(context.position_reference)
        or not _is_nonempty_string(context.venue) or context.asset_id <= 0 or not _is_nonempty_string(context.market)
        or not _is_nonempty_string(context.position_snapshot_id)
        or context.max_account_age_seconds < 0 or context.max_position_age_seconds < 0
        or context.max_free_quantity_age_seconds < 0 or context.max_candidate_age_seconds < 0
    ):
        return _decision(STATE_NON_ACTIONABLE, REASON_INVALID_ACCOUNT_EVIDENCE, candidate)

    if (candidate.trading_account_id, candidate.position_reference, candidate.venue, candidate.asset_id, candidate.market) != (
        context.trading_account_id, context.position_reference, context.venue, context.asset_id, context.market
    ):
        return _decision(STATE_NON_ACTIONABLE, REASON_IDENTITY_MISMATCH, candidate)

    if _stale(context.account_observed_ts_utc, context.evaluation_ts_utc, context.max_account_age_seconds):
        return _decision(STATE_NON_ACTIONABLE, REASON_ACCOUNT_EVIDENCE_STALE, candidate)
    if _stale(candidate.observed_ts_utc, context.evaluation_ts_utc, context.max_candidate_age_seconds):
        return _decision(STATE_NON_ACTIONABLE, REASON_CANDIDATE_EVIDENCE_STALE, candidate)
    if _stale(context.position_observed_ts_utc, context.evaluation_ts_utc, context.max_position_age_seconds):
        return _decision(STATE_NON_ACTIONABLE, REASON_POSITION_EVIDENCE_STALE, candidate)
    if _stale(context.free_quantity_observed_ts_utc, context.evaluation_ts_utc, context.max_free_quantity_age_seconds):
        return _decision(STATE_NON_ACTIONABLE, REASON_FREE_QUANTITY_EVIDENCE_STALE, candidate)

    if context.held_quantity_base <= 0 or context.free_quantity_base < 0:
        return _decision(STATE_NON_ACTIONABLE, REASON_INVALID_POSITION_EVIDENCE, candidate)
    if context.max_automatic_exit_quantity_base is not None and context.max_automatic_exit_quantity_base < 0:
        return _decision(STATE_NON_ACTIONABLE, REASON_RISK_BOUND_UNRESOLVED, candidate)
    if not context.account_enabled:
        return _decision(STATE_DENIED, REASON_ACCOUNT_DISABLED, candidate)
    if not context.automatic_exit_execution_enabled:
        return _decision(STATE_DENIED, REASON_EXECUTION_PERMISSION_DISABLED, candidate)
    if context.live_trading_enabled or context.account_mode != "paper":
        return _decision(STATE_DENIED, REASON_LIVE_EXECUTION_NOT_GRANTED, candidate)
    if context.blocking_conflict:
        return _decision(STATE_DENIED, REASON_BLOCKING_CONFLICT, candidate)
    if context.free_quantity_base == 0:
        return _decision(STATE_DENIED, REASON_NO_FREE_QUANTITY, candidate)

    requested_ceiling = context.held_quantity_base * candidate.reduction_fraction_candidate
    ceiling = min(requested_ceiling, context.free_quantity_base)
    if context.max_automatic_exit_quantity_base is not None:
        ceiling = min(ceiling, context.max_automatic_exit_quantity_base)
    if ceiling <= 0:
        return _decision(STATE_DENIED, REASON_RISK_BOUND_UNRESOLVED, candidate)
    return _decision(STATE_APPROVED, REASON_OK, candidate, ceiling=ceiling)


def evaluate_automatic_exit_candidate_permission_v1(
    *, candidate: AutomaticExitCandidateV1, context: AutomaticExitGateContextV1
) -> AutomaticExitGateDecisionV1:
    """Compose existing SELL permission with explicit P2 action evidence.

    A protection may only turn an otherwise approved gate result into denied.
    `REDUCE` and `EXIT` action semantics are resolved before this boundary by
    the account-protection runtime; this gate never inspects protection rules.
    """
    base = _evaluate_automatic_exit_candidate_permission_base_v1(candidate=candidate, context=context)
    protection = context.account_protection_evaluation
    if protection is None:
        return base
    try:
        validate_account_protection_evaluation_binding_v1(
            protection,
            trading_account_id=candidate.trading_account_id,
            requested_action=candidate.candidate_action,
            sleeve_code=None,
            asset_id=candidate.asset_id,
            evaluation_ts_utc=context.evaluation_ts_utc,
        )
    except AccountProtectionContractError:
        if base.state != STATE_APPROVED:
            return base
        return replace(
            base,
            state=STATE_DENIED,
            reason_code="INVALID_PROTECTION_EVALUATION_BINDING",
            approved_fraction_candidate=None,
            approved_quantity_ceiling_base=None,
            protection_reason_code="INVALID_PROTECTION_EVALUATION_BINDING",
        )
    enriched = replace(
        base,
        protection_reason_code=protection.reason_code,
        protection_code=protection.protection_code,
    )
    if protection.decision_state != PROTECTION_STATE_BLOCKED or base.state != STATE_APPROVED:
        return enriched
    return replace(
        enriched,
        state=STATE_DENIED,
        reason_code=protection.reason_code,
        approved_fraction_candidate=None,
        approved_quantity_ceiling_base=None,
    )
