"""
private_read_credential_resolver_v1 — Canonical account-bound private-read credentials.

Canonical runtime binding:

  trading_account_id + venue + READ_ONLY_PRIVATE
    -> exactly one ACTIVE validated db_encrypted credential

This module is account runtime/infrastructure. It does not belong to selection,
decision_gate, execution_planner, executor, or dashboard rendering.

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

import hmac
from dataclasses import dataclass, field
from typing import Any, Mapping

from src.account.linked_account_resolver_v1 import resolve_primary_linked_account
from src.account_provisioning.contracts_v1 import (
    CREDENTIAL_SCHEMA_VERSION,
    ENCRYPTION_ALGORITHM,
    EncryptedCredentialEnvelope,
    PlainBitvavoCredential,
)
from src.account_provisioning.credential_binding_contract_v1 import (
    PERMISSION_SCOPE_READ_ONLY_PRIVATE,
    CredentialBindingProfile,
    CredentialBindingValidationError,
    validate_credential_binding,
)
from src.account_provisioning.credential_crypto_v1 import (
    compute_fingerprint,
    decrypt_credential,
    load_master_key_from_env,
)
from src.execution.bitvavo_client import BitvavoClient


DEFAULT_PRIVATE_READ_VENUE = "bitvavo"


class PrivateReadCredentialResolutionError(RuntimeError):
    """Fail-closed private-read credential resolution error with safe code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class AccountRuntimeIdentity:
    trading_account_id: int
    account_code: str
    venue: str
    account_mode: str
    enabled: bool
    live_trading_enabled: bool
    profile_code: str | None = None


@dataclass(frozen=True, repr=False)
class PrivateReadCredential:
    profile: CredentialBindingProfile = field(repr=False)
    credential: PlainBitvavoCredential = field(repr=False)

    def __repr__(self) -> str:
        return (
            "PrivateReadCredential("
            f"profile={self.public_report()!r}, "
            "credential=<redacted>)"
        )

    def public_report(self) -> dict[str, Any]:
        return _private_read_profile_public_report(self.profile)


@dataclass(frozen=True, repr=False)
class EncryptedCredentialRecord:
    credential_kind: str
    encrypted_envelope: str = field(repr=False)
    encryption_algorithm: str
    key_version: str


@dataclass(frozen=True, repr=False)
class PrivateReadClientResolution:
    identity: AccountRuntimeIdentity
    profile: CredentialBindingProfile
    client: Any = field(repr=False)

    def __repr__(self) -> str:
        return f"PrivateReadClientResolution({self.public_report()!r}, client=<redacted>)"

    def public_report(self) -> dict[str, Any]:
        return {
            "trading_account_id": self.identity.trading_account_id,
            "account_code": self.identity.account_code,
            "venue": self.identity.venue,
            "credential_profile_id": self.profile.trading_account_credential_id,
            "credential_fingerprint": self.profile.credential_fingerprint,
            "permission_scope": self.profile.permission_scope,
            "validation_state": self.profile.validation_state,
        }


def resolve_account_identity(
    conn: Any,
    *,
    venue: str = DEFAULT_PRIVATE_READ_VENUE,
    trading_account_id: int | None = None,
    account_code: str | None = None,
    profile_code: str | None = None,
) -> AccountRuntimeIdentity:
    supplied = [
        trading_account_id is not None,
        bool(account_code),
        bool(profile_code),
    ]
    if sum(1 for value in supplied if value) != 1:
        raise PrivateReadCredentialResolutionError(
            "ACCOUNT_IDENTITY_NOT_EXACT",
            "supply exactly one of trading_account_id, account_code, or profile_code",
        )

    if profile_code:
        try:
            linked = resolve_primary_linked_account(
                conn,
                profile_code=profile_code,
                venue=venue,
            )
        except ValueError as exc:
            raise PrivateReadCredentialResolutionError(
                _leading_code(str(exc), default="PROFILE_ACCOUNT_RESOLUTION_FAILED"),
                str(exc),
            ) from None
        return _load_account_by_id(
            conn,
            trading_account_id=linked.trading_account_id,
            venue=venue,
            profile_code=profile_code,
        )

    if trading_account_id is not None:
        return _load_account_by_id(
            conn,
            trading_account_id=trading_account_id,
            venue=venue,
            profile_code=None,
        )

    assert account_code is not None
    rows = _query_all(
        conn,
        """
        SELECT
            trading_account_id,
            account_code,
            venue,
            account_mode,
            enabled,
            live_trading_enabled
        FROM trading_account
        WHERE account_code = %s
          AND venue = %s
        ORDER BY trading_account_id
        LIMIT 2
        """,
        (account_code, venue),
    )
    if not rows:
        raise PrivateReadCredentialResolutionError(
            "ACCOUNT_NOT_FOUND",
            f"account_code={account_code!r} venue={venue!r}",
        )
    if len(rows) > 1:
        raise PrivateReadCredentialResolutionError(
            "ACCOUNT_CODE_AMBIGUOUS",
            f"account_code={account_code!r} venue={venue!r} count={len(rows)}",
        )
    return _identity_from_account_row(rows[0], expected_venue=venue, profile_code=None)


def resolve_private_read_credential(
    conn: Any,
    *,
    master_key_bytes: bytes,
    venue: str = DEFAULT_PRIVATE_READ_VENUE,
    trading_account_id: int | None = None,
    account_code: str | None = None,
    profile_code: str | None = None,
) -> tuple[AccountRuntimeIdentity, PrivateReadCredential]:
    """Resolve only an already validated runtime credential.

    Runtime callers intentionally retain both fail-closed gates: a validated
    state and a non-null validation timestamp are required before static
    envelope verification or client construction can continue.
    """
    return _resolve_existing_private_read_credential(
        conn,
        master_key_bytes=master_key_bytes,
        venue=venue,
        trading_account_id=trading_account_id,
        account_code=account_code,
        profile_code=profile_code,
        require_validated=True,
        require_validation_timestamp=True,
        require_exactly_one_active_credential=False,
    )


def resolve_existing_private_read_credential_for_revalidation(
    conn: Any,
    *,
    master_key_bytes: bytes,
    venue: str = DEFAULT_PRIVATE_READ_VENUE,
    trading_account_id: int | None = None,
    account_code: str | None = None,
    profile_code: str | None = None,
) -> tuple[AccountRuntimeIdentity, PrivateReadCredential]:
    """Statically verify an existing binding before broker revalidation.

    This entrypoint relaxes only the two fields that the revalidation workflow
    is responsible for repairing. It still requires the exact account binding,
    ACTIVE db_encrypted READ_ONLY_PRIVATE metadata, envelope/account/venue
    alignment, decryption, and constant-time fingerprint verification.
    """
    return _resolve_existing_private_read_credential(
        conn,
        master_key_bytes=master_key_bytes,
        venue=venue,
        trading_account_id=trading_account_id,
        account_code=account_code,
        profile_code=profile_code,
        require_validated=False,
        require_validation_timestamp=False,
        require_exactly_one_active_credential=True,
    )


def _resolve_existing_private_read_credential(
    conn: Any,
    *,
    master_key_bytes: bytes,
    venue: str,
    trading_account_id: int | None,
    account_code: str | None,
    profile_code: str | None,
    require_validated: bool,
    require_validation_timestamp: bool,
    require_exactly_one_active_credential: bool,
) -> tuple[AccountRuntimeIdentity, PrivateReadCredential]:
    identity = resolve_account_identity(
        conn,
        venue=venue,
        trading_account_id=trading_account_id,
        account_code=account_code,
        profile_code=profile_code,
    )
    metadata_rows = _credential_metadata_rows(
        conn,
        trading_account_id=identity.trading_account_id,
        venue=identity.venue,
    )
    if require_exactly_one_active_credential:
        active_count = sum(
            row.get("credential_status") == "ACTIVE" for row in metadata_rows
        )
        if active_count != 1:
            raise PrivateReadCredentialResolutionError(
                "EXACTLY_ONE_ACTIVE_CREDENTIAL_REQUIRED",
                (
                    f"trading_account_id={identity.trading_account_id} "
                    f"venue={identity.venue!r} active_count={active_count}"
                ),
            )
    try:
        profile = validate_credential_binding(
            metadata_rows,
            trading_account_id=identity.trading_account_id,
            venue=identity.venue,
            required_permission_scope=PERMISSION_SCOPE_READ_ONLY_PRIVATE,
            require_validated=require_validated,
            allow_legacy_source=False,
        )
    except CredentialBindingValidationError as exc:
        raise PrivateReadCredentialResolutionError(
            exc.code,
            "credential binding validation failed",
        ) from None
    if require_validation_timestamp and profile.validated_ts_utc is None:
        raise PrivateReadCredentialResolutionError(
            "CREDENTIAL_VALIDATION_TIMESTAMP_MISSING",
            "validated credential must have validated_ts_utc",
        )

    encrypted_record = _load_encrypted_credential_record(
        conn,
        trading_account_id=identity.trading_account_id,
        venue=identity.venue,
        trading_account_credential_id=profile.trading_account_credential_id,
    )
    try:
        envelope = EncryptedCredentialEnvelope.from_json(
            encrypted_record.encrypted_envelope
        )
    except (KeyError, TypeError, ValueError):
        raise PrivateReadCredentialResolutionError(
            "INVALID_CREDENTIAL_ENVELOPE",
            "credential envelope metadata is invalid",
        ) from None

    _validate_encrypted_credential_metadata(
        identity=identity,
        profile=profile,
        record=encrypted_record,
        envelope=envelope,
    )
    try:
        credential = decrypt_credential(envelope, master_key_bytes)
    except ValueError as exc:
        raise PrivateReadCredentialResolutionError(
            _leading_code(str(exc), default="CREDENTIAL_DECRYPTION_FAILED"),
            "credential envelope could not be decrypted",
        ) from None
    expected_fingerprint = compute_fingerprint(
        identity.venue,
        credential.api_key,
        master_key_bytes,
    )
    if not hmac.compare_digest(expected_fingerprint, profile.credential_fingerprint):
        raise PrivateReadCredentialResolutionError(
            "CREDENTIAL_FINGERPRINT_MISMATCH",
            "decrypted credential fingerprint does not match binding metadata",
        )

    return identity, PrivateReadCredential(profile=profile, credential=credential)


def resolve_private_read_bitvavo_client(
    conn: Any,
    *,
    master_key_bytes: bytes,
    venue: str = DEFAULT_PRIVATE_READ_VENUE,
    trading_account_id: int | None = None,
    account_code: str | None = None,
    profile_code: str | None = None,
    timeout_seconds: int = 15,
    client_factory: Any | None = None,
) -> PrivateReadClientResolution:
    identity, resolved = resolve_private_read_credential(
        conn,
        master_key_bytes=master_key_bytes,
        venue=venue,
        trading_account_id=trading_account_id,
        account_code=account_code,
        profile_code=profile_code,
    )
    profile = resolved.profile
    if client_factory is None:
        client = BitvavoClient.for_private_read(
            api_key=resolved.credential.api_key,
            api_secret=resolved.credential.api_secret,
            timeout_seconds=timeout_seconds,
        )
    else:
        client = client_factory(
            resolved.credential.api_key,
            resolved.credential.api_secret,
        )
    del resolved
    return PrivateReadClientResolution(
        identity=identity,
        profile=profile,
        client=client,
    )


def resolve_private_read_bitvavo_client_from_env(
    conn: Any,
    *,
    venue: str = DEFAULT_PRIVATE_READ_VENUE,
    trading_account_id: int | None = None,
    account_code: str | None = None,
    profile_code: str | None = None,
    timeout_seconds: int = 15,
    client_factory: Any | None = None,
) -> PrivateReadClientResolution:
    try:
        _, master_key_bytes = load_master_key_from_env()
    except ValueError as exc:
        raise PrivateReadCredentialResolutionError(
            _leading_code(str(exc), default="MISSING_MASTER_KEY"),
            "host-local credential master key is missing or invalid",
        ) from None
    return resolve_private_read_bitvavo_client(
        conn,
        master_key_bytes=master_key_bytes,
        venue=venue,
        trading_account_id=trading_account_id,
        account_code=account_code,
        profile_code=profile_code,
        timeout_seconds=timeout_seconds,
        client_factory=client_factory,
    )


def _load_account_by_id(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    profile_code: str | None,
) -> AccountRuntimeIdentity:
    row = _query_one(
        conn,
        """
        SELECT
            trading_account_id,
            account_code,
            venue,
            account_mode,
            enabled,
            live_trading_enabled
        FROM trading_account
        WHERE trading_account_id = %s
        """,
        (trading_account_id,),
    )
    if row is None:
        raise PrivateReadCredentialResolutionError(
            "ACCOUNT_NOT_FOUND",
            f"trading_account_id={trading_account_id}",
        )
    return _identity_from_account_row(row, expected_venue=venue, profile_code=profile_code)


def _identity_from_account_row(
    row: Any,
    *,
    expected_venue: str,
    profile_code: str | None,
) -> AccountRuntimeIdentity:
    trading_account_id = int(_row_get(row, "trading_account_id", 0))
    account_code = str(_row_get(row, "account_code", 1))
    venue = str(_row_get(row, "venue", 2))
    account_mode = str(_row_get(row, "account_mode", 3))
    enabled = _bool_db_value(_row_get(row, "enabled", 4), field_name="enabled")
    live_trading_enabled = _bool_db_value(
        _row_get(row, "live_trading_enabled", 5),
        field_name="live_trading_enabled",
    )
    if venue != expected_venue:
        raise PrivateReadCredentialResolutionError(
            "VENUE_MISMATCH",
            (
                f"trading_account_id={trading_account_id} "
                f"expected_venue={expected_venue!r} actual_venue={venue!r}"
            ),
        )
    if not enabled:
        raise PrivateReadCredentialResolutionError(
            "ACCOUNT_DISABLED",
            f"trading_account_id={trading_account_id} account_code={account_code!r}",
        )
    return AccountRuntimeIdentity(
        trading_account_id=trading_account_id,
        account_code=account_code,
        venue=venue,
        account_mode=account_mode,
        enabled=enabled,
        live_trading_enabled=live_trading_enabled,
        profile_code=profile_code,
    )


def _credential_metadata_rows(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
) -> list[Mapping[str, Any]]:
    rows = _query_all(
        conn,
        """
        SELECT
            ta.trading_account_id,
            ta.account_code,
            tac.venue,
            ta.enabled AS trading_account_enabled,
            ta.live_trading_enabled,
            tac.trading_account_credential_id,
            tac.credential_source,
            tac.credential_status,
            tac.permission_scope,
            tac.allowed_private_read,
            tac.allowed_order_write,
            tac.allowed_withdrawal,
            tac.credential_fingerprint,
            tac.key_version,
            tac.validation_state,
            tac.validated_ts_utc,
            NULL AS last_validation_error_code
        FROM trading_account ta
        JOIN trading_account_credential tac
          ON tac.trading_account_id = ta.trading_account_id
        WHERE ta.trading_account_id = %s
          AND ta.venue = %s
          AND tac.venue = %s
        ORDER BY tac.trading_account_credential_id
        """,
        (trading_account_id, venue, venue),
    )
    return [_row_to_dict(row) for row in rows]


def _load_encrypted_credential_record(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    trading_account_credential_id: int,
) -> EncryptedCredentialRecord:
    row = _query_one(
        conn,
        """
        SELECT
            credential_kind,
            encrypted_envelope,
            encryption_algorithm,
            key_version
        FROM trading_account_credential
        WHERE trading_account_credential_id = %s
          AND trading_account_id = %s
          AND venue = %s
        """,
        (trading_account_credential_id, trading_account_id, venue),
    )
    if row is None:
        raise PrivateReadCredentialResolutionError(
            "CREDENTIAL_ENVELOPE_NOT_FOUND",
            f"trading_account_credential_id={trading_account_credential_id}",
        )
    return EncryptedCredentialRecord(
        credential_kind=str(_row_get(row, "credential_kind", 0)),
        encrypted_envelope=str(_row_get(row, "encrypted_envelope", 1)),
        encryption_algorithm=str(_row_get(row, "encryption_algorithm", 2)),
        key_version=str(_row_get(row, "key_version", 3)),
    )


def _validate_encrypted_credential_metadata(
    *,
    identity: AccountRuntimeIdentity,
    profile: CredentialBindingProfile,
    record: EncryptedCredentialRecord,
    envelope: EncryptedCredentialEnvelope,
) -> None:
    checks = (
        (
            record.credential_kind == "API_KEY_SECRET",
            "CREDENTIAL_KIND_MISMATCH",
            "credential kind is not API_KEY_SECRET",
        ),
        (
            record.encryption_algorithm == ENCRYPTION_ALGORITHM
            and envelope.alg == record.encryption_algorithm,
            "CREDENTIAL_ENCRYPTION_ALGORITHM_MISMATCH",
            "credential encryption algorithm metadata does not match",
        ),
        (
            record.key_version == profile.key_version
            and envelope.kv == record.key_version,
            "CREDENTIAL_KEY_VERSION_MISMATCH",
            "credential key-version metadata does not match",
        ),
        (
            envelope.sv == CREDENTIAL_SCHEMA_VERSION,
            "CREDENTIAL_SCHEMA_VERSION_MISMATCH",
            "credential schema-version metadata does not match",
        ),
        (
            envelope.trading_account_id == identity.trading_account_id,
            "CREDENTIAL_ENVELOPE_ACCOUNT_MISMATCH",
            "credential envelope is bound to a different trading account",
        ),
        (
            envelope.venue == identity.venue,
            "CREDENTIAL_ENVELOPE_VENUE_MISMATCH",
            "credential envelope is bound to a different venue",
        ),
    )
    for valid, code, message in checks:
        if not valid:
            raise PrivateReadCredentialResolutionError(code, message)


def _query_one(conn: Any, sql: str, params: tuple[Any, ...]) -> Any | None:
    rows = _query_all(conn, sql, params)
    return None if not rows else rows[0]


def _private_read_profile_public_report(
    profile: CredentialBindingProfile,
) -> dict[str, Any]:
    return {
        "trading_account_id": profile.trading_account_id,
        "account_code": profile.account_code,
        "venue": profile.venue,
        "trading_account_credential_id": profile.trading_account_credential_id,
        "credential_source": profile.credential_source,
        "credential_status": profile.credential_status,
        "permission_scope": profile.permission_scope,
        "allowed_private_read": profile.allowed_private_read,
        "allowed_order_write": profile.allowed_order_write,
        "allowed_withdrawal": profile.allowed_withdrawal,
        "credential_fingerprint": profile.credential_fingerprint,
        "key_version": profile.key_version,
        "validation_state": profile.validation_state,
        "validated_ts_utc": profile.validated_ts_utc,
    }


def _query_all(conn: Any, sql: str, params: tuple[Any, ...]) -> list[Any]:
    normalized = sql.replace("%s", "?")
    if conn.__class__.__module__.startswith("sqlite3"):
        return list(conn.execute(normalized, params).fetchall())

    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return list(cur.fetchall())
    finally:
        close = getattr(cur, "close", None)
        if callable(close):
            close()


def _row_get(row: Any, key: str, fallback_index: int) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return row[fallback_index]


def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    keys = getattr(row, "keys", None)
    if callable(keys):
        return {str(key): row[key] for key in keys()}
    raise PrivateReadCredentialResolutionError(
        "UNSUPPORTED_ROW_SHAPE",
        f"row_type={type(row).__name__}",
    )


def _bool_db_value(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value in {"0", "1"}:
        return value == "1"
    raise PrivateReadCredentialResolutionError(
        "INVALID_BOOLEAN_VALUE",
        f"field_name={field_name}",
    )


def _leading_code(message: str, *, default: str) -> str:
    token = message.split(":", 1)[0].strip()
    if token and token.upper() == token and " " not in token:
        return token
    return default
