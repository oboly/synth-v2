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
    """In-memory fake modeling the tuple-scoped uniqueness of the real
    executor_credential_binding table."""

    _UNSET = object()

    def __init__(self, _conn, *, account=True, credential=_UNSET, bindings=None) -> None:
        self.account = account
        self.credential = dict(_ACTIVE_CREDENTIAL) if credential is self._UNSET else credential
        self.bindings = dict(bindings or {})
        self.next_binding_id = 9

    def find_credential_by_id(self, **_):
        return self.credential

    def require_account(self, **_):
        if not self.account:
            raise ValueError("TRADING_ACCOUNT_VENUE_NOT_FOUND")

    def find_active_binding(self, *, executor_identity, runtime_owner, **_):
        return self.bindings.get((executor_identity, runtime_owner))

    def insert_binding(self, *, credential_id, executor_identity, runtime_owner, **kwargs):
        binding_id = self.next_binding_id
        self.next_binding_id += 1
        self.bindings[(executor_identity, runtime_owner)] = {
            "executor_credential_binding_id": binding_id,
            "trading_account_credential_id": credential_id,
            "executor_identity": executor_identity,
            "runtime_owner": runtime_owner,
        }
        return binding_id


def _run(repo: _Repo, *, executor_identity=SHARED_EXECUTOR_IDENTITY, runtime_owner=SHARED_EXECUTOR_RUNTIME_OWNER,
          trading_account_id=5, trading_account_credential_id=5):
    conn = _Conn()
    result = bind_existing_trade_execution_credential(
        trading_account_id=trading_account_id,
        trading_account_credential_id=trading_account_credential_id,
        executor_identity=executor_identity,
        runtime_owner=runtime_owner,
        conn_factory=lambda: conn,
        repository_factory=lambda _: repo,
    )
    return result, conn


def test_no_secret_input_and_no_credential_mutation_helpers() -> None:
    source = Path(
        "src/account_provisioning/existing_trade_execution_credential_binding_v1.py"
    ).read_text()
    assert "api_key" not in source and "api_secret" not in source
    assert "encrypt_credential" not in source and "decrypt_credential" not in source
    assert "getpass" not in source


def test_cli_never_accepts_secret_flags() -> None:
    source = Path(
        "src/account_provisioning/run_bind_existing_trade_execution_credential_v1.py"
    ).read_text()
    assert "add_argument(\"--api-key\"" not in source
    assert "add_argument(\"--api-secret\"" not in source
    assert "getpass" not in source


def test_binds_new_shared_tuple_to_existing_credential() -> None:
    repo = _Repo(None)
    result, conn = _run(repo)
    assert result.trading_account_credential_id == 5
    assert result.created_binding is True
    assert result.executor_identity == SHARED_EXECUTOR_IDENTITY
    assert result.runtime_owner == SHARED_EXECUTOR_RUNTIME_OWNER
    assert result.venue == "bitvavo"
    assert conn.committed and not conn.rolled_back


def test_idempotent_exact_tuple_retry_does_not_duplicate() -> None:
    repo = _Repo(None)
    first, _ = _run(repo)
    second, _ = _run(repo)
    assert first.executor_credential_binding_id == second.executor_credential_binding_id
    assert second.created_binding is False
    assert len(repo.bindings) == 1


def test_existing_manual_binding_id_two_is_untouched() -> None:
    existing_manual_binding = {
        "executor_credential_binding_id": 2,
        "trading_account_credential_id": 5,
        "executor_identity": MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY,
        "runtime_owner": MANUAL_EXECUTION_RUNTIME_OWNER,
    }
    repo = _Repo(None, bindings={_MANUAL_KEY: dict(existing_manual_binding)})

    result, _ = _run(repo)

    assert repo.bindings[_MANUAL_KEY] == existing_manual_binding
    assert result.executor_credential_binding_id != 2
    assert _SHARED_KEY in repo.bindings


def test_credential_not_found() -> None:
    repo = _Repo(None, credential=None)
    with pytest.raises(ValueError, match="TRADE_EXECUTION_CREDENTIAL_NOT_FOUND"):
        _run(repo)


def test_credential_account_id_mismatch_fails_closed() -> None:
    credential = {**_ACTIVE_CREDENTIAL, "trading_account_id": 999}
    repo = _Repo(None, credential=credential)
    with pytest.raises(ValueError, match="CREDENTIAL_ACCOUNT_ID_MISMATCH"):
        _run(repo)


@pytest.mark.parametrize("overrides,expected_error", [
    ({"permission_scope": "READ_ONLY_PRIVATE"}, "CREDENTIAL_PERMISSION_SCOPE_MISMATCH"),
    ({"credential_status": "REVOKED"}, "CREDENTIAL_NOT_ACTIVE"),
    ({"allowed_order_write": 0}, "CREDENTIAL_MISSING_ORDER_WRITE_SCOPE"),
    ({"allowed_withdrawal": 1}, "CREDENTIAL_WITHDRAWAL_CAPABILITY_NOT_ALLOWED"),
])
def test_credential_verification_fails_closed(overrides, expected_error) -> None:
    credential = {**_ACTIVE_CREDENTIAL, **overrides}
    repo = _Repo(None, credential=credential)
    with pytest.raises(ValueError, match=expected_error):
        _run(repo)


def test_trading_account_venue_not_found_fails_closed() -> None:
    repo = _Repo(None, account=False)
    with pytest.raises(ValueError, match="TRADING_ACCOUNT_VENUE_NOT_FOUND"):
        _run(repo)


def test_binding_conflict_when_existing_tuple_points_at_different_credential() -> None:
    conflicting_binding = {
        "executor_credential_binding_id": 42,
        "trading_account_credential_id": 999,
        "executor_identity": SHARED_EXECUTOR_IDENTITY,
        "runtime_owner": SHARED_EXECUTOR_RUNTIME_OWNER,
    }
    repo = _Repo(None, bindings={_SHARED_KEY: conflicting_binding})
    with pytest.raises(ValueError, match="ACTIVE_EXECUTOR_CREDENTIAL_BINDING_CONFLICT"):
        _run(repo)


@pytest.mark.parametrize("executor_identity,runtime_owner", [
    ("manual_execution_bitvavo_v1", "gurkdb"),
    ("shared-executor-v1", "odroid"),
    ("some_unreviewed_executor_v1", "odroid"),
])
def test_unsupported_tuple_fails_closed(executor_identity, runtime_owner) -> None:
    repo = _Repo(None)
    with pytest.raises(ValueError, match="UNSUPPORTED_EXECUTOR_BINDING_TUPLE"):
        _run(repo, executor_identity=executor_identity, runtime_owner=runtime_owner)


def test_multi_account_isolation() -> None:
    repo_a = _Repo(None, credential={**_ACTIVE_CREDENTIAL, "trading_account_id": 5})
    repo_b = _Repo(None, credential={**_ACTIVE_CREDENTIAL, "trading_account_id": 6,
                                      "trading_account_credential_id": 6})
    result_a, _ = _run(repo_a, trading_account_id=5, trading_account_credential_id=5)
    result_b, _ = _run(repo_b, trading_account_id=6, trading_account_credential_id=6)
    assert result_a.trading_account_credential_id == 5
    assert result_b.trading_account_credential_id == 6
    assert repo_a.bindings is not repo_b.bindings


def test_no_broker_import_or_crypto_import() -> None:
    tree = ast.parse(
        Path("src/account_provisioning/existing_trade_execution_credential_binding_v1.py").read_text()
    )
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(
        "bitvavo_client" in name or "credential_crypto" in name or "manual_execution_bitvavo" in name
        for name in imports
    )


def test_cli_rejects_unsupported_tuple() -> None:
    with pytest.raises(SystemExit):
        parse_args([
            "--trading-account-id", "5",
            "--trading-account-credential-id", "5",
            "--executor-identity", "shared-executor-v1",
            "--runtime-owner", "odroid",
        ])


def test_cli_accepts_canonical_shared_tuple_for_existing_credential() -> None:
    args = parse_args([
        "--trading-account-id", "5",
        "--trading-account-credential-id", "5",
        "--executor-identity", "shared-executor-v1",
        "--runtime-owner", "gurkdb",
    ])
    assert args.trading_account_id == 5
    assert args.trading_account_credential_id == 5
    assert args.executor_identity == SHARED_EXECUTOR_IDENTITY
    assert args.runtime_owner == SHARED_EXECUTOR_RUNTIME_OWNER


def test_repository_default_is_the_real_class() -> None:
    import inspect

    sig = inspect.signature(bind_existing_trade_execution_credential)
    assert sig.parameters["repository_factory"].default is BindExistingTradeExecutionCredentialRepository
