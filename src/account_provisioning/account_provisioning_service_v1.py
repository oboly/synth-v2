"""
account_provisioning_service_v1 — Bitvavo account provisioning orchestration.

Responsibilities:
  - Validate mocked credentials
  - Create trading_account + encrypted credential + profile link atomically
  - Update profile onboarding state

Not responsible for:
  - Session validation (handled by HTTP layer / website_registration_v1)
  - DB connection lifecycle (caller owns transaction boundary)
  - Order placement or execution
  - Live trading activation

Safety:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  executor=none
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.account_provisioning.contracts_v1 import PlainBitvavoCredential
from src.account_provisioning.credential_crypto_v1 import compute_fingerprint, encrypt_credential
from src.account_provisioning.credential_repository_v1 import CREDENTIAL_KIND_API_KEY_SECRET
from src.account_provisioning.credential_validator_v1 import BitvavoCredentialValidator

_BITVAVO_VENUE = "bitvavo"
_ACCOUNT_MODE_PAPER = "paper"
_ACCOUNT_CONNECTION_READ_ONLY = "READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED"


@dataclass(frozen=True)
class AuthenticatedProfileIdentity:
    """Server-derived identity from validated session. Never client-supplied."""
    app_user_id: int
    app_profile_id: int
    profile_code: str


@dataclass(frozen=True)
class ProvisioningResult:
    ok: bool
    error_code: str | None = None
    profile_code: str | None = None
    account_connection_state: str | None = None
    landing_path: str | None = None
    refresh_pending: bool = False


def _generate_account_code(profile_code: str, venue: str) -> str:
    """Deterministic account code: {safe_profile}-{safe_venue}. Unique because profile_code is unique."""
    safe_profile = re.sub(r"[^a-z0-9]", "", profile_code.lower())[:20]
    safe_venue = re.sub(r"[^a-z0-9]", "", venue.lower())[:10]
    return f"{safe_profile}-{safe_venue}"


class AccountProvisioningService:
    """
    Orchestrates atomic Bitvavo account provisioning.

    Caller owns the transaction boundary:
      - Pass account_repo and cred_repo initialized with the same connection.
      - Commit the connection on result.ok=True.
      - Roll back the connection on result.ok=False or exception.
      - This service never commits or rolls back.
    """

    def __init__(
        self,
        *,
        credential_validator: BitvavoCredentialValidator,
        master_key_version: str,
        master_key_bytes: bytes,
    ) -> None:
        self._credential_validator = credential_validator
        self._master_key_version = master_key_version
        self._master_key_bytes = master_key_bytes

    def provision_bitvavo_account(
        self,
        *,
        identity: AuthenticatedProfileIdentity,
        api_key: str,
        api_secret: str,
        withdrawal_disabled_confirmed: bool,
        account_repo: Any,
        cred_repo: Any,
        now_utc: datetime,
    ) -> ProvisioningResult:
        """
        Steps:
          1. Require withdrawal confirmation.
          2. Check for existing primary link — reject if already connected.
          3. Validate credentials (mocked in Batch 2).
          4. Create trading_account (paper, disabled for live, no write permission).
          5. Encrypt and store credential.
          6. Create primary profile link.
          7. Update profile onboarding state.

        Returns ProvisioningResult. Does not commit.
        """
        if not withdrawal_disabled_confirmed:
            return ProvisioningResult(ok=False, error_code="WITHDRAWAL_CONFIRMATION_REQUIRED")

        existing_link = account_repo.find_active_primary_link(identity.app_profile_id)
        if existing_link is not None:
            return ProvisioningResult(
                ok=False,
                error_code="ACCOUNT_ALREADY_CONNECTED",
                profile_code=identity.profile_code,
                landing_path=f"/synth/accounts/{identity.profile_code}/profit-plan.html",
            )

        credential = PlainBitvavoCredential(
            venue=_BITVAVO_VENUE,
            api_key=api_key,
            api_secret=api_secret,
        )
        validation = self._credential_validator.validate(credential)

        if not validation.success:
            return ProvisioningResult(
                ok=False,
                error_code=validation.safe_error_code or "CREDENTIAL_VALIDATION_FAILED",
            )

        account_code = _generate_account_code(identity.profile_code, _BITVAVO_VENUE)
        trading_account_id = account_repo.create_trading_account(
            account_code=account_code,
            venue=_BITVAVO_VENUE,
            account_mode=_ACCOUNT_MODE_PAPER,
            enabled=1,
            live_trading_enabled=0,
            created_ts_utc=now_utc,
        )

        envelope = encrypt_credential(
            credential,
            trading_account_id,
            self._master_key_version,
            self._master_key_bytes,
        )
        fingerprint = compute_fingerprint(_BITVAVO_VENUE, api_key, self._master_key_bytes)
        cred_repo.insert_active_credential(
            trading_account_id=trading_account_id,
            venue=_BITVAVO_VENUE,
            credential_kind=CREDENTIAL_KIND_API_KEY_SECRET,
            encrypted_envelope=envelope.to_json(),
            encryption_algorithm=envelope.alg,
            key_version=envelope.kv,
            credential_fingerprint=fingerprint,
            now_utc=now_utc,
        )

        account_repo.create_profile_link(
            app_profile_id=identity.app_profile_id,
            trading_account_id=trading_account_id,
            is_primary=True,
            created_ts_utc=now_utc,
        )

        account_repo.update_onboarding_state(
            app_profile_id=identity.app_profile_id,
            onboarding_state=_ACCOUNT_CONNECTION_READ_ONLY,
        )

        return ProvisioningResult(
            ok=True,
            profile_code=identity.profile_code,
            account_connection_state=_ACCOUNT_CONNECTION_READ_ONLY,
            landing_path=f"/synth/accounts/{identity.profile_code}/profit-plan.html",
            refresh_pending=True,
        )
