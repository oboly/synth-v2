from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.decision_gate.account_protection_contract_v1 import (
    ACTION_BUY,
    ACTION_EXIT,
    ACTION_REDUCE,
    LOCK_FACT_CONTRACT_VERSION,
    PROTECTION_LOW_PROFIT_ASSET_COOLDOWN,
    PROTECTION_MANUAL_ACCOUNT_LOCK,
    SCOPE_ACCOUNT,
    SCOPE_ASSET,
    STATE_BLOCKED,
    STATE_PERMITTED,
    ProtectionLockFactV1,
)
from src.decision_gate.account_protection_runtime_v1 import (
    AccountProtectionMetricFactV1,
    AccountProtectionPolicyV1,
    AccountProtectionRuntimeInputV1,
    METRIC_DAILY_REALIZED_LOSS,
    METRIC_MAX_ACCOUNT_DRAWDOWN,
    METRIC_REPEATED_STOPLOSS_STREAK,
    evaluate_account_protection_runtime_v1,
)


NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
ACCOUNT_A = 7
ACCOUNT_B = 8


def _metric(code: str, value: str, *, account_id: int = ACCOUNT_A, observed_to=NOW) -> AccountProtectionMetricFactV1:
    return AccountProtectionMetricFactV1(
        metric_code=code,
        trading_account_id=account_id,
        observed_from_ts_utc=observed_to - timedelta(minutes=1),
        observed_to_ts_utc=observed_to,
        value=Decimal(value),
        evidence_refs=(f"canonical:{code}:1",),
        source_version="1",
    )


def _lock(code: str, scope: str, scope_id: str, *, account_id: int = ACCOUNT_A, expires=None, triggered=NOW) -> ProtectionLockFactV1:
    return ProtectionLockFactV1(
        lifecycle_id=f"lifecycle-{code}-{scope}-{scope_id}",
        event_id=f"event-{code}-{scope}-{scope_id}",
        protection_code=code,
        protection_version=LOCK_FACT_CONTRACT_VERSION,
        trading_account_id=account_id,
        scope_type=scope,
        scope_id=scope_id,
        observed_from_ts_utc=NOW - timedelta(minutes=1),
        observed_to_ts_utc=NOW,
        triggered_ts_utc=triggered,
        expires_ts_utc=expires,
        reason_code="TEST",
        evidence_refs=("canonical:lock:1",),
        configuration_version="policy-1",
    )


def _inputs(*, account_id=ACCOUNT_A, asset_id=42, metrics=(), locks=(), fresh=True, observed=NOW) -> AccountProtectionRuntimeInputV1:
    return AccountProtectionRuntimeInputV1(
        trading_account_id=account_id,
        sleeve_code=None,
        asset_id=asset_id,
        account_state_observed_ts_utc=observed,
        account_state_fresh=fresh,
        metric_facts=tuple(metrics),
        persisted_lock_facts=tuple(locks),
        evaluation_ts_utc=NOW,
    )


def test_no_configured_protections_is_permitted_without_unrelated_account_snapshot():
    result = evaluate_account_protection_runtime_v1(
        policy=AccountProtectionPolicyV1("policy-1"),
        inputs=_inputs(fresh=False, observed=NOW - timedelta(days=1)),
        requested_action=ACTION_BUY,
    )
    assert result.decision_state == STATE_PERMITTED


def test_metric_protections_block_buy_and_allow_reduce_exit():
    policy = AccountProtectionPolicyV1(
        "policy-1", max_account_drawdown=Decimal("10"), max_daily_realized_loss=Decimal("100"), max_repeated_stoploss_streak=3,
    )
    metrics = (
        _metric(METRIC_MAX_ACCOUNT_DRAWDOWN, "10"),
        _metric(METRIC_DAILY_REALIZED_LOSS, "100"),
        _metric(METRIC_REPEATED_STOPLOSS_STREAK, "3"),
    )
    assert evaluate_account_protection_runtime_v1(policy=policy, inputs=_inputs(metrics=metrics), requested_action=ACTION_BUY).decision_state == STATE_BLOCKED
    assert evaluate_account_protection_runtime_v1(policy=policy, inputs=_inputs(metrics=metrics), requested_action=ACTION_REDUCE).decision_state == STATE_PERMITTED
    assert evaluate_account_protection_runtime_v1(policy=policy, inputs=_inputs(metrics=metrics), requested_action=ACTION_EXIT).decision_state == STATE_PERMITTED


def test_drawdown_is_strictly_account_scoped():
    policy = AccountProtectionPolicyV1("policy-1", max_account_drawdown=Decimal("10"))
    account_a = evaluate_account_protection_runtime_v1(
        policy=policy,
        inputs=_inputs(metrics=(_metric(METRIC_MAX_ACCOUNT_DRAWDOWN, "10", account_id=ACCOUNT_A),)),
        requested_action=ACTION_BUY,
    )
    account_b = evaluate_account_protection_runtime_v1(
        policy=policy,
        inputs=_inputs(account_id=ACCOUNT_B, metrics=(_metric(METRIC_MAX_ACCOUNT_DRAWDOWN, "1", account_id=ACCOUNT_B),)),
        requested_action=ACTION_BUY,
    )
    assert account_a.decision_state == STATE_BLOCKED
    assert account_b.decision_state == STATE_PERMITTED


def test_missing_or_stale_configured_metric_fails_closed():
    policy = AccountProtectionPolicyV1("policy-1", max_account_drawdown=Decimal("10"), max_metric_age_seconds=60)
    assert evaluate_account_protection_runtime_v1(policy=policy, inputs=_inputs(), requested_action=ACTION_BUY).decision_state == STATE_BLOCKED
    stale = _metric(METRIC_MAX_ACCOUNT_DRAWDOWN, "1", observed_to=NOW - timedelta(hours=1))
    assert evaluate_account_protection_runtime_v1(policy=policy, inputs=_inputs(metrics=(stale,)), requested_action=ACTION_BUY).decision_state == STATE_BLOCKED


def test_malformed_nonfinite_or_fractional_streak_metric_fails_closed():
    drawdown_policy = AccountProtectionPolicyV1("policy-1", max_account_drawdown=Decimal("10"))
    nan = _metric(METRIC_MAX_ACCOUNT_DRAWDOWN, "NaN")
    assert evaluate_account_protection_runtime_v1(policy=drawdown_policy, inputs=_inputs(metrics=(nan,)), requested_action=ACTION_BUY).decision_state == STATE_BLOCKED
    streak_policy = AccountProtectionPolicyV1("policy-1", max_repeated_stoploss_streak=3)
    fractional = _metric(METRIC_REPEATED_STOPLOSS_STREAK, "2.5")
    assert evaluate_account_protection_runtime_v1(policy=streak_policy, inputs=_inputs(metrics=(fractional,)), requested_action=ACTION_BUY).decision_state == STATE_BLOCKED
    malformed_ts = _metric(METRIC_REPEATED_STOPLOSS_STREAK, "2")
    malformed_ts = __import__("dataclasses").replace(malformed_ts, observed_from_ts_utc="bad")
    assert evaluate_account_protection_runtime_v1(policy=streak_policy, inputs=_inputs(metrics=(malformed_ts,)), requested_action=ACTION_BUY).decision_state == STATE_BLOCKED


def test_manual_lock_blocks_all_actions_and_is_account_isolated():
    policy = AccountProtectionPolicyV1("policy-1")
    lock = _lock(PROTECTION_MANUAL_ACCOUNT_LOCK, SCOPE_ACCOUNT, str(ACCOUNT_A))
    for action in (ACTION_BUY, ACTION_REDUCE, ACTION_EXIT):
        assert evaluate_account_protection_runtime_v1(policy=policy, inputs=_inputs(locks=(lock,)), requested_action=action).decision_state == STATE_BLOCKED
    assert evaluate_account_protection_runtime_v1(policy=policy, inputs=_inputs(account_id=ACCOUNT_B), requested_action=ACTION_EXIT).decision_state == STATE_PERMITTED


def test_cooldown_is_account_asset_scoped_and_does_not_block_exit():
    policy = AccountProtectionPolicyV1("policy-1")
    cooldown = _lock(PROTECTION_LOW_PROFIT_ASSET_COOLDOWN, SCOPE_ASSET, "42")
    assert evaluate_account_protection_runtime_v1(policy=policy, inputs=_inputs(locks=(cooldown,)), requested_action=ACTION_BUY).decision_state == STATE_BLOCKED
    assert evaluate_account_protection_runtime_v1(policy=policy, inputs=_inputs(locks=(cooldown,)), requested_action=ACTION_EXIT).decision_state == STATE_PERMITTED
    assert evaluate_account_protection_runtime_v1(policy=policy, inputs=_inputs(asset_id=99, locks=(cooldown,)), requested_action=ACTION_BUY).decision_state == STATE_PERMITTED
    assert evaluate_account_protection_runtime_v1(policy=policy, inputs=_inputs(account_id=ACCOUNT_B), requested_action=ACTION_BUY).decision_state == STATE_PERMITTED


def test_expired_cooldown_is_permitted_and_replay_is_deterministic():
    policy = AccountProtectionPolicyV1("policy-1")
    expired = _lock(
        PROTECTION_LOW_PROFIT_ASSET_COOLDOWN,
        SCOPE_ASSET,
        "42",
        triggered=NOW - timedelta(hours=1),
        expires=NOW - timedelta(seconds=1),
    )
    first = evaluate_account_protection_runtime_v1(policy=policy, inputs=_inputs(locks=(expired,)), requested_action=ACTION_BUY)
    second = evaluate_account_protection_runtime_v1(policy=policy, inputs=_inputs(locks=(expired,)), requested_action=ACTION_BUY)
    assert first.decision_state == STATE_PERMITTED
    assert first == second
