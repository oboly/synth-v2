from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.account_provisioning.credential_crypto_v1 import compute_fingerprint, generate_test_master_key, parse_master_key
from src.account_provisioning.run_provision_trade_execution_credential_v1 import parse_args
from src.account_provisioning.trade_execution_provisioning_v1 import (
    MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY,
    MANUAL_EXECUTION_RUNTIME_OWNER,
    provision_trade_execution_credential,
    readiness_report,
)


class _Conn:
    def __init__(self): self.committed = self.rolled_back = self.closed = False
    def commit(self): self.committed = True
    def rollback(self): self.rolled_back = True
    def close(self): self.closed = True


class _Repo:
    def __init__(self, _conn, *, account=True, credential=None, binding=None):
        self.account, self.credential, self.binding = account, credential, binding
        self.envelopes = []
    def require_account(self, **_):
        if not self.account: raise ValueError("TRADING_ACCOUNT_VENUE_NOT_FOUND")
    def find_active_credential(self, **_): return self.credential
    def insert_credential(self, **kwargs):
        self.envelopes.append(kwargs["encrypted_envelope"])
        self.credential = {"trading_account_credential_id": 7, "credential_status":"ACTIVE", "permission_scope":"TRADE_EXECUTION", "allowed_order_write":1, "allowed_withdrawal":0, "credential_fingerprint": kwargs["credential_fingerprint"]}
        return 7
    def find_active_binding(self, **_): return self.binding
    def insert_binding(self, **kwargs):
        assert kwargs["credential_id"] == 7
        self.binding = {"executor_credential_binding_id": 9, "trading_account_credential_id":7, "executor_identity":MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY, "runtime_owner":MANUAL_EXECUTION_RUNTIME_OWNER}
        return 9


def _run(repo: _Repo):
    conn = _Conn(); version, key = parse_master_key(generate_test_master_key())
    result = provision_trade_execution_credential(trading_account_id=1, venue="bitvavo", api_key="KEY_SENTINEL", api_secret="SECRET_SENTINEL", master_key_version=version, master_key_bytes=key, conn_factory=lambda:conn, repository_factory=lambda _:repo)
    return result, conn


def test_cli_contract_never_accepts_secrets_in_argv() -> None:
    actions = parse_args(["--trading-account-id", "1"])
    assert actions.venue == "bitvavo"
    source = Path("src/account_provisioning/run_provision_trade_execution_credential_v1.py").read_text()
    assert "add_argument(\"--api-key\"" not in source
    assert "add_argument(\"--api-secret\"" not in source


def test_profile_encrypts_and_persists_no_plaintext() -> None:
    repo = _Repo(None); result, conn = _run(repo)
    assert result.trading_account_credential_id == 7 and conn.committed
    assert "KEY_SENTINEL" not in repo.envelopes[0]
    assert "SECRET_SENTINEL" not in repo.envelopes[0]


def test_profile_requires_exact_account_venue_and_canonical_capabilities() -> None:
    with pytest.raises(ValueError, match="TRADING_ACCOUNT_VENUE_NOT_FOUND"):
        _run(_Repo(None, account=False))
    _, conn = _run(_Repo(None))
    assert conn.committed


@pytest.mark.parametrize("credential", [
    {"trading_account_credential_id":7, "credential_status":"ACTIVE", "permission_scope":"READ_ONLY_PRIVATE", "allowed_order_write":1, "allowed_withdrawal":0, "credential_fingerprint":"x"},
    {"trading_account_credential_id":7, "credential_status":"REVOKED", "permission_scope":"TRADE_EXECUTION", "allowed_order_write":1, "allowed_withdrawal":0, "credential_fingerprint":"x"},
    {"trading_account_credential_id":7, "credential_status":"ACTIVE", "permission_scope":"TRADE_EXECUTION", "allowed_order_write":0, "allowed_withdrawal":0, "credential_fingerprint":"x"},
    {"trading_account_credential_id":7, "credential_status":"ACTIVE", "permission_scope":"TRADE_EXECUTION", "allowed_order_write":1, "allowed_withdrawal":1, "credential_fingerprint":"x"},
])
def test_existing_credential_must_be_active_execution_nonwithdrawal(credential) -> None:
    with pytest.raises(ValueError, match="CREDENTIAL_CONFLICT"):
        _run(_Repo(None, credential=credential))


def test_exact_retry_is_idempotent_and_conflict_fails_closed() -> None:
    version, key = parse_master_key(generate_test_master_key())
    credential = {"trading_account_credential_id":7, "credential_status":"ACTIVE", "permission_scope":"TRADE_EXECUTION", "allowed_order_write":1, "allowed_withdrawal":0, "credential_fingerprint":compute_fingerprint("bitvavo", "KEY_SENTINEL", key)}
    binding = {"executor_credential_binding_id":9, "trading_account_credential_id":7, "executor_identity":MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY, "runtime_owner":MANUAL_EXECUTION_RUNTIME_OWNER}
    # Use an exact duplicate fingerprint: retries may reuse this exact identity only.
    result = provision_trade_execution_credential(trading_account_id=1, venue="bitvavo", api_key="KEY_SENTINEL", api_secret="SECRET_SENTINEL", master_key_version=version, master_key_bytes=key, conn_factory=_Conn, repository_factory=lambda _: _Repo(None, credential=credential, binding=binding))
    assert not result.created_credential and not result.created_binding
    with pytest.raises(ValueError, match="BINDING_CONFLICT"):
        provision_trade_execution_credential(trading_account_id=1, venue="bitvavo", api_key="KEY_SENTINEL", api_secret="SECRET_SENTINEL", master_key_version=version, master_key_bytes=key, conn_factory=_Conn, repository_factory=lambda _: _Repo(None, credential=credential, binding={**binding, "runtime_owner":"devlap"}))


def test_readiness_is_metadata_only_and_identity_is_stable() -> None:
    repo = _Repo(None)
    _run(repo)
    report = readiness_report(trading_account_id=1, venue="bitvavo", conn_factory=_Conn, repository_factory=lambda _:repo)
    assert report["TRADE_EXECUTION_CREDENTIAL_READY"] is True
    assert report["EXECUTOR_CREDENTIAL_BINDING_READY"] is True
    assert report["EXECUTOR_IDENTITY"] == "manual_execution_bitvavo_v1"
    assert report["RUNTIME_OWNER"] == "odroid"


def test_provisioning_path_has_no_broker_import_or_live_gate_mutation() -> None:
    tree = ast.parse(Path("src/account_provisioning/trade_execution_provisioning_v1.py").read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any("bitvavo_client" in name or name.startswith("src.executor.manual_execution_bitvavo") for name in imports)
    source = Path("src/account_provisioning/trade_execution_provisioning_v1.py").read_text()
    assert "SYNTH_BROKER_WRITE_PERMISSION" not in source and "live_trading_enabled" not in source
