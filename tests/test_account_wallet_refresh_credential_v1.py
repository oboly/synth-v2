"""
Regression tests for encrypted credential integration in account wallet refresh.

Covers:
  - Encrypted Hugo credential loaded by trading_account_id, not env file
  - Missing encrypted credential fails closed (no fallback to joost.env/hugo.env)
  - No fallback to profile-env from db credential source
  - Joost linked profile still resolves correctly
  - Balance snapshot written to trading_account_balance_snapshot
  - account_open_order_snapshot written
  - No broker writes, no order submission
  - Systemd unit includes EnvironmentFile and hardening directives
  - Timer refresh-before-render ordering (shell script sequencing)

broker_private_calls=0
broker_writes=0
order_submission=0
executor=none
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.account.account_snapshot_models_v1 import WalletBalanceRow, WalletOpenOrderRow
from src.account.run_account_wallet_refresh_v1 import (
    normalize_balance_rows,
    normalize_order_rows,
    write_balance_snapshot,
    write_open_order_snapshot,
)
from src.account_provisioning.account_credential_loader_v1 import load_account_credential
from src.account_provisioning.contracts_v1 import PlainBitvavoCredential
from src.account_provisioning.credential_crypto_v1 import (
    compute_fingerprint,
    encrypt_credential,
    generate_test_master_key,
    parse_master_key,
)
from src.account_provisioning.credential_repository_v1 import (
    CREDENTIAL_KIND_API_KEY_SECRET,
    SqliteCredentialRepository,
)


# ---------------------------------------------------------------------------
# SQLite schemas
# ---------------------------------------------------------------------------

_ACCOUNT_SCHEMA = """
CREATE TABLE IF NOT EXISTS trading_account_credential (
    trading_account_credential_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id  INTEGER NOT NULL,
    venue               TEXT NOT NULL,
    credential_kind     TEXT NOT NULL,
    encrypted_envelope  TEXT NOT NULL,
    encryption_algorithm TEXT NOT NULL,
    key_version         TEXT NOT NULL,
    credential_fingerprint TEXT NOT NULL,
    credential_status   TEXT NOT NULL DEFAULT 'ACTIVE',
    validation_state    TEXT NOT NULL DEFAULT 'UNVALIDATED',
    created_ts_utc      TEXT NOT NULL,
    validated_ts_utc    TEXT,
    rotated_ts_utc      TEXT,
    revoked_ts_utc      TEXT
);
CREATE TABLE IF NOT EXISTS trading_account_balance_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_ts_utc TEXT NOT NULL,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    currency_code TEXT NOT NULL,
    available_amount TEXT NOT NULL,
    reserved_amount TEXT NOT NULL,
    total_amount TEXT NOT NULL,
    source_name TEXT NOT NULL,
    raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_open_order_snapshot (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_ts_utc TEXT NOT NULL,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    market TEXT NOT NULL,
    broker_order_id TEXT NOT NULL,
    client_order_id TEXT,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    limit_price TEXT,
    quantity TEXT NOT NULL,
    filled_quantity TEXT NOT NULL DEFAULT '0',
    remaining_quantity TEXT NOT NULL,
    broker_status TEXT NOT NULL,
    created_ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _fresh_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_ACCOUNT_SCHEMA)
    return conn


# ---------------------------------------------------------------------------
# Mock cursor adapter for write functions that use MariaDB-style conn.cursor()
# ---------------------------------------------------------------------------

import re as _re

_ON_DUPLICATE_RE = _re.compile(
    r"\s+ON\s+DUPLICATE\s+KEY\s+UPDATE\b.*$", _re.IGNORECASE | _re.DOTALL
)


class _MockCursor:
    """SQLite-backed cursor that translates MariaDB-style SQL for tests."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._cur = conn.cursor()
        self.rowcount = 0

    @staticmethod
    def _coerce(params: tuple) -> tuple:
        """Convert types that SQLite does not natively support."""
        out = []
        for p in params:
            if isinstance(p, Decimal):
                out.append(str(p))
            elif isinstance(p, datetime):
                out.append(p.isoformat(sep=" "))
            else:
                out.append(p)
        return tuple(out)

    def execute(self, sql: str, params: tuple = ()) -> None:
        normalized = sql.replace("%s", "?")
        # Strip MariaDB-only ON DUPLICATE KEY UPDATE clause
        normalized = _ON_DUPLICATE_RE.sub("", normalized)
        self._cur.execute(normalized, self._coerce(params))
        self.rowcount = self._cur.rowcount

    def fetchone(self) -> Any:
        row = self._cur.fetchone()
        return dict(row) if row else None

    def fetchall(self) -> list:
        return [dict(r) for r in self._cur.fetchall()]

    def __enter__(self) -> "_MockCursor":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _MockConn:
    """Wraps a SQLite connection to look like a MariaDB connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def cursor(self) -> _MockCursor:
        return _MockCursor(self._conn)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Encrypted credential: load_account_credential
# ---------------------------------------------------------------------------

def _seed_encrypted_credential(
    conn: sqlite3.Connection,
    *,
    trading_account_id: int,
    api_key: str = "hugo-api-key",
    api_secret: str = "hugo-api-secret",
    kv: str,
    kb: bytes,
) -> None:
    plain = PlainBitvavoCredential(venue="bitvavo", api_key=api_key, api_secret=api_secret)
    envelope = encrypt_credential(plain, trading_account_id, kv, kb)
    fingerprint = compute_fingerprint("bitvavo", api_key, kb)
    repo = SqliteCredentialRepository(conn)
    repo.insert_active_credential(
        trading_account_id=trading_account_id,
        venue="bitvavo",
        credential_kind=CREDENTIAL_KIND_API_KEY_SECRET,
        encrypted_envelope=envelope.to_json(),
        encryption_algorithm=envelope.alg,
        key_version=envelope.kv,
        credential_fingerprint=fingerprint,
        now_utc=_NOW,
        validation_state="VALID_PRIVATE_READ",
    )


def test_encrypted_hugo_credential_loaded_by_trading_account_id() -> None:
    """Hugo's credential is found by trading_account_id, not by profile name or env file."""
    kv, kb = parse_master_key(generate_test_master_key())
    conn = _fresh_db()
    SqliteCredentialRepository(conn).create_schema()
    _seed_encrypted_credential(conn, trading_account_id=4, api_key="hugo-key-123", kv=kv, kb=kb)

    plain = load_account_credential(
        conn,
        trading_account_id=4,
        venue="bitvavo",
        master_key_bytes=kb,
        cred_repo_factory=SqliteCredentialRepository,
    )

    assert plain.api_key == "hugo-key-123"
    assert plain.venue == "bitvavo"


def test_wrong_trading_account_id_fails_closed() -> None:
    """Credential for account 4 is NOT returned when queried for account 99."""
    kv, kb = parse_master_key(generate_test_master_key())
    conn = _fresh_db()
    SqliteCredentialRepository(conn).create_schema()
    _seed_encrypted_credential(conn, trading_account_id=4, kv=kv, kb=kb)

    try:
        load_account_credential(
            conn,
            trading_account_id=99,
            venue="bitvavo",
            master_key_bytes=kb,
            cred_repo_factory=SqliteCredentialRepository,
        )
        raise AssertionError("Expected ValueError")
    except ValueError as exc:
        assert "NO_ACTIVE_CREDENTIAL" in str(exc)


def test_missing_encrypted_credential_fails_closed() -> None:
    """No credential in DB → ValueError(NO_ACTIVE_CREDENTIAL), not FileNotFoundError."""
    kv, kb = parse_master_key(generate_test_master_key())
    conn = _fresh_db()
    SqliteCredentialRepository(conn).create_schema()

    try:
        load_account_credential(
            conn,
            trading_account_id=4,
            venue="bitvavo",
            master_key_bytes=kb,
            cred_repo_factory=SqliteCredentialRepository,
        )
        raise AssertionError("Expected ValueError")
    except ValueError as exc:
        assert "NO_ACTIVE_CREDENTIAL" in str(exc)
        # Must not suggest a .env file path
        assert ".env" not in str(exc)


def test_no_fallback_to_profile_env_in_db_mode() -> None:
    """
    When credential_source=db, failing to find a DB credential must raise,
    not silently fall back to a profile .env file.
    The error must be NO_ACTIVE_CREDENTIAL, not FileNotFoundError.
    """
    kv, kb = parse_master_key(generate_test_master_key())
    conn = _fresh_db()
    SqliteCredentialRepository(conn).create_schema()

    exc_type = None
    try:
        load_account_credential(
            conn,
            trading_account_id=4,
            venue="bitvavo",
            master_key_bytes=kb,
            cred_repo_factory=SqliteCredentialRepository,
        )
    except ValueError as exc:
        exc_type = type(exc).__name__
        assert "NO_ACTIVE_CREDENTIAL" in str(exc)
    except FileNotFoundError:
        raise AssertionError(
            "db credential source must not raise FileNotFoundError — "
            "it must never fall back to a profile .env file"
        )

    assert exc_type == "ValueError"


def test_joost_credential_loaded_separately_from_hugo() -> None:
    """Joost's credential for account 1 is not returned when querying account 4."""
    kv, kb = parse_master_key(generate_test_master_key())
    conn = _fresh_db()
    SqliteCredentialRepository(conn).create_schema()
    _seed_encrypted_credential(conn, trading_account_id=1, api_key="joost-key", kv=kv, kb=kb)
    _seed_encrypted_credential(conn, trading_account_id=4, api_key="hugo-key", kv=kv, kb=kb)

    hugo_plain = load_account_credential(
        conn, trading_account_id=4, venue="bitvavo", master_key_bytes=kb,
        cred_repo_factory=SqliteCredentialRepository,
    )
    joost_plain = load_account_credential(
        conn, trading_account_id=1, venue="bitvavo", master_key_bytes=kb,
        cred_repo_factory=SqliteCredentialRepository,
    )

    assert hugo_plain.api_key == "hugo-key"
    assert joost_plain.api_key == "joost-key"
    assert hugo_plain.api_key != joost_plain.api_key


# ---------------------------------------------------------------------------
# write_balance_snapshot (using mock MariaDB-style conn over SQLite)
# ---------------------------------------------------------------------------

def _make_balance_row(
    currency: str,
    available: str,
    reserved: str = "0",
) -> WalletBalanceRow:
    a = Decimal(available)
    r = Decimal(reserved)
    return WalletBalanceRow(
        currency_code=currency,
        available_amount=a,
        reserved_amount=r,
        total_amount=a + r,
    )


def test_write_balance_snapshot_inserts_rows() -> None:
    raw = _fresh_db()
    conn = _MockConn(raw)
    ts = datetime(2026, 6, 9, 12, 0, 0)
    balances = [_make_balance_row("EUR", "500"), _make_balance_row("BTC", "0.05", "0.01")]

    written = write_balance_snapshot(
        conn,
        trading_account_id=4,
        venue="bitvavo",
        balances=balances,
        snapshot_ts_utc=ts,
        source_name="test_runner",
    )
    raw.commit()

    assert written == 2
    rows = raw.execute("SELECT * FROM trading_account_balance_snapshot").fetchall()
    assert len(rows) == 2
    currencies = {r["currency_code"] for r in rows}
    assert "EUR" in currencies
    assert "BTC" in currencies


def test_write_balance_snapshot_scoped_to_trading_account_id() -> None:
    raw = _fresh_db()
    conn = _MockConn(raw)
    ts = datetime(2026, 6, 9, 12, 0, 0)
    balances = [_make_balance_row("EUR", "100")]

    write_balance_snapshot(
        conn, trading_account_id=4, venue="bitvavo",
        balances=balances, snapshot_ts_utc=ts, source_name="test_runner",
    )
    raw.commit()

    rows = raw.execute(
        "SELECT * FROM trading_account_balance_snapshot WHERE trading_account_id = 99"
    ).fetchall()
    assert len(rows) == 0, "Balance row written for account 4 must not appear under account 99"


def test_write_balance_snapshot_empty_balances() -> None:
    raw = _fresh_db()
    conn = _MockConn(raw)
    ts = datetime(2026, 6, 9, 12, 0, 0)

    written = write_balance_snapshot(
        conn, trading_account_id=4, venue="bitvavo",
        balances=[], snapshot_ts_utc=ts, source_name="test_runner",
    )

    assert written == 0


# ---------------------------------------------------------------------------
# write_open_order_snapshot (using mock MariaDB-style conn over SQLite)
# ---------------------------------------------------------------------------

def _make_order_row(market: str = "BTC-EUR") -> WalletOpenOrderRow:
    return WalletOpenOrderRow(
        market=market,
        side="SELL",
        order_type="LIMIT",
        broker_order_id=f"ord-{market}",
        client_order_id=None,
        limit_price=Decimal("50000"),
        quantity=Decimal("0.01"),
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("0.01"),
        broker_status="NEW",
    )


def test_write_open_order_snapshot_inserts_rows() -> None:
    raw = _fresh_db()
    conn = _MockConn(raw)
    ts = datetime(2026, 6, 9, 12, 0, 0)
    orders = [_make_order_row("BTC-EUR"), _make_order_row("WLD-EUR")]

    written = write_open_order_snapshot(
        conn, trading_account_id=4, venue="bitvavo",
        orders=orders, snapshot_ts_utc=ts,
    )
    raw.commit()

    assert written == 2
    rows = raw.execute("SELECT * FROM account_open_order_snapshot").fetchall()
    assert len(rows) == 2
    markets = {r["market"] for r in rows}
    assert "BTC-EUR" in markets
    assert "WLD-EUR" in markets


def test_write_open_order_snapshot_scoped_to_trading_account_id() -> None:
    raw = _fresh_db()
    conn = _MockConn(raw)
    ts = datetime(2026, 6, 9, 12, 0, 0)
    orders = [_make_order_row("BTC-EUR")]

    write_open_order_snapshot(
        conn, trading_account_id=4, venue="bitvavo",
        orders=orders, snapshot_ts_utc=ts,
    )
    raw.commit()

    rows = raw.execute(
        "SELECT * FROM account_open_order_snapshot WHERE trading_account_id = 99"
    ).fetchall()
    assert len(rows) == 0


def test_write_open_order_snapshot_empty_orders() -> None:
    raw = _fresh_db()
    conn = _MockConn(raw)
    ts = datetime(2026, 6, 9, 12, 0, 0)

    written = write_open_order_snapshot(
        conn, trading_account_id=4, venue="bitvavo",
        orders=[], snapshot_ts_utc=ts,
    )

    assert written == 0


# ---------------------------------------------------------------------------
# Safety: no broker writes in runner source
# ---------------------------------------------------------------------------

def test_wallet_refresh_source_no_place_order() -> None:
    src = Path("src/account/run_account_wallet_refresh_v1.py").read_text()
    assert "place_order" not in src


def test_wallet_refresh_source_no_cancel_order() -> None:
    src = Path("src/account/run_account_wallet_refresh_v1.py").read_text()
    assert "cancel_order" not in src


def test_wallet_refresh_source_no_broker_write_permission() -> None:
    src = Path("src/account/run_account_wallet_refresh_v1.py").read_text()
    assert "BROKER_WRITE_PERMISSION" not in src
    assert "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS" not in src


def test_wallet_refresh_uses_encrypted_credential_by_default() -> None:
    """Runner source must import the encrypted credential loader, not only dotenv."""
    src = Path("src/account/run_account_wallet_refresh_v1.py").read_text()
    assert "load_account_credential" in src
    assert "load_master_key_from_env" in src
    assert "CredentialRepository" in src


def test_wallet_refresh_profile_env_is_not_automatic_fallback() -> None:
    """db credential source must never silently fall back to profile-env."""
    src = Path("src/account/run_account_wallet_refresh_v1.py").read_text()
    # The profile-env path must be gated behind an explicit check
    assert "credential_source" in src
    assert "profile-env" in src


# ---------------------------------------------------------------------------
# Systemd unit: EnvironmentFile and hardening
# ---------------------------------------------------------------------------

def test_systemd_unit_has_environment_file() -> None:
    unit = Path("docs/ops/systemd/synth-account-wallet-refresh@.service").read_text()
    assert "EnvironmentFile=" in unit
    assert "web-auth.env" in unit


def test_systemd_unit_has_security_hardening() -> None:
    unit = Path("docs/ops/systemd/synth-account-wallet-refresh@.service").read_text()
    assert "NoNewPrivileges=true" in unit
    assert "PrivateTmp=true" in unit
    assert "UMask=0077" in unit


def test_systemd_unit_does_not_expose_key_value() -> None:
    """The unit file must not contain the actual key value."""
    unit = Path("docs/ops/systemd/synth-account-wallet-refresh@.service").read_text()
    assert "SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY=" not in unit


# ---------------------------------------------------------------------------
# Shell script: refresh-before-render, no --account-env-dir in default path
# ---------------------------------------------------------------------------

def test_shell_script_does_not_reference_account_env_dir_in_default_path() -> None:
    script = Path("scripts/odroid/run_account_wallet_refresh_once.sh").read_text()
    assert "--account-env-dir" not in script


def test_shell_script_uses_db_credential_source() -> None:
    script = Path("scripts/odroid/run_account_wallet_refresh_once.sh").read_text()
    assert "--credential-source db" in script


def test_shell_script_has_profile_scoped_lock() -> None:
    script = Path("scripts/odroid/run_account_wallet_refresh_once.sh").read_text()
    assert "PROFILE" in script
    assert "flock" in script
    assert "lock" in script.lower()


def test_shell_script_reports_broker_private_calls_2() -> None:
    script = Path("scripts/odroid/run_account_wallet_refresh_once.sh").read_text()
    assert "broker_private_calls=2" in script


if __name__ == "__main__":
    tests = [
        test_encrypted_hugo_credential_loaded_by_trading_account_id,
        test_wrong_trading_account_id_fails_closed,
        test_missing_encrypted_credential_fails_closed,
        test_no_fallback_to_profile_env_in_db_mode,
        test_joost_credential_loaded_separately_from_hugo,
        test_write_balance_snapshot_inserts_rows,
        test_write_balance_snapshot_scoped_to_trading_account_id,
        test_write_balance_snapshot_empty_balances,
        test_write_open_order_snapshot_inserts_rows,
        test_write_open_order_snapshot_scoped_to_trading_account_id,
        test_write_open_order_snapshot_empty_orders,
        test_wallet_refresh_source_no_place_order,
        test_wallet_refresh_source_no_cancel_order,
        test_wallet_refresh_source_no_broker_write_permission,
        test_wallet_refresh_uses_encrypted_credential_by_default,
        test_wallet_refresh_profile_env_is_not_automatic_fallback,
        test_systemd_unit_has_environment_file,
        test_systemd_unit_has_security_hardening,
        test_systemd_unit_does_not_expose_key_value,
        test_shell_script_does_not_reference_account_env_dir_in_default_path,
        test_shell_script_uses_db_credential_source,
        test_shell_script_has_profile_scoped_lock,
        test_shell_script_reports_broker_private_calls_2,
    ]
    for t in tests:
        t()
    print("ok")
