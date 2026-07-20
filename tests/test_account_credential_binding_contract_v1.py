from __future__ import annotations

from pathlib import Path

import pytest

from src.account_provisioning.credential_binding_contract_v1 import (
    PERMISSION_SCOPE_READ_ONLY_PRIVATE,
    CredentialBindingValidationError,
    validate_credential_binding,
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "trading_account_id": 2,
        "account_code": "bitvavo_synth_read",
        "venue": "bitvavo",
        "trading_account_enabled": 1,
        "live_trading_enabled": 0,
        "trading_account_credential_id": 11,
        "credential_source": "db_encrypted",
        "credential_status": "ACTIVE",
        "permission_scope": "READ_ONLY_PRIVATE",
        "allowed_private_read": 1,
        "allowed_order_write": 0,
        "allowed_withdrawal": 0,
        "credential_fingerprint": "a" * 64,
        "key_version": "v1",
        "validation_state": "VALID_PRIVATE_READ",
        "validated_ts_utc": "2026-07-21 12:00:00",
        "last_validation_error_code": None,
    }
    row.update(overrides)
    return row


def _validate(rows: list[dict[str, object]]):
    return validate_credential_binding(
        rows,
        trading_account_id=2,
        venue="bitvavo",
        required_permission_scope=PERMISSION_SCOPE_READ_ONLY_PRIVATE,
    )


def _assert_code(exc: pytest.ExceptionInfo[CredentialBindingValidationError], code: str) -> None:
    assert exc.value.code == code
    assert str(exc.value).startswith(code + ":")


def test_exactly_one_active_binding_resolves_non_secret_profile() -> None:
    profile = _validate([_row()])

    assert profile.trading_account_id == 2
    assert profile.trading_account_credential_id == 11
    assert profile.permission_scope == "READ_ONLY_PRIVATE"
    assert profile.credential_source == "db_encrypted"
    assert profile.allowed_private_read is True
    assert profile.allowed_order_write is False
    assert profile.allowed_withdrawal is False


def test_missing_binding_rejected() -> None:
    with pytest.raises(CredentialBindingValidationError) as exc:
        _validate([])

    _assert_code(exc, "NO_CREDENTIAL_BINDING")


def test_duplicate_active_binding_rejected() -> None:
    rows = [
        _row(trading_account_credential_id=11),
        _row(trading_account_credential_id=12, credential_fingerprint="b" * 64),
    ]

    with pytest.raises(CredentialBindingValidationError) as exc:
        _validate(rows)

    _assert_code(exc, "MULTIPLE_ACTIVE_MATCHING_CREDENTIALS")


def test_venue_mismatch_rejected() -> None:
    with pytest.raises(CredentialBindingValidationError) as exc:
        _validate([_row(venue="kraken")])

    _assert_code(exc, "VENUE_MISMATCH")


def test_missing_required_private_read_scope_rejected() -> None:
    with pytest.raises(CredentialBindingValidationError) as exc:
        _validate([_row(allowed_private_read=0)])

    _assert_code(exc, "MISSING_REQUIRED_PRIVATE_READ_SCOPE")


def test_read_only_order_write_capability_rejected() -> None:
    with pytest.raises(CredentialBindingValidationError) as exc:
        _validate([_row(allowed_order_write=1)])

    _assert_code(exc, "ORDER_WRITE_CAPABILITY_IN_READ_ONLY_CONTEXT")


def test_withdrawal_capability_rejected() -> None:
    with pytest.raises(CredentialBindingValidationError) as exc:
        _validate([_row(allowed_withdrawal=1)])

    _assert_code(exc, "WITHDRAWAL_CAPABILITY_NOT_ALLOWED")


def test_legacy_source_cannot_be_implicit_fallback() -> None:
    with pytest.raises(CredentialBindingValidationError) as exc:
        _validate([_row(credential_source="legacy_profile_env_deprecated")])

    _assert_code(exc, "LEGACY_SOURCE_NOT_EXPLICITLY_ALLOWED")


def test_global_env_source_rejected() -> None:
    with pytest.raises(CredentialBindingValidationError) as exc:
        _validate([_row(credential_source="global_env")])

    _assert_code(exc, "GLOBAL_FALLBACK_REQUIREMENT")


def test_unknown_credential_status_rejected() -> None:
    with pytest.raises(CredentialBindingValidationError) as exc:
        _validate([_row(credential_status="CURRENT")])

    _assert_code(exc, "UNKNOWN_CREDENTIAL_STATUS")


def test_unvalidated_credential_rejected_when_validation_required() -> None:
    with pytest.raises(CredentialBindingValidationError) as exc:
        _validate([_row(validation_state="UNVALIDATED")])

    _assert_code(exc, "UNVALIDATED_CREDENTIAL")


def test_disabled_account_rejected() -> None:
    with pytest.raises(CredentialBindingValidationError) as exc:
        _validate([_row(trading_account_enabled=0)])

    _assert_code(exc, "ACCOUNT_DISABLED")


def test_secret_fields_are_rejected_before_reporting() -> None:
    with pytest.raises(CredentialBindingValidationError) as exc:
        _validate([_row(api_key="secret-key")])

    _assert_code(exc, "SECRET_FIELD_EXPOSED_TO_BINDING_VALIDATOR")


def test_public_report_exposes_no_secret_fields() -> None:
    profile = _validate([_row()])
    report = profile.public_report()
    text = repr(report).lower()

    assert "api_key" not in report
    assert "api_secret" not in report
    assert "encrypted_envelope" not in report
    assert "master_key" not in report
    assert "secret" not in text


def test_migration_contains_active_scope_unique_index_and_no_plaintext_columns() -> None:
    migration = Path("db/migrations/20260721_account_credential_binding_contract_v1.sql").read_text()

    assert "uq_tac_active_account_venue_scope_v1" in migration
    assert "active_permission_scope" in migration
    assert "allowed_withdrawal = 0" in migration
    assert "BITVAVO_API_KEY" not in migration
    assert "BITVAVO_API_SECRET" not in migration
    assert "api_key" not in migration.lower()
    assert "api_secret" not in migration.lower()
