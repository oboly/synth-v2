"""Pure account-permission gate for :class:`AutomaticBuyCandidateV1`.

Issue #399 Phase 2: the decision_gate BUY permission/allocation owner. This
is deliberately a bounded permission layer, mirroring the structural
discipline of ``automatic_exit_gate_v1``: it consumes account/bucket
evidence assembled by a caller, never fetches it, and does not create
execution intent, ladders, or broker payloads. It never re-evaluates the
entry/re-entry zone decision made by ``entry_policy.automatic_buy_candidate_v1``.

It reuses two existing account-policy owners rather than recreating account
policy in the BUY lane:

- ``strategy_bucket_participation_evaluation_v1`` (Issue #279): strategy-bucket
  enable state, new-entry allowance, max position amount, max bucket amount,
  max asset exposure, and max open positions.
- ``account_protection_contract_v1`` (Issue #318): drawdown/loss/cooldown/
  manual-lock protection, evaluated for the canonical ``ACTION_BUY`` action
  that module already defines.

This repository phase supports ``account_mode == "paper"`` only. No
automatic-BUY LIVE permission contract exists yet -- Issue #399 Phase 7
(separately authorized LIVE activation) is future work, out of scope here.
A non-paper ``account_mode`` fails closed to ``NON_ACTIONABLE`` rather than
being silently approved or denied as if it had been evaluated.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from src.decision_gate.account_protection_contract_v1 import (
    ACTION_BUY,
    AccountProtectionContractError,
    AccountProtectionEvaluationV1,
    STATE_BLOCKED as PROTECTION_STATE_BLOCKED,
    validate_account_protection_evaluation_binding_v1,
)
from src.decision_gate.strategy_bucket_participation_evaluation_v1 import (
    DECISION_BLOCKED as BUCKET_DECISION_BLOCKED,
    REQUEST_KIND_NEW_ENTRY,
    StrategyBucketParticipationEvaluationError,
    StrategyBucketParticipationRequestV1,
    evaluate_strategy_bucket_participation_v1,
)
from src.entry_policy import POLICY_NAME, POLICY_VERSION
from src.entry_policy.automatic_buy_candidate_v1 import AutomaticBuyCandidateV1


STATE_APPROVED: Final[str] = "APPROVED"
STATE_DENIED: Final[str] = "DENIED"
STATE_NON_ACTIONABLE: Final[str] = "NON_ACTIONABLE"

SUPPORTED_CANDIDATE_ACTIONS: Final[frozenset[str]] = frozenset({"ENTER", "RE_ENTER"})

# This gate's only supported account mode for the current repository phase.
# LIVE BUY permission is separately authorized future work (Issue #399
# Phase 7); it must never be inferred from this constant growing silently.
ACCOUNT_MODE_PAPER: Final[str] = "paper"
SUPPORTED_ACCOUNT_MODES: Final[frozenset[str]] = frozenset({ACCOUNT_MODE_PAPER})

REASON_OK: Final[str] = "OK"
REASON_INVALID_CANDIDATE: Final[str] = "INVALID_AUTOMATIC_BUY_CANDIDATE"
REASON_UNSUPPORTED_POLICY_CONTRACT: Final[str] = "UNSUPPORTED_AUTOMATIC_BUY_POLICY_CONTRACT"
REASON_IDENTITY_MISMATCH: Final[str] = "CANDIDATE_ACCOUNT_MARKET_IDENTITY_MISMATCH"
REASON_INVALID_TIMESTAMP: Final[str] = "NAIVE_OR_INVALID_TIMESTAMP"
REASON_INVALID_ACCOUNT_EVIDENCE: Final[str] = "INVALID_ACCOUNT_EVIDENCE"
REASON_ACCOUNT_EVIDENCE_STALE: Final[str] = "ACCOUNT_EVIDENCE_STALE"
REASON_CANDIDATE_EVIDENCE_STALE: Final[str] = "CANDIDATE_EVIDENCE_STALE"
REASON_FREE_QUOTE_BALANCE_STALE: Final[str] = "FREE_QUOTE_BALANCE_EVIDENCE_STALE"
REASON_INVALID_FREE_QUOTE_BALANCE: Final[str] = "INVALID_FREE_QUOTE_BALANCE_EVIDENCE"
REASON_INVALID_PROPOSED_POSITION_AMOUNT: Final[str] = "INVALID_PROPOSED_POSITION_AMOUNT"
REASON_ACCOUNT_DISABLED: Final[str] = "ACCOUNT_DISABLED"
REASON_EXECUTION_PERMISSION_DISABLED: Final[str] = "AUTOMATIC_BUY_EXECUTION_PERMISSION_DISABLED"
REASON_UNSUPPORTED_ACCOUNT_MODE: Final[str] = "UNSUPPORTED_ACCOUNT_MODE"
REASON_BLOCKING_CONFLICT: Final[str] = "BLOCKING_BUY_ORDER_OR_RESERVATION_CONFLICT"
REASON_NO_FREE_QUOTE_BALANCE: Final[str] = "NO_FREE_QUOTE_BALANCE"
REASON_RISK_BOUND_UNRESOLVED: Final[str] = "AUTOMATIC_BUY_RISK_BOUND_UNRESOLVED"
REASON_INVALID_STRATEGY_BUCKET_PARTICIPATION_REQUEST: Final[str] = "INVALID_STRATEGY_BUCKET_PARTICIPATION_REQUEST"
REASON_INVALID_PROTECTION_EVALUATION_BINDING: Final[str] = "INVALID_PROTECTION_EVALUATION_BINDING"


@dataclass(frozen=True)
class AutomaticBuyGateContextV1:
    """Fresh, account-owned facts for one exact automatic-BUY candidate.

    ``proposed_position_amount_eur`` is the account-side proposed sizing for
    this candidate (e.g. a configured default per-entry amount) -- it is not
    read from the candidate, which is account-agnostic by construction and
    carries no sizing field. This context supplies it the same way
    ``AutomaticExitGateContextV1`` supplies ``held_quantity_base``: as an
    already-decided, caller-assembled account fact, not a value this gate
    derives.

    ``strategy_bucket_config_rows``/``strategy_bucket_config_revocations``
    are forwarded unchanged to
    ``strategy_bucket_participation_evaluation_v1.evaluate_strategy_bucket_participation_v1``
    (Issue #279) together with ``current_bucket_amount_eur``,
    ``current_open_positions``, and ``current_asset_exposure_pct`` so the
    bucket ceilings (max position amount, max bucket amount, max asset
    exposure, max open positions, new-entry allowance) are resolved from the
    single canonical bucket-config owner rather than recomputed here.

    ``blocking_conflict`` represents any active reservation/open BUY-order
    state which cannot safely coexist with the proposed BUY.

    ``account_protection_evaluation`` is the typed decision-gate protection
    evaluation (Issue #318), composed by the caller for ``ACTION_BUY`` and
    forwarded unchanged -- this gate never re-resolves protection state
    itself, matching ``automatic_exit_gate_v1``.
    """

    trading_account_id: int
    venue: str
    asset_id: int
    market: str
    strategy_bucket_id: str
    account_observed_ts_utc: datetime
    account_enabled: bool
    account_mode: str
    automatic_buy_execution_enabled: bool
    free_quote_balance_eur: Decimal
    free_quote_balance_observed_ts_utc: datetime
    blocking_conflict: bool
    proposed_position_amount_eur: Decimal
    current_bucket_amount_eur: Decimal
    current_open_positions: int
    current_asset_exposure_pct: Decimal
    evaluation_ts_utc: datetime
    max_account_age_seconds: int = 15 * 60
    max_candidate_age_seconds: int = 15 * 60
    max_free_quote_balance_age_seconds: int = 15 * 60
    # A caller may supply a stricter account risk ceiling. None means the
    # account evidence has no additional cap, not that planning may bypass
    # the proposed-amount/free-balance bounds.
    max_automatic_buy_notional_eur: Decimal | None = None
    strategy_bucket_config_rows: tuple = ()
    strategy_bucket_config_revocations: tuple = ()
    account_protection_evaluation: AccountProtectionEvaluationV1 | None = None


@dataclass(frozen=True)
class AutomaticBuyGateDecisionV1:
    state: str  # APPROVED | DENIED | NON_ACTIONABLE
    reason_code: str
    candidate: AutomaticBuyCandidateV1
    approved_notional_ceiling_eur: Decimal | None
    strategy_bucket_reason_code: str | None = None
    protection_reason_code: str | None = None
    protection_code: str | None = None


def _is_aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _stale(observed: datetime, evaluation: datetime, max_age_seconds: int) -> bool:
    age = evaluation - observed
    return age < timedelta(0) or age > timedelta(seconds=max_age_seconds)


def _decision(
    state: str, reason: str, candidate: AutomaticBuyCandidateV1, *,
    ceiling: Decimal | None = None, bucket_reason: str | None = None,
) -> AutomaticBuyGateDecisionV1:
    return AutomaticBuyGateDecisionV1(
        state=state,
        reason_code=reason,
        candidate=candidate,
        approved_notional_ceiling_eur=(ceiling if state == STATE_APPROVED else None),
        strategy_bucket_reason_code=bucket_reason,
    )


def _evaluate_automatic_buy_candidate_permission_base_v1(
    *, candidate: AutomaticBuyCandidateV1, context: AutomaticBuyGateContextV1
) -> AutomaticBuyGateDecisionV1:
    """Fail-closed permission decision for an already-selected BUY candidate.

    The approved ceiling is account safety data, not a strategy quantity: it
    is the account's own proposed sizing, bounded by fresh free quote
    balance, the resolved strategy-bucket ceilings, and (if supplied) an
    account risk cap. Downstream planning must not exceed it.
    """
    if (
        not _is_nonempty_string(candidate.venue)
        or candidate.asset_id <= 0
        or not _is_nonempty_string(candidate.market)
        or not _is_nonempty_string(candidate.strategy_id)
        or not _is_nonempty_string(candidate.strategy_version)
        or not _is_nonempty_string(candidate.setup_id)
        or candidate.candidate_action not in SUPPORTED_CANDIDATE_ACTIONS
        or not _is_nonempty_string(candidate.evidence_id)
    ):
        return _decision(STATE_NON_ACTIONABLE, REASON_INVALID_CANDIDATE, candidate)
    if candidate.policy_name != POLICY_NAME or candidate.policy_version != POLICY_VERSION:
        return _decision(STATE_NON_ACTIONABLE, REASON_UNSUPPORTED_POLICY_CONTRACT, candidate)

    if not all(_is_aware(value) for value in (
        candidate.observed_ts_utc, context.account_observed_ts_utc,
        context.free_quote_balance_observed_ts_utc, context.evaluation_ts_utc,
    )):
        return _decision(STATE_NON_ACTIONABLE, REASON_INVALID_TIMESTAMP, candidate)

    if (
        context.trading_account_id <= 0 or not _is_nonempty_string(context.venue)
        or context.asset_id <= 0 or not _is_nonempty_string(context.market)
        or not _is_nonempty_string(context.strategy_bucket_id)
        or context.max_account_age_seconds < 0 or context.max_candidate_age_seconds < 0
        or context.max_free_quote_balance_age_seconds < 0
    ):
        return _decision(STATE_NON_ACTIONABLE, REASON_INVALID_ACCOUNT_EVIDENCE, candidate)

    if (candidate.venue, candidate.asset_id, candidate.market) != (context.venue, context.asset_id, context.market):
        return _decision(STATE_NON_ACTIONABLE, REASON_IDENTITY_MISMATCH, candidate)

    if _stale(context.account_observed_ts_utc, context.evaluation_ts_utc, context.max_account_age_seconds):
        return _decision(STATE_NON_ACTIONABLE, REASON_ACCOUNT_EVIDENCE_STALE, candidate)
    if _stale(candidate.observed_ts_utc, context.evaluation_ts_utc, context.max_candidate_age_seconds):
        return _decision(STATE_NON_ACTIONABLE, REASON_CANDIDATE_EVIDENCE_STALE, candidate)
    if _stale(
        context.free_quote_balance_observed_ts_utc, context.evaluation_ts_utc,
        context.max_free_quote_balance_age_seconds,
    ):
        return _decision(STATE_NON_ACTIONABLE, REASON_FREE_QUOTE_BALANCE_STALE, candidate)

    if context.free_quote_balance_eur < 0:
        return _decision(STATE_NON_ACTIONABLE, REASON_INVALID_FREE_QUOTE_BALANCE, candidate)
    if context.proposed_position_amount_eur <= 0:
        return _decision(STATE_NON_ACTIONABLE, REASON_INVALID_PROPOSED_POSITION_AMOUNT, candidate)
    if context.max_automatic_buy_notional_eur is not None and context.max_automatic_buy_notional_eur < 0:
        return _decision(STATE_NON_ACTIONABLE, REASON_RISK_BOUND_UNRESOLVED, candidate)

    if not context.account_enabled:
        return _decision(STATE_DENIED, REASON_ACCOUNT_DISABLED, candidate)
    if not context.automatic_buy_execution_enabled:
        return _decision(STATE_DENIED, REASON_EXECUTION_PERMISSION_DISABLED, candidate)
    if context.account_mode not in SUPPORTED_ACCOUNT_MODES:
        return _decision(STATE_NON_ACTIONABLE, REASON_UNSUPPORTED_ACCOUNT_MODE, candidate)

    if context.blocking_conflict:
        return _decision(STATE_DENIED, REASON_BLOCKING_CONFLICT, candidate)
    if context.free_quote_balance_eur == 0:
        return _decision(STATE_DENIED, REASON_NO_FREE_QUOTE_BALANCE, candidate)

    bucket_request = StrategyBucketParticipationRequestV1(
        trading_account_id=context.trading_account_id,
        strategy_bucket_id=context.strategy_bucket_id,
        request_kind=REQUEST_KIND_NEW_ENTRY,
        proposed_position_amount_eur=context.proposed_position_amount_eur,
        current_bucket_amount_eur=context.current_bucket_amount_eur,
        current_open_positions=context.current_open_positions,
        current_asset_exposure_pct=context.current_asset_exposure_pct,
        evaluation_ts_utc=context.evaluation_ts_utc,
    )
    try:
        bucket_decision = evaluate_strategy_bucket_participation_v1(
            context.strategy_bucket_config_rows,
            context.strategy_bucket_config_revocations,
            request=bucket_request,
        )
    except StrategyBucketParticipationEvaluationError:
        return _decision(STATE_NON_ACTIONABLE, REASON_INVALID_STRATEGY_BUCKET_PARTICIPATION_REQUEST, candidate)

    if bucket_decision.decision_state == BUCKET_DECISION_BLOCKED:
        return _decision(STATE_DENIED, bucket_decision.reason_code, candidate, bucket_reason=bucket_decision.reason_code)

    ceiling = min(context.proposed_position_amount_eur, context.free_quote_balance_eur)
    if context.max_automatic_buy_notional_eur is not None:
        ceiling = min(ceiling, context.max_automatic_buy_notional_eur)
    if ceiling <= 0:
        return _decision(STATE_DENIED, REASON_RISK_BOUND_UNRESOLVED, candidate, bucket_reason=bucket_decision.reason_code)
    return _decision(STATE_APPROVED, REASON_OK, candidate, ceiling=ceiling, bucket_reason=bucket_decision.reason_code)


def evaluate_automatic_buy_candidate_permission_v1(
    *, candidate: AutomaticBuyCandidateV1, context: AutomaticBuyGateContextV1
) -> AutomaticBuyGateDecisionV1:
    """Compose base BUY permission with explicit account-protection evidence.

    A protection may only turn an otherwise approved gate result into
    denied; it can never approve a candidate the base evaluation denied or
    left non-actionable. This gate never inspects protection rules itself.
    """
    base = _evaluate_automatic_buy_candidate_permission_base_v1(candidate=candidate, context=context)
    protection = context.account_protection_evaluation
    if protection is None:
        return base
    try:
        validate_account_protection_evaluation_binding_v1(
            protection,
            trading_account_id=context.trading_account_id,
            requested_action=ACTION_BUY,
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
            reason_code=REASON_INVALID_PROTECTION_EVALUATION_BINDING,
            approved_notional_ceiling_eur=None,
            protection_reason_code=REASON_INVALID_PROTECTION_EVALUATION_BINDING,
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
        approved_notional_ceiling_eur=None,
    )
