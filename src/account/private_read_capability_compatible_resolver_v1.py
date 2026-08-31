"""
Explicit capability-compatible private-read credential resolution.

This seam is intentionally separate from the canonical strict
READ_ONLY_PRIVATE resolver. It is for bounded private-read-only consumers that
may reuse either:

- a validated READ_ONLY_PRIVATE credential, or
- a validated TRADE_EXECUTION credential whose canonical contract already
  requires allowed_private_read=1.

The resolved broker client is always constructed through
BitvavoClient.for_private_read(...). This module exposes no broker-write path.

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
from typing import Any

from src.account.private_read_credential_resolver_v1 import (
    DEFAULT_PRIVATE_READ_VENUE,
    AccountRuntimeIdentity,
    PrivateReadClientResolution,
    PrivateReadCredential,
    PrivateReadCredentialResolutionError,
    _credential_metadata_rows,
    _leading_code,
    _load_encrypted_credential_record,
    _validate_encrypted_credential_metadata,
    resolve_account_identity,
)
from src.account_provisioning.contracts_v1 import EncryptedCredentialEnvelope
from src.account_provisioning.credential_binding_contract_v1 import (
    PERMISSION_SCOPE_READ_ONLY_PRIVATE,
    PERMISSION_SCOPE_TRADE_EXECUTION,
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


def resolve_private_read_capable_credential(
    conn: Any,
    *,
    master_key_bytes: bytes,
    venue: str = DEFAULT_PRIVATE_READ_VENUE,
    trading_account_id: int | None = None,
    account_code: str | None = None,
    profile_code: str | None = None,
) -> tuple[AccountRuntimeIdentity, PrivateReadCredential]:
    """Resolve exactly one validated private-read-capable credential.

    Eligibility is explicit and limited to the two canonical permission scopes.
    A valid candidate in both scopes is treated as ambiguous and fails closed.
    """
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

    candidates: list[CredentialBindingProfile] = []
    failures: list[CredentialBindingValidationError] = []
    for scope in (
        PERMISSION_SCOPE_READ_ONLY_PRIVATE,
        PERMISSION_SCOPE_TRADE_EXECUTION,
    ):
        try:
            profile = validate_credential_binding(
                metadata_rows,
                trading_account_id=identity.trading_account_id,
                venue=identity.venue,
                required_permission_scope=scope,
                require_validated=True,
                allow_legacy_source=False,
            )
        except CredentialBindingValidationError as exc:
            if exc.code != "NO_CREDENTIAL_BINDING":
                failures.append(exc)
        else:
            candidates.append(profile)

    if len(candidates) > 1:
        raise PrivateReadCredentialResolutionError(
            "AMBIGUOUS_PRIVATE_READ_CAPABLE_CREDENTIALS",
            (
                f"trading_account_id={identity.trading_account_id} "
                f"venue={identity.venue!r} eligible_count={len(candidates)}"
            ),
        )
    if not candidates:
        if failures:
            exc = failures[0]
            raise PrivateReadCredentialResolutionError(
                exc.code,
                "credential binding validation failed",
            ) from None
        raise PrivateReadCredentialResolutionError(
            "NO_CREDENTIAL_BINDING",
            "no validated private-read-capable credential binding found",
        )

    profile = candidates[0]
    if not profile.allowed_private_read:
        raise PrivateReadCredentialResolutionError(
            "MISSING_REQUIRED_PRIVATE_READ_SCOPE",
            "private-read-capable credential requires allowed_private_read=1",
        )
    if profile.allowed_withdrawal:
        raise PrivateReadCredentialResolutionError(
            "WITHDRAWAL_CAPABILITY_NOT_ALLOWED",
            "Synth never accepts withdrawal-capable credentials",
        )
    if profile.validated_ts_utc is None:
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


def resolve_private_read_capable_bitvavo_client(
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
    """Resolve capability-compatible credentials into a private-read client."""
    identity, resolved = resolve_private_read_capable_credential(
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


def resolve_private_read_capable_bitvavo_client_from_env(
    conn: Any,
    *,
    venue: str = DEFAULT_PRIVATE_READ_VENUE,
    trading_account_id: int | None = None,
    account_code: str | None = None,
    profile_code: str | None = None,
    timeout_seconds: int = 15,
    client_factory: Any | None = None,
) -> PrivateReadClientResolution:
    """Load the host-local master key and construct only a private-read client."""
    try:
        _, master_key_bytes = load_master_key_from_env()
    except ValueError as exc:
        raise PrivateReadCredentialResolutionError(
            _leading_code(str(exc), default="MISSING_MASTER_KEY"),
            "host-local credential master key is missing or invalid",
        ) from None
    return resolve_private_read_capable_bitvavo_client(
        conn,
        master_key_bytes=master_key_bytes,
        venue=venue,
        trading_account_id=trading_account_id,
        account_code=account_code,
        profile_code=profile_code,
        timeout_seconds=timeout_seconds,
        client_factory=client_factory,
    )
