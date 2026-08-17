from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.decision_gate.account_protection_policy_repository_v1 import (
    AccountProtectionPolicyRepositoryError,
    load_account_protection_policy_config_rows_v1,
)


NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, rows=()):
        self.rows = rows
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows=()):
        self.cursor_instance = _Cursor(rows)

    def cursor(self):
        return self.cursor_instance


def _row():
    return {
        "account_protection_policy_config_id": 1,
        "trading_account_id": 7,
        "config_version": "1",
        "configuration_version": "policy-1",
        "max_account_drawdown": "10.5",
        "max_daily_realized_loss": None,
        "max_repeated_stoploss_streak": 3,
        "max_metric_age_seconds": 900,
        "effective_from_ts_utc": NOW,
        "effective_until_ts_utc": None,
    }


def test_load_is_account_scoped_and_reconstructs_typed_row():
    conn = _Connection((_row(),))
    rows = load_account_protection_policy_config_rows_v1(conn, trading_account_id=7)
    assert len(rows) == 1
    row = rows[0]
    assert row.trading_account_id == 7
    assert row.max_account_drawdown == Decimal("10.5")
    assert row.max_daily_realized_loss is None
    assert row.max_repeated_stoploss_streak == 3
    _sql, params = conn.cursor_instance.calls[0]
    assert params == (7,)


def test_load_rejects_invalid_account_id():
    with pytest.raises(AccountProtectionPolicyRepositoryError, match="INVALID_TRADING_ACCOUNT_ID"):
        load_account_protection_policy_config_rows_v1(_Connection(), trading_account_id=0)


def test_load_rejects_malformed_persisted_row():
    row = _row()
    row["max_account_drawdown"] = "not-a-decimal"
    with pytest.raises(AccountProtectionPolicyRepositoryError, match="INVALID_PERSISTED_PROTECTION_CONFIG_ROW"):
        load_account_protection_policy_config_rows_v1(_Connection((row,)), trading_account_id=7)


def test_load_rejects_row_missing_required_key():
    row = _row()
    del row["config_version"]
    with pytest.raises(AccountProtectionPolicyRepositoryError, match="INVALID_PERSISTED_PROTECTION_CONFIG_ROW"):
        load_account_protection_policy_config_rows_v1(_Connection((row,)), trading_account_id=7)
