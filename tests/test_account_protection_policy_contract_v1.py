from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.decision_gate.account_protection_policy_contract_v1 import (
    AccountProtectionPolicyConfigError,
    AccountProtectionPolicyConfigRevocationV1,
    AccountProtectionPolicyConfigRowV1,
    resolve_account_protection_policy_v1,
)


NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
ACCOUNT_A = 7
ACCOUNT_B = 8


def _row(**changes: object) -> AccountProtectionPolicyConfigRowV1:
    values: dict[str, object] = dict(
        account_protection_policy_config_id=1,
        trading_account_id=ACCOUNT_A,
        config_version="1",
        configuration_version="policy-1",
        max_account_drawdown=None,
        max_daily_realized_loss=None,
        max_repeated_stoploss_streak=None,
        max_metric_age_seconds=900,
        effective_from_ts_utc=NOW - timedelta(days=1),
        effective_until_ts_utc=None,
        source_provenance="manual_review",
    )
    values.update(changes)
    return AccountProtectionPolicyConfigRowV1(**values)  # type: ignore[arg-type]


def _revocation(**changes: object) -> AccountProtectionPolicyConfigRevocationV1:
    values: dict[str, object] = dict(
        account_protection_policy_config_revocation_id=1,
        account_protection_policy_config_id=1,
        trading_account_id=ACCOUNT_A,
        revocation_version="1",
        effective_ts_utc=NOW,
        actor="operator-v1",
        reason="superseded",
    )
    values.update(changes)
    return AccountProtectionPolicyConfigRevocationV1(**values)  # type: ignore[arg-type]


def test_no_row_is_unresolved_and_fails_closed():
    with pytest.raises(AccountProtectionPolicyConfigError, match="PROTECTION_CONFIGURATION_UNRESOLVED"):
        resolve_account_protection_policy_v1((), trading_account_id=ACCOUNT_A, at=NOW)


def test_row_for_another_account_does_not_resolve():
    with pytest.raises(AccountProtectionPolicyConfigError, match="PROTECTION_CONFIGURATION_UNRESOLVED"):
        resolve_account_protection_policy_v1((_row(trading_account_id=ACCOUNT_B),), trading_account_id=ACCOUNT_A, at=NOW)


def test_row_outside_effective_window_does_not_resolve():
    future = _row(effective_from_ts_utc=NOW + timedelta(days=1))
    with pytest.raises(AccountProtectionPolicyConfigError, match="PROTECTION_CONFIGURATION_UNRESOLVED"):
        resolve_account_protection_policy_v1((future,), trading_account_id=ACCOUNT_A, at=NOW)


def test_overlapping_active_rows_are_ambiguous_and_fail_closed():
    row_a = _row(account_protection_policy_config_id=1)
    row_b = _row(account_protection_policy_config_id=2)
    with pytest.raises(AccountProtectionPolicyConfigError, match="AMBIGUOUS_PROTECTION_CONFIGURATION"):
        resolve_account_protection_policy_v1((row_a, row_b), trading_account_id=ACCOUNT_A, at=NOW)


def test_unsupported_config_version_fails_closed():
    row = _row(config_version="999")
    with pytest.raises(AccountProtectionPolicyConfigError, match="UNSUPPORTED_PROTECTION_CONFIGURATION_VERSION"):
        resolve_account_protection_policy_v1((row,), trading_account_id=ACCOUNT_A, at=NOW)


def test_malformed_effective_window_fails_closed():
    row = _row(effective_until_ts_utc=NOW - timedelta(days=2))  # until <= from
    with pytest.raises(AccountProtectionPolicyConfigError, match="INVALID_PROTECTION_CONFIGURATION_WINDOW"):
        resolve_account_protection_policy_v1((row,), trading_account_id=ACCOUNT_A, at=NOW)


def test_empty_source_provenance_fails_closed():
    row = _row(source_provenance="   ")
    with pytest.raises(AccountProtectionPolicyConfigError, match="INVALID_PROTECTION_CONFIGURATION_SOURCE_PROVENANCE"):
        resolve_account_protection_policy_v1((row,), trading_account_id=ACCOUNT_A, at=NOW)


def test_resolves_single_effective_row_to_typed_policy():
    row = _row(
        max_account_drawdown=Decimal("10"), max_daily_realized_loss=Decimal("100"),
        max_repeated_stoploss_streak=3, max_metric_age_seconds=120, configuration_version="policy-42",
    )
    policy = resolve_account_protection_policy_v1((row,), trading_account_id=ACCOUNT_A, at=NOW)
    assert policy.configuration_version == "policy-42"
    assert policy.max_account_drawdown == Decimal("10")
    assert policy.max_daily_realized_loss == Decimal("100")
    assert policy.max_repeated_stoploss_streak == 3
    assert policy.max_metric_age_seconds == 120


def test_invalid_lookup_arguments_raise():
    with pytest.raises(AccountProtectionPolicyConfigError, match="INVALID_PROTECTION_CONFIGURATION_LOOKUP"):
        resolve_account_protection_policy_v1((), trading_account_id=0, at=NOW)


# --- Revocation lifecycle -----------------------------------------------------


def test_open_ended_config_resolves_before_any_revocation():
    row = _row(effective_until_ts_utc=None)
    policy = resolve_account_protection_policy_v1((row,), (), trading_account_id=ACCOUNT_A, at=NOW)
    assert policy.configuration_version == "policy-1"


def test_revocation_makes_config_inactive_at_and_after_its_effective_timestamp():
    row = _row(account_protection_policy_config_id=1, effective_until_ts_utc=None)
    revocation = _revocation(account_protection_policy_config_id=1, effective_ts_utc=NOW)
    with pytest.raises(AccountProtectionPolicyConfigError, match="PROTECTION_CONFIGURATION_UNRESOLVED"):
        resolve_account_protection_policy_v1((row,), (revocation,), trading_account_id=ACCOUNT_A, at=NOW)
    with pytest.raises(AccountProtectionPolicyConfigError, match="PROTECTION_CONFIGURATION_UNRESOLVED"):
        resolve_account_protection_policy_v1(
            (row,), (revocation,), trading_account_id=ACCOUNT_A, at=NOW + timedelta(minutes=1),
        )
    # Still active strictly before the revocation's effective timestamp.
    policy = resolve_account_protection_policy_v1(
        (row,), (revocation,), trading_account_id=ACCOUNT_A, at=NOW - timedelta(minutes=1),
    )
    assert policy.configuration_version == "policy-1"


def test_successor_becomes_sole_effective_config_after_revocation():
    old = _row(
        account_protection_policy_config_id=1,
        effective_from_ts_utc=NOW - timedelta(days=10),
        effective_until_ts_utc=None,
        configuration_version="policy-old",
    )
    new = _row(
        account_protection_policy_config_id=2,
        effective_from_ts_utc=NOW,
        effective_until_ts_utc=None,
        configuration_version="policy-new",
    )
    revocation = _revocation(account_protection_policy_config_id=1, effective_ts_utc=NOW)
    policy = resolve_account_protection_policy_v1((old, new), (revocation,), trading_account_id=ACCOUNT_A, at=NOW)
    assert policy.configuration_version == "policy-new"


def test_future_revocation_does_not_revoke_early():
    row = _row(account_protection_policy_config_id=1, effective_until_ts_utc=None)
    future_revocation = _revocation(account_protection_policy_config_id=1, effective_ts_utc=NOW + timedelta(days=1))
    policy = resolve_account_protection_policy_v1(
        (row,), (future_revocation,), trading_account_id=ACCOUNT_A, at=NOW,
    )
    assert policy.configuration_version == "policy-1"


def test_future_revocation_does_not_prevent_a_later_immediate_valid_revoke():
    row = _row(account_protection_policy_config_id=1, effective_until_ts_utc=None)
    future_revocation = _revocation(
        account_protection_policy_config_revocation_id=1,
        account_protection_policy_config_id=1,
        effective_ts_utc=NOW + timedelta(days=1),
    )
    immediate_revocation = _revocation(
        account_protection_policy_config_revocation_id=2,
        account_protection_policy_config_id=1,
        effective_ts_utc=NOW,
    )
    with pytest.raises(AccountProtectionPolicyConfigError, match="PROTECTION_CONFIGURATION_UNRESOLVED"):
        resolve_account_protection_policy_v1(
            (row,), (future_revocation, immediate_revocation), trading_account_id=ACCOUNT_A, at=NOW,
        )


def test_multiple_unrevoked_active_configs_remain_ambiguous():
    row_a = _row(account_protection_policy_config_id=1)
    row_b = _row(account_protection_policy_config_id=2)
    # A not-yet-effective (future) revocation for row_a does not resolve
    # today's ambiguity between the two currently-active rows.
    not_yet_effective = _revocation(account_protection_policy_config_id=1, effective_ts_utc=NOW + timedelta(days=1))
    with pytest.raises(AccountProtectionPolicyConfigError, match="AMBIGUOUS_PROTECTION_CONFIGURATION"):
        resolve_account_protection_policy_v1(
            (row_a, row_b), (not_yet_effective,), trading_account_id=ACCOUNT_A, at=NOW,
        )


def test_revocation_referencing_unknown_config_fails_closed():
    row = _row(account_protection_policy_config_id=1)
    dangling = _revocation(account_protection_policy_config_id=999)
    with pytest.raises(AccountProtectionPolicyConfigError, match="INVALID_PROTECTION_CONFIGURATION_REVOCATION"):
        resolve_account_protection_policy_v1((row,), (dangling,), trading_account_id=ACCOUNT_A, at=NOW)


def test_revocation_effective_before_config_start_fails_closed():
    row = _row(account_protection_policy_config_id=1, effective_from_ts_utc=NOW - timedelta(days=1))
    too_early = _revocation(account_protection_policy_config_id=1, effective_ts_utc=NOW - timedelta(days=2))
    with pytest.raises(AccountProtectionPolicyConfigError, match="INVALID_PROTECTION_CONFIGURATION_REVOCATION"):
        resolve_account_protection_policy_v1((row,), (too_early,), trading_account_id=ACCOUNT_A, at=NOW)


def test_revocation_with_empty_reason_fails_closed():
    row = _row(account_protection_policy_config_id=1)
    malformed = _revocation(account_protection_policy_config_id=1, reason="  ")
    with pytest.raises(AccountProtectionPolicyConfigError, match="INVALID_PROTECTION_CONFIGURATION_REVOCATION"):
        resolve_account_protection_policy_v1((row,), (malformed,), trading_account_id=ACCOUNT_A, at=NOW)


def test_revocation_account_mismatch_fails_closed():
    row_a = _row(account_protection_policy_config_id=1, trading_account_id=ACCOUNT_A)
    row_b = _row(account_protection_policy_config_id=2, trading_account_id=ACCOUNT_B)
    # Corrupt fact: claims account A but actually references account B's config row.
    mismatched = AccountProtectionPolicyConfigRevocationV1(
        account_protection_policy_config_revocation_id=1,
        account_protection_policy_config_id=2,
        trading_account_id=ACCOUNT_A,
        revocation_version="1",
        effective_ts_utc=NOW,
        actor="operator-v1",
        reason="corrupt",
    )
    with pytest.raises(AccountProtectionPolicyConfigError, match="PROTECTION_CONFIGURATION_REVOCATION_ACCOUNT_MISMATCH"):
        resolve_account_protection_policy_v1(
            (row_a, row_b), (mismatched,), trading_account_id=ACCOUNT_A, at=NOW,
        )


def test_unsupported_revocation_version_fails_closed():
    row = _row(account_protection_policy_config_id=1)
    revocation = _revocation(account_protection_policy_config_id=1, revocation_version="999")
    with pytest.raises(
        AccountProtectionPolicyConfigError, match="UNSUPPORTED_PROTECTION_CONFIGURATION_REVOCATION_VERSION",
    ):
        resolve_account_protection_policy_v1((row,), (revocation,), trading_account_id=ACCOUNT_A, at=NOW)


def test_replay_is_deterministic_independent_of_row_and_revocation_order():
    old = _row(
        account_protection_policy_config_id=1,
        effective_from_ts_utc=NOW - timedelta(days=10),
        effective_until_ts_utc=None,
        configuration_version="policy-old",
    )
    new = _row(
        account_protection_policy_config_id=2,
        effective_from_ts_utc=NOW,
        effective_until_ts_utc=None,
        configuration_version="policy-new",
    )
    revoke_old = _revocation(account_protection_policy_config_revocation_id=1, account_protection_policy_config_id=1, effective_ts_utc=NOW)
    unrelated = _revocation(
        account_protection_policy_config_revocation_id=2,
        account_protection_policy_config_id=2,
        effective_ts_utc=NOW + timedelta(days=100),
    )

    forward = resolve_account_protection_policy_v1(
        (old, new), (revoke_old, unrelated), trading_account_id=ACCOUNT_A, at=NOW,
    )
    reversed_ = resolve_account_protection_policy_v1(
        (new, old), (unrelated, revoke_old), trading_account_id=ACCOUNT_A, at=NOW,
    )
    assert forward == reversed_
    assert forward.configuration_version == "policy-new"


def test_account_b_is_unaffected_by_account_a_config_revocation():
    """Account B cannot receive Account A's revocation as valid evidence."""
    config_a = _row(account_protection_policy_config_id=1, trading_account_id=ACCOUNT_A)
    config_b = _row(
        account_protection_policy_config_id=2, trading_account_id=ACCOUNT_B, configuration_version="policy-b",
    )
    revoke_a = _revocation(
        account_protection_policy_config_id=1, trading_account_id=ACCOUNT_A, effective_ts_utc=NOW,
    )

    with pytest.raises(AccountProtectionPolicyConfigError, match="PROTECTION_CONFIGURATION_UNRESOLVED"):
        resolve_account_protection_policy_v1(
            (config_a, config_b), (revoke_a,), trading_account_id=ACCOUNT_A, at=NOW,
        )

    policy_b = resolve_account_protection_policy_v1(
        (config_a, config_b), (revoke_a,), trading_account_id=ACCOUNT_B, at=NOW,
    )
    assert policy_b.configuration_version == "policy-b"
