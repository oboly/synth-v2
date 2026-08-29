from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.account_provisioning.credential_crypto_v1 import compute_fingerprint, generate_test_master_key, parse_master_key
from src.account_provisioning.run_provision_trade_execution_credential_v1 import parse_args
from src.account_provisioning.trade_execution_provisioning_v1 import (
    MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY,
    MANUAL_EXECUTION_RUNTIME_OWNER,
    SHARED_EXECUTOR_IDENTITY,
    SHARED_EXECUTOR_RUNTIME_OWNER,
    SUPPORTED_EXECUTOR_BINDING_TUPLES,
    provision_trade_execution_credential,
    readiness_report,
)


class _Conn:
    def __init__(self): self.committed = self.rolled_back = self.closed = False
    def commit(self): self.committed = True
    def rollback(self): self.rolled_back = True
    def close(self): self.closed = True


class _Repo:
    """In-memory fake modeling the real table's tuple-scoped uniqueness.

    `bindings` maps (executor_identity, runtime_owner) -> binding row, so
    multiple ACTIVE bindings for one credential can coexist, matching the
    real `uq_ecb_active_identity_scope` constraint. `find_active_binding`
    only ever returns the row for the exact requested tuple, mirroring the
    real repository's tuple-scoped WHERE clause.
    """
    def __init__(self, _conn, *, account=True, credential=None, bindings=None):
        self.account, self.credential = account, credential
        self.bindings = dict(bindings or {})
        self.envelopes = []
        self.next_binding_id = 9
    def require_account(self, **_):
        if not self.account: raise ValueError("TRADING_ACCOUNT_VENUE_NOT_FOUND")
    def find_active_credential(self, **_): return self.credential
    def insert_credential(self, **kwargs):
        self.envelopes.append(kwargs["encrypted_envelope"])
        self.credential = {"trading_account_credential_id": 7, "credential_status":"ACTIVE", "permission_scope":"TRADE_EXECUTION", "allowed_order_write":1, "allowed_withdrawal":0, "credential_fingerprint": kwargs["credential_fingerprint"]}
        return 7
    def find_active_binding(self, *, executor_identity, runtime_owner, **_):
        return self.bindings.get((executor_identity, runtime_owner))
    def insert_binding(self, *, credential_id, executor_identity, runtime_owner, **kwargs):
        assert credential_id == 7
        binding_id = self.next_binding_id
        self.next_binding_id += 1
        self.bindings[(executor_identity, runtime_owner)] = {
            "executor_credential_binding_id": binding_id, "trading_account_credential_id": 7,
            "executor_identity": executor_identity, "runtime_owner": runtime_owner,
        }
        return binding_id


_DEFAULT_MASTER_KEY = parse_master_key(generate_test_master_key())


def _run(repo: _Repo, *, executor_identity=MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY,
         runtime_owner=MANUAL_EXECUTION_RUNTIME_OWNER, trading_account_id=1, master_key=None):
    conn = _Conn(); version, key = master_key or _DEFAULT_MASTER_KEY
    result = provision_trade_execution_credential(trading_account_id=trading_account_id, venue="bitvavo", api_key="KEY_SENTINEL", api_secret="SECRET_SENTINEL", master_key_version=version, master_key_bytes=key,
        executor_identity=executor_identity, runtime_owner=runtime_owner,
        conn_factory=lambda:conn, repository_factory=lambda _:repo)
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
    manual_key = (MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY, MANUAL_EXECUTION_RUNTIME_OWNER)
    # Use an exact duplicate fingerprint: retries may reuse this exact identity only.
    result = provision_trade_execution_credential(trading_account_id=1, venue="bitvavo", api_key="KEY_SENTINEL", api_secret="SECRET_SENTINEL", master_key_version=version, master_key_bytes=key, conn_factory=_Conn, repository_factory=lambda _: _Repo(None, credential=credential, bindings={manual_key: binding}))
    assert not result.created_credential and not result.created_binding
    # Row-integrity guard: even though the query is tuple-scoped, the returned
    # row's own identity fields must still match the requested tuple.
    with pytest.raises(ValueError, match="BINDING_CONFLICT"):
        provision_trade_execution_credential(trading_account_id=1, venue="bitvavo", api_key="KEY_SENTINEL", api_secret="SECRET_SENTINEL", master_key_version=version, master_key_bytes=key, conn_factory=_Conn, repository_factory=lambda _: _Repo(None, credential=credential, bindings={manual_key: {**binding, "runtime_owner":"devlap"}}))


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


# --- Shared-executor tuple / multi-binding coverage (Issue: shared-executor binding provisioning fix) ---

def test_supported_tuples_are_exactly_manual_and_shared() -> None:
    assert SUPPORTED_EXECUTOR_BINDING_TUPLES == frozenset({
        (MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY, MANUAL_EXECUTION_RUNTIME_OWNER),
        (SHARED_EXECUTOR_IDENTITY, SHARED_EXECUTOR_RUNTIME_OWNER),
    })


def test_shared_tuple_provisions_and_idempotently_resolves() -> None:
    repo = _Repo(None)
    result, conn = _run(repo, executor_identity=SHARED_EXECUTOR_IDENTITY, runtime_owner=SHARED_EXECUTOR_RUNTIME_OWNER)
    assert result.created_binding and conn.committed
    assert result.executor_identity == SHARED_EXECUTOR_IDENTITY
    assert result.runtime_owner == SHARED_EXECUTOR_RUNTIME_OWNER
    first_binding_id = result.executor_credential_binding_id

    # Idempotent retry against the same repo state: no duplicate row created.
    result2, _ = _run(repo, executor_identity=SHARED_EXECUTOR_IDENTITY, runtime_owner=SHARED_EXECUTOR_RUNTIME_OWNER)
    assert not result2.created_credential and not result2.created_binding
    assert result2.executor_credential_binding_id == first_binding_id


def test_one_credential_can_hold_both_manual_and_shared_active_bindings() -> None:
    repo = _Repo(None)
    manual_result, _ = _run(repo)
    shared_result, _ = _run(repo, executor_identity=SHARED_EXECUTOR_IDENTITY, runtime_owner=SHARED_EXECUTOR_RUNTIME_OWNER)

    assert manual_result.trading_account_credential_id == shared_result.trading_account_credential_id == 7
    assert manual_result.executor_credential_binding_id != shared_result.executor_credential_binding_id
    assert len(repo.bindings) == 2
    manual_key = (MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY, MANUAL_EXECUTION_RUNTIME_OWNER)
    shared_key = (SHARED_EXECUTOR_IDENTITY, SHARED_EXECUTOR_RUNTIME_OWNER)
    assert manual_key in repo.bindings and shared_key in repo.bindings


def test_second_tuple_never_creates_a_second_credential() -> None:
    repo = _Repo(None)
    manual_result, _ = _run(repo)
    assert manual_result.created_credential
    shared_result, _ = _run(repo, executor_identity=SHARED_EXECUTOR_IDENTITY, runtime_owner=SHARED_EXECUTOR_RUNTIME_OWNER)
    assert not shared_result.created_credential
    assert shared_result.trading_account_credential_id == manual_result.trading_account_credential_id
    assert len(repo.envelopes) == 1  # exactly one credential ever encrypted/inserted


def test_lookup_does_not_raise_ambiguous_identity_with_two_legitimate_bindings() -> None:
    repo = _Repo(None)
    _run(repo)
    _run(repo, executor_identity=SHARED_EXECUTOR_IDENTITY, runtime_owner=SHARED_EXECUTOR_RUNTIME_OWNER)
    # Re-resolving either tuple must not observe the other binding or raise.
    manual_report = readiness_report(trading_account_id=1, venue="bitvavo", conn_factory=_Conn, repository_factory=lambda _: repo)
    shared_report = readiness_report(trading_account_id=1, venue="bitvavo", conn_factory=_Conn, repository_factory=lambda _: repo,
        executor_identity=SHARED_EXECUTOR_IDENTITY, runtime_owner=SHARED_EXECUTOR_RUNTIME_OWNER)
    assert manual_report["EXECUTOR_CREDENTIAL_BINDING_READY"] is True
    assert shared_report["EXECUTOR_CREDENTIAL_BINDING_READY"] is True
    assert manual_report["EXECUTOR_CREDENTIAL_BINDING_ID"] != shared_report["EXECUTOR_CREDENTIAL_BINDING_ID"]


def test_manual_binding_id_two_is_never_touched_by_shared_provisioning() -> None:
    manual_key = (MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY, MANUAL_EXECUTION_RUNTIME_OWNER)
    existing_manual_binding = {"executor_credential_binding_id": 2, "trading_account_credential_id": 7,
                                "executor_identity": MANUAL_EXECUTION_BITVAVO_EXECUTOR_IDENTITY,
                                "runtime_owner": MANUAL_EXECUTION_RUNTIME_OWNER}
    _, key = _DEFAULT_MASTER_KEY
    credential = {"trading_account_credential_id":7, "credential_status":"ACTIVE", "permission_scope":"TRADE_EXECUTION",
                  "allowed_order_write":1, "allowed_withdrawal":0, "credential_fingerprint": compute_fingerprint("bitvavo", "KEY_SENTINEL", key)}
    repo = _Repo(None, credential=credential, bindings={manual_key: dict(existing_manual_binding)})

    result, _ = _run(repo, executor_identity=SHARED_EXECUTOR_IDENTITY, runtime_owner=SHARED_EXECUTOR_RUNTIME_OWNER)

    assert repo.bindings[manual_key] == existing_manual_binding  # untouched: identical dict, id still 2
    assert result.executor_credential_binding_id != 2


def test_duplicate_exact_tuple_is_idempotent_not_duplicated() -> None:
    repo = _Repo(None)
    first, _ = _run(repo, executor_identity=SHARED_EXECUTOR_IDENTITY, runtime_owner=SHARED_EXECUTOR_RUNTIME_OWNER)
    second, _ = _run(repo, executor_identity=SHARED_EXECUTOR_IDENTITY, runtime_owner=SHARED_EXECUTOR_RUNTIME_OWNER)
    assert first.executor_credential_binding_id == second.executor_credential_binding_id
    assert second.created_binding is False
    assert len(repo.bindings) == 1


@pytest.mark.parametrize("executor_identity,runtime_owner", [
    ("manual_execution_bitvavo_v1", "gurkdb"),       # right identity, wrong owner
    ("shared-executor-v1", "odroid"),                 # right identity, wrong owner (swapped)
    ("some_unreviewed_executor_v1", "odroid"),
    ("shared-executor-v1", "devlap"),
])
def test_invalid_identity_owner_pair_fails_closed(executor_identity, runtime_owner) -> None:
    version, key = parse_master_key(generate_test_master_key())
    with pytest.raises(ValueError, match="UNSUPPORTED_EXECUTOR_BINDING_TUPLE"):
        provision_trade_execution_credential(trading_account_id=1, venue="bitvavo", api_key="KEY_SENTINEL", api_secret="SECRET_SENTINEL",
            master_key_version=version, master_key_bytes=key, executor_identity=executor_identity, runtime_owner=runtime_owner,
            conn_factory=_Conn, repository_factory=lambda _: _Repo(None))
    with pytest.raises(ValueError, match="UNSUPPORTED_EXECUTOR_BINDING_TUPLE"):
        readiness_report(trading_account_id=1, venue="bitvavo", executor_identity=executor_identity, runtime_owner=runtime_owner,
            conn_factory=_Conn, repository_factory=lambda _: _Repo(None))


def test_multi_account_isolation_for_shared_tuple() -> None:
    repo_a = _Repo(None)
    repo_b = _Repo(None)
    result_a, _ = _run(repo_a, executor_identity=SHARED_EXECUTOR_IDENTITY, runtime_owner=SHARED_EXECUTOR_RUNTIME_OWNER, trading_account_id=1)
    result_b, _ = _run(repo_b, executor_identity=SHARED_EXECUTOR_IDENTITY, runtime_owner=SHARED_EXECUTOR_RUNTIME_OWNER, trading_account_id=5)
    # Distinct repositories model distinct accounts' rows; each provisions its own credential/binding independently.
    assert result_a.trading_account_credential_id == 7 and result_b.trading_account_credential_id == 7
    assert repo_a.bindings is not repo_b.bindings
    assert set(repo_a.bindings) == {(SHARED_EXECUTOR_IDENTITY, SHARED_EXECUTOR_RUNTIME_OWNER)}
    assert set(repo_b.bindings) == {(SHARED_EXECUTOR_IDENTITY, SHARED_EXECUTOR_RUNTIME_OWNER)}


def test_cli_rejects_unsupported_executor_identity_owner_pair() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--trading-account-id", "1", "--executor-identity", "shared-executor-v1", "--runtime-owner", "odroid"])


def test_cli_accepts_canonical_shared_tuple() -> None:
    args = parse_args(["--trading-account-id", "1", "--executor-identity", "shared-executor-v1", "--runtime-owner", "gurkdb"])
    assert args.executor_identity == SHARED_EXECUTOR_IDENTITY
    assert args.runtime_owner == SHARED_EXECUTOR_RUNTIME_OWNER
