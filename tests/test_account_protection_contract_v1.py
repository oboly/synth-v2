from datetime import datetime, timedelta, timezone

import pytest

from src.decision_gate.account_protection_contract_v1 import (
    ACTION_BUY,
    ACTION_EXIT,
    ACTION_REDUCE,
    AccountProtectionContractError,
    LOCK_FACT_CONTRACT_VERSION,
    LOCK_STATE_ACTIVE,
    LOCK_STATE_RECOVERED,
    PROTECTION_DAILY_REALIZED_LOSS_BLOCK,
    PROTECTION_LOW_PROFIT_ASSET_COOLDOWN,
    PROTECTION_MANUAL_ACCOUNT_LOCK,
    PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
    PROTECTION_POST_CLOSE_REENTRY_COOLDOWN,
    PROTECTION_REPEATED_STOPLOSS_BLOCK,
    ProtectionLockFactV1,
    REASON_ACCOUNT_STATE_EVIDENCE_MISSING,
    REASON_ACCOUNT_STATE_EVIDENCE_STALE,
    REASON_MANUAL_ACCOUNT_LOCK_ACTIVE,
    REASON_MAX_ACCOUNT_DRAWDOWN_TRIGGERED,
    REASON_OK,
    SCOPE_ACCOUNT,
    SCOPE_ASSET,
    STATE_BLOCKED,
    STATE_PERMITTED,
    account_protection_lock_event_id_v1,
    account_protection_lock_lifecycle_id_v1,
    resolve_account_protection_state_for_action_v1,
    resolve_account_protection_state_v1,
)


NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 7


def _lock(**changes: object) -> ProtectionLockFactV1:
    values: dict[str, object] = dict(
        lifecycle_id="",
        event_id="",
        protection_code=PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
        protection_version=LOCK_FACT_CONTRACT_VERSION,
        trading_account_id=ACCOUNT_ID,
        scope_type=SCOPE_ACCOUNT,
        scope_id=str(ACCOUNT_ID),
        observed_from_ts_utc=NOW - timedelta(days=1),
        observed_to_ts_utc=NOW,
        triggered_ts_utc=NOW,
        expires_ts_utc=NOW + timedelta(hours=1),
        reason_code="DRAWDOWN_EXCEEDED",
        evidence_refs=("equity_curve:123",),
        configuration_version="cfg-1",
        lock_state=LOCK_STATE_ACTIVE,
    )
    values.update(changes)
    if not values["lifecycle_id"]:
        values["lifecycle_id"] = f"lifecycle-{values['protection_code']}-{values['scope_type']}-{values['scope_id']}"
    if not values["event_id"]:
        values["event_id"] = f"event-{values['lifecycle_id']}-{values['lock_state']}-{values['triggered_ts_utc'].isoformat()}"
    return ProtectionLockFactV1(**values)


def _resolve(facts, **changes):
    values: dict[str, object] = dict(
        facts=facts,
        trading_account_id=ACCOUNT_ID,
        sleeve_code=None,
        asset_id=None,
        account_state_observed_ts_utc=NOW,
        account_state_fresh=True,
        at=NOW,
    )
    values.update(changes)
    return resolve_account_protection_state_v1(**values)


def _resolve_action(facts, *, action=ACTION_BUY, **changes):
    values: dict[str, object] = dict(
        facts=facts,
        trading_account_id=ACCOUNT_ID,
        sleeve_code=None,
        asset_id=42,
        requested_action=action,
        account_state_observed_ts_utc=NOW,
        account_state_fresh=True,
        at=NOW,
    )
    values.update(changes)
    return resolve_account_protection_state_for_action_v1(**values)


def test_permitted_when_no_locks():
    result = _resolve(())
    assert result.decision_state == STATE_PERMITTED
    assert result.reason_code == REASON_OK
    assert result.contributing_lock_facts == ()


def test_blocked_when_active_drawdown_lock():
    result = _resolve((_lock(),))
    assert result.decision_state == STATE_BLOCKED
    assert result.reason_code == REASON_MAX_ACCOUNT_DRAWDOWN_TRIGGERED
    assert result.protection_code == PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK


def test_expired_lock_does_not_block():
    expired = _lock(triggered_ts_utc=NOW - timedelta(hours=2), expires_ts_utc=NOW - timedelta(hours=1))
    result = _resolve((expired,))
    assert result.decision_state == STATE_PERMITTED


def test_future_triggered_lock_does_not_block_yet():
    future = _lock(triggered_ts_utc=NOW + timedelta(hours=1), expires_ts_utc=NOW + timedelta(hours=2))
    result = _resolve((future,))
    assert result.decision_state == STATE_PERMITTED


def test_recovered_lock_state_does_not_block():
    recovered = _lock(lock_state=LOCK_STATE_RECOVERED)
    result = _resolve((recovered,))
    assert result.decision_state == STATE_PERMITTED


def test_precedence_manual_lock_over_drawdown():
    drawdown = _lock()
    manual = _lock(protection_code=PROTECTION_MANUAL_ACCOUNT_LOCK, reason_code="OPERATOR_LOCK")
    result = _resolve((drawdown, manual))
    assert result.decision_state == STATE_BLOCKED
    assert result.protection_code == PROTECTION_MANUAL_ACCOUNT_LOCK
    assert result.reason_code == REASON_MANUAL_ACCOUNT_LOCK_ACTIVE
    # Evidence for both active locks is preserved even though one wins.
    assert len(result.contributing_lock_facts) == 2


def test_precedence_drawdown_over_daily_loss():
    daily_loss = _lock(protection_code=PROTECTION_DAILY_REALIZED_LOSS_BLOCK)
    drawdown = _lock()
    result = _resolve((daily_loss, drawdown))
    assert result.protection_code == PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK
    assert result.reason_code == REASON_MAX_ACCOUNT_DRAWDOWN_TRIGGERED


def test_precedence_cooldown_is_lowest():
    cooldown = _lock(
        protection_code=PROTECTION_LOW_PROFIT_ASSET_COOLDOWN, scope_type=SCOPE_ASSET, scope_id="42",
    )
    streak = _lock(protection_code=PROTECTION_REPEATED_STOPLOSS_BLOCK, scope_type=SCOPE_ASSET, scope_id="42")
    result = _resolve((cooldown, streak), asset_id=42)
    assert result.protection_code == PROTECTION_REPEATED_STOPLOSS_BLOCK


def test_fail_closed_when_account_state_not_fresh():
    result = _resolve((), account_state_fresh=False)
    assert result.decision_state == STATE_BLOCKED
    assert result.reason_code == REASON_ACCOUNT_STATE_EVIDENCE_MISSING


def test_fail_closed_when_account_state_stale():
    stale_observed = NOW - timedelta(hours=1)
    result = _resolve((), account_state_observed_ts_utc=stale_observed, max_account_state_age_seconds=60)
    assert result.decision_state == STATE_BLOCKED
    assert result.reason_code == REASON_ACCOUNT_STATE_EVIDENCE_STALE


def test_fail_closed_beats_an_otherwise_permitted_result():
    # Even with zero locks, stale account state must still block.
    result = _resolve((), account_state_fresh=False)
    assert result.decision_state == STATE_BLOCKED


def test_naive_evaluation_timestamp_raises():
    with pytest.raises(AccountProtectionContractError):
        _resolve((), at=datetime(2026, 8, 15, 12, 0))


def test_cross_account_evidence_raises():
    foreign = _lock(trading_account_id=ACCOUNT_ID + 1)
    with pytest.raises(AccountProtectionContractError):
        _resolve((foreign,))


def test_invalid_protection_scope_pairing_raises():
    bad = _lock(protection_code=PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK, scope_type=SCOPE_ASSET, scope_id="42")
    with pytest.raises(AccountProtectionContractError):
        _resolve((bad,))


def test_sleeve_and_asset_scope_isolation():
    other_asset_cooldown = _lock(
        protection_code=PROTECTION_POST_CLOSE_REENTRY_COOLDOWN, scope_type=SCOPE_ASSET, scope_id="99",
    )
    result = _resolve((other_asset_cooldown,), asset_id=42)
    assert result.decision_state == STATE_PERMITTED


def test_account_scope_lock_applies_regardless_of_asset_lookup():
    result = _resolve((_lock(),), asset_id=42)
    assert result.decision_state == STATE_BLOCKED
    assert result.protection_code == PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK


def test_restart_determinism_latest_triggered_fact_wins():
    original = _lock(triggered_ts_utc=NOW - timedelta(minutes=30), expires_ts_utc=NOW + timedelta(hours=1))
    recovery = _lock(
        triggered_ts_utc=NOW - timedelta(minutes=1), lock_state=LOCK_STATE_RECOVERED,
        expires_ts_utc=NOW + timedelta(hours=1), event_id="event-recovered",
    )
    # Order in the input iterable must not affect the outcome.
    result_a = _resolve((original, recovery))
    result_b = _resolve((recovery, original))
    assert result_a.decision_state == STATE_PERMITTED
    assert result_b.decision_state == STATE_PERMITTED


def test_lifecycle_identity_stable_across_reordering():
    evidence = dict(
        protection_code=PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
        protection_version=LOCK_FACT_CONTRACT_VERSION,
        trading_account_id=ACCOUNT_ID,
        scope_type=SCOPE_ACCOUNT,
        scope_id=str(ACCOUNT_ID),
        observed_from_ts_utc=NOW - timedelta(days=1),
        observed_to_ts_utc=NOW,
        configuration_version="cfg-1",
    )
    key_a = account_protection_lock_lifecycle_id_v1(evidence)
    key_b = account_protection_lock_lifecycle_id_v1(dict(reversed(list(evidence.items()))))
    assert key_a == key_b


def test_lifecycle_identity_ignores_event_fields_but_changes_with_window():
    base = dict(
        protection_code=PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
        protection_version=LOCK_FACT_CONTRACT_VERSION,
        trading_account_id=ACCOUNT_ID,
        scope_type=SCOPE_ACCOUNT,
        scope_id=str(ACCOUNT_ID),
        observed_from_ts_utc=NOW - timedelta(days=1),
        observed_to_ts_utc=NOW,
        configuration_version="cfg-1",
    )
    with_extra = dict(base, triggered_ts_utc=NOW, reason_code="X")
    key_ignoring_extra = account_protection_lock_lifecycle_id_v1(with_extra)
    key_base = account_protection_lock_lifecycle_id_v1(base)
    assert key_ignoring_extra == key_base

    changed_window = dict(base, observed_to_ts_utc=NOW + timedelta(minutes=1))
    key_changed = account_protection_lock_lifecycle_id_v1(changed_window)
    assert key_changed != key_base


def test_lifecycle_identity_requires_all_fields():
    incomplete = dict(protection_code=PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK)
    with pytest.raises(AccountProtectionContractError):
        account_protection_lock_lifecycle_id_v1(incomplete)


def test_lifecycle_transitions_are_distinct_append_only_events():
    lifecycle_id = account_protection_lock_lifecycle_id_v1(dict(
        protection_code=PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
        protection_version=LOCK_FACT_CONTRACT_VERSION,
        trading_account_id=ACCOUNT_ID,
        scope_type=SCOPE_ACCOUNT,
        scope_id=str(ACCOUNT_ID),
        observed_from_ts_utc=NOW - timedelta(days=1),
        observed_to_ts_utc=NOW,
        configuration_version="cfg-1",
    ))
    active_event_id = account_protection_lock_event_id_v1(dict(
        lifecycle_id=lifecycle_id, lock_state=LOCK_STATE_ACTIVE, triggered_ts_utc=NOW - timedelta(minutes=30),
    ))
    recovered_event_id = account_protection_lock_event_id_v1(dict(
        lifecycle_id=lifecycle_id, lock_state=LOCK_STATE_RECOVERED, triggered_ts_utc=NOW - timedelta(minutes=1),
    ))
    assert active_event_id != recovered_event_id
    active = _lock(
        lifecycle_id=lifecycle_id, event_id=active_event_id,
        triggered_ts_utc=NOW - timedelta(minutes=30), expires_ts_utc=NOW + timedelta(hours=1),
    )
    recovered = _lock(
        lifecycle_id=lifecycle_id, event_id=recovered_event_id,
        triggered_ts_utc=NOW - timedelta(minutes=1), expires_ts_utc=NOW + timedelta(hours=1),
        lock_state=LOCK_STATE_RECOVERED,
    )
    assert _resolve((active, recovered)).decision_state == STATE_PERMITTED


def test_duplicate_event_identity_is_rejected():
    with pytest.raises(AccountProtectionContractError, match="DUPLICATE_PROTECTION_LOCK_EVENT_ID"):
        _resolve((_lock(), _lock()))


@pytest.mark.parametrize(
    "protection_code,scope_type,scope_id",
    [
        (PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK, SCOPE_ACCOUNT, str(ACCOUNT_ID)),
        (PROTECTION_DAILY_REALIZED_LOSS_BLOCK, SCOPE_ACCOUNT, str(ACCOUNT_ID)),
        (PROTECTION_REPEATED_STOPLOSS_BLOCK, SCOPE_ASSET, "42"),
        (PROTECTION_LOW_PROFIT_ASSET_COOLDOWN, SCOPE_ASSET, "42"),
        (PROTECTION_POST_CLOSE_REENTRY_COOLDOWN, SCOPE_ASSET, "42"),
    ],
)
def test_risk_increase_protections_block_buy_but_allow_reduce_and_exit(protection_code, scope_type, scope_id):
    lock = _lock(protection_code=protection_code, scope_type=scope_type, scope_id=scope_id)
    assert _resolve_action((lock,), action=ACTION_BUY).decision_state == STATE_BLOCKED
    assert _resolve_action((lock,), action=ACTION_REDUCE).decision_state == STATE_PERMITTED
    assert _resolve_action((lock,), action=ACTION_EXIT).decision_state == STATE_PERMITTED


@pytest.mark.parametrize("action", [ACTION_BUY, ACTION_REDUCE, ACTION_EXIT])
def test_manual_lock_blocks_every_action(action):
    lock = _lock(protection_code=PROTECTION_MANUAL_ACCOUNT_LOCK)
    assert _resolve_action((lock,), action=action).decision_state == STATE_BLOCKED


def test_unsupported_action_is_rejected_fail_closed():
    with pytest.raises(AccountProtectionContractError, match="UNSUPPORTED_PROTECTION_ACTION"):
        _resolve_action((), action="SELL")


def test_precedence_applies_after_action_filter():
    drawdown = _lock(protection_code=PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK)
    cooldown = _lock(protection_code=PROTECTION_LOW_PROFIT_ASSET_COOLDOWN, scope_type=SCOPE_ASSET, scope_id="42")
    assert _resolve_action((drawdown, cooldown), action=ACTION_EXIT).decision_state == STATE_PERMITTED
    buy = _resolve_action((drawdown, cooldown), action=ACTION_BUY)
    assert buy.protection_code == PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK
    manual = _lock(protection_code=PROTECTION_MANUAL_ACCOUNT_LOCK)
    exit_result = _resolve_action((manual, drawdown), action=ACTION_EXIT)
    assert exit_result.protection_code == PROTECTION_MANUAL_ACCOUNT_LOCK


def test_action_resolution_preserves_account_and_asset_isolation():
    cooldown = _lock(protection_code=PROTECTION_LOW_PROFIT_ASSET_COOLDOWN, scope_type=SCOPE_ASSET, scope_id="42")
    assert _resolve_action((cooldown,), asset_id=99).decision_state == STATE_PERMITTED
    foreign = _lock(trading_account_id=ACCOUNT_ID + 1)
    with pytest.raises(AccountProtectionContractError, match="CROSS_ACCOUNT_EVIDENCE_LEAKAGE"):
        _resolve_action((foreign,))


def test_stale_evidence_blocks_independently_of_action():
    for action in (ACTION_BUY, ACTION_REDUCE, ACTION_EXIT):
        result = _resolve_action((), action=action, account_state_fresh=False)
        assert result.decision_state == STATE_BLOCKED


def test_ambiguous_same_lifecycle_timestamp_is_rejected():
    original = _lock(lifecycle_id="same", event_id="event-a")
    contradictory = _lock(lifecycle_id="same", event_id="event-b")
    with pytest.raises(AccountProtectionContractError, match="AMBIGUOUS_PROTECTION_LIFECYCLE_EVENT"):
        _resolve_action((original, contradictory))


def test_lifecycle_identity_cannot_change_across_append_only_events():
    active = _lock(lifecycle_id="same", event_id="active", triggered_ts_utc=NOW - timedelta(minutes=1))
    invalid_clear = _lock(
        lifecycle_id="same",
        event_id="clear",
        triggered_ts_utc=NOW,
        lock_state=LOCK_STATE_RECOVERED,
        configuration_version="different-policy",
    )
    with pytest.raises(AccountProtectionContractError, match="CONTRADICTORY_PROTECTION_LIFECYCLE_IDENTITY"):
        _resolve_action((active, invalid_clear))
