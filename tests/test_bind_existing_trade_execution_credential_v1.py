from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.account_provisioning.existing_trade_execution_credential_binding_v1 import (
    BindExistingTradeExecutionCredentialRepository,
    bind_existing_trade_execution_credential,
)
from src.account_provisioning.run_bind_existing_trade_execution_credential_v1 import parse_args
from src.account_provisioning.trade_execution_provisioning_v1 import (
    MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY,
    MANUAL_EXECUTION_RUNTIME_OWNER,
    SHARED_EXECUTOR_IDENTITY,
    SHARED_EXECUTOR_RUNTIME_OWNER,
)

_ACTIVE_CREDENTIAL = {
    "trading_account_credential_id": 5,
    "trading_account_id": 5,
    "venue": "bitvavo",
    "permission_scope": "TRADE_EXECUTION",
    "credential_status": "ACTIVE",
    "allowed_order_write": 1,
    "allowed_withdrawal": 0,
    "credential_source": "db_encrypted",
    "validation_state": "VALID_TRADE_EXECUTION",
    "validated_ts_utc": "2026-08-29T12:00:00Z",
    "allowed_private_read": 1,
}

_MANUAL_KEY = (MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY, MANUAL_EXECUTION_RUNTIME_OWNER)
_SHARED_KEY = (SHARED_EXECUTOR_IDENTITY, SHARED_EXECUTOR_RUNTIME_OWNER)


class _Conn:
    def __init__(self) -> None:
        self.committed = self.rolled_back = self.closed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class _Repo:
    _UNSET = object()

    def __init__(self, _conn, *, account=True, credential=_UNSET, bindings=None) -> None:
        self.account = account
        self.credential = dict(_ACTIVE_CREDENTIAL) if credential is self._UNSET else credential
        self.bindings = dict(bindings or {})
        self.next_binding_id = 9
        self.insert_calls = 0

    def find_credential_by_id(self, **_):
        return self.credential

    def require_account(self, **_):
        if not self.account:
            raise ValueError("TRADING_ACCOUNT_VENUE_NOT_FOUND")

    def find_active_binding(self, *, executor_identity, runtime_owner, **_):
        return self.bindings.get((executor_identity, runtime_owner))

    def insert_binding(self, *, credential_id, executor_identity, runtime_owner, **kwargs):
        self.insert_calls += 1
        binding_id = self.next_binding_id
        self.next_binding_id += 1
        self.bindings[(executor_identity, runtime_owner)] = {
            "executor_credential_binding_id": binding_id,
            "trading_account_credential_id": credential_id,
            "executor_identity": executor_identity,
            "runtime_owner": runtime_owner,
        }
        return binding_id


def _run(
    repo: _Repo,
    *,
    executor_identity=SHARED_EXECUTOR_IDENTITY,
    runtime_owner=SHARED_EXECUTOR_RUNTIME_OWNER,
    trading_account_id=5,
    trading_account_credential_id=5,
    apply=False,
):
    conn = _Conn()
    result = bind_existing_trade_execution_credential(
        trading_account_id=trading_account_id,
        trading_account_credential_id=trading_account_credential_id,
        executor_identity=executor_identity,
        runtime_owner=runtime_owner,
        conn_factory=lambda: conn,
        repository_factory=lambda _: repo,
        apply=apply,
    )
    return result, conn


def test_default_service_call_is_read_only_when_binding_missing() -> None:
    repo = _Repo(None)
    result, conn = _run(repo)
    assert result.binding_exists is False
    assert result.created_binding is False
    assert result.executor_credential_binding_id == 0
    assert repo.insert_calls == 0
    assert not conn.committed and conn.rolled_back and conn.closed


def test_apply_binds_new_shared_tuple_to_existing_credential() -> None:
    repo = _Repo(None)
    result, conn = _run(repo, apply=True)
    assert result.binding_exists is True
    assert result.created_binding is True
    assert result.executor_identity == SHARED_EXECUTOR_IDENTITY
    assert result.runtime_owner == SHARED_EXECUTOR_RUNTIME_OWNER
    assert repo.insert_calls == 1
    assert conn.committed and not conn.rolled_back


def test_check_existing_binding_is_idempotent_and_read_only() -> None:
    existing = {
        "executor_credential_binding_id": 9,
        "trading_account_credential_id": 5,
        "executor_identity": SHARED_EXECUTOR_IDENTITY,
        "runtime_owner": SHARED_EXECUTOR_RUNTIME_OWNER,
    }
    repo = _Repo(None, bindings={_SHARED_KEY: existing})
    result, conn = _run(repo)
    assert result.binding_exists is True
    assert result.executor_credential_binding_id == 9
    assert result.created_binding is False
    assert repo.insert_calls == 0
    assert conn.rolled_back and not conn.committed


def test_idempotent_apply_does_not_duplicate() -> None:
    repo = _Repo(None)
    first, _ = _run(repo, apply=True)
    second, _ = _run(repo, apply=True)
    assert first.executor_credential_binding_id == second.executor_credential_binding_id
    assert second.created_binding is False
    assert repo.insert_calls == 1


def test_existing_manual_binding_is_untouched() -> None:
    existing_manual = {
        "executor_credential_binding_id": 2,
        "trading_account_credential_id": 5,
        "executor_identity": MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY,
        "runtime_owner": MANUAL_EXECUTION_RUNTIME_OWNER,
    }
    repo = _Repo(None, bindings={_MANUAL_KEY: dict(existing_manual)})
    result, _ = _run(repo, apply=True)
    assert repo.bindings[_MANUAL_KEY] == existing_manual
    assert result.executor_credential_binding_id != 2
    assert _SHARED_KEY in repo.bindings


@pytest.mark.parametrize(
    "overrides,expected_error",
    [
        ({"permission_scope": "READ_ONLY_PRIVATE"}, "CREDENTIAL_PERMISSION_SCOPE_MISMATCH"),
        ({"credential_status": "REVOKED"}, "CREDENTIAL_NOT_ACTIVE"),
        ({"allowed_order_write": 0}, "CREDENTIAL_MISSING_ORDER_WRITE_SCOPE"),
        ({"allowed_withdrawal": 1}, "CREDENTIAL_WITHDRAWAL_CAPABILITY_NOT_ALLOWED"),
        ({"credential_source": "legacy_env"}, "CREDENTIAL_SOURCE_MISMATCH"),
        ({"validation_state": "UNVALIDATED"}, "CREDENTIAL_NOT_VALID_TRADE_EXECUTION"),
        ({"validated_ts_utc": None}, "CREDENTIAL_VALIDATION_TIMESTAMP_MISSING"),
        ({"allowed_private_read": 0}, "CREDENTIAL_MISSING_PRIVATE_READ_SCOPE"),
    ],
)
def test_credential_eligibility_fails_closed(overrides, expected_error) -> None:
    repo = _Repo(None, credential={**_ACTIVE_CREDENTIAL, **overrides})
    with pytest.raises(ValueError, match=expected_error):
        _run(repo)
    assert repo.insert_calls == 0


def test_credential_not_found_and_account_mismatch_fail_closed() -> None:
    with pytest.raises(ValueError, match="TRADE_EXECUTION_CREDENTIAL_NOT_FOUND"):
        _run(_Repo(None, credential=None))
    with pytest.raises(ValueError, match="CREDENTIAL_ACCOUNT_ID_MISMATCH"):
        _run(_Repo(None, credential={**_ACTIVE_CREDENTIAL, "trading_account_id": 999}))


def test_trading_account_venue_not_found_fails_closed() -> None:
    with pytest.raises(ValueError, match="TRADING_ACCOUNT_VENUE_NOT_FOUND"):
        _run(_Repo(None, account=False))


def test_binding_conflict_fails_closed() -> None:
    conflicting = {
        "executor_credential_binding_id": 42,
        "trading_account_credential_id": 999,
        "executor_identity": SHARED_EXECUTOR_IDENTITY,
        "runtime_owner": SHARED_EXECUTOR_RUNTIME_OWNER,
    }
    with pytest.raises(ValueError, match="ACTIVE_EXECUTOR_CREDENTIAL_BINDING_CONFLICT"):
        _run(_Repo(None, bindings={_SHARED_KEY: conflicting}))


def test_unsupported_tuple_fails_closed() -> None:
    with pytest.raises(ValueError, match="UNSUPPORTED_EXECUTOR_BINDING_TUPLE"):
        _run(_Repo(None), executor_identity="shared-executor-v1", runtime_owner="odroid")


def test_cli_has_safe_default_check_and_explicit_apply() -> None:
    base = [
        "--trading-account-id", "5",
        "--trading-account-credential-id", "5",
        "--executor-identity", "shared-executor-v1",
        "--runtime-owner", "gurkdb",
    ]
    args = parse_args(base)
    assert args.check is True and args.apply is False
    args = parse_args(base + ["--apply"])
    assert args.apply is True and args.check is False
    with pytest.raises(SystemExit):
        parse_args(base + ["--check", "--apply"])


def test_cli_rejects_unsupported_tuple() -> None:
    with pytest.raises(SystemExit):
        parse_args([
            "--trading-account-id", "5",
            "--trading-account-credential-id", "5",
            "--executor-identity", "shared-executor-v1",
            "--runtime-owner", "odroid",
            "--check",
        ])


def test_no_secret_or_broker_capability_imports() -> None:
    service = Path("src/account_provisioning/existing_trade_execution_credential_binding_v1.py").read_text()
    runner = Path("src/account_provisioning/run_bind_existing_trade_execution_credential_v1.py").read_text()
    assert "api_key" not in service and "api_secret" not in service
    assert "encrypt_credential" not in service and "decrypt_credential" not in service
    assert "getpass" not in service + runner
    tree = ast.parse(service)
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any("bitvavo_client" in name or "credential_crypto" in name for name in imports)


def test_repository_default_is_real_class_and_apply_defaults_read_only() -> None:
    import inspect

    sig = inspect.signature(bind_existing_trade_execution_credential)
    assert sig.parameters["repository_factory"].default is BindExistingTradeExecutionCredentialRepository
    assert sig.parameters["apply"].default is False
