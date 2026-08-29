from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.account_provisioning.contracts_v1 import (
    CredentialValidationState,
    PlainBitvavoCredential,
)
from src.account_provisioning.credential_binding_contract_v1 import (
    PERMISSION_SCOPE_TRADE_EXECUTION,
    CredentialBindingValidationError,
    validate_credential_binding,
)
from src.account_provisioning.credential_crypto_v1 import (
    compute_fingerprint,
    encrypt_credential,
)
from src.account_provisioning.credential_validator_v1 import (
    CredentialValidationResult,
    VALIDATION_STATE_UNAVAILABLE,
)
from src.account_provisioning.trade_execution_credential_revalidation_v1 import (
    CHECK_ALREADY_VALIDATED,
    CHECK_BLOCKED,
    CHECK_READY_TO_VALIDATE,
    RESULT_ALREADY_VALIDATED,
    RESULT_BLOCKED,
    RESULT_INVALID,
    RESULT_VALIDATED,
    EncryptedTradeExecutionCredentialRecordV1,
    TradeExecutionCredentialRevalidationServiceV1,
    check_trade_execution_credential_validation_v1,
)
from src.executor.execution_credential_scope_v1 import (
    CredentialScopeDeniedError,
    ExecutorCredentialScopeRepository,
)


NOW = datetime(2026, 8, 29, 4, 0, tzinfo=UTC)
MASTER_KEY = b"k" * 32
ACCOUNT_ID = 5
VENUE = "bitvavo"
API_KEY = "trade-validation-key"
API_SECRET = "trade-validation-secret"


class _Conn:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class _Repo:
    def __init__(self, rows, record) -> None:
        self.rows = rows
        self.record = record
        self.updates: list[dict[str, object]] = []

    def load_metadata_rows(self, **_kwargs):
        return list(self.rows)

    def load_encrypted_record(self, **_kwargs):
        return self.record

    def update_validation_state(self, **kwargs) -> None:
        self.updates.append(kwargs)


class _Validator:
    def __init__(self, result: CredentialValidationResult) -> None:
        self.result = result
        self.calls = 0

    def validate(self, credential: PlainBitvavoCredential) -> CredentialValidationResult:
        self.calls += 1
        assert credential.venue == VENUE
        assert credential.api_key == API_KEY
        assert credential.api_secret == API_SECRET
        return self.result


def _row(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "trading_account_id": ACCOUNT_ID,
        "account_code": "bitvavo_joost_live",
        "venue": VENUE,
        "trading_account_enabled": 1,
        "live_trading_enabled": 1,
        "trading_account_credential_id": 5,
        "credential_source": "db_encrypted",
        "credential_status": "ACTIVE",
        "permission_scope": "TRADE_EXECUTION",
        "allowed_private_read": 1,
        "allowed_order_write": 1,
        "allowed_withdrawal": 0,
        "credential_fingerprint": compute_fingerprint(VENUE, API_KEY, MASTER_KEY),
        "key_version": "v1",
        "validation_state": "UNVALIDATED",
        "validated_ts_utc": None,
        "last_validation_error_code": None,
    }
    values.update(overrides)
    return values


def _record(*, fingerprint: str | None = None) -> EncryptedTradeExecutionCredentialRecordV1:
    credential = PlainBitvavoCredential(
        venue=VENUE,
        api_key=API_KEY,
        api_secret=API_SECRET,
    )
    envelope = encrypt_credential(credential, ACCOUNT_ID, "v1", MASTER_KEY)
    return EncryptedTradeExecutionCredentialRecordV1(
        trading_account_credential_id=5,
        trading_account_id=ACCOUNT_ID,
        venue=VENUE,
        credential_kind="API_KEY_SECRET",
        encrypted_envelope=envelope.to_json(),
        encryption_algorithm="AESGCM-256",
        key_version="v1",
        credential_fingerprint=(
            fingerprint
            if fingerprint is not None
            else compute_fingerprint(VENUE, API_KEY, MASTER_KEY)
        ),
    )


def _service(repo: _Repo, validator: _Validator, conn: _Conn) -> TradeExecutionCredentialRevalidationServiceV1:
    return TradeExecutionCredentialRevalidationServiceV1(
        master_key_bytes=MASTER_KEY,
        validator=validator,
        conn_factory=lambda: conn,
        repository_factory=lambda _conn: repo,
        now_factory=lambda: NOW,
    )


def test_check_is_metadata_only_and_reports_ready() -> None:
    conn = _Conn()
    repo = _Repo([_row()], _record())
    result = check_trade_execution_credential_validation_v1(
        trading_account_id=ACCOUNT_ID,
        venue=VENUE,
        conn_factory=lambda: conn,
        repository_factory=lambda _conn: repo,
    )
    assert result.check_state == CHECK_READY_TO_VALIDATE
    assert result.previous_validation_state == "UNVALIDATED"
    assert result.broker_private_calls == 0
    assert conn.commits == 0
    assert conn.closed is True


def test_check_reports_already_validated_only_with_timestamp() -> None:
    conn = _Conn()
    repo = _Repo(
        [
            _row(
                validation_state="VALID_TRADE_EXECUTION",
                validated_ts_utc=NOW,
            )
        ],
        _record(),
    )
    result = check_trade_execution_credential_validation_v1(
        trading_account_id=ACCOUNT_ID,
        venue=VENUE,
        conn_factory=lambda: conn,
        repository_factory=lambda _conn: repo,
    )
    assert result.check_state == CHECK_ALREADY_VALIDATED
    assert result.validated_ts_utc_present is True


def test_check_blocks_valid_trade_state_without_timestamp() -> None:
    conn = _Conn()
    repo = _Repo([_row(validation_state="VALID_TRADE_EXECUTION")], _record())
    result = check_trade_execution_credential_validation_v1(
        trading_account_id=ACCOUNT_ID,
        venue=VENUE,
        conn_factory=lambda: conn,
        repository_factory=lambda _conn: repo,
    )
    assert result.check_state == CHECK_BLOCKED
    assert result.safe_error_code == "CREDENTIAL_VALIDATION_TIMESTAMP_MISSING"


def test_success_persists_valid_trade_execution_after_two_read_capabilities() -> None:
    conn = _Conn()
    repo = _Repo([_row()], _record())
    validator = _Validator(
        CredentialValidationResult(
            success=True,
            validation_state="VALID_PRIVATE_READ",
            capabilities=["read_balance", "read_orders"],
            broker_private_calls=2,
        )
    )
    result = _service(repo, validator, conn).revalidate(
        trading_account_id=ACCOUNT_ID,
        venue=VENUE,
    )
    assert result.result == RESULT_VALIDATED
    assert result.new_validation_state == "VALID_TRADE_EXECUTION"
    assert result.validated_ts_utc_present is True
    assert result.broker_private_calls == 2
    assert validator.calls == 1
    assert len(repo.updates) == 1
    assert repo.updates[0]["validation_state"] == "VALID_TRADE_EXECUTION"
    assert repo.updates[0]["validated_ts_utc"] == NOW
    assert conn.commits == 1
    assert conn.closed is True


def test_already_validated_is_idempotent_without_private_call() -> None:
    conn = _Conn()
    repo = _Repo(
        [_row(validation_state="VALID_TRADE_EXECUTION", validated_ts_utc=NOW)],
        _record(),
    )
    validator = _Validator(
        CredentialValidationResult(
            success=True,
            validation_state="VALID_PRIVATE_READ",
            capabilities=["read_balance", "read_orders"],
            broker_private_calls=2,
        )
    )
    result = _service(repo, validator, conn).revalidate(
        trading_account_id=ACCOUNT_ID,
        venue=VENUE,
    )
    assert result.result == RESULT_ALREADY_VALIDATED
    assert validator.calls == 0
    assert repo.updates == []
    assert conn.commits == 0
    assert conn.rollbacks == 1


def test_unavailable_validation_does_not_mutate_state() -> None:
    conn = _Conn()
    repo = _Repo([_row()], _record())
    validator = _Validator(
        CredentialValidationResult(
            success=False,
            validation_state=VALIDATION_STATE_UNAVAILABLE,
            safe_error_code="VALIDATION_UNAVAILABLE",
            broker_private_calls=1,
        )
    )
    result = _service(repo, validator, conn).revalidate(
        trading_account_id=ACCOUNT_ID,
        venue=VENUE,
    )
    assert result.result == RESULT_BLOCKED
    assert result.safe_error_code == "VALIDATION_UNAVAILABLE"
    assert result.broker_private_calls == 1
    assert repo.updates == []
    assert conn.commits == 0
    assert conn.rollbacks == 1


def test_definitive_trade_permission_failure_persists_invalid() -> None:
    conn = _Conn()
    repo = _Repo([_row()], _record())
    validator = _Validator(
        CredentialValidationResult(
            success=False,
            validation_state="INVALID_CREDENTIALS",
            safe_error_code="TRADE_PERMISSION_REQUIRED",
            broker_private_calls=2,
        )
    )
    result = _service(repo, validator, conn).revalidate(
        trading_account_id=ACCOUNT_ID,
        venue=VENUE,
    )
    assert result.result == RESULT_INVALID
    assert result.new_validation_state == "INVALID_CREDENTIALS"
    assert repo.updates[0]["safe_error_code"] == "TRADE_PERMISSION_REQUIRED"
    assert conn.commits == 1


def test_withdrawal_capable_metadata_blocks_before_validator() -> None:
    conn = _Conn()
    repo = _Repo([_row(allowed_withdrawal=1)], _record())
    validator = _Validator(
        CredentialValidationResult(True, "VALID_PRIVATE_READ", ["read_balance", "read_orders"])
    )
    result = _service(repo, validator, conn).revalidate(
        trading_account_id=ACCOUNT_ID,
        venue=VENUE,
    )
    assert result.result == RESULT_BLOCKED
    assert result.safe_error_code == "WITHDRAWAL_CAPABILITY_NOT_ALLOWED"
    assert validator.calls == 0
    assert repo.updates == []


def test_fingerprint_mismatch_blocks_before_validator() -> None:
    conn = _Conn()
    repo = _Repo([_row()], _record(fingerprint="0" * 64))
    validator = _Validator(
        CredentialValidationResult(True, "VALID_PRIVATE_READ", ["read_balance", "read_orders"])
    )
    result = _service(repo, validator, conn).revalidate(
        trading_account_id=ACCOUNT_ID,
        venue=VENUE,
    )
    assert result.result == RESULT_BLOCKED
    assert result.safe_error_code == "CREDENTIAL_FINGERPRINT_METADATA_MISMATCH"
    assert validator.calls == 0


def test_trade_binding_contract_rejects_private_read_state_as_trade_validated() -> None:
    with pytest.raises(CredentialBindingValidationError) as excinfo:
        validate_credential_binding(
            [_row(validation_state="VALID_PRIVATE_READ", validated_ts_utc=NOW)],
            trading_account_id=ACCOUNT_ID,
            venue=VENUE,
            required_permission_scope=PERMISSION_SCOPE_TRADE_EXECUTION,
            require_validated=True,
        )
    assert excinfo.value.code == "UNVALIDATED_CREDENTIAL"

    profile = validate_credential_binding(
        [_row(validation_state="VALID_TRADE_EXECUTION", validated_ts_utc=NOW)],
        trading_account_id=ACCOUNT_ID,
        venue=VENUE,
        required_permission_scope=PERMISSION_SCOPE_TRADE_EXECUTION,
        require_validated=True,
    )
    assert profile.validation_state == "VALID_TRADE_EXECUTION"


class _Cursor:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row
        self.params = None

    def execute(self, _sql, params) -> None:
        self.params = params

    def fetchall(self):
        return [self.row]


def _scope_row(validation_state: str) -> dict[str, object]:
    return {
        "executor_credential_binding_id": 2,
        "trading_account_credential_id": 5,
        "trading_account_id": ACCOUNT_ID,
        "venue": VENUE,
        "permission_scope": "TRADE_EXECUTION",
        "executor_identity": "shared-executor-v1",
        "runtime_owner": "gurkdb",
        "binding_status": "ACTIVE",
        "credential_trading_account_id": ACCOUNT_ID,
        "credential_venue": VENUE,
        "credential_permission_scope": "TRADE_EXECUTION",
        "credential_status": "ACTIVE",
        "credential_source": "db_encrypted",
        "allowed_private_read": 1,
        "allowed_order_write": 1,
        "allowed_withdrawal": 0,
        "validation_state": validation_state,
    }


def test_executor_scope_denies_unvalidated_and_private_read_only_states() -> None:
    repo = ExecutorCredentialScopeRepository()
    for state in ("UNVALIDATED", "VALID_PRIVATE_READ"):
        with pytest.raises(CredentialScopeDeniedError) as excinfo:
            repo.resolve(
                trading_account_id=ACCOUNT_ID,
                venue=VENUE,
                executor_identity="shared-executor-v1",
                runtime_owner="gurkdb",
                cursor=_Cursor(_scope_row(state)),
            )
        assert str(excinfo.value) == "CREDENTIAL_SCOPE_CREDENTIAL_NOT_VALIDATED_FOR_TRADE_EXECUTION"


def test_executor_scope_accepts_only_valid_trade_execution_state() -> None:
    repo = ExecutorCredentialScopeRepository()
    binding = repo.resolve(
        trading_account_id=ACCOUNT_ID,
        venue=VENUE,
        executor_identity="shared-executor-v1",
        runtime_owner="gurkdb",
        cursor=_Cursor(_scope_row("VALID_TRADE_EXECUTION")),
    )
    assert binding.validation_state == "VALID_TRADE_EXECUTION"
    assert binding.allowed_private_read is True
