"""Issue #392 Phase 6 blocker C: the single composition seam for account
protection evaluation on the real automatic-exit runtime path.

Assembles ``AccountProtectionRuntimeInputV1`` from canonical persisted
evidence (durable config + append-only lock facts + the caller's own already
-loaded account-state freshness evidence) and calls
``evaluate_account_protection_runtime_v1`` exactly once. No broker, executor,
or execution_planner import. No second PnL/equity/trade ledger: metric facts
for MAX_ACCOUNT_DRAWDOWN / DAILY_REALIZED_LOSS / REPEATED_STOPLOSS_STREAK
have no canonical producer yet (see
``docs/status/issue_392_phase6_sell_live_readiness_v1.md``), so this seam
always supplies an empty metric-fact set; if a future durable config ever
enables one of those thresholds without a producer wired here, the P2
evaluator itself fails closed (``REQUIRED_PROTECTION_METRIC_MISSING``) rather
than this module inventing a value.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final

from src.decision_gate.account_protection_contract_v1 import (
    EVALUATION_CONTRACT_VERSION,
    REASON_PROTECTION_CONFIGURATION_UNRESOLVED,
    REASON_PROTECTION_EVIDENCE_INVALID,
    STATE_BLOCKED,
    AccountProtectionEvaluationV1,
)
from src.decision_gate.account_protection_policy_contract_v1 import (
    AccountProtectionPolicyConfigError,
    resolve_account_protection_policy_v1,
)
from src.decision_gate.account_protection_policy_repository_v1 import (
    AccountProtectionPolicyRepositoryError,
    load_account_protection_policy_config_revocations_v1,
    load_account_protection_policy_config_rows_v1,
)
from src.decision_gate.account_protection_repository_v1 import (
    AccountProtectionRepositoryError,
    load_protection_lock_facts_for_account_v1,
)
from src.decision_gate.account_protection_runtime_v1 import (
    AccountProtectionMetricFactV1,
    AccountProtectionRuntimeInputV1,
    evaluate_account_protection_runtime_v1,
)


DEFAULT_MAX_ACCOUNT_STATE_AGE_SECONDS: Final[int] = 15 * 60


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _account_state_fresh(
    *, observed_ts_utc: datetime, evaluation_ts_utc: datetime, max_age_seconds: int,
) -> bool:
    """Explicit staleness check; never an implicit ``fresh=True`` default."""
    if not _aware(observed_ts_utc) or not _aware(evaluation_ts_utc):
        return False
    age = evaluation_ts_utc - observed_ts_utc
    return timedelta(0) <= age <= timedelta(seconds=max_age_seconds)


def _blocked(
    *, trading_account_id: int, reason: str, at: datetime, requested_action: str, asset_id: int,
) -> AccountProtectionEvaluationV1:
    return AccountProtectionEvaluationV1(
        evaluation_contract_version=EVALUATION_CONTRACT_VERSION,
        decision_state=STATE_BLOCKED,
        reason_code=reason,
        trading_account_id=trading_account_id,
        protection_code=None,
        scope_type=None,
        scope_id=None,
        expires_ts_utc=None,
        contributing_lock_facts=(),
        evaluated_ts_utc=at,
        requested_action=requested_action,
        sleeve_code=None,
        asset_id=asset_id,
    )


def evaluate_account_protection_for_automatic_exit_v1(
    conn: Any,
    *,
    trading_account_id: int,
    asset_id: int,
    requested_action: str,
    account_state_observed_ts_utc: datetime,
    evaluation_ts_utc: datetime,
    max_account_state_age_seconds: int = DEFAULT_MAX_ACCOUNT_STATE_AGE_SECONDS,
) -> AccountProtectionEvaluationV1:
    """Evaluate #318 account protection for one #392 automatic-exit item.

    ``sleeve_code`` is always ``None``: the automatic-exit runtime has no
    sleeve concept (matches ``automatic_exit_gate_v1``'s own hardcoded
    ``sleeve_code=None`` binding). Any missing/ambiguous/unsupported-version
    configuration or invalid persisted lock evidence returns a typed
    ``BLOCKED`` evaluation rather than raising -- a data-quality condition,
    not a caller bug -- so one bad account's evidence cannot abort the whole
    runtime cycle.
    """
    try:
        config_rows = load_account_protection_policy_config_rows_v1(conn, trading_account_id=trading_account_id)
        config_revocations = load_account_protection_policy_config_revocations_v1(
            conn, trading_account_id=trading_account_id,
        )
        policy = resolve_account_protection_policy_v1(
            config_rows, config_revocations, trading_account_id=trading_account_id, at=evaluation_ts_utc,
        )
    except (AccountProtectionPolicyRepositoryError, AccountProtectionPolicyConfigError):
        return _blocked(
            trading_account_id=trading_account_id,
            reason=REASON_PROTECTION_CONFIGURATION_UNRESOLVED,
            at=evaluation_ts_utc,
            requested_action=requested_action,
            asset_id=asset_id,
        )

    try:
        persisted_locks = load_protection_lock_facts_for_account_v1(conn, trading_account_id=trading_account_id)
    except AccountProtectionRepositoryError:
        return _blocked(
            trading_account_id=trading_account_id,
            reason=REASON_PROTECTION_EVIDENCE_INVALID,
            at=evaluation_ts_utc,
            requested_action=requested_action,
            asset_id=asset_id,
        )

    metric_facts: tuple[AccountProtectionMetricFactV1, ...] = ()

    inputs = AccountProtectionRuntimeInputV1(
        trading_account_id=trading_account_id,
        sleeve_code=None,
        asset_id=asset_id,
        account_state_observed_ts_utc=account_state_observed_ts_utc,
        account_state_fresh=_account_state_fresh(
            observed_ts_utc=account_state_observed_ts_utc,
            evaluation_ts_utc=evaluation_ts_utc,
            max_age_seconds=max_account_state_age_seconds,
        ),
        metric_facts=metric_facts,
        persisted_lock_facts=persisted_locks,
        evaluation_ts_utc=evaluation_ts_utc,
    )
    return evaluate_account_protection_runtime_v1(policy=policy, inputs=inputs, requested_action=requested_action)
