"""Tests for src/executor/manual_execution_credential_scope_v1.py's
deny-by-default TRADE_EXECUTION credential scope resolver."""
from __future__ import annotations

from typing import Any

import pytest

from src.executor.manual_execution_credential_scope_v1 import (
    CredentialScopeDeniedError,
    ExecutorCredentialScopeRepository,
)


class _FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self._result: list[dict] = []

    def execute(self, sql: str, params: list) -> None:
        trading_account_id, venue, executor_identity, runtime_owner, binding_status = params
        self._result = [
            row
            for row in self._rows
            if row["trading_account_id"] == trading_account_id
            and row["venue"] == venue
            and row["executor_identity"] == executor_identity
            and row["runtime_owner"] == runtime_owner
            and row["binding_status"] == binding_status
        ]

    def fetchall(self) -> list[dict]:
        return self._result

    def fetchone(self):
        return self._result[0] if self._result else None


class _FakeSession:
    def __init__(self, rows: list[dict]) -> None:
        self._cursor = _FakeCursor(rows)

    def __enter__(self) -> Any:
        return self._cursor

    def __exit__(self, *exc: Any) -> bool:
        return False


def _binding_row(**overrides: Any) -> dict:
    values = dict(
        executor_credential_binding_id=1,
        trading_account_credential_id=10,
        trading_account_id=1,
        venue="bitvavo",
        permission_scope="TRADE_EXECUTION",
        executor_identity="executor-dryrun-v1",
        runtime_owner="devlap",
        binding_status="ACTIVE",
        credential_status="ACTIVE",
        credential_source="db_encrypted",
        allowed_order_write=1,
        allowed_withdrawal=0,
    )
    values.update(overrides)
    return values


def _repo(rows: list[dict]) -> ExecutorCredentialScopeRepository:
    return ExecutorCredentialScopeRepository(cursor_factory=lambda **_: _FakeSession(rows))


def test_resolves_exact_active_binding() -> None:
    repo = _repo([_binding_row()])
    binding = repo.resolve(
        trading_account_id=1, venue="bitvavo", executor_identity="executor-dryrun-v1", runtime_owner="devlap"
    )
    assert binding.executor_credential_binding_id == 1
    assert binding.allowed_withdrawal is False


def test_deny_by_default_when_no_binding_exists() -> None:
    repo = _repo([])
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_NOT_BOUND"):
        repo.resolve(trading_account_id=1, venue="bitvavo", executor_identity="x", runtime_owner="devlap")


def test_deny_on_ambiguous_duplicate_active_binding() -> None:
    repo = _repo([_binding_row(executor_credential_binding_id=1), _binding_row(executor_credential_binding_id=2)])
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_AMBIGUOUS"):
        repo.resolve(
            trading_account_id=1, venue="bitvavo", executor_identity="executor-dryrun-v1", runtime_owner="devlap"
        )


def test_deny_wrong_executor_identity() -> None:
    repo = _repo([_binding_row(executor_identity="other-executor")])
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_NOT_BOUND"):
        repo.resolve(
            trading_account_id=1, venue="bitvavo", executor_identity="executor-dryrun-v1", runtime_owner="devlap"
        )


def test_deny_wrong_runtime_owner() -> None:
    repo = _repo([_binding_row(runtime_owner="odroid")])
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_NOT_BOUND"):
        repo.resolve(
            trading_account_id=1, venue="bitvavo", executor_identity="executor-dryrun-v1", runtime_owner="devlap"
        )


def test_deny_wrong_account_or_venue() -> None:
    repo = _repo([_binding_row()])
    with pytest.raises(CredentialScopeDeniedError):
        repo.resolve(
            trading_account_id=2, venue="bitvavo", executor_identity="executor-dryrun-v1", runtime_owner="devlap"
        )
    with pytest.raises(CredentialScopeDeniedError):
        repo.resolve(
            trading_account_id=1, venue="kraken", executor_identity="executor-dryrun-v1", runtime_owner="devlap"
        )


def test_deny_non_trade_execution_scope() -> None:
    repo = _repo([_binding_row(permission_scope="READ_ONLY_PRIVATE")])
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_NOT_TRADE_EXECUTION"):
        repo.resolve(
            trading_account_id=1, venue="bitvavo", executor_identity="executor-dryrun-v1", runtime_owner="devlap"
        )


def test_deny_inactive_credential_status() -> None:
    repo = _repo([_binding_row(credential_status="REVOKED")])
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_CREDENTIAL_NOT_ACTIVE"):
        repo.resolve(
            trading_account_id=1, venue="bitvavo", executor_identity="executor-dryrun-v1", runtime_owner="devlap"
        )


def test_deny_withdrawal_capable_credential() -> None:
    repo = _repo([_binding_row(allowed_withdrawal=1)])
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_WITHDRAWAL_CAPABLE"):
        repo.resolve(
            trading_account_id=1, venue="bitvavo", executor_identity="executor-dryrun-v1", runtime_owner="devlap"
        )


def test_no_secret_fields_ever_selected() -> None:
    from src.executor.manual_execution_credential_scope_v1 import _SCOPE_SELECT

    for forbidden in ("encrypted_envelope", "credential_fingerprint", "api_key", "api_secret", "key_version"):
        assert forbidden not in _SCOPE_SELECT
