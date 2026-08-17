"""P2 deterministic account-protection evaluation.

This module consumes small, typed, pre-derived account risk facts.  It does
not read a broker, calculate a portfolio ledger, create execution intent, or
perform persistence.  Lock persistence is a separate append-only repository
boundary; callers provide its immutable facts here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final, Iterable

from src.decision_gate.account_protection_contract_v1 import (
    AccountProtectionContractError,
    AccountProtectionEvaluationV1,
    EVALUATION_CONTRACT_VERSION,
    LOCK_FACT_CONTRACT_VERSION,
    LOCK_STATE_ACTIVE,
    PROTECTION_DAILY_REALIZED_LOSS_BLOCK,
    PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
    PROTECTION_REPEATED_STOPLOSS_BLOCK,
    REASON_ACCOUNT_STATE_EVIDENCE_MISSING,
    REASON_ACCOUNT_STATE_EVIDENCE_STALE,
    REASON_PROTECTION_EVIDENCE_INVALID,
    SCOPE_ACCOUNT,
    STATE_BLOCKED,
    ProtectionLockFactV1,
    account_protection_lock_event_id_v1,
    account_protection_lock_lifecycle_id_v1,
    resolve_account_protection_state_for_action_v1,
)


METRIC_MAX_ACCOUNT_DRAWDOWN: Final[str] = "MAX_ACCOUNT_DRAWDOWN"
METRIC_DAILY_REALIZED_LOSS: Final[str] = "DAILY_REALIZED_LOSS"
METRIC_REPEATED_STOPLOSS_STREAK: Final[str] = "REPEATED_STOPLOSS_STREAK"
SUPPORTED_METRIC_CODES: Final[frozenset[str]] = frozenset({
    METRIC_MAX_ACCOUNT_DRAWDOWN,
    METRIC_DAILY_REALIZED_LOSS,
    METRIC_REPEATED_STOPLOSS_STREAK,
})
METRIC_PROTECTION_CODES: Final[dict[str, str]] = {
    METRIC_MAX_ACCOUNT_DRAWDOWN: PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
    METRIC_DAILY_REALIZED_LOSS: PROTECTION_DAILY_REALIZED_LOSS_BLOCK,
    METRIC_REPEATED_STOPLOSS_STREAK: PROTECTION_REPEATED_STOPLOSS_BLOCK,
}
DEFAULT_MAX_METRIC_AGE_SECONDS: Final[int] = 15 * 60


class AccountProtectionRuntimeError(ValueError):
    """Invalid P2 producer/policy input."""


@dataclass(frozen=True)
class AccountProtectionPolicyV1:
    """Configured thresholds; ``None`` disables that metric protection."""

    configuration_version: str
    max_account_drawdown: Decimal | None = None
    max_daily_realized_loss: Decimal | None = None
    max_repeated_stoploss_streak: int | None = None
    max_metric_age_seconds: int = DEFAULT_MAX_METRIC_AGE_SECONDS


@dataclass(frozen=True)
class AccountProtectionMetricFactV1:
    """Pre-derived value from a canonical future account-risk producer.

    The value is a non-negative magnitude: drawdown and realized loss use the
    policy's unit, while stoploss is an integer represented as ``Decimal``.
    This boundary intentionally does not claim to be an equity, PnL, or fill
    ledger.
    """

    metric_code: str
    trading_account_id: int
    observed_from_ts_utc: datetime
    observed_to_ts_utc: datetime
    value: Decimal
    evidence_refs: tuple[str, ...]
    source_version: str


@dataclass(frozen=True)
class AccountProtectionRuntimeInputV1:
    trading_account_id: int
    sleeve_code: str | None
    asset_id: int | None
    account_state_observed_ts_utc: datetime
    account_state_fresh: bool
    metric_facts: tuple[AccountProtectionMetricFactV1, ...]
    persisted_lock_facts: tuple[ProtectionLockFactV1, ...]
    evaluation_ts_utc: datetime


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _blocked(
    *, account_id: int, reason: str, at: datetime, requested_action: str,
    sleeve_code: str | None, asset_id: int | None,
) -> AccountProtectionEvaluationV1:
    return AccountProtectionEvaluationV1(
        evaluation_contract_version=EVALUATION_CONTRACT_VERSION,
        decision_state=STATE_BLOCKED,
        reason_code=reason,
        trading_account_id=account_id,
        protection_code=None,
        scope_type=None,
        scope_id=None,
        expires_ts_utc=None,
        contributing_lock_facts=(),
        evaluated_ts_utc=at,
        requested_action=requested_action,
        sleeve_code=sleeve_code,
        asset_id=asset_id,
    )


def _enabled_thresholds(policy: AccountProtectionPolicyV1) -> dict[str, Decimal]:
    if not policy.configuration_version.strip() or policy.max_metric_age_seconds < 0:
        raise AccountProtectionRuntimeError("INVALID_PROTECTION_POLICY")
    values: dict[str, Decimal] = {}
    for metric, threshold in (
        (METRIC_MAX_ACCOUNT_DRAWDOWN, policy.max_account_drawdown),
        (METRIC_DAILY_REALIZED_LOSS, policy.max_daily_realized_loss),
    ):
        if threshold is not None:
            if not isinstance(threshold, Decimal) or not threshold.is_finite() or threshold <= 0:
                raise AccountProtectionRuntimeError("INVALID_PROTECTION_THRESHOLD")
            values[metric] = threshold
    if policy.max_repeated_stoploss_streak is not None:
        if not isinstance(policy.max_repeated_stoploss_streak, int) or isinstance(policy.max_repeated_stoploss_streak, bool) or policy.max_repeated_stoploss_streak <= 0:
            raise AccountProtectionRuntimeError("INVALID_STOPLOSS_STREAK_THRESHOLD")
        values[METRIC_REPEATED_STOPLOSS_STREAK] = Decimal(policy.max_repeated_stoploss_streak)
    return values


def _metric_map(
    facts: Iterable[AccountProtectionMetricFactV1], *, account_id: int, at: datetime, max_age_seconds: int,
) -> dict[str, AccountProtectionMetricFactV1]:
    result: dict[str, AccountProtectionMetricFactV1] = {}
    for fact in facts:
        if (
            fact.metric_code not in SUPPORTED_METRIC_CODES
            or fact.trading_account_id != account_id
            or not _aware(fact.observed_from_ts_utc)
            or not _aware(fact.observed_to_ts_utc)
            or fact.observed_to_ts_utc <= fact.observed_from_ts_utc
            or not isinstance(fact.value, Decimal)
            or not fact.value.is_finite()
            or fact.value < 0
            or not isinstance(fact.evidence_refs, tuple)
            or not fact.evidence_refs
            or not all(isinstance(ref, str) and bool(ref.strip()) for ref in fact.evidence_refs)
            or not fact.source_version.strip()
        ):
            raise AccountProtectionRuntimeError("INVALID_PROTECTION_METRIC_FACT")
        if fact.metric_code in result:
            raise AccountProtectionRuntimeError("AMBIGUOUS_PROTECTION_METRIC_FACT")
        if fact.metric_code == METRIC_REPEATED_STOPLOSS_STREAK and fact.value != fact.value.to_integral_value():
            raise AccountProtectionRuntimeError("INVALID_STOPLOSS_STREAK_METRIC")
        if at - fact.observed_to_ts_utc < timedelta(0) or at - fact.observed_to_ts_utc > timedelta(seconds=max_age_seconds):
            raise AccountProtectionRuntimeError("STALE_PROTECTION_METRIC_FACT")
        result[fact.metric_code] = fact
    return result


def _triggered_metric_locks(
    *, account_id: int, thresholds: dict[str, Decimal], metrics: dict[str, AccountProtectionMetricFactV1], policy: AccountProtectionPolicyV1,
) -> tuple[ProtectionLockFactV1, ...]:
    locks: list[ProtectionLockFactV1] = []
    for metric_code, threshold in thresholds.items():
        metric = metrics.get(metric_code)
        if metric is None:
            raise AccountProtectionRuntimeError("REQUIRED_PROTECTION_METRIC_MISSING")
        if metric.value < threshold:
            continue
        protection_code = METRIC_PROTECTION_CODES[metric_code]
        identity = {
            "protection_code": protection_code,
            "protection_version": LOCK_FACT_CONTRACT_VERSION,
            "trading_account_id": account_id,
            "scope_type": SCOPE_ACCOUNT,
            "scope_id": str(account_id),
            "observed_from_ts_utc": metric.observed_from_ts_utc,
            "observed_to_ts_utc": metric.observed_to_ts_utc,
            "configuration_version": policy.configuration_version,
        }
        lifecycle_id = account_protection_lock_lifecycle_id_v1(identity)
        event_id = account_protection_lock_event_id_v1({
            "lifecycle_id": lifecycle_id,
            "lock_state": LOCK_STATE_ACTIVE,
            "triggered_ts_utc": metric.observed_to_ts_utc,
        })
        locks.append(ProtectionLockFactV1(
            lifecycle_id=lifecycle_id,
            event_id=event_id,
            protection_code=protection_code,
            protection_version=LOCK_FACT_CONTRACT_VERSION,
            trading_account_id=account_id,
            scope_type=SCOPE_ACCOUNT,
            scope_id=str(account_id),
            observed_from_ts_utc=metric.observed_from_ts_utc,
            observed_to_ts_utc=metric.observed_to_ts_utc,
            triggered_ts_utc=metric.observed_to_ts_utc,
            expires_ts_utc=None,
            reason_code=f"{metric_code}_THRESHOLD_REACHED",
            evidence_refs=metric.evidence_refs,
            configuration_version=policy.configuration_version,
        ))
    return tuple(locks)


def evaluate_account_protection_runtime_v1(
    *, policy: AccountProtectionPolicyV1, inputs: AccountProtectionRuntimeInputV1, requested_action: str,
) -> AccountProtectionEvaluationV1:
    """Evaluate P2 facts through the canonical action-aware P1 resolver.

    Any malformed, contradictory, stale, or missing configured metric fact
    returns a typed blocked result. No account evidence is required when no
    metric-derived protection is configured; persisted manual/cooldown facts
    then resolve independently and deterministically.
    """
    if inputs.trading_account_id <= 0 or not _aware(inputs.evaluation_ts_utc):
        raise AccountProtectionRuntimeError("INVALID_RUNTIME_INPUT")
    try:
        thresholds = _enabled_thresholds(policy)
        metrics = _metric_map(
            (fact for fact in inputs.metric_facts if fact.metric_code in thresholds),
            account_id=inputs.trading_account_id,
            at=inputs.evaluation_ts_utc,
            max_age_seconds=policy.max_metric_age_seconds,
        )
        derived_locks = _triggered_metric_locks(
            account_id=inputs.trading_account_id,
            thresholds=thresholds,
            metrics=metrics,
            policy=policy,
        )
        return resolve_account_protection_state_for_action_v1(
            (*inputs.persisted_lock_facts, *derived_locks),
            trading_account_id=inputs.trading_account_id,
            sleeve_code=inputs.sleeve_code,
            asset_id=inputs.asset_id,
            requested_action=requested_action,
            account_state_observed_ts_utc=inputs.account_state_observed_ts_utc,
            account_state_fresh=inputs.account_state_fresh,
            at=inputs.evaluation_ts_utc,
            require_account_state_evidence=bool(thresholds),
        )
    except AccountProtectionRuntimeError as exc:
        reason = (
            REASON_ACCOUNT_STATE_EVIDENCE_STALE
            if str(exc) == "STALE_PROTECTION_METRIC_FACT"
            else REASON_ACCOUNT_STATE_EVIDENCE_MISSING
            if str(exc) == "REQUIRED_PROTECTION_METRIC_MISSING"
            else REASON_PROTECTION_EVIDENCE_INVALID
        )
        return _blocked(
            account_id=inputs.trading_account_id, reason=reason, at=inputs.evaluation_ts_utc,
            requested_action=requested_action, sleeve_code=inputs.sleeve_code, asset_id=inputs.asset_id,
        )
    except AccountProtectionContractError:
        return _blocked(
            account_id=inputs.trading_account_id, reason=REASON_PROTECTION_EVIDENCE_INVALID,
            at=inputs.evaluation_ts_utc, requested_action=requested_action,
            sleeve_code=inputs.sleeve_code, asset_id=inputs.asset_id,
        )
