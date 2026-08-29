from __future__ import annotations

from pathlib import Path

import pytest

from src.account_provisioning.credential_crypto_v1 import (
    compute_fingerprint,
    decrypt_credential,
    generate_test_master_key,
    parse_master_key,
)
from src.account_provisioning.contracts_v1 import (
    ENCRYPTION_ALGORITHM,
    EncryptedCredentialEnvelope,
)
from src.account_provisioning.trade_execution_credential_rotation_v1 import (
    CHECK_BLOCKED,
    CHECK_READY,
    RESULT_BLOCKED,
    RESULT_ROTATED,
    TradeExecutionCredentialRotationError,
    check_trade_execution_credential_rotation_v1,
    rotate_trade_execution_credential_v1,
)


class FakeConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed += 1


class FakeRepository:
    def __init__(self, conn: FakeConnection, *, row: dict | None, binding_count: int = 1, stale: bool = False) -> None:
        self.conn = conn
        self.row = row
        self.binding_count = binding_count
        self.stale = stale
        self.rotate_calls = 0
        self.last_update: dict | None = None

    def load_credential(self, *, trading_account_credential_id: int):
        if self.row is None:
            return None
        if int(self.row["trading_account_credential_id"]) != trading_account_credential_id:
            return None
        return dict(self.row)

    def count_bindings(self, *, trading_account_credential_id: int) -> int:
        assert trading_account_credential_id == 5
        return self.binding_count

    def rotate_exact(self, **kwargs) -> None:
        self.rotate_calls += 1
        if self.stale:
            raise TradeExecutionCredentialRotationError(
                "EXACT_ACTIVE_TRADE_EXECUTION_CREDENTIAL_UPDATE_REQUIRED"
            )
        self.last_update = kwargs


def _row(master_key_bytes: bytes) -> dict:
    return {
        "trading_account_credential_id": 5,
        "trading_account_id": 5,
        "venue": "bitvavo",
        "credential_kind": "API_KEY_SECRET",
        "encryption_algorithm": ENCRYPTION_ALGORITHM,
        "key_version": "v1",
        "credential_fingerprint": compute_fingerprint("bitvavo", "old-key", master_key_bytes),
        "credential_status": "ACTIVE",
        "validation_state": "INVALID_CREDENTIALS",
        "credential_source": "db_encrypted",
        "permission_scope": "TRADE_EXECUTION",
        "allowed_private_read": 1,
        "allowed_order_write": 1,
        "allowed_withdrawal": 0,
        "validated_ts_utc": None,
        "last_validation_error_code": "INVALID_CREDENTIALS_OR_READ_PERMISSION",
    }


def _factory(repo: FakeRepository):
    return lambda conn: repo


def test_check_is_read_only_and_reports_binding_count() -> None:
    _, key = parse_master_key(generate_test_master_key())
    conn = FakeConnection()
    repo = FakeRepository(conn, row=_row(key), binding_count=2)

    result = check_trade_execution_credential_rotation_v1(
        trading_account_id=5,
        trading_account_credential_id=5,
        venue="bitvavo",
        conn_factory=lambda: conn,
        repository_factory=_factory(repo),
    )

    assert result.check_state == CHECK_READY
    assert result.binding_count == 2
    assert result.credential_mutations == 0
    assert result.binding_mutations == 0
    assert repo.rotate_calls == 0
    assert conn.commits == 0
    assert conn.rollbacks == 1
    assert conn.closed == 1


def test_happy_path_rotates_in_place_and_preserves_bindings() -> None:
    key_version, key = parse_master_key(generate_test_master_key())
    conn = FakeConnection()
    row = _row(key)
    old_fingerprint = row["credential_fingerprint"]
    repo = FakeRepository(conn, row=row, binding_count=2)

    result = rotate_trade_execution_credential_v1(
        trading_account_id=5,
        trading_account_credential_id=5,
        venue="bitvavo",
        api_key="new-key",
        api_secret="new-secret",
        master_key_version=key_version,
        master_key_bytes=key,
        conn_factory=lambda: conn,
        repository_factory=_factory(repo),
    )

    assert result.result == RESULT_ROTATED
    assert result.trading_account_credential_id == 5
    assert result.binding_count == 2
    assert result.binding_mutations == 0
    assert result.credential_mutations == 1
    assert result.previous_validation_state == "INVALID_CREDENTIALS"
    assert result.new_validation_state == "UNVALIDATED"
    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert repo.rotate_calls == 1

    assert repo.last_update is not None
    assert repo.last_update["credential_fingerprint"] != old_fingerprint
    envelope = EncryptedCredentialEnvelope.from_json(repo.last_update["encrypted_envelope"])
    plain = decrypt_credential(envelope, key)
    assert plain.api_key == "new-key"
    assert plain.api_secret == "new-secret"


def test_same_api_key_fails_closed_without_mutation() -> None:
    key_version, key = parse_master_key(generate_test_master_key())
    conn = FakeConnection()
    repo = FakeRepository(conn, row=_row(key))

    result = rotate_trade_execution_credential_v1(
        trading_account_id=5,
        trading_account_credential_id=5,
        venue="bitvavo",
        api_key="old-key",
        api_secret="different-secret",
        master_key_version=key_version,
        master_key_bytes=key,
        conn_factory=lambda: conn,
        repository_factory=_factory(repo),
    )

    assert result.result == RESULT_BLOCKED
    assert result.safe_error_code == "NEW_CREDENTIAL_MATCHES_CURRENT_API_KEY"
    assert repo.rotate_calls == 0
    assert conn.commits == 0
    assert conn.rollbacks == 1


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("trading_account_id", 6, "CREDENTIAL_ACCOUNT_ID_MISMATCH"),
        ("venue", "other", "CREDENTIAL_VENUE_MISMATCH"),
        ("credential_status", "REVOKED", "CREDENTIAL_NOT_ACTIVE"),
        ("credential_source", "legacy_env", "CREDENTIAL_SOURCE_MISMATCH"),
        ("permission_scope", "READ_ONLY", "CREDENTIAL_PERMISSION_SCOPE_MISMATCH"),
        ("allowed_private_read", 0, "CREDENTIAL_MISSING_PRIVATE_READ_SCOPE"),
        ("allowed_order_write", 0, "CREDENTIAL_MISSING_ORDER_WRITE_SCOPE"),
        ("allowed_withdrawal", 1, "CREDENTIAL_WITHDRAWAL_CAPABILITY_NOT_ALLOWED"),
    ],
)
def test_invalid_metadata_fails_closed(field: str, value: object, code: str) -> None:
    key_version, key = parse_master_key(generate_test_master_key())
    conn = FakeConnection()
    row = _row(key)
    row[field] = value
    repo = FakeRepository(conn, row=row)

    result = rotate_trade_execution_credential_v1(
        trading_account_id=5,
        trading_account_credential_id=5,
        venue="bitvavo",
        api_key="new-key",
        api_secret="new-secret",
        master_key_version=key_version,
        master_key_bytes=key,
        conn_factory=lambda: conn,
        repository_factory=_factory(repo),
    )

    assert result.result == RESULT_BLOCKED
    assert result.safe_error_code == code
    assert repo.rotate_calls == 0
    assert conn.commits == 0
    assert conn.rollbacks == 1


def test_missing_exact_credential_fails_closed() -> None:
    conn = FakeConnection()
    repo = FakeRepository(conn, row=None)

    result = check_trade_execution_credential_rotation_v1(
        trading_account_id=5,
        trading_account_credential_id=5,
        venue="bitvavo",
        conn_factory=lambda: conn,
        repository_factory=_factory(repo),
    )

    assert result.check_state == CHECK_BLOCKED
    assert result.safe_error_code == "TRADE_EXECUTION_CREDENTIAL_NOT_FOUND"


def test_stale_update_rolls_back() -> None:
    key_version, key = parse_master_key(generate_test_master_key())
    conn = FakeConnection()
    repo = FakeRepository(conn, row=_row(key), stale=True)

    result = rotate_trade_execution_credential_v1(
        trading_account_id=5,
        trading_account_credential_id=5,
        venue="bitvavo",
        api_key="new-key",
        api_secret="new-secret",
        master_key_version=key_version,
        master_key_bytes=key,
        conn_factory=lambda: conn,
        repository_factory=_factory(repo),
    )

    assert result.result == RESULT_BLOCKED
    assert result.safe_error_code == "EXACT_ACTIVE_TRADE_EXECUTION_CREDENTIAL_UPDATE_REQUIRED"
    assert conn.commits == 0
    assert conn.rollbacks == 1


def test_blank_secret_input_is_rejected_before_database_access() -> None:
    _, key = parse_master_key(generate_test_master_key())
    called = False

    def conn_factory():
        nonlocal called
        called = True
        raise AssertionError("must not connect")

    result = rotate_trade_execution_credential_v1(
        trading_account_id=5,
        trading_account_credential_id=5,
        venue="bitvavo",
        api_key="",
        api_secret="secret",
        master_key_version="v1",
        master_key_bytes=key,
        conn_factory=conn_factory,
    )

    assert result.result == RESULT_BLOCKED
    assert result.safe_error_code == "BLANK_SECRET_INPUT"
    assert called is False


def test_rotation_module_has_no_broker_import() -> None:
    source = Path("src/account_provisioning/trade_execution_credential_rotation_v1.py").read_text()
    assert "src.execution" not in source
    assert "BitvavoClient" not in source
    assert "requests" not in source
