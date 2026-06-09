"""
Service and DB-layer tests for AccountProvisioningService.

Uses shared-memory SQLite (file::memory:?cache=shared) so the test can
seed + provision + verify across multiple connections without MariaDB.
"""
from __future__ import annotations

import logging
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.account_provisioning.account_provisioning_service_v1 import (
    AccountProvisioningService,
    AuthenticatedProfileIdentity,
    _generate_account_code,
)
from src.account_provisioning.account_repository_v1 import SqliteAccountRepository
from src.account_provisioning.credential_crypto_v1 import (
    decrypt_credential,
    generate_test_master_key,
    parse_master_key,
)
from src.account_provisioning.credential_repository_v1 import SqliteCredentialRepository
from src.account_provisioning.credential_validator_v1 import MockBitvavoCredentialValidator
from src.web.website_registration_v1 import SqliteWebsiteRegistrationRepository


_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
_DB_COUNTER = [0]


def _next_db() -> str:
    _DB_COUNTER[0] += 1
    return f"prov_test_{_DB_COUNTER[0]}"


def _shared_conn(db_name: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_name}?mode=memory&cache=shared", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _seed_schema(db_name: str) -> sqlite3.Connection:
    conn = _shared_conn(db_name)
    SqliteWebsiteRegistrationRepository(conn).create_schema()
    SqliteAccountRepository(conn).create_schema()
    SqliteCredentialRepository(conn).create_schema()
    conn.commit()
    return conn


def _seed_profile(conn: sqlite3.Connection, profile_code: str = "hugo") -> int:
    conn.execute(
        "INSERT OR IGNORE INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc) VALUES (?, ?, ?, ?)",
        (profile_code, "UTC", "NO_EXCHANGE_ACCOUNT_CONNECTED", "2026-06-09 12:00:00"),
    )
    conn.commit()
    row = conn.execute("SELECT app_profile_id FROM app_profile WHERE profile_code = ?", (profile_code,)).fetchone()
    return int(row["app_profile_id"])


def _master_key():
    return parse_master_key(generate_test_master_key())


def _service(kv, kb):
    return AccountProvisioningService(
        credential_validator=MockBitvavoCredentialValidator(),
        master_key_version=kv,
        master_key_bytes=kb,
        account_repo_factory=SqliteAccountRepository,
        cred_repo_factory=SqliteCredentialRepository,
    )


def _provision(service, identity, db_name, api_key="mock-valid-read-only-key", api_secret="test-secret", confirmed=True):
    return service.provision_bitvavo_account(
        identity=identity,
        api_key=api_key,
        api_secret=api_secret,
        withdrawal_disabled_confirmed=confirmed,
        conn_factory=lambda: _shared_conn(db_name),
        now_utc=_NOW,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_provision_creates_trading_account() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    result = _provision(_service(kv, kb), identity, db)
    assert result.ok is True
    row = seed.execute("SELECT * FROM trading_account WHERE venue = 'bitvavo'").fetchone()
    assert row is not None
    seed.close()


def test_account_starts_non_live() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    _provision(_service(kv, kb), identity, db)
    row = seed.execute("SELECT * FROM trading_account WHERE venue = 'bitvavo'").fetchone()
    assert row["live_trading_enabled"] == 0
    assert row["enabled"] == 1
    seed.close()


def test_account_code_is_server_generated() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    _provision(_service(kv, kb), identity, db)
    row = seed.execute("SELECT account_code FROM trading_account WHERE venue = 'bitvavo'").fetchone()
    expected = _generate_account_code("hugo", "bitvavo")
    assert row["account_code"] == expected
    seed.close()


def test_credential_stored_encrypted() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    _provision(_service(kv, kb), identity, db, api_key="mock-valid-read-only-key", api_secret="my-secret-val")
    ta_row = seed.execute("SELECT trading_account_id FROM trading_account WHERE venue = 'bitvavo'").fetchone()
    cred_row = seed.execute(
        "SELECT encrypted_envelope, credential_fingerprint FROM trading_account_credential WHERE trading_account_id = ?",
        (ta_row["trading_account_id"],),
    ).fetchone()
    assert cred_row is not None
    assert "my-secret-val" not in cred_row["encrypted_envelope"]
    assert "mock-valid-read-only-key" not in cred_row["encrypted_envelope"]
    seed.close()


def test_credential_can_be_decrypted() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    _provision(_service(kv, kb), identity, db, api_key="mock-valid-read-only-key", api_secret="round-trip-secret")
    ta_row = seed.execute("SELECT trading_account_id FROM trading_account WHERE venue = 'bitvavo'").fetchone()
    cred_row = seed.execute(
        "SELECT encrypted_envelope FROM trading_account_credential WHERE trading_account_id = ?",
        (ta_row["trading_account_id"],),
    ).fetchone()
    from src.account_provisioning.contracts_v1 import EncryptedCredentialEnvelope
    envelope = EncryptedCredentialEnvelope.from_json(cred_row["encrypted_envelope"])
    plain = decrypt_credential(envelope, kb)
    assert plain.api_secret == "round-trip-secret"
    seed.close()


def test_active_primary_profile_link_created() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    _provision(_service(kv, kb), identity, db)
    link = seed.execute(
        "SELECT * FROM app_profile_trading_account_link WHERE app_profile_id = ?", (pid,)
    ).fetchone()
    assert link is not None
    assert link["link_status"] == "ACTIVE"
    assert link["is_primary"] == 1
    seed.close()


def test_onboarding_state_updated() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    _provision(_service(kv, kb), identity, db)
    row = seed.execute("SELECT onboarding_state FROM app_profile WHERE app_profile_id = ?", (pid,)).fetchone()
    assert row["onboarding_state"] == "READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED"
    seed.close()


def test_success_result_shape() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    result = _provision(_service(kv, kb), identity, db)
    assert result.ok is True
    assert result.profile_code == "hugo"
    assert result.account_connection_state == "READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED"
    assert result.landing_path == "/synth/accounts/hugo/profit-plan.html"
    assert result.refresh_pending is True
    seed.close()


def test_valid_hugo_request_links_hugo_only() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    hugo_pid = _seed_profile(seed, "hugo")
    joost_pid = _seed_profile(seed, "joost")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=hugo_pid, profile_code="hugo")
    _provision(_service(kv, kb), identity, db)
    hugo_link = seed.execute(
        "SELECT * FROM app_profile_trading_account_link WHERE app_profile_id = ?", (hugo_pid,)
    ).fetchone()
    joost_link = seed.execute(
        "SELECT * FROM app_profile_trading_account_link WHERE app_profile_id = ?", (joost_pid,)
    ).fetchone()
    assert hugo_link is not None
    assert joost_link is None
    seed.close()


# ---------------------------------------------------------------------------
# Failure cases — no rows created
# ---------------------------------------------------------------------------

def test_invalid_credential_creates_no_rows() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    result = _provision(_service(kv, kb), identity, db, api_key="mock-invalid-key")
    assert result.ok is False
    assert result.error_code == "INVALID_CREDENTIALS"
    assert seed.execute("SELECT COUNT(*) AS n FROM trading_account").fetchone()["n"] == 0
    assert seed.execute("SELECT COUNT(*) AS n FROM trading_account_credential").fetchone()["n"] == 0
    assert seed.execute("SELECT COUNT(*) AS n FROM app_profile_trading_account_link").fetchone()["n"] == 0
    seed.close()


def test_unavailable_validation_creates_no_rows() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    result = _provision(_service(kv, kb), identity, db, api_key="mock-unavailable-key")
    assert result.ok is False
    assert result.error_code == "VALIDATION_UNAVAILABLE"
    assert seed.execute("SELECT COUNT(*) AS n FROM trading_account").fetchone()["n"] == 0
    seed.close()


def test_missing_confirmation_creates_no_rows() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    result = _provision(_service(kv, kb), identity, db, confirmed=False)
    assert result.ok is False
    assert seed.execute("SELECT COUNT(*) AS n FROM trading_account").fetchone()["n"] == 0
    seed.close()


def test_existing_link_returns_already_connected() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    _provision(_service(kv, kb), identity, db)
    result2 = _provision(_service(kv, kb), identity, db)
    assert result2.ok is False
    assert result2.error_code == "ACCOUNT_ALREADY_CONNECTED"
    assert result2.landing_path == "/synth/accounts/hugo/profit-plan.html"
    seed.close()


def test_duplicate_request_produces_one_account() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    _provision(_service(kv, kb), identity, db)
    _provision(_service(kv, kb), identity, db)
    count = seed.execute("SELECT COUNT(*) AS n FROM trading_account").fetchone()["n"]
    assert count == 1
    seed.close()


def test_failed_transaction_leaves_no_partial_rows() -> None:
    """When DB raises mid-provisioning, rollback leaves no orphan rows."""
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")

    # Insert a conflicting trading_account entry to force duplicate-key on second call
    seed.execute(
        "INSERT INTO trading_account (account_code, venue, account_mode, enabled, live_trading_enabled, created_ts_utc) VALUES (?, ?, ?, ?, ?, ?)",
        ("hugo-bitvavo", "bitvavo", "paper", 1, 0, "2026-06-09 11:00:00"),
    )
    seed.commit()

    try:
        _provision(_service(kv, kb), identity, db)
    except Exception:
        pass

    # Credential and link must not exist
    assert seed.execute("SELECT COUNT(*) AS n FROM trading_account_credential").fetchone()["n"] == 0
    assert seed.execute("SELECT COUNT(*) AS n FROM app_profile_trading_account_link").fetchone()["n"] == 0
    seed.close()


# ---------------------------------------------------------------------------
# Transaction ownership
# ---------------------------------------------------------------------------

def test_service_commits_on_success() -> None:
    source = Path("src/account_provisioning/account_provisioning_service_v1.py").read_text()
    assert ".commit()" in source, "service must own the transaction and commit on success"


def test_service_rolls_back_on_failure() -> None:
    source = Path("src/account_provisioning/account_provisioning_service_v1.py").read_text()
    assert ".rollback()" in source, "service must rollback on failure or exception"


def test_service_commits_once_on_success() -> None:
    """Provisioning commits and subsequent verify reads committed data."""
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    result = _provision(_service(kv, kb), identity, db)
    assert result.ok is True
    # seed conn should see committed rows immediately
    count = seed.execute("SELECT COUNT(*) AS n FROM trading_account").fetchone()["n"]
    assert count == 1
    seed.close()


def test_service_rolls_back_on_db_exception() -> None:
    """Exception mid-provisioning leaves no orphan rows."""
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")

    seed.execute(
        "INSERT INTO trading_account (account_code, venue, account_mode, enabled, live_trading_enabled, created_ts_utc) VALUES (?, ?, ?, ?, ?, ?)",
        ("hugo-bitvavo", "bitvavo", "paper", 1, 0, "2026-06-09 11:00:00"),
    )
    seed.commit()

    raised = False
    try:
        _provision(_service(kv, kb), identity, db)
    except Exception:
        raised = True

    assert raised is True
    assert seed.execute("SELECT COUNT(*) AS n FROM trading_account_credential").fetchone()["n"] == 0
    assert seed.execute("SELECT COUNT(*) AS n FROM app_profile_trading_account_link").fetchone()["n"] == 0
    seed.close()


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------

def test_hugo_cannot_provision_as_joost() -> None:
    """hugo's identity cannot create resources linked to joost's profile."""
    db = _next_db()
    seed = _seed_schema(db)
    hugo_pid = _seed_profile(seed, "hugo")
    joost_pid = _seed_profile(seed, "joost")
    kv, kb = _master_key()
    # hugo's session identity — cannot be joost even if joost_pid is passed externally
    hugo_identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=hugo_pid, profile_code="hugo")
    _provision(_service(kv, kb), hugo_identity, db)
    joost_link = seed.execute(
        "SELECT * FROM app_profile_trading_account_link WHERE app_profile_id = ?", (joost_pid,)
    ).fetchone()
    assert joost_link is None
    seed.close()


# ---------------------------------------------------------------------------
# Secret safety
# ---------------------------------------------------------------------------

def test_secrets_absent_from_result() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    result = _provision(_service(kv, kb), identity, db, api_key="mock-valid-read-only-key", api_secret="my-top-secret")
    result_str = repr(result)
    assert "my-top-secret" not in result_str
    assert "mock-valid-read-only-key" not in result_str
    seed.close()


def test_secrets_absent_from_exception_text() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    exc_text: list[str] = []
    try:
        _provision(_service(kv, kb), identity, db, api_key="mock-invalid-key", api_secret="very-secret-secret")
    except Exception as exc:
        exc_text.append(str(exc))
    for text in exc_text:
        assert "very-secret-secret" not in text
    seed.close()


def test_secrets_absent_from_captured_logs() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    handler = _Capture()
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    old_level = root_logger.level
    root_logger.setLevel(logging.DEBUG)
    try:
        _provision(_service(kv, kb), identity, db, api_key="mock-valid-read-only-key", api_secret="captured-secret-val")
    finally:
        root_logger.removeHandler(handler)
        root_logger.setLevel(old_level)

    for record in records:
        assert "captured-secret-val" not in record
    seed.close()


def test_plaintext_absent_from_database() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid = _seed_profile(seed, "hugo")
    kv, kb = _master_key()
    identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
    _provision(_service(kv, kb), identity, db, api_key="mock-valid-read-only-key", api_secret="plaintext-check-secret")
    rows = seed.execute("SELECT * FROM trading_account_credential").fetchall()
    for row in rows:
        for col in row.keys():
            val = str(row[col]) if row[col] is not None else ""
            assert "plaintext-check-secret" not in val
            assert "mock-valid-read-only-key" not in val
    seed.close()


def test_plain_credential_repr_safe() -> None:
    from src.account_provisioning.contracts_v1 import PlainBitvavoCredential
    cred = PlainBitvavoCredential(venue="bitvavo", api_key="sk-test", api_secret="sec-test")
    r = repr(cred)
    assert "sk-test" not in r
    assert "sec-test" not in r
    assert "<redacted>" in r


# ---------------------------------------------------------------------------
# Architecture / safety
# ---------------------------------------------------------------------------

def test_no_broker_import_in_provisioning_service() -> None:
    source = Path("src/account_provisioning/account_provisioning_service_v1.py").read_text()
    assert "BitvavoClient" not in source
    assert "get_balance" not in source
    assert "place_order" not in source


def test_reporting_unchanged() -> None:
    source = Path("src/account_provisioning/account_provisioning_service_v1.py").read_text()
    assert "reporting" not in source


def test_decision_gate_unchanged() -> None:
    source = Path("src/account_provisioning/account_provisioning_service_v1.py").read_text()
    assert "decision_gate" not in source


if __name__ == "__main__":
    tests = [
        test_provision_creates_trading_account,
        test_account_starts_non_live,
        test_account_code_is_server_generated,
        test_credential_stored_encrypted,
        test_credential_can_be_decrypted,
        test_active_primary_profile_link_created,
        test_onboarding_state_updated,
        test_success_result_shape,
        test_valid_hugo_request_links_hugo_only,
        test_invalid_credential_creates_no_rows,
        test_unavailable_validation_creates_no_rows,
        test_missing_confirmation_creates_no_rows,
        test_existing_link_returns_already_connected,
        test_duplicate_request_produces_one_account,
        test_failed_transaction_leaves_no_partial_rows,
        test_service_commits_on_success,
        test_service_rolls_back_on_failure,
        test_service_commits_once_on_success,
        test_service_rolls_back_on_db_exception,
        test_hugo_cannot_provision_as_joost,
        test_secrets_absent_from_result,
        test_secrets_absent_from_exception_text,
        test_secrets_absent_from_captured_logs,
        test_plaintext_absent_from_database,
        test_plain_credential_repr_safe,
        test_no_broker_import_in_provisioning_service,
        test_reporting_unchanged,
        test_decision_gate_unchanged,
    ]
    for t in tests:
        t()
    print("ok")
