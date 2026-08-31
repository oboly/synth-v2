from __future__ import annotations

import base64
import errno
import hashlib
import hmac
import json
import os
import stat

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.account_provisioning.contracts_v1 import (
    CREDENTIAL_SCHEMA_VERSION,
    ENCRYPTION_ALGORITHM,
    EncryptedCredentialEnvelope,
    PlainBitvavoCredential,
)

MASTER_KEY_ENV_VAR = "SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY"
DEFAULT_MASTER_KEY_FILE = "/etc/synth/account-credential-master-key"
_SUPPORTED_KEY_VERSIONS = frozenset({"v1"})
_FINGERPRINT_DOMAIN = b"synth-fingerprint-key-v1"
_AAD_PREFIX = b"synth-credential-aad-v1"
_MAX_MASTER_KEY_FILE_BYTES = 512


def parse_master_key(raw: str) -> tuple[str, bytes]:
    """
    Parse a versioned master key string.

    Format: ``v1:<base64url-encoded-32-byte-key>``

    Returns (version, key_bytes). Fails closed on any error.
    Never logs or includes the key value in error messages.
    """
    if not raw or ":" not in raw:
        raise ValueError("INVALID_MASTER_KEY_FORMAT")
    version, encoded = raw.split(":", 1)
    if version not in _SUPPORTED_KEY_VERSIONS:
        raise ValueError(f"UNSUPPORTED_KEY_VERSION: {version!r}")
    try:
        # Add padding — handles both padded and unpadded base64url
        key_bytes = base64.urlsafe_b64decode(encoded + "==")
    except Exception:
        raise ValueError("INVALID_MASTER_KEY_BASE64")
    if len(key_bytes) != 32:
        raise ValueError(f"INVALID_MASTER_KEY_LENGTH: expected 32, got {len(key_bytes)}")
    return version, key_bytes


def load_master_key_from_env(
    env_var: str = MASTER_KEY_ENV_VAR,
    *,
    env: dict[str, str] | None = None,
    file_path: str = DEFAULT_MASTER_KEY_FILE,
) -> tuple[str, bytes]:
    """
    Load and parse the credential master key.

    Source precedence is explicit and deterministic:

    1. ``env_var`` when present in the supplied/current process environment.
       This remains the test/emergency override seam.
    2. The canonical host-local file (``DEFAULT_MASTER_KEY_FILE`` by default).

    The file fallback removes the need for normal production callers to
    manually export the master key into ephemeral shell state. The file is
    opened once with ``O_NOFOLLOW`` and all type/owner/mode/size checks are
    performed with ``fstat`` on that same descriptor before the bounded read,
    avoiding path-check/path-read races.

    Errors never include key material.
    """
    source = env if env is not None else os.environ
    raw = source.get(env_var, "")
    if raw:
        return parse_master_key(raw)
    return _load_master_key_from_host_file(file_path)


def _load_master_key_from_host_file(file_path: str) -> tuple[str, bytes]:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        fd = os.open(file_path, flags)
    except FileNotFoundError:
        raise ValueError(
            "MISSING_MASTER_KEY: no environment override and host-local key file missing"
        ) from None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError("MASTER_KEY_FILE_NOT_REGULAR") from None
        raise ValueError("MASTER_KEY_FILE_OPEN_FAILED") from None

    try:
        try:
            metadata = os.fstat(fd)
        except OSError:
            raise ValueError("MASTER_KEY_FILE_STAT_FAILED") from None

        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("MASTER_KEY_FILE_NOT_REGULAR")

        allowed_owner_uids = {0, os.geteuid()}
        if metadata.st_uid not in allowed_owner_uids:
            raise ValueError("MASTER_KEY_FILE_OWNER_INVALID")

        mode = stat.S_IMODE(metadata.st_mode)
        if not (mode & stat.S_IRUSR):
            raise ValueError("MASTER_KEY_FILE_OWNER_READ_REQUIRED")
        # Allow root/user owner read/write and optional group read (0640), but
        # no world access, group write/execute, or executable secret file.
        if mode & 0o007 or mode & 0o030 or mode & 0o100:
            raise ValueError("INSECURE_MASTER_KEY_FILE_PERMISSIONS")

        if metadata.st_size <= 0 or metadata.st_size > _MAX_MASTER_KEY_FILE_BYTES:
            raise ValueError("INVALID_MASTER_KEY_FILE_SIZE")

        try:
            payload = os.read(fd, _MAX_MASTER_KEY_FILE_BYTES + 1)
        except OSError:
            raise ValueError("MASTER_KEY_FILE_READ_FAILED") from None
        if len(payload) > _MAX_MASTER_KEY_FILE_BYTES:
            raise ValueError("INVALID_MASTER_KEY_FILE_SIZE")
        try:
            raw = payload.decode("utf-8").strip()
        except UnicodeError:
            raise ValueError("MASTER_KEY_FILE_READ_FAILED") from None
    finally:
        try:
            os.close(fd)
        except OSError:
            pass

    if not raw or "\n" in raw or "\r" in raw:
        raise ValueError("INVALID_MASTER_KEY_FILE_CONTENT")
    return parse_master_key(raw)


def generate_test_master_key() -> str:
    """
    Generate a random master key string suitable for use in tests.
    Must not be used in production.
    """
    return "v1:" + base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def _derive_fingerprint_key(master_key_bytes: bytes) -> bytes:
    """Derive a domain-separated fingerprint key from the master key."""
    return hmac.new(master_key_bytes, _FINGERPRINT_DOMAIN, hashlib.sha256).digest()


def compute_fingerprint(
    venue: str,
    api_key: str,
    master_key_bytes: bytes,
) -> str:
    """
    Compute a deterministic HMAC-SHA256 fingerprint for deduplication.

    Input: normalized venue + api_key.
    Does not include the API secret.
    Returns a 64-char hex string (256-bit).
    """
    fingerprint_key = _derive_fingerprint_key(master_key_bytes)
    msg = f"{venue}\n{api_key}".encode("utf-8")
    return hmac.new(fingerprint_key, msg, hashlib.sha256).hexdigest()


def _make_aad(venue: str, trading_account_id: int) -> bytes:
    """
    Build authenticated additional data for AES-GCM.

    Binds the ciphertext to the specific venue and trading_account_id.
    Decryption will fail if either value changes.
    """
    return _AAD_PREFIX + f"\n{venue}\n{trading_account_id}".encode("utf-8")


def encrypt_credential(
    credential: PlainBitvavoCredential,
    trading_account_id: int,
    key_version: str,
    master_key_bytes: bytes,
) -> EncryptedCredentialEnvelope:
    """
    Encrypt api_key + api_secret into one authenticated envelope.

    Nonce is 12 random bytes (unique per call).
    AAD binds ciphertext to venue + trading_account_id.
    """
    plaintext = json.dumps(
        {"api_key": credential.api_key, "api_secret": credential.api_secret},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    nonce = os.urandom(12)
    aad = _make_aad(credential.venue, trading_account_id)
    aesgcm = AESGCM(master_key_bytes)
    ciphertext = aesgcm.encrypt(nonce, plaintext, aad)

    return EncryptedCredentialEnvelope(
        alg=ENCRYPTION_ALGORITHM,
        kv=key_version,
        sv=CREDENTIAL_SCHEMA_VERSION,
        venue=credential.venue,
        trading_account_id=trading_account_id,
        nonce_b64=base64.urlsafe_b64encode(nonce).decode("ascii"),
        ciphertext_b64=base64.urlsafe_b64encode(ciphertext).decode("ascii"),
    )


def decrypt_credential(
    envelope: EncryptedCredentialEnvelope,
    master_key_bytes: bytes,
) -> PlainBitvavoCredential:
    """
    Decrypt an envelope and return the plaintext credential.

    Raises ValueError on any failure (tampered data, wrong key, wrong account,
    wrong venue). Error messages never include plaintext values.
    """
    if envelope.alg != ENCRYPTION_ALGORITHM:
        raise ValueError(f"UNSUPPORTED_ENCRYPTION_ALGORITHM: {envelope.alg!r}")
    if envelope.kv not in _SUPPORTED_KEY_VERSIONS:
        raise ValueError(f"UNSUPPORTED_KEY_VERSION: {envelope.kv!r}")

    try:
        nonce = base64.urlsafe_b64decode(envelope.nonce_b64 + "==")
        ciphertext = base64.urlsafe_b64decode(envelope.ciphertext_b64 + "==")
    except Exception:
        raise ValueError("CREDENTIAL_ENVELOPE_DECODE_ERROR")

    aad = _make_aad(envelope.venue, envelope.trading_account_id)
    aesgcm = AESGCM(master_key_bytes)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, aad)
    except Exception:
        # Suppress original exception — do not expose bytes or key material
        raise ValueError("CREDENTIAL_DECRYPTION_FAILED") from None

    try:
        d = json.loads(plaintext.decode("utf-8"))
        api_key = d["api_key"]
        api_secret = d["api_secret"]
    except Exception:
        raise ValueError("CREDENTIAL_PLAINTEXT_DECODE_ERROR") from None

    return PlainBitvavoCredential(
        venue=envelope.venue,
        api_key=api_key,
        api_secret=api_secret,
    )
