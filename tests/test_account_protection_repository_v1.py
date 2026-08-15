from datetime import datetime, timezone

import pytest

from src.decision_gate.account_protection_contract_v1 import LOCK_FACT_CONTRACT_VERSION, PROTECTION_MANUAL_ACCOUNT_LOCK, PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK, SCOPE_ACCOUNT, SCOPE_ASSET, ProtectionLockFactV1
from src.decision_gate.account_protection_repository_v1 import (
    AccountProtectionRepositoryError,
    append_protection_lock_fact_v1,
    load_protection_lock_facts_for_account_v1,
)


NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def _fact() -> ProtectionLockFactV1:
    return ProtectionLockFactV1(
        lifecycle_id="lifecycle", event_id="event", protection_code=PROTECTION_MANUAL_ACCOUNT_LOCK,
        protection_version=LOCK_FACT_CONTRACT_VERSION, trading_account_id=7, scope_type=SCOPE_ACCOUNT, scope_id="7",
        observed_from_ts_utc=NOW, observed_to_ts_utc=NOW.replace(minute=1), triggered_ts_utc=NOW.replace(minute=1),
        expires_ts_utc=None, reason_code="OPERATOR", evidence_refs=("operator:1",), configuration_version="policy-1",
    )


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
    fact = _fact()
    return {
        "lifecycle_id": fact.lifecycle_id, "event_id": fact.event_id, "protection_code": fact.protection_code,
        "protection_version": fact.protection_version, "trading_account_id": fact.trading_account_id,
        "scope_type": fact.scope_type, "scope_id": fact.scope_id, "observed_from_ts_utc": fact.observed_from_ts_utc,
        "observed_to_ts_utc": fact.observed_to_ts_utc, "triggered_ts_utc": fact.triggered_ts_utc,
        "expires_ts_utc": None, "reason_code": fact.reason_code, "evidence_refs_json": '["operator:1"]',
        "configuration_version": fact.configuration_version, "lock_state": fact.lock_state,
    }


def test_append_uses_immutable_event_identity_and_validates_fact():
    conn = _Connection()
    append_protection_lock_fact_v1(conn, fact=_fact())
    sql, params = conn.cursor_instance.calls[0]
    assert "INSERT INTO account_protection_lock_fact_v1" in sql
    assert params[1] == "event"
    with pytest.raises(AccountProtectionRepositoryError, match="INVALID_PROTECTION_LOCK_FACT"):
        append_protection_lock_fact_v1(
            conn,
            fact=__import__("dataclasses").replace(
                _fact(), protection_code=PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK, scope_type=SCOPE_ASSET,
            ),
        )
    with pytest.raises(AccountProtectionRepositoryError, match="INVALID_PROTECTION_LOCK_FACT"):
        append_protection_lock_fact_v1(conn, fact=__import__("dataclasses").replace(_fact(), evidence_refs=()))


def test_load_is_account_scoped_and_reconstructs_typed_fact():
    conn = _Connection((_row(),))
    facts = load_protection_lock_facts_for_account_v1(conn, trading_account_id=7)
    assert facts == (_fact(),)
    _sql, params = conn.cursor_instance.calls[0]
    assert params == (7,)
    with pytest.raises(AccountProtectionRepositoryError, match="INVALID_TRADING_ACCOUNT_ID"):
        load_protection_lock_facts_for_account_v1(conn, trading_account_id=0)


def test_load_rejects_unsupported_persisted_fact_version():
    row = _row()
    row["protection_version"] = "999"
    with pytest.raises(AccountProtectionRepositoryError, match="INVALID_PERSISTED_PROTECTION_FACT"):
        load_protection_lock_facts_for_account_v1(_Connection((row,)), trading_account_id=7)
