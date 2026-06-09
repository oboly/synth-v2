from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.account_provisioning.contracts_v1 import (
    ENCRYPTION_ALGORITHM,
    PlainBitvavoCredential,
    EncryptedCredentialEnvelope,
)
from src.account_provisioning.credential_crypto_v1 import (
    MASTER_KEY_ENV_VAR,
    compute_fingerprint,
    decrypt_credential,
    encrypt_credential,
    generate_test_master_key,
    load_master_key_from_env,
    parse_master_key,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _key() -> tuple[str, bytes]:
    raw = generate_test_master_key()
    return parse_master_key(raw)


def _cred(
    venue: str = "bitvavo",
    api_key: str = "test-api-key-abc123",
    api_secret: str = "test-api-secret-xyz789",
) -> PlainBitvavoCredential:
    return PlainBitvavoCredential(venue=venue, api_key=api_key, api_secret=api_secret)


def _encrypt(
    cred: PlainBitvavoCredential | None = None,
    trading_account_id: int = 42,
    key_bytes: bytes | None = None,
    key_version: str = "v1",
) -> EncryptedCredentialEnvelope:
    if cred is None:
        cred = _cred()
    if key_bytes is None:
        _, key_bytes = _key()
    return encrypt_credential(cred, trading_account_id, key_version, key_bytes)


# ---------------------------------------------------------------------------
# Master key parsing
# ---------------------------------------------------------------------------

def test_parse_master_key_valid() -> None:
    key_bytes = os.urandom(32)
    raw = "v1:" + base64.urlsafe_b64encode(key_bytes).decode("ascii")
    version, parsed = parse_master_key(raw)
    assert version == "v1"
    assert parsed == key_bytes


def test_parse_master_key_missing_colon_rejected() -> None:
    try:
        parse_master_key("v1AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "INVALID_MASTER_KEY_FORMAT" in str(e)


def test_parse_master_key_empty_rejected() -> None:
    try:
        parse_master_key("")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "INVALID_MASTER_KEY_FORMAT" in str(e)


def test_parse_master_key_unsupported_version_rejected() -> None:
    key_bytes = os.urandom(32)
    raw = "v2:" + base64.urlsafe_b64encode(key_bytes).decode("ascii")
    try:
        parse_master_key(raw)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "UNSUPPORTED_KEY_VERSION" in str(e)


def test_parse_master_key_wrong_length_rejected() -> None:
    raw = "v1:" + base64.urlsafe_b64encode(b"short-key").decode("ascii")
    try:
        parse_master_key(raw)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "INVALID_MASTER_KEY_LENGTH" in str(e)


def test_parse_master_key_bad_base64_rejected() -> None:
    try:
        parse_master_key("v1:not!valid!base64!!!")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "INVALID_MASTER_KEY" in str(e)


def test_parse_master_key_error_does_not_include_key_value() -> None:
    key_secret = "v1:super-secret-raw-key-value"
    try:
        parse_master_key(key_secret)
    except ValueError as e:
        msg = str(e)
        assert "super-secret-raw-key-value" not in msg


def test_load_master_key_from_env_valid() -> None:
    raw = generate_test_master_key()
    version, key_bytes = load_master_key_from_env(env={MASTER_KEY_ENV_VAR: raw})
    assert version == "v1"
    assert len(key_bytes) == 32


def test_load_master_key_from_env_missing_raises() -> None:
    try:
        load_master_key_from_env(env={})
        assert False, "expected ValueError"
    except ValueError as e:
        assert "MISSING_MASTER_KEY" in str(e)


def test_load_master_key_error_does_not_include_env_var_value() -> None:
    try:
        load_master_key_from_env(env={MASTER_KEY_ENV_VAR: "v1:bad"})
    except ValueError as e:
        assert "v1:bad" not in str(e)


# ---------------------------------------------------------------------------
# Encrypt / decrypt round trip
# ---------------------------------------------------------------------------

def test_encrypt_decrypt_roundtrip() -> None:
    _, key_bytes = _key()
    cred = _cred()
    envelope = _encrypt(cred, key_bytes=key_bytes)
    recovered = decrypt_credential(envelope, key_bytes)
    assert recovered.venue == cred.venue
    assert recovered.api_key == cred.api_key
    assert recovered.api_secret == cred.api_secret


def test_same_plaintext_produces_different_ciphertext() -> None:
    _, key_bytes = _key()
    cred = _cred()
    env1 = _encrypt(cred, key_bytes=key_bytes)
    env2 = _encrypt(cred, key_bytes=key_bytes)
    assert env1.nonce_b64 != env2.nonce_b64
    assert env1.ciphertext_b64 != env2.ciphertext_b64


def test_tampered_ciphertext_rejected() -> None:
    _, key_bytes = _key()
    envelope = _encrypt(key_bytes=key_bytes)
    ct_bytes = bytearray(base64.urlsafe_b64decode(envelope.ciphertext_b64 + "=="))
    ct_bytes[0] ^= 0xFF
    bad_envelope = EncryptedCredentialEnvelope(
        alg=envelope.alg, kv=envelope.kv, sv=envelope.sv, venue=envelope.venue,
        trading_account_id=envelope.trading_account_id,
        nonce_b64=envelope.nonce_b64,
        ciphertext_b64=base64.urlsafe_b64encode(bytes(ct_bytes)).decode("ascii"),
    )
    try:
        decrypt_credential(bad_envelope, key_bytes)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "CREDENTIAL_DECRYPTION_FAILED" in str(e)


def test_modified_nonce_rejected() -> None:
    _, key_bytes = _key()
    envelope = _encrypt(key_bytes=key_bytes)
    nonce_bytes = bytearray(base64.urlsafe_b64decode(envelope.nonce_b64 + "=="))
    nonce_bytes[0] ^= 0x01
    bad_envelope = EncryptedCredentialEnvelope(
        alg=envelope.alg, kv=envelope.kv, sv=envelope.sv, venue=envelope.venue,
        trading_account_id=envelope.trading_account_id,
        nonce_b64=base64.urlsafe_b64encode(bytes(nonce_bytes)).decode("ascii"),
        ciphertext_b64=envelope.ciphertext_b64,
    )
    try:
        decrypt_credential(bad_envelope, key_bytes)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "CREDENTIAL_DECRYPTION_FAILED" in str(e)


def test_modified_associated_data_rejected() -> None:
    """Changing trading_account_id changes AAD — decryption must fail."""
    _, key_bytes = _key()
    envelope = _encrypt(trading_account_id=42, key_bytes=key_bytes)
    bad_envelope = EncryptedCredentialEnvelope(
        alg=envelope.alg, kv=envelope.kv, sv=envelope.sv, venue=envelope.venue,
        trading_account_id=999,  # different account
        nonce_b64=envelope.nonce_b64,
        ciphertext_b64=envelope.ciphertext_b64,
    )
    try:
        decrypt_credential(bad_envelope, key_bytes)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "CREDENTIAL_DECRYPTION_FAILED" in str(e)


def test_wrong_master_key_rejected() -> None:
    _, key1 = _key()
    _, key2 = _key()
    assert key1 != key2
    envelope = _encrypt(key_bytes=key1)
    try:
        decrypt_credential(envelope, key2)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "CREDENTIAL_DECRYPTION_FAILED" in str(e)


def test_malformed_master_key_rejected() -> None:
    try:
        parse_master_key("garbage")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_key_version_mismatch_rejected() -> None:
    _, key_bytes = _key()
    envelope = _encrypt(key_bytes=key_bytes)
    bad_envelope = EncryptedCredentialEnvelope(
        alg=envelope.alg, kv="v99", sv=envelope.sv, venue=envelope.venue,
        trading_account_id=envelope.trading_account_id,
        nonce_b64=envelope.nonce_b64,
        ciphertext_b64=envelope.ciphertext_b64,
    )
    try:
        decrypt_credential(bad_envelope, key_bytes)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "UNSUPPORTED_KEY_VERSION" in str(e)


def test_unicode_key_and_secret_roundtrip() -> None:
    _, key_bytes = _key()
    cred = PlainBitvavoCredential(
        venue="bitvavo",
        api_key="api_key_with_unicode_éàü",
        api_secret="secret_with_unicode_中文キー",
    )
    envelope = encrypt_credential(cred, 1, "v1", key_bytes)
    recovered = decrypt_credential(envelope, key_bytes)
    assert recovered.api_key == cred.api_key
    assert recovered.api_secret == cred.api_secret


# ---------------------------------------------------------------------------
# Envelope contents — no plaintext
# ---------------------------------------------------------------------------

def test_no_plaintext_in_encrypted_envelope() -> None:
    _, key_bytes = _key()
    cred = _cred(api_key="UNIQUE_API_KEY_SENTINEL", api_secret="UNIQUE_SECRET_SENTINEL")
    envelope = _encrypt(cred, key_bytes=key_bytes)
    json_str = envelope.to_json()
    assert "UNIQUE_API_KEY_SENTINEL" not in json_str
    assert "UNIQUE_SECRET_SENTINEL" not in json_str


def test_no_plaintext_in_repr() -> None:
    cred = _cred(api_key="REPR_KEY_SENTINEL", api_secret="REPR_SECRET_SENTINEL")
    r = repr(cred)
    assert "REPR_KEY_SENTINEL" not in r
    assert "REPR_SECRET_SENTINEL" not in r
    assert "<redacted>" in r


def test_no_plaintext_in_str() -> None:
    cred = _cred(api_key="STR_KEY_SENTINEL", api_secret="STR_SECRET_SENTINEL")
    s = str(cred)
    assert "STR_KEY_SENTINEL" not in s
    assert "STR_SECRET_SENTINEL" not in s


def test_decrypt_error_does_not_expose_secret() -> None:
    _, key1 = _key()
    _, key2 = _key()
    cred = _cred(api_secret="DO_NOT_EXPOSE_THIS_SECRET")
    envelope = _encrypt(cred, key_bytes=key1)
    try:
        decrypt_credential(envelope, key2)
    except ValueError as e:
        assert "DO_NOT_EXPOSE_THIS_SECRET" not in str(e)
    except Exception as e:
        assert "DO_NOT_EXPOSE_THIS_SECRET" not in str(e)


def test_envelope_json_roundtrip() -> None:
    _, key_bytes = _key()
    envelope = _encrypt(key_bytes=key_bytes)
    j = envelope.to_json()
    restored = EncryptedCredentialEnvelope.from_json(j)
    assert restored == envelope


# ---------------------------------------------------------------------------
# PlainBitvavoCredential validation
# ---------------------------------------------------------------------------

def test_unsupported_venue_rejected() -> None:
    try:
        PlainBitvavoCredential(venue="unsupported", api_key="k", api_secret="s")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "UNSUPPORTED_VENUE" in str(e)


def test_blank_api_key_rejected() -> None:
    try:
        PlainBitvavoCredential(venue="bitvavo", api_key="  ", api_secret="s")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "BLANK_API_KEY" in str(e)


def test_blank_api_secret_rejected() -> None:
    try:
        PlainBitvavoCredential(venue="bitvavo", api_key="k", api_secret="")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "BLANK_API_SECRET" in str(e)


def test_credential_immutable() -> None:
    cred = _cred()
    try:
        cred.api_key = "mutated"  # type: ignore[misc]
        assert False, "expected FrozenInstanceError"
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------

def test_fingerprint_deterministic() -> None:
    _, key_bytes = _key()
    fp1 = compute_fingerprint("bitvavo", "same-api-key", key_bytes)
    fp2 = compute_fingerprint("bitvavo", "same-api-key", key_bytes)
    assert fp1 == fp2


def test_different_api_key_changes_fingerprint() -> None:
    _, key_bytes = _key()
    fp1 = compute_fingerprint("bitvavo", "key-A", key_bytes)
    fp2 = compute_fingerprint("bitvavo", "key-B", key_bytes)
    assert fp1 != fp2


def test_different_venue_changes_fingerprint() -> None:
    _, key_bytes = _key()
    fp1 = compute_fingerprint("bitvavo", "same-key", key_bytes)
    fp2 = compute_fingerprint("other-venue", "same-key", key_bytes)
    assert fp1 != fp2


def test_fingerprint_does_not_contain_api_key_text() -> None:
    _, key_bytes = _key()
    unique_key = "FINGERPRINT_SENTINEL_KEY_VALUE"
    fp = compute_fingerprint("bitvavo", unique_key, key_bytes)
    assert unique_key not in fp


def test_different_master_key_changes_fingerprint() -> None:
    _, kb1 = _key()
    _, kb2 = _key()
    fp1 = compute_fingerprint("bitvavo", "same-key", kb1)
    fp2 = compute_fingerprint("bitvavo", "same-key", kb2)
    assert fp1 != fp2


def test_fingerprint_is_hex_string() -> None:
    _, key_bytes = _key()
    fp = compute_fingerprint("bitvavo", "any-key", key_bytes)
    assert len(fp) == 64
    int(fp, 16)  # raises if not hex


# ---------------------------------------------------------------------------
# Architecture / safety
# ---------------------------------------------------------------------------

def test_no_bitvavo_broker_call_in_crypto_module() -> None:
    source = Path("src/account_provisioning/credential_crypto_v1.py").read_text()
    assert "BitvavoClient" not in source
    assert "get_balance" not in source
    assert "BITVAVO_API_KEY" not in source
    assert "SYNTH_BROKER" not in source


def test_no_executor_in_crypto_module() -> None:
    source = Path("src/account_provisioning/credential_crypto_v1.py").read_text()
    assert "executor" not in source.lower()
    assert "place_order" not in source
    assert "cancel_order" not in source


if __name__ == "__main__":
    tests = [
        test_parse_master_key_valid,
        test_parse_master_key_missing_colon_rejected,
        test_parse_master_key_empty_rejected,
        test_parse_master_key_unsupported_version_rejected,
        test_parse_master_key_wrong_length_rejected,
        test_parse_master_key_bad_base64_rejected,
        test_parse_master_key_error_does_not_include_key_value,
        test_load_master_key_from_env_valid,
        test_load_master_key_from_env_missing_raises,
        test_load_master_key_error_does_not_include_env_var_value,
        test_encrypt_decrypt_roundtrip,
        test_same_plaintext_produces_different_ciphertext,
        test_tampered_ciphertext_rejected,
        test_modified_nonce_rejected,
        test_modified_associated_data_rejected,
        test_wrong_master_key_rejected,
        test_malformed_master_key_rejected,
        test_key_version_mismatch_rejected,
        test_unicode_key_and_secret_roundtrip,
        test_no_plaintext_in_encrypted_envelope,
        test_no_plaintext_in_repr,
        test_no_plaintext_in_str,
        test_decrypt_error_does_not_expose_secret,
        test_envelope_json_roundtrip,
        test_unsupported_venue_rejected,
        test_blank_api_key_rejected,
        test_blank_api_secret_rejected,
        test_credential_immutable,
        test_fingerprint_deterministic,
        test_different_api_key_changes_fingerprint,
        test_different_venue_changes_fingerprint,
        test_fingerprint_does_not_contain_api_key_text,
        test_different_master_key_changes_fingerprint,
        test_fingerprint_is_hex_string,
        test_no_bitvavo_broker_call_in_crypto_module,
        test_no_executor_in_crypto_module,
    ]
    for t in tests:
        t()
    print("ok")
