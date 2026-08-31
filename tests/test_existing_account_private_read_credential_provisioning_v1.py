from __future__ import annotations

import ast
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.account_provisioning.credential_crypto_v1 import (
    compute_fingerprint,
    generate_test_master_key,
    parse_master_key,
)
from src.account_provisioning.credential_validator_v1 import CredentialValidationResult
from src.account_provisioning.existing_account_private_read_credential_provisioning_v1 import (
    STATUS_ALREADY_PROVISIONED,
    STATUS_BLOCKED,
    STATUS_CREATED,
    STATUS_READY,
    STATUS_VALIDATION_FAILED,
    STATUS_VALIDATION_UNAVAILABLE,
    ExistingAccountPrivateReadProvisioningRepository,
    check_readiness,
    provision_existing_private_read_credential,
)
from src.account_provisioning.run_provision_existing_private_read_credential_v1 import parse_args

_NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
_KEY_VERSION, _KEY_BYTES = parse_master_key(generate_test_master_key())
_API_KEY = "PRIVATE_READ_KEY_SENTINEL"
_API_SECRET = "PRIVATE_READ_SECRET_SENTINEL"


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
    """In-memory fake modeling the DB's per-scope ACTIVE uniqueness grain.

    ``credentials`` maps permission_scope -> row, so an ACTIVE TRADE_EXECUTION
    row and an ACTIVE READ_ONLY_PRIVATE row can coexist independently,
    mirroring ``uq_tac_active_account_venue_scope_v1``.
    """

    def __init__(self, *, account=(1, "bitvavo", "live", 1), credentials=None) -> None:
        self.account = account
        self.credentials: dict[str, dict] = dict(credentials or {})
        self.inserted: list[dict] = []
        self.next_id = 100

    def find_account(self, *, trading_account_id, venue):
        if self.account is None:
            return None
        acct_id, acct_venue, mode, enabled = self.account
        if acct_id != trading_account_id or acct_venue != venue:
            return None
        return {
            "trading_account_id": acct_id,
            "venue": acct_venue,
            "account_mode": mode,
            "enabled": enabled,
        }

    def find_active_credential(self, *, trading_account_id, venue, permission_scope):
        return self.credentials.get(permission_scope)

    def insert_active_credential(self, **kwargs):
        credential_id = self.next_id
        self.next_id += 1
        row = {"trading_account_credential_id": credential_id, **kwargs}
        self.credentials["READ_ONLY_PRIVATE"] = {
            "trading_account_credential_id": credential_id,
            "credential_status": "ACTIVE",
            "permission_scope": "READ_ONLY_PRIVATE",
            "validation_state": kwargs["validation_state"],
            "validated_ts_utc": kwargs["validated_ts_utc"],
        }
        self.inserted.append(row)
        return credential_id


class _Validator:
    def __init__(self, result: CredentialValidationResult, *, raises: Exception | None = None) -> None:
        self.result = result
        self.raises = raises
        self.calls: list = []

    def validate(self, credential):
        self.calls.append(credential)
        if self.raises is not None:
            raise self.raises
        return self.result


def _success_result(calls: int = 2) -> CredentialValidationResult:
    return CredentialValidationResult(
        success=True,
        validation_state="VALID_PRIVATE_READ",
        capabilities=["read_balance", "read_orders"],
        broker_private_calls=calls,
    )


def _invalid_result(calls: int = 1) -> CredentialValidationResult:
    return CredentialValidationResult(
        success=False,
        validation_state="INVALID_CREDENTIALS",
        safe_error_code="INVALID_CREDENTIALS_OR_READ_PERMISSION",
        broker_private_calls=calls,
    )


def _unavailable_result(calls: int = 0) -> CredentialValidationResult:
    return CredentialValidationResult(
        success=False,
        validation_state="VALIDATION_UNAVAILABLE",
        safe_error_code="VALIDATION_UNAVAILABLE",
        broker_private_calls=calls,
    )


def _run(repo: _Repo, validator: _Validator, *, trading_account_id=1, venue="bitvavo"):
    conn = _Conn()
    result = provision_existing_private_read_credential(
        trading_account_id=trading_account_id,
        venue=venue,
        api_key=_API_KEY,
        api_secret=_API_SECRET,
        master_key_version=_KEY_VERSION,
        master_key_bytes=_KEY_BYTES,
        validator=validator,
        conn_factory=lambda: conn,
        repository_factory=lambda _: repo,
        now_utc=_NOW,
    )
    return result, conn


@pytest.mark.parametrize("account_mode", ["live", "live_readonly", "paper"])
def test_enabled_account_accepted_for_every_supported_mode(account_mode: str) -> None:
    repo = _Repo(account=(1, "bitvavo", account_mode, 1))
    validator = _Validator(_success_result())
    result, conn = _run(repo, validator)
    assert result.status == STATUS_CREATED
    assert conn.committed and not conn.rolled_back
    assert len(repo.inserted) == 1


def test_missing_account_fails_closed() -> None:
    repo = _Repo(account=None)
    validator = _Validator(_success_result())
    with pytest.raises(ValueError, match="TRADING_ACCOUNT_VENUE_NOT_FOUND"):
        _run(repo, validator)
    assert validator.calls == []
    assert repo.inserted == []


def test_disabled_account_fails_closed() -> None:
    repo = _Repo(account=(1, "bitvavo", "live", 0))
    validator = _Validator(_success_result())
    with pytest.raises(ValueError, match="ACCOUNT_DISABLED"):
        _run(repo, validator)
    assert validator.calls == []
    assert repo.inserted == []


def test_existing_trade_execution_row_is_untouched_and_never_blocks_provisioning() -> None:
    trade_execution_row = {
        "trading_account_credential_id": 7,
        "credential_status": "ACTIVE",
        "permission_scope": "TRADE_EXECUTION",
        "validation_state": "VALID_TRADE_EXECUTION",
        "validated_ts_utc": "2026-07-01 00:00:00",
    }
    frozen_snapshot = dict(trade_execution_row)
    repo = _Repo(credentials={"TRADE_EXECUTION": trade_execution_row})
    validator = _Validator(_success_result())

    first, _ = _run(repo, validator)
    second, _ = _run(repo, validator)

    assert first.status == STATUS_CREATED
    assert second.status == STATUS_ALREADY_PROVISIONED
    assert repo.credentials["TRADE_EXECUTION"] == frozen_snapshot
    assert repo.credentials["READ_ONLY_PRIVATE"]["trading_account_credential_id"] != 7
    assert len(repo.inserted) == 1


def test_successful_validation_records_valid_private_read_and_timestamp() -> None:
    repo = _Repo()
    validator = _Validator(_success_result(calls=2))
    result, conn = _run(repo, validator)
    assert result.status == STATUS_CREATED
    assert result.validation_state == "VALID_PRIVATE_READ"
    assert result.validated_ts_utc_present is True
    assert result.broker_private_calls == 2
    assert conn.committed


def test_invalid_credentials_do_not_become_valid_private_read() -> None:
    repo = _Repo()
    validator = _Validator(_invalid_result(calls=1))
    result, conn = _run(repo, validator)
    assert result.status == STATUS_VALIDATION_FAILED
    assert result.safe_error_code == "INVALID_CREDENTIALS_OR_READ_PERMISSION"
    assert repo.inserted == []
    assert conn.rolled_back and not conn.committed


def test_unavailable_validation_fails_closed_without_half_provisioning() -> None:
    repo = _Repo()
    validator = _Validator(_unavailable_result())
    result, conn = _run(repo, validator)
    assert result.status == STATUS_VALIDATION_UNAVAILABLE
    assert repo.inserted == []
    assert conn.rolled_back and not conn.committed


def test_check_readiness_ready_never_touches_a_validator() -> None:
    repo = _Repo()
    result = check_readiness(
        trading_account_id=1,
        venue="bitvavo",
        conn_factory=lambda: _Conn(),
        repository_factory=lambda _: repo,
    )
    assert result.status == STATUS_READY
    assert repo.inserted == []


def test_parse_args_defaults_to_check_and_keeps_apply_explicit() -> None:
    default = parse_args(["--trading-account-id", "5"])
    assert default.check is True and default.apply is False
    apply = parse_args(["--trading-account-id", "5", "--apply"])
    assert apply.apply is True and apply.check is False


def test_module_has_no_secret_print_literals() -> None:
    path = Path("src/account_provisioning/run_provision_existing_private_read_credential_v1.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    printed_names = {
        node.id
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "print"
        for node in ast.walk(call)
        if isinstance(node, ast.Name)
    }
    assert "api_key" not in printed_names
    assert "api_secret" not in printed_names


def test_compute_fingerprint_is_stable_for_same_key() -> None:
    assert compute_fingerprint("bitvavo", _API_KEY, _KEY_BYTES) == compute_fingerprint(
        "bitvavo", _API_KEY, _KEY_BYTES
    )
