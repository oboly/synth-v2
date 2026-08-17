from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.decision_gate.account_protection_policy_contract_v1 import (
    AccountProtectionPolicyConfigError,
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
    )
    values.update(changes)
    return AccountProtectionPolicyConfigRowV1(**values)  # type: ignore[arg-type]


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


def test_superseded_row_is_ignored_once_a_later_window_is_active():
    old = _row(
        account_protection_policy_config_id=1,
        effective_from_ts_utc=NOW - timedelta(days=10),
        effective_until_ts_utc=NOW - timedelta(days=1),
        configuration_version="policy-old",
    )
    new = _row(
        account_protection_policy_config_id=2,
        effective_from_ts_utc=NOW - timedelta(days=1),
        effective_until_ts_utc=None,
        configuration_version="policy-new",
    )
    policy = resolve_account_protection_policy_v1((old, new), trading_account_id=ACCOUNT_A, at=NOW)
    assert policy.configuration_version == "policy-new"


def test_invalid_lookup_arguments_raise():
    with pytest.raises(AccountProtectionPolicyConfigError, match="INVALID_PROTECTION_CONFIGURATION_LOOKUP"):
        resolve_account_protection_policy_v1((), trading_account_id=0, at=NOW)
