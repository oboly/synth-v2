"""Pure account-permission gate for :class:`AutomaticBuyCandidateV1`.

Issue #399: decision_gate owns automatic-BUY account permission, allocation,
protection, and LIVE decision-gate permission. It consumes typed evidence
assembled by the caller, never fetches it, never creates execution intent,
and never grants executor operational LIVE authority, credentials,
kill-switch state, broker access, or order authority.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from src.account.account_mode_contract_v1 import (
    ACCOUNT_MODE_LIVE,
    ACCOUNT_MODE_LIVE_READONLY,
    ACCOUNT_MODE_PAPER,
    SUPPORTED_ACCOUNT_MODES,
    is_account_mode_live_trading_enabled_consistent,
    is_execution_eligible_account_mode,
)
from src.decision_gate.account_protection_contract_v1 import (
    ACTION_BUY,
    AccountProtectionContractError,
    AccountProtectionEvaluationV1,
    STATE_BLOCKED as PROTECTION_STATE_BLOCKED,
    validate_account_protection_evaluation_binding_v1,
)
from src.decision_gate.automatic_buy_live_permission_evaluation_v1 import (
    DECISION_GRANTED as LIVE_PERMISSION_DECISION_GRANTED,
    AutomaticBuyLivePermissionEvaluationError,
    AutomaticBuyLivePermissionEvaluationV1,
    validate_automatic_buy_live_permission_evaluation_binding_v1,
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
# Issue #551 account-mode split: canonical account_mode vocabulary and its
# live_trading_enabled agreement/execution-eligibility semantics are shared
# from src.account.account_mode_contract_v1 rather than redefined here.

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
REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT: Final[str] = "ACCOUNT_MODE_LIVE_FLAG_EVIDENCE_INCONSISTENT"
REASON_ACCOUNT_MODE_NOT_EXECUTION_ELIGIBLE: Final[str] = "ACCOUNT_MODE_NOT_EXECUTION_ELIGIBLE"
REASON_LIVE_EXECUTION_NOT_GRANTED: Final[str] = "LIVE_EXECUTION_NOT_GRANTED"
REASON_LIVE_PERMISSION_EVALUATION_BINDING_MISMATCH: Final[str] = "AUTOMATIC_BUY_LIVE_PERMISSION_EVALUATION_BINDING_MISMATCH"
REASON_BLOCKING_CONFLICT: Final[str] = "BLOCKING_BUY_ORDER_OR_RESERVATION_CONFLICT"
REASON_NO_FREE_QUOTE_BALANCE: Final[str] = "NO_FREE_QUOTE_BALANCE"
REASON_RISK_BOUND_UNRESOLVED: Final[str] = "AUTOMATIC_BUY_RISK_BOUND_UNRESOLVED"
REASON_INVALID_STRATEGY_BUCKET_PARTICIPATION_REQUEST: Final[str] = "INVALID_STRATEGY_BUCKET_PARTICIPATION_REQUEST"
REASON_INVALID_PROTECTION_EVALUATION_BINDING: Final[str] = "INVALID_PROTECTION_EVALUATION_BINDING"


@dataclass(frozen=True)
class AutomaticBuyGateContextV1:
    """Fresh account-owned facts for one exact automatic-BUY candidate.

    ``account_mode`` and ``live_trading_enabled`` are evidence, not mutations.
    See ``src.account.account_mode_contract_v1`` for the canonical three-mode
    vocabulary. PAPER and LIVE_READONLY both require
    ``live_trading_enabled=False`` and are never execution-eligible. LIVE
    requires ``live_trading_enabled=True`` plus an exact typed GRANTED
    ``automatic_buy_live_permission_evaluation``. This establishes the
    software contract while production may remain non-live until a separately
    authorized activation change sets those facts.

    Decision-gate LIVE permission remains wholly separate from downstream
    executor operational LIVE authority, credential scope and kill switch.
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
    max_automatic_buy_notional_eur: Decimal | None = None
    strategy_bucket_config_rows: tuple = ()
    strategy_bucket_config_revocations: tuple = ()
    account_protection_evaluation: AccountProtectionEvaluationV1 | None = None
    live_trading_enabled: bool = False
    automatic_buy_live_permission_evaluation: AutomaticBuyLivePermissionEvaluationV1 | None = None


@dataclass(frozen=True)
class AutomaticBuyGateDecisionV1:
    state: str
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
    state: str,
    reason: str,
    candidate: AutomaticBuyCandidateV1,
    *,
    ceiling: Decimal | None = None,
    bucket_reason: str | None = None,
) -> AutomaticBuyGateDecisionV1:
    return AutomaticBuyGateDecisionV1(
        state=state,
        reason_code=reason,
        candidate=candidate,
        approved_notional_ceiling_eur=(ceiling if state == STATE_APPROVED else None),
        strategy_bucket_reason_code=bucket_reason,
    )


def _evaluate_automatic_buy_candidate_permission_base_v1(
    *,
    candidate: AutomaticBuyCandidateV1,
    context: AutomaticBuyGateContextV1,
) -> AutomaticBuyGateDecisionV1:
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
        candidate.observed_ts_utc,
        context.account_observed_ts_utc,
        context.free_quote_balance_observed_ts_utc,
        context.evaluation_ts_utc,
    )):
        return _decision(STATE_NON_ACTIONABLE, REASON_INVALID_TIMESTAMP, candidate)

    if (
        context.trading_account_id <= 0
        or not _is_nonempty_string(context.venue)
        or context.asset_id <= 0
        or not _is_nonempty_string(context.market)
        or not _is_nonempty_string(context.strategy_bucket_id)
        or context.max_account_age_seconds < 0
        or context.max_candidate_age_seconds < 0
        or context.max_free_quote_balance_age_seconds < 0
        or type(context.live_trading_enabled) is not bool
    ):
        return _decision(STATE_NON_ACTIONABLE, REASON_INVALID_ACCOUNT_EVIDENCE, candidate)

    if (candidate.venue, candidate.asset_id, candidate.market) != (
        context.venue,
        context.asset_id,
        context.market,
    ):
        return _decision(STATE_NON_ACTIONABLE, REASON_IDENTITY_MISMATCH, candidate)

    if _stale(context.account_observed_ts_utc, context.evaluation_ts_utc, context.max_account_age_seconds):
        return _decision(STATE_NON_ACTIONABLE, REASON_ACCOUNT_EVIDENCE_STALE, candidate)
    if _stale(candidate.observed_ts_utc, context.evaluation_ts_utc, context.max_candidate_age_seconds):
        return _decision(STATE_NON_ACTIONABLE, REASON_CANDIDATE_EVIDENCE_STALE, candidate)
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
    if not is_account_mode_live_trading_enabled_consistent(context.account_mode, context.live_trading_enabled):
        return _decision(STATE_NON_ACTIONABLE, REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT, candidate)
    if not is_execution_eligible_account_mode(context.account_mode):
        # paper falls through to APPROVED via the existing PAPER runtime
        # lane below; live_readonly (real broker, read-only) must never
        # reach the free-quote-balance/LIVE-permission branch or executor
        # LIVE routing, so it is rejected here explicitly and distinctly
        # from ACCOUNT_MODE_EVIDENCE_INCONSISTENT.
        if context.account_mode == ACCOUNT_MODE_LIVE_READONLY:
            return _decision(STATE_NON_ACTIONABLE, REASON_ACCOUNT_MODE_NOT_EXECUTION_ELIGIBLE, candidate)
    else:
        if _stale(
            context.free_quote_balance_observed_ts_utc,
            context.evaluation_ts_utc,
            context.max_free_quote_balance_age_seconds,
        ):
            return _decision(STATE_NON_ACTIONABLE, REASON_FREE_QUOTE_BALANCE_STALE, candidate)
        live_permission = context.automatic_buy_live_permission_evaluation
        if live_permission is None:
            return _decision(STATE_DENIED, REASON_LIVE_EXECUTION_NOT_GRANTED, candidate)
        try:
            validate_automatic_buy_live_permission_evaluation_binding_v1(
                live_permission,
                trading_account_id=context.trading_account_id,
                evaluation_ts_utc=context.evaluation_ts_utc,
            )
        except AutomaticBuyLivePermissionEvaluationError:
            return _decision(
                STATE_DENIED,
                REASON_LIVE_PERMISSION_EVALUATION_BINDING_MISMATCH,
                candidate,
            )
        if live_permission.decision_state != LIVE_PERMISSION_DECISION_GRANTED:
            return _decision(STATE_DENIED, REASON_LIVE_EXECUTION_NOT_GRANTED, candidate)

    if context.blocking_conflict:
        return _decision(STATE_DENIED, REASON_BLOCKING_CONFLICT, candidate)
    if context.account_mode == ACCOUNT_MODE_LIVE and context.free_quote_balance_eur == 0:
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
        return _decision(
            STATE_NON_ACTIONABLE,
            REASON_INVALID_STRATEGY_BUCKET_PARTICIPATION_REQUEST,
            candidate,
        )

    if bucket_decision.decision_state == BUCKET_DECISION_BLOCKED:
        return _decision(
            STATE_DENIED,
            bucket_decision.reason_code,
            candidate,
            bucket_reason=bucket_decision.reason_code,
        )

    ceiling = context.proposed_position_amount_eur
    if context.account_mode == ACCOUNT_MODE_LIVE:
        ceiling = min(ceiling, context.free_quote_balance_eur)
    if context.max_automatic_buy_notional_eur is not None:
        ceiling = min(ceiling, context.max_automatic_buy_notional_eur)
    if ceiling <= 0:
        return _decision(
            STATE_DENIED,
            REASON_RISK_BOUND_UNRESOLVED,
            candidate,
            bucket_reason=bucket_decision.reason_code,
        )
    return _decision(
        STATE_APPROVED,
        REASON_OK,
        candidate,
        ceiling=ceiling,
        bucket_reason=bucket_decision.reason_code,
    )


def evaluate_automatic_buy_candidate_permission_v1(
    *,
    candidate: AutomaticBuyCandidateV1,
    context: AutomaticBuyGateContextV1,
) -> AutomaticBuyGateDecisionV1:
    """Compose BUY permission with canonical action-aware protection evidence."""
    base = _evaluate_automatic_buy_candidate_permission_base_v1(
        candidate=candidate,
        context=context,
    )
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
