from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

SUPPORTED_VENUES: frozenset[str] = frozenset({"bitvavo"})
CREDENTIAL_SCHEMA_VERSION = "1"
ENCRYPTION_ALGORITHM = "AESGCM-256"


class CredentialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    ROTATED = "ROTATED"
    INVALID = "INVALID"


class CredentialValidationState(str, Enum):
    UNVALIDATED = "UNVALIDATED"
    VALID_READ_ONLY = "VALID_READ_ONLY"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"


@dataclass(frozen=True, repr=False)
class PlainBitvavoCredential:
    """
    Plaintext exchange credential. Never log, serialize, or repr this object.
    Intentionally repr=False; __repr__ redacts secrets.
    """

    venue: str
    api_key: str
    api_secret: str

    def __post_init__(self) -> None:
        if self.venue not in SUPPORTED_VENUES:
            raise ValueError(f"UNSUPPORTED_VENUE: {self.venue!r}")
        if not (self.api_key or "").strip():
            raise ValueError("BLANK_API_KEY")
        if not (self.api_secret or "").strip():
            raise ValueError("BLANK_API_SECRET")

    def __repr__(self) -> str:
        return f"PlainBitvavoCredential(venue={self.venue!r}, api_key=<redacted>, api_secret=<redacted>)"

    def __str__(self) -> str:
        return self.__repr__()


@dataclass(frozen=True)
class EncryptedCredentialEnvelope:
    """
    Serializable envelope. Contains ciphertext, nonce, and metadata.
    No plaintext credentials.
    """

    alg: str            # encryption algorithm, e.g. AESGCM-256
    kv: str             # key version, e.g. v1
    sv: str             # credential schema version
    venue: str
    trading_account_id: int
    nonce_b64: str      # base64url-encoded 12-byte nonce
    ciphertext_b64: str # base64url-encoded ciphertext + auth tag

    def to_json(self) -> str:
        return json.dumps(
            {
                "alg": self.alg,
                "kv": self.kv,
                "sv": self.sv,
                "venue": self.venue,
                "tid": self.trading_account_id,
                "nonce": self.nonce_b64,
                "ct": self.ciphertext_b64,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, data: str) -> EncryptedCredentialEnvelope:
        d = json.loads(data)
        return cls(
            alg=d["alg"],
            kv=d["kv"],
            sv=d["sv"],
            venue=d["venue"],
            trading_account_id=int(d["tid"]),
            nonce_b64=d["nonce"],
            ciphertext_b64=d["ct"],
        )


@dataclass(frozen=True)
class StoredAccountCredential:
    """Repository output. Contains encrypted envelope only — no plaintext."""

    trading_account_credential_id: int
    trading_account_id: int
    venue: str
    credential_kind: str
    encrypted_envelope: str       # JSON string — no plaintext
    encryption_algorithm: str
    key_version: str
    credential_fingerprint: str
    credential_status: CredentialStatus
    validation_state: CredentialValidationState
    created_ts_utc: datetime
    validated_ts_utc: datetime | None
    rotated_ts_utc: datetime | None
    revoked_ts_utc: datetime | None
