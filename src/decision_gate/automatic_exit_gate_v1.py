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

# Issue #392 Phase 6 blocker B: the only two supported account modes. This
# gate never guesses, lowercases, or canonicalizes an unsupported mode -- an
# unrecognized value fails closed to NON_ACTIONABLE.
ACCOUNT_MODE_PAPER: Final[str] = "paper"
ACCOUNT_MODE_LIVE: Final[str] = "live"
SUPPORTED_ACCOUNT_MODES: Final[frozenset[str]] = frozenset({ACCOUNT_MODE_PAPER, ACCOUNT_MODE_LIVE})

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
REASON_UNSUPPORTED_ACCOUNT_MODE: Final[str] = "UNSUPPORTED_ACCOUNT_MODE"
REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT: Final[str] = "ACCOUNT_MODE_LIVE_FLAG_EVIDENCE_INCONSISTENT"
REASON_LIVE_EXECUTION_NOT_GRANTED: Final[str] = "LIVE_EXECUTION_NOT_GRANTED"
REASON_BLOCKING_CONFLICT: Final[str] = "BLOCKING_SELL_RESERVATION_OR_ORDER_CONFLICT"
REASON_NO_FREE_QUANTITY: Final[str] = "NO_FREE_UNRESERVED_QUANTITY"
REASON_RISK_BOUND_UNRESOLVED: Final[str] = "AUTOMATIC_EXIT_RISK_BOUND_UNRESOLVED"


@dataclass(frozen=True)
class AutomaticExitGateContextV1:
    """Fresh, account-owned facts for one exact automatic-exit candidate.

    ``automatic_exit_execution_enabled`` is an explicit permission for this
    lane, independent of account mode.

    ``account_mode`` must be exactly ``"paper"`` or ``"live"``
    (``SUPPORTED_ACCOUNT_MODES``); any other value is NON_ACTIONABLE. This
    gate never guesses or canonicalizes an unrecognized mode.

    ``live_trading_enabled`` is the account-level "this account is
    provisioned as a live-trading account" fact mirrored from
    ``trading_account.live_trading_enabled`` -- the same column other
    account-scoped modules (e.g. broker snapshot writers) already trust as
    the authoritative live/non-live account flag. It must always agree with
    ``account_mode`` (``paper`` implies ``False``, ``live`` implies
    ``True``); disagreement is treated as inconsistent evidence and fails
    closed to NON_ACTIONABLE rather than being trusted either way. On its
    own it is never sufficient LIVE permission and is never executor
    authority, a kill switch, or a credential/broker permission of any kind.

    ``automatic_exit_live_permission_enabled`` is the explicit, separately
    persisted, account-scoped decision-gate LIVE permission fact resolved by
    ``automatic_exit_live_permission_contract_v1.resolve_automatic_exit_live_decision_gate_permission_v1``
    (Issue #392 Phase 6 blocker B). It is required, in addition to
    ``account_mode == "live"`` and ``live_trading_enabled == True``, before a
    LIVE candidate may reach APPROVED. It is decision-gate permission only:
    it grants no executor operational LIVE authority
    (``src/executor/execution_live_authority_v1.py``), no kill-switch state,
    and no credential/broker access -- those remain a wholly separate,
    downstream gate. For ``account_mode == "paper"`` this field is not
    consulted.

    ``blocking_conflict`` represents any active reservation/open-order state
    which cannot safely coexist with the proposed SELL.
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
    automatic_exit_live_permission_enabled: bool
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

    # Issue #392 Phase 6 blocker B: explicit typed LIVE decision-gate
    # semantics. account_mode alone, live_trading_enabled alone, or both
    # together are never sufficient LIVE permission -- only an explicit,
    # separately persisted automatic_exit_live_permission_enabled fact can
    # approve a LIVE candidate. This grants decision-gate permission only;
    # it never grants executor operational LIVE authority, a kill switch, or
    # broker/credential access (see AutomaticExitGateContextV1 docstring).
    if context.account_mode not in SUPPORTED_ACCOUNT_MODES:
        return _decision(STATE_NON_ACTIONABLE, REASON_UNSUPPORTED_ACCOUNT_MODE, candidate)
    if context.account_mode == ACCOUNT_MODE_PAPER:
        if context.live_trading_enabled:
            return _decision(STATE_NON_ACTIONABLE, REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT, candidate)
    else:  # ACCOUNT_MODE_LIVE
        if not context.live_trading_enabled:
            return _decision(STATE_NON_ACTIONABLE, REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT, candidate)
        if not context.automatic_exit_live_permission_enabled:
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
