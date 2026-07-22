from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.account.private_read_credential_resolver_v1 import (
    PrivateReadCredentialResolutionError,
    resolve_private_read_credential,
)
from src.account_provisioning.contracts_v1 import PlainBitvavoCredential
from src.account_provisioning.credential_crypto_v1 import (
    compute_fingerprint,
    encrypt_credential,
    generate_test_master_key,
    parse_master_key,
)
from src.account_provisioning.credential_repository_v1 import (
    CredentialRepository,
    CredentialValidationUpdateError,
    SqliteCredentialRepository,
)
from src.account_provisioning.credential_validator_v1 import (
    CredentialValidationResult,
)
from src.account_provisioning.existing_credential_revalidation_service_v1 import (
    ExistingCredentialRevalidationResult,
    ExistingCredentialRevalidationService,
)
from src.account_provisioning.run_revalidate_existing_private_read_credential_v1 import (
    EXIT_INVALID,
    EXIT_STRUCTURAL_FAILURE,
    EXIT_SUCCESS,
    EXIT_UNAVAILABLE,
    main as cli_main,
    parse_args,
)

_NOW = datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC)
_SECRET_KEY = "PRIVATE_KEY_SENTINEL"
_SECRET_VALUE = "PRIVATE_SECRET_SENTINEL"

_SCHEMA = """
CREATE TABLE trading_account (
    trading_account_id INTEGER PRIMARY KEY,
    account_code TEXT NOT NULL,
    venue TEXT NOT NULL,
    account_mode TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    live_trading_enabled INTEGER NOT NULL
);
CREATE TABLE app_profile (
    app_profile_id INTEGER PRIMARY KEY,
    profile_code TEXT NOT NULL
);
CREATE TABLE app_profile_trading_account_link (
    link_id INTEGER PRIMARY KEY,
    app_profile_id INTEGER NOT NULL,
    trading_account_id INTEGER NOT NULL,
    link_status TEXT NOT NULL,
    is_primary INTEGER NOT NULL
);
CREATE TABLE trading_account_credential (
    trading_account_credential_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    credential_kind TEXT NOT NULL,
    encrypted_envelope TEXT NOT NULL,
    encryption_algorithm TEXT NOT NULL,
    key_version TEXT NOT NULL,
    credential_fingerprint TEXT NOT NULL,
    credential_status TEXT NOT NULL,
    validation_state TEXT NOT NULL,
    created_ts_utc TEXT NOT NULL,
    validated_ts_utc TEXT,
    rotated_ts_utc TEXT,
    revoked_ts_utc TEXT,
    credential_source TEXT NOT NULL,
    permission_scope TEXT NOT NULL,
    allowed_private_read INTEGER NOT NULL,
    allowed_order_write INTEGER NOT NULL,
    allowed_withdrawal INTEGER NOT NULL,
    last_validation_error_code TEXT
);
"""


@dataclass(frozen=True)
class Scenario:
    path: Path
    key_version: str
    key_bytes: bytes
    credential_id: int


class RecordingValidator:
    def __init__(self, result: CredentialValidationResult) -> None:
        self.result = result
        self.calls = 0

    def validate(self, credential: PlainBitvavoCredential) -> CredentialValidationResult:
        self.calls += 1
        assert credential.api_key == _SECRET_KEY
        assert credential.api_secret == _SECRET_VALUE
        return self.result


class FakeCliService:
    def __init__(self, result: ExistingCredentialRevalidationResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def revalidate(self, **kwargs: object) -> ExistingCredentialRevalidationResult:
        self.calls.append(kwargs)
        return self.result


def _validation_result(kind: str) -> CredentialValidationResult:
    if kind == "success":
        return CredentialValidationResult(
            success=True,
            validation_state="VALID_PRIVATE_READ",
            capabilities=["read_balance", "read_orders"],
            broker_private_calls=0,
        )
    if kind == "invalid":
        return CredentialValidationResult(
            success=False,
            validation_state="INVALID_CREDENTIALS",
            safe_error_code="INVALID_CREDENTIALS_OR_READ_PERMISSION",
            broker_private_calls=0,
        )
    return CredentialValidationResult(
        success=False,
        validation_state="VALIDATION_UNAVAILABLE",
        safe_error_code="VALIDATION_UNAVAILABLE",
        broker_private_calls=0,
    )


def _scenario(
    tmp_path: Path,
    *,
    validation_state: str = "UNVALIDATED",
    validated_ts_utc: str | None = None,
    row_overrides: dict[str, object] | None = None,
    envelope_overrides: dict[str, object] | None = None,
) -> Scenario:
    path = tmp_path / "credential.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT INTO trading_account VALUES (1, 'joost-read', 'bitvavo', 'paper', 1, 0)"
    )
    conn.execute("INSERT INTO app_profile VALUES (10, 'joost')")
    conn.execute(
        "INSERT INTO app_profile_trading_account_link "
        "VALUES (100, 10, 1, 'ACTIVE', 1)"
    )
    key_version, key_bytes = parse_master_key(generate_test_master_key())
    plain = PlainBitvavoCredential(
        venue="bitvavo",
        api_key=_SECRET_KEY,
        api_secret=_SECRET_VALUE,
    )
    envelope = json.loads(
        encrypt_credential(plain, 1, key_version, key_bytes).to_json()
    )
    envelope.update(envelope_overrides or {})
    row: dict[str, object] = {
        "trading_account_id": 1,
        "venue": "bitvavo",
        "credential_kind": "API_KEY_SECRET",
        "encrypted_envelope": json.dumps(envelope),
        "encryption_algorithm": "AESGCM-256",
        "key_version": key_version,
        "credential_fingerprint": compute_fingerprint(
            "bitvavo", _SECRET_KEY, key_bytes
        ),
        "credential_status": "ACTIVE",
        "validation_state": validation_state,
        "created_ts_utc": "2026-07-21 00:00:00",
        "validated_ts_utc": validated_ts_utc,
        "rotated_ts_utc": None,
        "revoked_ts_utc": None,
        "credential_source": "db_encrypted",
        "permission_scope": "READ_ONLY_PRIVATE",
        "allowed_private_read": 1,
        "allowed_order_write": 0,
        "allowed_withdrawal": 0,
        "last_validation_error_code": None,
    }
    row.update(row_overrides or {})
    columns = list(row)
    cur = conn.execute(
        "INSERT INTO trading_account_credential ("
        + ",".join(columns)
        + ") VALUES ("
        + ",".join("?" for _ in columns)
        + ")",
        tuple(row[column] for column in columns),
    )
    credential_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return Scenario(path, key_version, key_bytes, credential_id)


def _connect(scenario: Scenario) -> sqlite3.Connection:
    conn = sqlite3.connect(scenario.path)
    conn.row_factory = sqlite3.Row
    return conn


def _service(
    scenario: Scenario,
    validator: RecordingValidator,
    *,
    repository_factory=SqliteCredentialRepository,
) -> ExistingCredentialRevalidationService:
    return ExistingCredentialRevalidationService(
        master_key_bytes=scenario.key_bytes,
        validator=validator,
        conn_factory=lambda: _connect(scenario),
        repository_factory=repository_factory,
        now_factory=lambda: _NOW,
    )


def _stored_row(scenario: Scenario) -> dict[str, object]:
    conn = _connect(scenario)
    try:
        row = conn.execute(
            "SELECT * FROM trading_account_credential "
            "WHERE trading_account_credential_id = ?",
            (scenario.credential_id,),
        ).fetchone()
        assert row is not None
        return dict(row)
    finally:
        conn.close()


@pytest.mark.parametrize(
    "identity",
    (
        {"trading_account_id": 1},
        {"account_code": "joost-read"},
        {"profile_code": "joost"},
    ),
)
def test_unvalidated_existing_binding_can_be_revalidated(
    tmp_path: Path,
    identity: dict[str, object],
) -> None:
    scenario = _scenario(tmp_path)
    validator = RecordingValidator(_validation_result("success"))

    result = _service(scenario, validator).revalidate(**identity)

    row = _stored_row(scenario)
    assert result.result == "SUCCESS"
    assert result.previous_validation_state == "UNVALIDATED"
    assert result.new_validation_state == "VALID_PRIVATE_READ"
    assert result.validated_ts_utc_present is True
    assert validator.calls == 1
    assert row["validation_state"] == "VALID_PRIVATE_READ"
    assert row["validated_ts_utc"] == "2026-07-22 12:00:00"
    assert row["last_validation_error_code"] is None


def test_valid_state_with_null_timestamp_is_genuinely_revalidated(tmp_path: Path) -> None:
    scenario = _scenario(
        tmp_path,
        validation_state="VALID_PRIVATE_READ",
        validated_ts_utc=None,
    )
    validator = RecordingValidator(_validation_result("success"))

    result = _service(scenario, validator).revalidate(profile_code="joost")

    assert validator.calls == 1
    assert result.previous_validation_state == "VALID_PRIVATE_READ"
    assert result.validated_ts_utc_present is True
    assert _stored_row(scenario)["validated_ts_utc"] == "2026-07-22 12:00:00"


def test_definitive_invalid_result_is_transactionally_persisted(tmp_path: Path) -> None:
    scenario = _scenario(tmp_path)
    validator = RecordingValidator(_validation_result("invalid"))

    result = _service(scenario, validator).revalidate(profile_code="joost")

    row = _stored_row(scenario)
    assert result.result == "INVALID"
    assert result.new_validation_state == "INVALID_CREDENTIALS"
    assert result.validated_ts_utc_present is False
    assert result.safe_error_code == "INVALID_CREDENTIALS_OR_READ_PERMISSION"
    assert row["validation_state"] == "INVALID_CREDENTIALS"
    assert row["validated_ts_utc"] is None
    assert row["last_validation_error_code"] == result.safe_error_code


def test_unavailable_result_rolls_back_without_mutation(tmp_path: Path) -> None:
    scenario = _scenario(tmp_path)
    before = _stored_row(scenario)
    validator = RecordingValidator(_validation_result("unavailable"))

    result = _service(scenario, validator).revalidate(profile_code="joost")

    assert result.result == "BLOCKED"
    assert result.safe_error_code == "VALIDATION_UNAVAILABLE"
    assert _stored_row(scenario) == before


@pytest.mark.parametrize(
    ("row_overrides", "safe_error_code"),
    (
        ({"credential_source": "legacy_profile_env_deprecated"}, "LEGACY_SOURCE_NOT_EXPLICITLY_ALLOWED"),
        ({"permission_scope": "TRADE_EXECUTION", "allowed_order_write": 1}, "NO_CREDENTIAL_BINDING"),
        ({"allowed_private_read": 0}, "MISSING_REQUIRED_PRIVATE_READ_SCOPE"),
        ({"allowed_order_write": 1}, "ORDER_WRITE_CAPABILITY_IN_READ_ONLY_CONTEXT"),
        ({"allowed_withdrawal": 1}, "WITHDRAWAL_CAPABILITY_NOT_ALLOWED"),
        ({"credential_status": "REVOKED"}, "EXACTLY_ONE_ACTIVE_CREDENTIAL_REQUIRED"),
    ),
)
def test_binding_mismatch_blocks_before_broker_calls(
    tmp_path: Path,
    row_overrides: dict[str, object],
    safe_error_code: str,
) -> None:
    scenario = _scenario(tmp_path, row_overrides=row_overrides)
    validator = RecordingValidator(_validation_result("success"))

    result = _service(scenario, validator).revalidate(profile_code="joost")

    assert result.result == "BLOCKED"
    assert result.safe_error_code == safe_error_code
    assert validator.calls == 0


def test_second_active_credential_blocks_before_broker_calls(tmp_path: Path) -> None:
    scenario = _scenario(tmp_path)
    conn = _connect(scenario)
    row = _stored_row(scenario)
    row.pop("trading_account_credential_id")
    row["permission_scope"] = "TRADE_EXECUTION"
    row["allowed_order_write"] = 1
    columns = list(row)
    conn.execute(
        "INSERT INTO trading_account_credential ("
        + ",".join(columns)
        + ") VALUES ("
        + ",".join("?" for _ in columns)
        + ")",
        tuple(row[column] for column in columns),
    )
    conn.commit()
    conn.close()
    validator = RecordingValidator(_validation_result("success"))

    result = _service(scenario, validator).revalidate(profile_code="joost")

    assert result.safe_error_code == "EXACTLY_ONE_ACTIVE_CREDENTIAL_REQUIRED"
    assert validator.calls == 0


def test_account_or_venue_identity_mismatch_blocks_before_broker_calls(
    tmp_path: Path,
) -> None:
    scenario = _scenario(tmp_path)
    validator = RecordingValidator(_validation_result("success"))
    service = _service(scenario, validator)

    missing = service.revalidate(account_code="not-joost")
    wrong_venue = service.revalidate(profile_code="joost", venue="kraken")

    assert missing.safe_error_code == "ACCOUNT_NOT_FOUND"
    assert wrong_venue.safe_error_code == "UNSUPPORTED_VENUE"
    assert validator.calls == 0


@pytest.mark.parametrize(
    ("row_overrides", "envelope_overrides", "safe_error_code"),
    (
        ({"encrypted_envelope": "{}"}, {}, "INVALID_CREDENTIAL_ENVELOPE"),
        ({}, {"tid": 2}, "CREDENTIAL_ENVELOPE_ACCOUNT_MISMATCH"),
        ({}, {"venue": "kraken"}, "CREDENTIAL_ENVELOPE_VENUE_MISMATCH"),
        ({"credential_fingerprint": "f" * 64}, {}, "CREDENTIAL_FINGERPRINT_MISMATCH"),
    ),
)
def test_static_credential_failure_blocks_before_broker_calls(
    tmp_path: Path,
    row_overrides: dict[str, object],
    envelope_overrides: dict[str, object],
    safe_error_code: str,
) -> None:
    scenario = _scenario(
        tmp_path,
        row_overrides=row_overrides,
        envelope_overrides=envelope_overrides,
    )
    validator = RecordingValidator(_validation_result("success"))

    result = _service(scenario, validator).revalidate(profile_code="joost")

    assert result.safe_error_code == safe_error_code
    assert validator.calls == 0


def test_repository_failure_rolls_back_and_closes_connection(tmp_path: Path) -> None:
    scenario = _scenario(tmp_path)
    validator = RecordingValidator(_validation_result("success"))

    class FailingRepository(SqliteCredentialRepository):
        def update_existing_active_credential_validation(self, **kwargs: object) -> int:
            super().update_existing_active_credential_validation(**kwargs)
            raise RuntimeError("persistence failed")

    result = _service(
        scenario,
        validator,
        repository_factory=FailingRepository,
    ).revalidate(profile_code="joost")

    row = _stored_row(scenario)
    assert result.result == "BLOCKED"
    assert result.safe_error_code == "PERSISTENCE_FAILED"
    assert row["validation_state"] == "UNVALIDATED"
    assert row["validated_ts_utc"] is None


def test_runtime_resolver_gate_changes_only_after_persisted_revalidation(
    tmp_path: Path,
) -> None:
    scenario = _scenario(tmp_path)
    conn = _connect(scenario)
    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn,
            profile_code="joost",
            master_key_bytes=scenario.key_bytes,
        )
    assert exc.value.code == "UNVALIDATED_CREDENTIAL"
    conn.close()

    validator = RecordingValidator(_validation_result("success"))
    _service(scenario, validator).revalidate(profile_code="joost")

    conn = _connect(scenario)
    identity, resolved = resolve_private_read_credential(
        conn,
        profile_code="joost",
        master_key_bytes=scenario.key_bytes,
    )
    assert identity.trading_account_id == 1
    assert resolved.profile.validated_ts_utc is not None
    conn.close()


def test_runtime_resolver_still_rejects_valid_state_without_timestamp(
    tmp_path: Path,
) -> None:
    scenario = _scenario(tmp_path, validation_state="VALID_PRIVATE_READ")
    conn = _connect(scenario)
    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn,
            profile_code="joost",
            master_key_bytes=scenario.key_bytes,
        )
    assert exc.value.code == "CREDENTIAL_VALIDATION_TIMESTAMP_MISSING"
    conn.close()


def test_secret_material_never_appears_in_result_or_failure(tmp_path: Path) -> None:
    scenario = _scenario(
        tmp_path,
        row_overrides={"credential_fingerprint": "f" * 64},
    )
    validator = RecordingValidator(_validation_result("success"))

    result = _service(scenario, validator).revalidate(profile_code="joost")
    text = repr(result)

    assert _SECRET_KEY not in text
    assert _SECRET_VALUE not in text
    assert "encrypted_envelope" not in text
    assert scenario.key_bytes.hex() not in text


def test_validator_exception_is_redacted_and_rolls_back(tmp_path: Path) -> None:
    scenario = _scenario(tmp_path)

    class LeakingValidator:
        def validate(self, _credential: PlainBitvavoCredential) -> CredentialValidationResult:
            raise RuntimeError(_SECRET_VALUE)

    service = ExistingCredentialRevalidationService(
        master_key_bytes=scenario.key_bytes,
        validator=LeakingValidator(),
        conn_factory=lambda: _connect(scenario),
        repository_factory=SqliteCredentialRepository,
        now_factory=lambda: _NOW,
    )

    result = service.revalidate(profile_code="joost")

    assert result.safe_error_code == "VALIDATION_UNAVAILABLE"
    assert _SECRET_VALUE not in repr(result)
    assert _stored_row(scenario)["validation_state"] == "UNVALIDATED"


def test_exact_repository_update_rejects_multiple_affected_rows() -> None:
    class Cursor:
        rowcount = 2

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _sql: str, _params: tuple[object, ...]) -> None:
            return None

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

    with pytest.raises(CredentialValidationUpdateError) as exc:
        CredentialRepository(Connection()).update_existing_active_credential_validation(
            trading_account_credential_id=1,
            trading_account_id=1,
            venue="bitvavo",
            validation_state="VALID_PRIVATE_READ",
            validated_ts_utc=_NOW,
            safe_error_code=None,
        )
    assert exc.value.code == "EXACT_ACTIVE_CREDENTIAL_UPDATE_REQUIRED"


def test_cli_requires_exactly_one_identity_selector() -> None:
    with pytest.raises(SystemExit) as none_exc:
        parse_args([])
    with pytest.raises(SystemExit) as many_exc:
        parse_args(["--profile-code", "joost", "--trading-account-id", "1"])
    assert none_exc.value.code == 2
    assert many_exc.value.code == 2


@pytest.mark.parametrize(
    ("result", "expected_exit"),
    (
        (
            ExistingCredentialRevalidationResult(
                result="SUCCESS",
                trading_account_id=1,
                account_code="joost-read",
                profile_code="joost",
                trading_account_credential_id=2,
                credential_source="db_encrypted",
                permission_scope="READ_ONLY_PRIVATE",
                previous_validation_state="UNVALIDATED",
                new_validation_state="VALID_PRIVATE_READ",
                validated_ts_utc_present=True,
            ),
            EXIT_SUCCESS,
        ),
        (
            ExistingCredentialRevalidationResult(
                result="INVALID",
                safe_error_code="INVALID_CREDENTIALS_OR_READ_PERMISSION",
            ),
            EXIT_INVALID,
        ),
        (
            ExistingCredentialRevalidationResult(
                result="BLOCKED",
                safe_error_code="VALIDATION_UNAVAILABLE",
            ),
            EXIT_UNAVAILABLE,
        ),
        (
            ExistingCredentialRevalidationResult(
                result="BLOCKED",
                safe_error_code="INVALID_CREDENTIAL_ENVELOPE",
            ),
            EXIT_STRUCTURAL_FAILURE,
        ),
    ),
)
def test_cli_exit_codes_and_redacted_output(
    capsys: pytest.CaptureFixture[str],
    result: ExistingCredentialRevalidationResult,
    expected_exit: int,
) -> None:
    service = FakeCliService(result)

    exit_code = cli_main(["--profile-code", "joost"], service=service)  # type: ignore[arg-type]
    output = capsys.readouterr().out

    assert exit_code == expected_exit
    assert "result=" in output
    assert "broker_writes=0" in output
    assert "order_submission=0" in output
    assert "live_orders=0" in output
    assert "credential_fingerprint" not in output
    assert _SECRET_KEY not in output
    assert _SECRET_VALUE not in output
    assert "encrypted_envelope" not in output


def test_cli_redacts_unexpected_service_exception(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class LeakingService:
        def revalidate(self, **_kwargs: object) -> ExistingCredentialRevalidationResult:
            raise RuntimeError(_SECRET_VALUE)

    exit_code = cli_main(  # type: ignore[arg-type]
        ["--profile-code", "joost"],
        service=LeakingService(),
    )
    output = capsys.readouterr().out

    assert exit_code == EXIT_STRUCTURAL_FAILURE
    assert "safe_error_code=UNEXPECTED_REVALIDATION_FAILURE" in output
    assert _SECRET_VALUE not in output


def test_no_global_or_order_write_fallback_in_revalidation_sources() -> None:
    service_source = Path(
        "src/account_provisioning/existing_credential_revalidation_service_v1.py"
    ).read_text(encoding="utf-8")
    cli_source = Path(
        "src/account_provisioning/run_revalidate_existing_private_read_credential_v1.py"
    ).read_text(encoding="utf-8")
    combined = service_source + cli_source

    assert "BITVAVO_API_KEY" not in combined
    assert "BITVAVO_API_SECRET" not in combined
    assert "SYNTH_BROKER_WRITE_PERMISSION" not in combined
    assert "allowed_order_write" not in combined
    assert "RealBitvavoCredentialValidator" in cli_source
    assert "resolve_existing_private_read_credential_for_revalidation" in service_source
