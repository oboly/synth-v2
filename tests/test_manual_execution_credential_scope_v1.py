"""Tests for src/executor/manual_execution_credential_scope_v1.py's
deny-by-default TRADE_EXECUTION credential scope resolver.

The fake cursor models the real INNER JOIN ... ON predicate (matching
trading_account_credential_id, trading_account_id, venue, and
permission_scope between the binding and the referenced credential row) so
identity-mismatch tests exercise the same "row never even joins" behavior
the production SQL enforces, not just the Python-side fallback."""
from __future__ import annotations

from typing import Any

import pytest

from src.executor.manual_execution_credential_scope_v1 import (
    CredentialScopeBinding,
    CredentialScopeDeniedError,
    ExecutorCredentialScopeRepository,
    _assert_credential_identity_match,
)


class _FakeCursor:
    def __init__(self, bindings: list[dict], credentials: list[dict]) -> None:
        self._bindings = bindings
        self._credentials = credentials
        self._result: list[dict] = []

    def execute(self, sql: str, params: list) -> None:
        trading_account_id, venue, executor_identity, runtime_owner, binding_status = params
        joined: list[dict] = []
        for binding in self._bindings:
            for credential in self._credentials:
                if credential["trading_account_credential_id"] != binding["trading_account_credential_id"]:
                    continue
                if credential["trading_account_id"] != binding["trading_account_id"]:
                    continue
                if credential["venue"] != binding["venue"]:
                    continue
                if credential["permission_scope"] != binding["permission_scope"]:
                    continue
                row = dict(binding)
                row["credential_trading_account_id"] = credential["trading_account_id"]
                row["credential_venue"] = credential["venue"]
                row["credential_permission_scope"] = credential["permission_scope"]
                row["credential_status"] = credential["credential_status"]
                row["credential_source"] = credential["credential_source"]
                row["allowed_order_write"] = credential["allowed_order_write"]
                row["allowed_withdrawal"] = credential["allowed_withdrawal"]
                joined.append(row)

        self._result = [
            row
            for row in joined
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
    def __init__(self, bindings: list[dict], credentials: list[dict]) -> None:
        self._cursor = _FakeCursor(bindings, credentials)

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
    )
    values.update(overrides)
    return values


def _credential_row(**overrides: Any) -> dict:
    values = dict(
        trading_account_credential_id=10,
        trading_account_id=1,
        venue="bitvavo",
        permission_scope="TRADE_EXECUTION",
        credential_status="ACTIVE",
        credential_source="db_encrypted",
        allowed_order_write=1,
        allowed_withdrawal=0,
    )
    values.update(overrides)
    return values


def _repo(bindings: list[dict], credentials: list[dict] | None = None) -> ExecutorCredentialScopeRepository:
    credentials = credentials if credentials is not None else [_credential_row()]
    return ExecutorCredentialScopeRepository(cursor_factory=lambda **_: _FakeSession(bindings, credentials))


def _resolve(repo: ExecutorCredentialScopeRepository, **overrides: Any) -> CredentialScopeBinding:
    values = dict(trading_account_id=1, venue="bitvavo", executor_identity="executor-dryrun-v1", runtime_owner="devlap")
    values.update(overrides)
    return repo.resolve(**values)


def test_resolves_exact_active_binding() -> None:
    repo = _repo([_binding_row()])
    binding = _resolve(repo)
    assert binding.executor_credential_binding_id == 1
    assert binding.allowed_withdrawal is False
    assert binding.allowed_order_write is True


def test_deny_by_default_when_no_binding_exists() -> None:
    repo = _repo([])
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_NOT_BOUND"):
        _resolve(repo, executor_identity="x")


def test_deny_on_ambiguous_duplicate_active_binding() -> None:
    repo = _repo(
        [
            _binding_row(executor_credential_binding_id=1, trading_account_credential_id=10),
            _binding_row(executor_credential_binding_id=2, trading_account_credential_id=11),
        ],
        credentials=[_credential_row(trading_account_credential_id=10), _credential_row(trading_account_credential_id=11)],
    )
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_AMBIGUOUS"):
        _resolve(repo)


def test_deny_wrong_executor_identity() -> None:
    repo = _repo([_binding_row(executor_identity="other-executor")])
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_NOT_BOUND"):
        _resolve(repo)


def test_deny_wrong_runtime_owner() -> None:
    repo = _repo([_binding_row(runtime_owner="odroid")])
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_NOT_BOUND"):
        _resolve(repo)


def test_deny_wrong_account_or_venue() -> None:
    repo = _repo([_binding_row()])
    with pytest.raises(CredentialScopeDeniedError):
        _resolve(repo, trading_account_id=2)
    with pytest.raises(CredentialScopeDeniedError):
        _resolve(repo, venue="kraken")


def test_deny_non_trade_execution_scope() -> None:
    repo = _repo(
        [_binding_row(permission_scope="READ_ONLY_PRIVATE")],
        credentials=[_credential_row(permission_scope="READ_ONLY_PRIVATE")],
    )
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_NOT_TRADE_EXECUTION"):
        _resolve(repo)


def test_deny_inactive_credential_status() -> None:
    repo = _repo([_binding_row()], credentials=[_credential_row(credential_status="REVOKED")])
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_CREDENTIAL_NOT_ACTIVE"):
        _resolve(repo)


def test_deny_withdrawal_capable_credential() -> None:
    repo = _repo([_binding_row()], credentials=[_credential_row(allowed_withdrawal=1)])
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_WITHDRAWAL_CAPABLE"):
        _resolve(repo)


def test_deny_trade_execution_credential_with_order_write_disabled() -> None:
    """The capability CHECK constraint only forbids order-write under
    READ_ONLY_PRIVATE; TRADE_EXECUTION + allowed_order_write=0 is a schema-
    legal row that must still be denied here."""
    repo = _repo([_binding_row()], credentials=[_credential_row(allowed_order_write=0)])
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_ORDER_WRITE_NOT_PERMITTED"):
        _resolve(repo)


def test_deny_binding_account_differs_from_credential_account() -> None:
    """A binding row cannot silently point at a credential belonging to a
    different trading_account_id: the JOIN predicate never matches, so the
    binding resolves as if it did not exist at all."""
    repo = _repo([_binding_row()], credentials=[_credential_row(trading_account_id=999)])
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_NOT_BOUND"):
        _resolve(repo)


def test_deny_binding_venue_differs_from_credential_venue() -> None:
    repo = _repo([_binding_row()], credentials=[_credential_row(venue="kraken")])
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_NOT_BOUND"):
        _resolve(repo)


def test_deny_binding_permission_scope_differs_from_credential_permission_scope() -> None:
    repo = _repo([_binding_row()], credentials=[_credential_row(permission_scope="READ_ONLY_PRIVATE")])
    with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_NOT_BOUND"):
        _resolve(repo)


def test_no_secret_fields_ever_selected() -> None:
    from src.executor.manual_execution_credential_scope_v1 import _SCOPE_SELECT

    for forbidden in ("encrypted_envelope", "credential_fingerprint", "api_key", "api_secret", "key_version"):
        assert forbidden not in _SCOPE_SELECT


class TestIdentityMatchDefenseInDepth:
    """Direct unit coverage of the Python-side identity check, independent
    of whether the SQL JOIN predicate is ever bypassed (e.g. by a future
    refactor or a test double that skips it)."""

    _BINDING = CredentialScopeBinding(
        executor_credential_binding_id=1, trading_account_credential_id=10,
        trading_account_id=1, venue="bitvavo", permission_scope="TRADE_EXECUTION",
        executor_identity="executor-dryrun-v1", runtime_owner="devlap",
        credential_status="ACTIVE", credential_source="db_encrypted",
        allowed_order_write=True, allowed_withdrawal=False,
    )

    def test_passes_on_matching_row(self) -> None:
        row = {
            "credential_trading_account_id": 1,
            "credential_venue": "bitvavo",
            "credential_permission_scope": "TRADE_EXECUTION",
        }
        _assert_credential_identity_match(row, binding=self._BINDING)

    def test_denies_mismatched_account(self) -> None:
        row = {"credential_trading_account_id": 2, "credential_venue": "bitvavo", "credential_permission_scope": "TRADE_EXECUTION"}
        with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_ACCOUNT_MISMATCH"):
            _assert_credential_identity_match(row, binding=self._BINDING)

    def test_denies_mismatched_venue(self) -> None:
        row = {"credential_trading_account_id": 1, "credential_venue": "kraken", "credential_permission_scope": "TRADE_EXECUTION"}
        with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_VENUE_MISMATCH"):
            _assert_credential_identity_match(row, binding=self._BINDING)

    def test_denies_mismatched_permission_scope(self) -> None:
        row = {"credential_trading_account_id": 1, "credential_venue": "bitvavo", "credential_permission_scope": "READ_ONLY_PRIVATE"}
        with pytest.raises(CredentialScopeDeniedError, match="CREDENTIAL_SCOPE_PERMISSION_SCOPE_MISMATCH"):
            _assert_credential_identity_match(row, binding=self._BINDING)
