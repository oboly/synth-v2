"""
Canonical account-to-credential binding contract.

This module is intentionally pure validation code. It does not connect to the
database, decrypt credentials, read environment files, or construct broker
clients. Runtime enforcement belongs in a follow-up PR after callers are moved
onto this contract.

Safety:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


PERMISSION_SCOPE_READ_ONLY_PRIVATE = "READ_ONLY_PRIVATE"
PERMISSION_SCOPE_TRADE_EXECUTION = "TRADE_EXECUTION"

CREDENTIAL_SOURCE_DB_ENCRYPTED = "db_encrypted"
CREDENTIAL_SOURCE_LEGACY_PROFILE_ENV_DEPRECATED = "legacy_profile_env_deprecated"

CREDENTIAL_STATUS_ACTIVE = "ACTIVE"
VALID_CREDENTIAL_STATUSES = frozenset({"ACTIVE", "REVOKED", "ROTATED", "INVALID"})
VALID_CREDENTIAL_SOURCES = frozenset(
    {
        CREDENTIAL_SOURCE_DB_ENCRYPTED,
        CREDENTIAL_SOURCE_LEGACY_PROFILE_ENV_DEPRECATED,
    }
)
VALID_PERMISSION_SCOPES = frozenset(
    {
        PERMISSION_SCOPE_READ_ONLY_PRIVATE,
        PERMISSION_SCOPE_TRADE_EXECUTION,
    }
)
VALID_CREDENTIAL_VALIDATION_STATES = frozenset(
    {
        "UNVALIDATED",
        "VALID_READ_ONLY",
        "VALID_PRIVATE_READ",
        "INVALID_CREDENTIALS",
    }
)
VALIDATED_PRIVATE_READ_STATES = frozenset({"VALID_READ_ONLY", "VALID_PRIVATE_READ"})

SECRET_FIELD_NAMES = frozenset(
    {
        "api_key",
        "api_secret",
        "bitvavo_api_key",
        "bitvavo_api_secret",
        "encrypted_envelope",
        "master_key",
        "secret",
    }
)


class CredentialBindingValidationError(ValueError):
    """Raised when account-to-credential binding fails closed."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class CredentialBindingProfile:
    """
    Non-secret resolved credential profile.

    This is safe to print as a diagnostic contract object: it includes no
    plaintext key, secret, encrypted envelope, or master decryption material.
    """

    trading_account_id: int
    account_code: str
    venue: str
    trading_account_enabled: bool
    live_trading_enabled: bool
    trading_account_credential_id: int
    credential_source: str
    credential_status: str
    permission_scope: str
    allowed_private_read: bool
    allowed_order_write: bool
    allowed_withdrawal: bool
    credential_fingerprint: str
    key_version: str
    validation_state: str
    validated_ts_utc: Any | None
    last_validation_error_code: str | None

    def public_report(self) -> dict[str, Any]:
        """Return a non-secret report payload for logs/tests/docs."""
        return {
            "trading_account_id": self.trading_account_id,
            "account_code": self.account_code,
            "venue": self.venue,
            "trading_account_credential_id": self.trading_account_credential_id,
            "credential_source": self.credential_source,
            "credential_status": self.credential_status,
            "permission_scope": self.permission_scope,
            "allowed_private_read": self.allowed_private_read,
            "allowed_order_write": self.allowed_order_write,
            "allowed_withdrawal": self.allowed_withdrawal,
            "credential_fingerprint": self.credential_fingerprint,
            "key_version": self.key_version,
            "validation_state": self.validation_state,
            "validated_ts_utc": self.validated_ts_utc,
            "last_validation_error_code": self.last_validation_error_code,
        }


def validate_credential_binding(
    rows: Iterable[Mapping[str, Any]],
    *,
    trading_account_id: int,
    venue: str,
    required_permission_scope: str,
    require_validated: bool = True,
    allow_legacy_source: bool = False,
) -> CredentialBindingProfile:
    """
    Validate deterministic binding:

      trading_account_id + venue + required_permission_scope
        -> exactly one ACTIVE credential profile.

    The caller supplies repository rows from a query that joins
    trading_account to trading_account_credential. This function validates the
    contract and returns only non-secret metadata.
    """
    if required_permission_scope not in VALID_PERMISSION_SCOPES:
        raise CredentialBindingValidationError(
            "UNKNOWN_REQUIRED_PERMISSION_SCOPE",
            f"required_permission_scope={required_permission_scope!r}",
        )

    profiles = [_profile_from_row(row) for row in rows]
    for profile in profiles:
        _validate_row_metadata(profile)
        if profile.trading_account_id != trading_account_id:
            raise CredentialBindingValidationError(
                "ACCOUNT_ID_MISMATCH",
                (
                    f"expected_trading_account_id={trading_account_id} "
                    f"actual_trading_account_id={profile.trading_account_id}"
                ),
            )
        if profile.venue != venue:
            raise CredentialBindingValidationError(
                "VENUE_MISMATCH",
                f"expected_venue={venue!r} actual_venue={profile.venue!r}",
            )

    matches = [
        profile
        for profile in profiles
        if profile.credential_status == CREDENTIAL_STATUS_ACTIVE
        and profile.permission_scope == required_permission_scope
    ]

    if not matches:
        raise CredentialBindingValidationError(
            "NO_CREDENTIAL_BINDING",
            (
                f"trading_account_id={trading_account_id} venue={venue!r} "
                f"required_permission_scope={required_permission_scope!r}"
            ),
        )
    if len(matches) > 1:
        raise CredentialBindingValidationError(
            "MULTIPLE_ACTIVE_MATCHING_CREDENTIALS",
            (
                f"trading_account_id={trading_account_id} venue={venue!r} "
                f"required_permission_scope={required_permission_scope!r} "
                f"count={len(matches)}"
            ),
        )

    profile = matches[0]
    if not profile.trading_account_enabled:
        raise CredentialBindingValidationError(
            "ACCOUNT_DISABLED",
            f"trading_account_id={trading_account_id} account_code={profile.account_code!r}",
        )
    if profile.credential_source == CREDENTIAL_SOURCE_LEGACY_PROFILE_ENV_DEPRECATED:
        if not allow_legacy_source:
            raise CredentialBindingValidationError(
                "LEGACY_SOURCE_NOT_EXPLICITLY_ALLOWED",
                "legacy profile env credentials cannot be an implicit fallback",
            )
    elif profile.credential_source != CREDENTIAL_SOURCE_DB_ENCRYPTED:
        raise CredentialBindingValidationError(
            "GLOBAL_FALLBACK_REQUIREMENT",
            f"credential_source={profile.credential_source!r}",
        )

    if required_permission_scope == PERMISSION_SCOPE_READ_ONLY_PRIVATE:
        if not profile.allowed_private_read:
            raise CredentialBindingValidationError(
                "MISSING_REQUIRED_PRIVATE_READ_SCOPE",
                "read-only account runtime requires allowed_private_read=1",
            )
        if profile.allowed_order_write:
            raise CredentialBindingValidationError(
                "ORDER_WRITE_CAPABILITY_IN_READ_ONLY_CONTEXT",
                "READ_ONLY_PRIVATE credentials must not allow order writes",
            )

    if profile.allowed_withdrawal:
        raise CredentialBindingValidationError(
            "WITHDRAWAL_CAPABILITY_NOT_ALLOWED",
            "Synth never accepts withdrawal-capable credentials",
        )

    if require_validated and profile.validation_state not in VALIDATED_PRIVATE_READ_STATES:
        raise CredentialBindingValidationError(
            "UNVALIDATED_CREDENTIAL",
            (
                f"validation_state={profile.validation_state!r} "
                f"last_validation_error_code={profile.last_validation_error_code!r}"
            ),
        )

    return profile


def _validate_row_metadata(profile: CredentialBindingProfile) -> None:
    if profile.credential_status not in VALID_CREDENTIAL_STATUSES:
        raise CredentialBindingValidationError(
            "UNKNOWN_CREDENTIAL_STATUS",
            f"credential_status={profile.credential_status!r}",
        )
    if profile.credential_source not in VALID_CREDENTIAL_SOURCES:
        raise CredentialBindingValidationError(
            "GLOBAL_FALLBACK_REQUIREMENT",
            f"credential_source={profile.credential_source!r}",
        )
    if profile.permission_scope not in VALID_PERMISSION_SCOPES:
        raise CredentialBindingValidationError(
            "UNKNOWN_PERMISSION_SCOPE",
            f"permission_scope={profile.permission_scope!r}",
        )
    if profile.validation_state not in VALID_CREDENTIAL_VALIDATION_STATES:
        raise CredentialBindingValidationError(
            "UNKNOWN_VALIDATION_STATE",
            f"validation_state={profile.validation_state!r}",
        )
    if profile.allowed_withdrawal:
        raise CredentialBindingValidationError(
            "WITHDRAWAL_CAPABILITY_NOT_ALLOWED",
            "allowed_withdrawal must be false",
        )
    if (
        profile.permission_scope == PERMISSION_SCOPE_READ_ONLY_PRIVATE
        and profile.allowed_order_write
    ):
        raise CredentialBindingValidationError(
            "ORDER_WRITE_CAPABILITY_IN_READ_ONLY_CONTEXT",
            "READ_ONLY_PRIVATE credentials must not allow order writes",
        )


def _profile_from_row(row: Mapping[str, Any]) -> CredentialBindingProfile:
    forbidden = sorted(set(row.keys()) & SECRET_FIELD_NAMES)
    if forbidden:
        raise CredentialBindingValidationError(
            "SECRET_FIELD_EXPOSED_TO_BINDING_VALIDATOR",
            "forbidden_fields=" + ",".join(forbidden),
        )

    trading_account_enabled = _required_field(
        row,
        "trading_account_enabled",
        legacy_field_name="enabled",
    )

    return CredentialBindingProfile(
        trading_account_id=int(row["trading_account_id"]),
        account_code=str(row["account_code"]),
        venue=str(row["venue"]),
        trading_account_enabled=_bool_value(
            trading_account_enabled,
            field_name="trading_account_enabled",
        ),
        live_trading_enabled=_bool_value(
            _required_field(row, "live_trading_enabled"),
            field_name="live_trading_enabled",
        ),
        trading_account_credential_id=int(row["trading_account_credential_id"]),
        credential_source=str(row["credential_source"]),
        credential_status=str(row["credential_status"]),
        permission_scope=str(row["permission_scope"]),
        allowed_private_read=_bool_value(
            _required_field(row, "allowed_private_read"),
            field_name="allowed_private_read",
        ),
        allowed_order_write=_bool_value(
            _required_field(row, "allowed_order_write"),
            field_name="allowed_order_write",
        ),
        allowed_withdrawal=_bool_value(
            _required_field(row, "allowed_withdrawal"),
            field_name="allowed_withdrawal",
        ),
        credential_fingerprint=str(row["credential_fingerprint"]),
        key_version=str(row["key_version"]),
        validation_state=str(row["validation_state"]),
        validated_ts_utc=row.get("validated_ts_utc"),
        last_validation_error_code=(
            None
            if row.get("last_validation_error_code") is None
            else str(row.get("last_validation_error_code"))
        ),
    )


def _required_field(
    row: Mapping[str, Any],
    field_name: str,
    *,
    legacy_field_name: str | None = None,
) -> Any:
    if field_name in row:
        return row[field_name]
    if legacy_field_name is not None and legacy_field_name in row:
        return row[legacy_field_name]
    raise CredentialBindingValidationError(
        "MISSING_REQUIRED_BOOLEAN_FIELD",
        f"field_name={field_name}",
    )


def _bool_value(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if value in (0, 1):
            return bool(value)
        raise CredentialBindingValidationError(
            "INVALID_BOOLEAN_VALUE",
            f"field_name={field_name}",
        )
    if value is None:
        raise CredentialBindingValidationError(
            "INVALID_BOOLEAN_VALUE",
            f"field_name={field_name}",
        )
    if isinstance(value, str):
        if value in {"1", "true"}:
            return True
        if value in {"0", "false"}:
            return False
    raise CredentialBindingValidationError(
        "INVALID_BOOLEAN_VALUE",
        f"field_name={field_name}",
    )
