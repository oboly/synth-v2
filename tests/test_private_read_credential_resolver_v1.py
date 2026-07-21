from __future__ import annotations

import os
import base64
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.account.private_read_credential_resolver_v1 import (
    PrivateReadCredentialResolutionError,
    resolve_private_read_bitvavo_client_from_env,
    resolve_private_read_credential,
)
from src.account_provisioning.contracts_v1 import PlainBitvavoCredential
from src.account_provisioning.credential_crypto_v1 import (
    compute_fingerprint,
    encrypt_credential,
    generate_test_master_key,
    parse_master_key,
)


_NOW = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)


_SCHEMA = """
CREATE TABLE trading_account (
    trading_account_id INTEGER PRIMARY KEY,
    account_code TEXT NOT NULL,
    venue TEXT NOT NULL,
    account_mode TEXT NOT NULL DEFAULT 'paper',
    enabled INTEGER NOT NULL DEFAULT 1,
    live_trading_enabled INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE app_profile (
    app_profile_id INTEGER PRIMARY KEY,
    profile_code TEXT NOT NULL,
    display_timezone TEXT NOT NULL DEFAULT 'Europe/Amsterdam'
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
    credential_kind TEXT NOT NULL DEFAULT 'API_KEY_SECRET',
    encrypted_envelope TEXT NOT NULL,
    encryption_algorithm TEXT NOT NULL DEFAULT 'AESGCM-256',
    key_version TEXT NOT NULL,
    credential_fingerprint TEXT NOT NULL,
    credential_status TEXT NOT NULL DEFAULT 'ACTIVE',
    validation_state TEXT NOT NULL DEFAULT 'VALID_PRIVATE_READ',
    created_ts_utc TEXT NOT NULL,
    validated_ts_utc TEXT,
    rotated_ts_utc TEXT,
    revoked_ts_utc TEXT,
    credential_source TEXT NOT NULL DEFAULT 'db_encrypted',
    permission_scope TEXT NOT NULL DEFAULT 'READ_ONLY_PRIVATE',
    allowed_private_read INTEGER NOT NULL DEFAULT 1,
    allowed_order_write INTEGER NOT NULL DEFAULT 0,
    allowed_withdrawal INTEGER NOT NULL DEFAULT 0,
    last_validation_error_code TEXT
);
"""


def _fresh_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        """
        INSERT INTO trading_account (
            trading_account_id, account_code, venue, account_mode, enabled, live_trading_enabled
        ) VALUES (1, 'joost-read', 'bitvavo', 'paper', 1, 0)
        """
    )
    conn.execute(
        "INSERT INTO app_profile (app_profile_id, profile_code) VALUES (10, 'joost')"
    )
    conn.execute(
        """
        INSERT INTO app_profile_trading_account_link (
            link_id, app_profile_id, trading_account_id, link_status, is_primary
        ) VALUES (100, 10, 1, 'ACTIVE', 1)
        """
    )
    return conn


def _seed_credential(
    conn: sqlite3.Connection,
    *,
    trading_account_id: int = 1,
    venue: str = "bitvavo",
    api_key: str = "account-specific-key",
    api_secret: str = "account-specific-secret",
    key_version: str,
    master_key_bytes: bytes,
    encrypted_envelope: str | None = None,
    **overrides: object,
) -> int:
    if encrypted_envelope is None:
        plain = PlainBitvavoCredential(
            venue=venue,
            api_key=api_key,
            api_secret=api_secret,
        )
        envelope = encrypt_credential(
            plain,
            trading_account_id,
            key_version,
            master_key_bytes,
        )
        encrypted_envelope = envelope.to_json()
        encryption_algorithm = envelope.alg
    else:
        encryption_algorithm = "AESGCM-256"
    row = {
        "trading_account_id": trading_account_id,
        "venue": venue,
        "credential_kind": "API_KEY_SECRET",
        "encrypted_envelope": encrypted_envelope,
        "encryption_algorithm": encryption_algorithm,
        "key_version": key_version,
        "credential_fingerprint": compute_fingerprint(venue, api_key, master_key_bytes),
        "credential_status": "ACTIVE",
        "validation_state": "VALID_PRIVATE_READ",
        "created_ts_utc": _NOW.isoformat(sep=" "),
        "validated_ts_utc": _NOW.isoformat(sep=" "),
        "rotated_ts_utc": None,
        "revoked_ts_utc": None,
        "credential_source": "db_encrypted",
        "permission_scope": "READ_ONLY_PRIVATE",
        "allowed_private_read": 1,
        "allowed_order_write": 0,
        "allowed_withdrawal": 0,
        "last_validation_error_code": None,
    }
    row.update(overrides)
    cols = list(row)
    placeholders = ",".join(["?"] * len(cols))
    cur = conn.execute(
        f"INSERT INTO trading_account_credential ({','.join(cols)}) VALUES ({placeholders})",
        tuple(row[col] for col in cols),
    )
    return int(cur.lastrowid)


def _key() -> tuple[str, bytes]:
    return parse_master_key(generate_test_master_key())


def _assert_code(exc: pytest.ExceptionInfo[PrivateReadCredentialResolutionError], code: str) -> None:
    assert exc.value.code == code
    assert str(exc.value).startswith(code + ":")


def test_exact_account_resolves_exact_validated_read_only_credential() -> None:
    kv, kb = _key()
    conn = _fresh_db()
    row_id = _seed_credential(conn, key_version=kv, master_key_bytes=kb)

    identity, resolved = resolve_private_read_credential(
        conn,
        trading_account_id=1,
        venue="bitvavo",
        master_key_bytes=kb,
    )

    assert identity.trading_account_id == 1
    assert identity.account_code == "joost-read"
    assert resolved.profile.trading_account_credential_id == row_id
    assert resolved.profile.permission_scope == "READ_ONLY_PRIVATE"
    assert resolved.credential.api_key == "account-specific-key"


def test_account_code_ambiguity_rejected() -> None:
    kv, kb = _key()
    conn = _fresh_db()
    conn.execute(
        """
        INSERT INTO trading_account (
            trading_account_id, account_code, venue, account_mode, enabled, live_trading_enabled
        ) VALUES (2, 'joost-read', 'bitvavo', 'paper', 1, 0)
        """
    )
    _seed_credential(conn, key_version=kv, master_key_bytes=kb)

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn,
            account_code="joost-read",
            venue="bitvavo",
            master_key_bytes=kb,
        )

    _assert_code(exc, "ACCOUNT_CODE_AMBIGUOUS")


def test_missing_binding_rejected() -> None:
    _kv, kb = _key()
    conn = _fresh_db()

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn,
            trading_account_id=1,
            venue="bitvavo",
            master_key_bytes=kb,
        )

    _assert_code(exc, "NO_CREDENTIAL_BINDING")


def test_multiple_active_binding_rejected() -> None:
    kv, kb = _key()
    conn = _fresh_db()
    _seed_credential(conn, key_version=kv, master_key_bytes=kb, api_key="one")
    _seed_credential(conn, key_version=kv, master_key_bytes=kb, api_key="two")

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn,
            trading_account_id=1,
            venue="bitvavo",
            master_key_bytes=kb,
        )

    _assert_code(exc, "MULTIPLE_ACTIVE_MATCHING_CREDENTIALS")


def test_disabled_account_rejected() -> None:
    kv, kb = _key()
    conn = _fresh_db()
    conn.execute("UPDATE trading_account SET enabled = 0 WHERE trading_account_id = 1")
    _seed_credential(conn, key_version=kv, master_key_bytes=kb)

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn,
            trading_account_id=1,
            venue="bitvavo",
            master_key_bytes=kb,
        )

    _assert_code(exc, "ACCOUNT_DISABLED")


def test_venue_mismatch_rejected() -> None:
    _kv, kb = _key()
    conn = _fresh_db()

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn,
            trading_account_id=1,
            venue="kraken",
            master_key_bytes=kb,
        )

    _assert_code(exc, "VENUE_MISMATCH")


def test_wrong_credential_venue_is_not_a_match() -> None:
    kv, kb = _key()
    conn = _fresh_db()
    row_id = _seed_credential(conn, key_version=kv, master_key_bytes=kb)
    conn.execute(
        "UPDATE trading_account_credential SET venue = 'kraken' "
        "WHERE trading_account_credential_id = ?",
        (row_id,),
    )

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn,
            trading_account_id=1,
            venue="bitvavo",
            master_key_bytes=kb,
        )

    _assert_code(exc, "NO_CREDENTIAL_BINDING")


@pytest.mark.parametrize(
    "override",
    (
        {"credential_status": "REVOKED"},
        {"permission_scope": "TRADE_EXECUTION", "allowed_order_write": 1},
    ),
)
def test_inactive_or_wrong_scope_credential_is_not_a_match(
    override: dict[str, object],
) -> None:
    kv, kb = _key()
    conn = _fresh_db()
    _seed_credential(conn, key_version=kv, master_key_bytes=kb, **override)

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn,
            trading_account_id=1,
            venue="bitvavo",
            master_key_bytes=kb,
        )

    _assert_code(exc, "NO_CREDENTIAL_BINDING")


@pytest.mark.parametrize(
    ("override", "code"),
    (
        ({"credential_source": "legacy_profile_env_deprecated"}, "LEGACY_SOURCE_NOT_EXPLICITLY_ALLOWED"),
        ({"validation_state": "MYSTERY"}, "UNKNOWN_VALIDATION_STATE"),
        ({"allowed_private_read": 0}, "MISSING_REQUIRED_PRIVATE_READ_SCOPE"),
        ({"allowed_order_write": 1}, "ORDER_WRITE_CAPABILITY_IN_READ_ONLY_CONTEXT"),
        ({"allowed_withdrawal": 1}, "WITHDRAWAL_CAPABILITY_NOT_ALLOWED"),
        ({"validated_ts_utc": None}, "CREDENTIAL_VALIDATION_TIMESTAMP_MISSING"),
    ),
)
def test_metadata_fail_closed_rules(override: dict[str, object], code: str) -> None:
    kv, kb = _key()
    conn = _fresh_db()
    _seed_credential(conn, key_version=kv, master_key_bytes=kb, **override)

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn,
            trading_account_id=1,
            venue="bitvavo",
            master_key_bytes=kb,
        )

    _assert_code(exc, code)


def test_missing_master_key_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    kv, kb = _key()
    conn = _fresh_db()
    _seed_credential(conn, key_version=kv, master_key_bytes=kb)
    monkeypatch.delenv("SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY", raising=False)

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_bitvavo_client_from_env(
            conn,
            trading_account_id=1,
            venue="bitvavo",
        )

    _assert_code(exc, "MISSING_MASTER_KEY")


def test_decryption_failure_rejected() -> None:
    kv, kb = _key()
    _wrong_kv, wrong_kb = _key()
    conn = _fresh_db()
    _seed_credential(conn, key_version=kv, master_key_bytes=kb)

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn,
            trading_account_id=1,
            venue="bitvavo",
            master_key_bytes=wrong_kb,
        )

    _assert_code(exc, "CREDENTIAL_DECRYPTION_FAILED")


@pytest.mark.parametrize(
    ("envelope_override", "row_override", "code"),
    (
        ({"tid": 2}, {}, "CREDENTIAL_ENVELOPE_ACCOUNT_MISMATCH"),
        ({"venue": "kraken"}, {}, "CREDENTIAL_ENVELOPE_VENUE_MISMATCH"),
        ({"alg": "UNKNOWN"}, {}, "CREDENTIAL_ENCRYPTION_ALGORITHM_MISMATCH"),
        ({"kv": "v2"}, {}, "CREDENTIAL_KEY_VERSION_MISMATCH"),
        ({"sv": "2"}, {}, "CREDENTIAL_SCHEMA_VERSION_MISMATCH"),
        ({}, {"encryption_algorithm": "UNKNOWN"}, "CREDENTIAL_ENCRYPTION_ALGORITHM_MISMATCH"),
        ({}, {"key_version": "v2"}, "CREDENTIAL_KEY_VERSION_MISMATCH"),
        ({}, {"credential_kind": "UNKNOWN"}, "CREDENTIAL_KIND_MISMATCH"),
        ({}, {"credential_fingerprint": "f" * 64}, "CREDENTIAL_FINGERPRINT_MISMATCH"),
    ),
)
def test_encrypted_credential_metadata_mismatch_rejected(
    envelope_override: dict[str, object],
    row_override: dict[str, object],
    code: str,
) -> None:
    kv, kb = _key()
    plain = PlainBitvavoCredential(
        venue="bitvavo",
        api_key="metadata-key",
        api_secret="metadata-secret",
    )
    envelope_data = json.loads(encrypt_credential(plain, 1, kv, kb).to_json())
    envelope_data.update(envelope_override)
    conn = _fresh_db()
    stored_key_version = str(row_override.get("key_version", kv))
    stored_row_override = {
        key: value for key, value in row_override.items() if key != "key_version"
    }
    _seed_credential(
        conn,
        key_version=stored_key_version,
        master_key_bytes=kb,
        encrypted_envelope=json.dumps(envelope_data),
        **stored_row_override,
    )

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn,
            trading_account_id=1,
            venue="bitvavo",
            master_key_bytes=kb,
        )

    _assert_code(exc, code)
    assert "metadata-key" not in str(exc.value)
    assert "metadata-secret" not in str(exc.value)


def test_malformed_encrypted_credential_metadata_rejected() -> None:
    kv, kb = _key()
    conn = _fresh_db()
    _seed_credential(
        conn,
        key_version=kv,
        master_key_bytes=kb,
        encrypted_envelope="{}",
    )

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn,
            trading_account_id=1,
            venue="bitvavo",
            master_key_bytes=kb,
        )

    _assert_code(exc, "INVALID_CREDENTIAL_ENVELOPE")


def test_conflicting_repository_global_credentials_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    kv, kb = _key()
    conn = _fresh_db()
    _seed_credential(
        conn,
        key_version=kv,
        master_key_bytes=kb,
        api_key="db-account-key",
        api_secret="db-account-secret",
    )
    monkeypatch.setenv("BITVAVO_API_KEY", "wrong-global-key")
    monkeypatch.setenv("BITVAVO_API_SECRET", "wrong-global-secret")

    _identity, resolved = resolve_private_read_credential(
        conn,
        account_code="joost-read",
        venue="bitvavo",
        master_key_bytes=kb,
    )

    assert resolved.credential.api_key == "db-account-key"


def test_no_secret_appears_in_exceptions_or_reports() -> None:
    kv, kb = _key()
    conn = _fresh_db()
    _seed_credential(
        conn,
        key_version=kv,
        master_key_bytes=kb,
        api_key="never-log-key",
        api_secret="never-log-secret",
        last_validation_error_code="never-log-secret",
    )
    _identity, resolved = resolve_private_read_credential(
        conn,
        trading_account_id=1,
        venue="bitvavo",
        master_key_bytes=kb,
    )

    report_text = repr(resolved.public_report())
    repr_text = repr(resolved)
    assert "never-log-key" not in report_text
    assert "never-log-secret" not in report_text
    assert "never-log-key" not in repr_text
    assert "never-log-secret" not in repr_text

    conn.execute(
        "UPDATE trading_account_credential SET validation_state = 'UNVALIDATED'"
    )
    with pytest.raises(PrivateReadCredentialResolutionError) as validation_exc:
        resolve_private_read_credential(
            conn,
            trading_account_id=1,
            venue="bitvavo",
            master_key_bytes=kb,
        )
    assert "never-log-secret" not in str(validation_exc.value)
    conn.execute(
        "UPDATE trading_account_credential SET validation_state = 'VALID_PRIVATE_READ'"
    )

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn,
            trading_account_id=1,
            venue="bitvavo",
            master_key_bytes=b"0" * 32,
        )
    assert "never-log-key" not in str(exc.value)
    assert "never-log-secret" not in str(exc.value)


def test_linked_profile_wallet_resolution_uses_canonical_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    kv, kb = _key()
    conn = _fresh_db()
    _seed_credential(
        conn,
        key_version=kv,
        master_key_bytes=kb,
        api_key="linked-profile-key",
    )
    monkeypatch.setenv("SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY", generate_test_master_key())
    # Use the actual key for the successful path after proving env lookup is the source.
    encoded = os.environ["SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY"]
    assert encoded.startswith("v1:")
    monkeypatch.setenv(
        "SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY",
        "v1:" + base64.urlsafe_b64encode(kb).decode("ascii"),
    )

    resolved = resolve_private_read_bitvavo_client_from_env(
        conn,
        profile_code="joost",
        venue="bitvavo",
    )

    assert resolved.identity.trading_account_id == 1
    assert resolved.identity.profile_code == "joost"
    assert resolved.profile.permission_scope == "READ_ONLY_PRIVATE"


def test_legacy_mvp_account_refresh_cannot_use_global_fallback() -> None:
    script = Path("scripts/odroid/run_mvp_account_refresh_once.sh").read_text()
    assert "SYNTH_MVP_ACCOUNT_CODE must be set" in script
    assert "SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY must be loaded" in script
    assert "--account-code \"${SYNTH_MVP_ACCOUNT_CODE}\"" in script
    assert "--account-code bitvavo_synth_read" not in script
