"""
account_credential_loader_v1 — Load and decrypt stored account credentials.

Provides a single entry point to retrieve a PlainBitvavoCredential from the
encrypted credential store for a given (trading_account_id, venue).

Rules:
  - Never falls back to global env vars.
  - Hugo's account always uses Hugo's stored credential, never Joost's env fallback.
  - Raises ValueError if no active credential is found.
  - Caller is responsible for zero-ing/discarding the returned PlainBitvavoCredential.

Safety:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  executor=none
"""
from __future__ import annotations

from typing import Any

from src.account_provisioning.contracts_v1 import EncryptedCredentialEnvelope, PlainBitvavoCredential
from src.account_provisioning.credential_crypto_v1 import decrypt_credential


def load_account_credential(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    master_key_bytes: bytes,
    cred_repo_factory: Any,
) -> PlainBitvavoCredential:
    """
    Load and decrypt the active credential for (trading_account_id, venue).

    Returns PlainBitvavoCredential with explicit api_key and api_secret.
    Never falls back to global env vars — Hugo's credentials are always
    loaded from the encrypted store, not from any environment fallback.

    Raises ValueError(NO_ACTIVE_CREDENTIAL) if no active credential exists.
    """
    cred_repo = cred_repo_factory(conn)
    stored = cred_repo.load_active_encrypted_credential(
        trading_account_id=trading_account_id,
        venue=venue,
    )
    if stored is None:
        raise ValueError(
            f"NO_ACTIVE_CREDENTIAL: trading_account_id={trading_account_id} venue={venue!r}"
        )

    envelope = EncryptedCredentialEnvelope.from_json(stored.encrypted_envelope)
    return decrypt_credential(envelope, master_key_bytes)


def load_account_credential_by_id(
    conn: Any, *, trading_account_credential_id: int, trading_account_id: int, venue: str,
    master_key_bytes: bytes, cred_repo_factory: Any,
) -> PlainBitvavoCredential:
    """Decrypt only the credential identity already authorized by an executor binding."""
    stored = cred_repo_factory(conn).load_active_encrypted_credential_by_id(
        trading_account_credential_id=trading_account_credential_id,
        trading_account_id=trading_account_id,
        venue=venue,
    )
    if stored is None:
        raise ValueError("NO_EXACT_ACTIVE_CREDENTIAL")
    return decrypt_credential(EncryptedCredentialEnvelope.from_json(stored.encrypted_envelope), master_key_bytes)
