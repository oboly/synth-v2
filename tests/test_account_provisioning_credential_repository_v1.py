from __future__ import annotations

import ast
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.account_provisioning.contracts_v1 import (
    CredentialStatus,
    CredentialValidationState,
)
from src.account_provisioning.credential_crypto_v1 import (
    compute_fingerprint,
    encrypt_credential,
    generate_test_master_key,
    parse_master_key,
)
from src.account_provisioning.contracts_v1 import PlainBitvavoCredential
from src.account_provisioning.credential_repository_v1 import (
    CREDENTIAL_KIND_API_KEY_SECRET,
    CredentialValidationUpdateError,
    SqliteCredentialRepository,
)


_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
_ACCOUNT_ID = 1
_VENUE = "bitvavo"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _repo() -> SqliteCredentialRepository:
    conn = sqlite3.connect(":memory:")
    repo = SqliteCredentialRepository(conn)
    repo.create_schema()
    return repo


def _master_key() -> tuple[str, bytes]:
    raw = generate_test_master_key()
    return parse_master_key(raw)


def _cred(api_key: str = "test-api-key", api_secret: str = "test-secret") -> PlainBitvavoCredential:
    return PlainBitvavoCredential(venue=_VENUE, api_key=api_key, api_secret=api_secret)


def _insert(
    repo: SqliteCredentialRepository,
    *,
    trading_account_id: int = _ACCOUNT_ID,
    cred: PlainBitvavoCredential | None = None,
    key_bytes: bytes | None = None,
    key_version: str = "v1",
) -> int:
    kv, kb = _master_key()
    if key_bytes is None:
        key_bytes = kb
    if key_version != "v1":
        kv = key_version
    if cred is None:
        cred = _cred()
    envelope = encrypt_credential(cred, trading_account_id, kv, key_bytes)
    fingerprint = compute_fingerprint(_VENUE, cred.api_key, key_bytes)
    return repo.insert_active_credential(
        trading_account_id=trading_account_id,
        venue=_VENUE,
        credential_kind=CREDENTIAL_KIND_API_KEY_SECRET,
        encrypted_envelope=envelope.to_json(),
        encryption_algorithm=envelope.alg,
        key_version=envelope.kv,
        credential_fingerprint=fingerprint,
        now_utc=_NOW,
    )


# ---------------------------------------------------------------------------
# Insert
# ---------------------------------------------------------------------------

def test_insert_stores_encrypted_envelope_only() -> None:
    repo = _repo()
    api_key_sentinel = "SECRET_API_KEY_SENTINEL"
    api_secret_sentinel = "SECRET_API_SECRET_SENTINEL"
    cred = PlainBitvavoCredential(venue=_VENUE, api_key=api_key_sentinel, api_secret=api_secret_sentinel)
    _, kb = _master_key()
    envelope = encrypt_credential(cred, _ACCOUNT_ID, "v1", kb)
    fp = compute_fingerprint(_VENUE, api_key_sentinel, kb)
    row_id = repo.insert_active_credential(
        trading_account_id=_ACCOUNT_ID,
        venue=_VENUE,
        credential_kind=CREDENTIAL_KIND_API_KEY_SECRET,
        encrypted_envelope=envelope.to_json(),
        encryption_algorithm=envelope.alg,
        key_version=envelope.kv,
        credential_fingerprint=fp,
        now_utc=_NOW,
    )
    assert row_id > 0
    # Verify raw storage contains no plaintext
    row = repo._fetchone(
        "SELECT encrypted_envelope, credential_fingerprint FROM trading_account_credential WHERE trading_account_credential_id = %s",
        (row_id,),
    )
    assert row is not None
    assert api_key_sentinel not in row["encrypted_envelope"]
    assert api_secret_sentinel not in row["encrypted_envelope"]
    assert api_key_sentinel not in row["credential_fingerprint"]


def test_insert_returns_positive_id() -> None:
    repo = _repo()
    row_id = _insert(repo)
    assert row_id > 0


def test_validated_insert_records_validation_timestamp() -> None:
    repo = _repo()
    kv, kb = _master_key()
    cred = _cred()
    envelope = encrypt_credential(cred, _ACCOUNT_ID, kv, kb)
    row_id = repo.insert_active_credential(
        trading_account_id=_ACCOUNT_ID,
        venue=_VENUE,
        credential_kind=CREDENTIAL_KIND_API_KEY_SECRET,
        encrypted_envelope=envelope.to_json(),
        encryption_algorithm=envelope.alg,
        key_version=envelope.kv,
        credential_fingerprint=compute_fingerprint(_VENUE, cred.api_key, kb),
        now_utc=_NOW,
        validation_state="VALID_PRIVATE_READ",
    )

    row = repo._fetchone(
        "SELECT validated_ts_utc FROM trading_account_credential "
        "WHERE trading_account_credential_id = %s",
        (row_id,),
    )
    assert row is not None
    assert row["validated_ts_utc"] == "2026-06-09 12:00:00"


def test_duplicate_active_credential_rejected() -> None:
    repo = _repo()
    _insert(repo)
    try:
        _insert(repo)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "DUPLICATE_ACTIVE_CREDENTIAL" in str(e)


def test_different_account_can_have_credential() -> None:
    repo = _repo()
    _insert(repo, trading_account_id=1)
    row_id2 = _insert(repo, trading_account_id=2)
    assert row_id2 > 0


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def test_load_returns_stored_credential() -> None:
    repo = _repo()
    _insert(repo)
    stored = repo.load_active_encrypted_credential(trading_account_id=_ACCOUNT_ID, venue=_VENUE)
    assert stored is not None
    assert stored.trading_account_id == _ACCOUNT_ID
    assert stored.venue == _VENUE
    assert stored.credential_status == CredentialStatus.ACTIVE
    assert stored.validation_state == CredentialValidationState.UNVALIDATED


def test_load_is_account_scoped() -> None:
    repo = _repo()
    _insert(repo, trading_account_id=10)
    result = repo.load_active_encrypted_credential(trading_account_id=99, venue=_VENUE)
    assert result is None


def test_wrong_account_cannot_load_credential() -> None:
    repo = _repo()
    _insert(repo, trading_account_id=1)
    result = repo.load_active_encrypted_credential(trading_account_id=2, venue=_VENUE)
    assert result is None


def test_load_returns_none_when_no_credential() -> None:
    repo = _repo()
    result = repo.load_active_encrypted_credential(trading_account_id=_ACCOUNT_ID, venue=_VENUE)
    assert result is None


def test_multiple_active_rows_fail_closed() -> None:
    """Bypass application check to simulate data integrity violation."""
    repo = _repo()
    kv, kb = _master_key()
    cred = _cred()
    env = encrypt_credential(cred, _ACCOUNT_ID, kv, kb)
    fp = compute_fingerprint(_VENUE, cred.api_key, kb)

    def _raw_insert() -> None:
        repo._conn.execute(
            """
            INSERT INTO trading_account_credential (
                trading_account_id, venue, credential_kind,
                encrypted_envelope, encryption_algorithm, key_version,
                credential_fingerprint, credential_status, validation_state,
                created_ts_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', 'UNVALIDATED', ?)
            """,
            (_ACCOUNT_ID, _VENUE, CREDENTIAL_KIND_API_KEY_SECRET,
             env.to_json(), env.alg, kv, fp, "2026-06-09 12:00:00"),
        )

    _raw_insert()
    _raw_insert()

    try:
        repo.load_active_encrypted_credential(trading_account_id=_ACCOUNT_ID, venue=_VENUE)
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "MULTIPLE_ACTIVE_CREDENTIALS" in str(e)


# ---------------------------------------------------------------------------
# Exact existing-credential validation update
# ---------------------------------------------------------------------------

def test_exact_active_validation_success_update() -> None:
    repo = _repo()
    row_id = _insert(repo)

    affected = repo.update_existing_active_credential_validation(
        trading_account_credential_id=row_id,
        trading_account_id=_ACCOUNT_ID,
        venue=_VENUE,
        validation_state="VALID_PRIVATE_READ",
        validated_ts_utc=_NOW,
        safe_error_code=None,
    )

    row = repo._fetchone(
        "SELECT validation_state, validated_ts_utc, last_validation_error_code "
        "FROM trading_account_credential WHERE trading_account_credential_id = %s",
        (row_id,),
    )
    assert affected == 1
    assert row is not None
    assert row["validation_state"] == "VALID_PRIVATE_READ"
    assert row["validated_ts_utc"] == "2026-06-09 12:00:00"
    assert row["last_validation_error_code"] is None


def test_exact_active_validation_invalid_update() -> None:
    repo = _repo()
    row_id = _insert(repo)

    repo.update_existing_active_credential_validation(
        trading_account_credential_id=row_id,
        trading_account_id=_ACCOUNT_ID,
        venue=_VENUE,
        validation_state="INVALID_CREDENTIALS",
        validated_ts_utc=None,
        safe_error_code="INVALID_CREDENTIALS_OR_READ_PERMISSION",
    )

    row = repo._fetchone(
        "SELECT validation_state, validated_ts_utc, last_validation_error_code "
        "FROM trading_account_credential WHERE trading_account_credential_id = %s",
        (row_id,),
    )
    assert row is not None
    assert row["validation_state"] == "INVALID_CREDENTIALS"
    assert row["validated_ts_utc"] is None
    assert row["last_validation_error_code"] == "INVALID_CREDENTIALS_OR_READ_PERMISSION"


def test_exact_active_validation_rejects_untrusted_error_code() -> None:
    repo = _repo()
    row_id = _insert(repo)

    with pytest.raises(CredentialValidationUpdateError) as exc:
        repo.update_existing_active_credential_validation(
            trading_account_credential_id=row_id,
            trading_account_id=_ACCOUNT_ID,
            venue=_VENUE,
            validation_state="INVALID_CREDENTIALS",
            validated_ts_utc=None,
            safe_error_code="PRIVATE_SECRET_SENTINEL",
        )

    assert exc.value.code == "INVALID_FAILURE_VALIDATION_UPDATE"


@pytest.mark.parametrize(
    ("credential_id", "account_id", "venue"),
    (
        (999, _ACCOUNT_ID, _VENUE),
        (1, 999, _VENUE),
        (1, _ACCOUNT_ID, "kraken"),
    ),
)
def test_exact_active_validation_update_rejects_identity_mismatch(
    credential_id: int,
    account_id: int,
    venue: str,
) -> None:
    repo = _repo()
    row_id = _insert(repo)
    if credential_id == 1:
        credential_id = row_id

    with pytest.raises(CredentialValidationUpdateError) as exc:
        repo.update_existing_active_credential_validation(
            trading_account_credential_id=credential_id,
            trading_account_id=account_id,
            venue=venue,
            validation_state="VALID_PRIVATE_READ",
            validated_ts_utc=_NOW,
            safe_error_code=None,
        )

    assert exc.value.code == "EXACT_ACTIVE_CREDENTIAL_UPDATE_REQUIRED"


def test_exact_active_validation_update_rejects_non_active_row() -> None:
    repo = _repo()
    row_id = _insert(repo)
    repo.mark_revoked(trading_account_credential_id=row_id, now_utc=_NOW)

    with pytest.raises(CredentialValidationUpdateError) as exc:
        repo.update_existing_active_credential_validation(
            trading_account_credential_id=row_id,
            trading_account_id=_ACCOUNT_ID,
            venue=_VENUE,
            validation_state="VALID_PRIVATE_READ",
            validated_ts_utc=_NOW,
            safe_error_code=None,
        )

    assert exc.value.code == "EXACT_ACTIVE_CREDENTIAL_UPDATE_REQUIRED"


def test_exact_active_validation_update_remains_caller_transaction_owned() -> None:
    repo = _repo()
    row_id = _insert(repo)
    repo._conn.commit()

    repo.update_existing_active_credential_validation(
        trading_account_credential_id=row_id,
        trading_account_id=_ACCOUNT_ID,
        venue=_VENUE,
        validation_state="VALID_PRIVATE_READ",
        validated_ts_utc=_NOW,
        safe_error_code=None,
    )
    repo._conn.rollback()

    row = repo._fetchone(
        "SELECT validation_state, validated_ts_utc "
        "FROM trading_account_credential WHERE trading_account_credential_id = %s",
        (row_id,),
    )
    assert row is not None
    assert row["validation_state"] == "UNVALIDATED"
    assert row["validated_ts_utc"] is None


# ---------------------------------------------------------------------------
# Revoke / rotate
# ---------------------------------------------------------------------------

def test_revoked_credential_cannot_load_as_active() -> None:
    repo = _repo()
    row_id = _insert(repo)
    repo.mark_revoked(trading_account_credential_id=row_id, now_utc=_NOW)
    result = repo.load_active_encrypted_credential(trading_account_id=_ACCOUNT_ID, venue=_VENUE)
    assert result is None


def test_revoked_sets_status_and_timestamp() -> None:
    repo = _repo()
    row_id = _insert(repo)
    repo.mark_revoked(trading_account_credential_id=row_id, now_utc=_NOW)
    row = repo._fetchone(
        "SELECT credential_status, revoked_ts_utc FROM trading_account_credential WHERE trading_account_credential_id = %s",
        (row_id,),
    )
    assert row["credential_status"] == "REVOKED"
    assert row["revoked_ts_utc"] is not None


def test_rotated_credential_cannot_load_as_active() -> None:
    repo = _repo()
    row_id = _insert(repo)
    repo.mark_rotated(trading_account_credential_id=row_id, now_utc=_NOW)
    result = repo.load_active_encrypted_credential(trading_account_id=_ACCOUNT_ID, venue=_VENUE)
    assert result is None


def test_after_revoke_new_active_credential_can_be_inserted() -> None:
    repo = _repo()
    row_id = _insert(repo, cred=_cred(api_key="old-key"))
    repo.mark_revoked(trading_account_credential_id=row_id, now_utc=_NOW)
    new_id = _insert(repo, cred=_cred(api_key="new-key"))
    assert new_id > row_id


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------

def test_find_by_fingerprint_returns_row() -> None:
    repo = _repo()
    _, kb = _master_key()
    cred = _cred(api_key="finger-test-key")
    fp = compute_fingerprint(_VENUE, cred.api_key, kb)
    _insert(repo, cred=cred, key_bytes=kb)
    result = repo.find_by_fingerprint(credential_fingerprint=fp, venue=_VENUE)
    assert result is not None
    assert result.credential_fingerprint == fp


def test_find_by_fingerprint_returns_none_on_miss() -> None:
    repo = _repo()
    result = repo.find_by_fingerprint(credential_fingerprint="a" * 64, venue=_VENUE)
    assert result is None


def test_find_by_fingerprint_returns_any_status() -> None:
    repo = _repo()
    _, kb = _master_key()
    cred = _cred(api_key="fp-revoked-key")
    fp = compute_fingerprint(_VENUE, cred.api_key, kb)
    row_id = _insert(repo, cred=cred, key_bytes=kb)
    repo.mark_revoked(trading_account_credential_id=row_id, now_utc=_NOW)
    result = repo.find_by_fingerprint(credential_fingerprint=fp, venue=_VENUE)
    assert result is not None
    assert result.credential_status == CredentialStatus.REVOKED


# ---------------------------------------------------------------------------
# Transaction model
# ---------------------------------------------------------------------------

def test_rollback_leaves_no_credential_row() -> None:
    conn = sqlite3.connect(":memory:")
    repo = SqliteCredentialRepository(conn)
    repo.create_schema()
    conn.execute("BEGIN")
    _insert(repo)
    conn.rollback()
    result = repo.load_active_encrypted_credential(trading_account_id=_ACCOUNT_ID, venue=_VENUE)
    assert result is None


def test_repository_does_not_auto_commit() -> None:
    """Repository source must not contain conn.commit() — caller owns the transaction."""
    source = Path("src/account_provisioning/credential_repository_v1.py").read_text()
    assert ".commit()" not in source, "repository must not call conn.commit() — caller owns the transaction"


# ---------------------------------------------------------------------------
# Migration / schema
# ---------------------------------------------------------------------------

def test_migration_contains_no_plaintext_credential_columns() -> None:
    import re
    migration = Path("db/migrations/20260609_trading_account_credential_v1.sql").read_text()
    # Strip line comments, inline COMMENT clauses, and DEFAULT string literals
    # before checking — these may legitimately reference "api_key" as descriptive text.
    stripped = re.sub(r"--[^\n]*", "", migration)
    stripped = re.sub(r"COMMENT\s+'[^']*'", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"DEFAULT\s+'[^']*'", "", stripped, flags=re.IGNORECASE)
    lower = stripped.lower()
    assert "api_key" not in lower, "no structural column named api_key"
    assert "api_secret" not in lower, "no structural column named api_secret"
    # Confirm "plaintext" is not a column name (safe to check against raw migration)
    column_defs = re.findall(r"^\s+\w+\s+\w+", migration, re.MULTILINE)
    col_names = [c.strip().split()[0].lower() for c in column_defs]
    assert "plaintext" not in col_names


def test_migration_references_trading_account_fk() -> None:
    migration = Path("db/migrations/20260609_trading_account_credential_v1.sql").read_text()
    assert "REFERENCES trading_account" in migration


def test_migration_has_check_constraints() -> None:
    migration = Path("db/migrations/20260609_trading_account_credential_v1.sql").read_text()
    assert "ACTIVE" in migration
    assert "REVOKED" in migration
    assert "UNVALIDATED" in migration
    assert "VALID_READ_ONLY" in migration


def test_migration_is_idempotent() -> None:
    migration = Path("db/migrations/20260609_trading_account_credential_v1.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS" in migration


def test_migration_follows_repository_style() -> None:
    migration = Path("db/migrations/20260609_trading_account_credential_v1.sql").read_text()
    assert "ENGINE=InnoDB" in migration
    assert "utf8mb4" in migration
    assert "utc" in migration.lower()


# ---------------------------------------------------------------------------
# Architecture / safety
# ---------------------------------------------------------------------------

def test_reporting_does_not_import_credential_crypto() -> None:
    """Reporting modules must not import the provisioning crypto module."""
    reporting_dir = Path("src/reporting")
    for py_file in reporting_dir.glob("*.py"):
        source = py_file.read_text()
        assert "credential_crypto_v1" not in source, \
            f"{py_file.name} must not import credential_crypto_v1"
        assert "account_provisioning" not in source, \
            f"{py_file.name} must not import account_provisioning"


def test_executor_does_not_import_provisioning() -> None:
    for src_path in [Path("src/executor"), Path("src/execution")]:
        if not src_path.exists():
            continue
        for py_file in src_path.glob("*.py"):
            source = py_file.read_text()
            assert "account_provisioning" not in source, \
                f"{py_file.name} must not import account_provisioning"


def test_no_bitvavo_broker_call_in_repository() -> None:
    source = Path("src/account_provisioning/credential_repository_v1.py").read_text()
    assert "BitvavoClient" not in source
    assert "get_balance" not in source
    assert "place_order" not in source


def test_no_environment_fallback_to_bitvavo_api_key() -> None:
    for path in Path("src/account_provisioning").glob("*.py"):
        source = path.read_text()
        assert "BITVAVO_API_KEY" not in source, \
            f"{path.name} must not reference BITVAVO_API_KEY"
        assert "BITVAVO_API_SECRET" not in source, \
            f"{path.name} must not reference BITVAVO_API_SECRET"


def test_safety_markers_in_repository_module() -> None:
    source = Path("src/account_provisioning/credential_repository_v1.py").read_text()
    assert "broker_private_calls=0" in source
    assert "broker_writes=0" in source
    assert "order_submission=0" in source
    assert "executor=none" in source


if __name__ == "__main__":
    tests = [
        test_insert_stores_encrypted_envelope_only,
        test_insert_returns_positive_id,
        test_duplicate_active_credential_rejected,
        test_different_account_can_have_credential,
        test_load_returns_stored_credential,
        test_load_is_account_scoped,
        test_wrong_account_cannot_load_credential,
        test_load_returns_none_when_no_credential,
        test_multiple_active_rows_fail_closed,
        test_revoked_credential_cannot_load_as_active,
        test_revoked_sets_status_and_timestamp,
        test_rotated_credential_cannot_load_as_active,
        test_after_revoke_new_active_credential_can_be_inserted,
        test_find_by_fingerprint_returns_row,
        test_find_by_fingerprint_returns_none_on_miss,
        test_find_by_fingerprint_returns_any_status,
        test_rollback_leaves_no_credential_row,
        test_repository_does_not_auto_commit,
        test_migration_contains_no_plaintext_credential_columns,
        test_migration_references_trading_account_fk,
        test_migration_has_check_constraints,
        test_migration_is_idempotent,
        test_migration_follows_repository_style,
        test_reporting_does_not_import_credential_crypto,
        test_executor_does_not_import_provisioning,
        test_no_bitvavo_broker_call_in_repository,
        test_no_environment_fallback_to_bitvavo_api_key,
        test_safety_markers_in_repository_module,
    ]
    for t in tests:
        t()
    print("ok")
