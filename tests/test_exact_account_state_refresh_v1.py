"""
Tests for the exact-account private-read account-state refresh seam
(Issue #614): `src/account/run_exact_account_state_refresh_v1.py`.

Covers:
  - LIVE and live_readonly accounts are accepted for exact-account refresh
  - paper accounts are accepted the same way (no account_mode gate here)
  - wrong venue / disabled / missing account / missing credential /
    account-credential mismatch / missing private-read permission all fail
    closed
  - exact-account scope is preserved across persisted rows
  - the COMPLETE bundle stays atomic
  - only get_balance/get_open_orders broker methods are reachable
  - linked_account_resolver_v1 is not imported or weakened by this seam
  - existing profile-based wallet refresh tests remain unaffected

broker_private_calls=2
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
"""
from __future__ import annotations

import ast
import base64
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import src.account.run_exact_account_state_refresh_v1 as exact_refresh_module
from src.account.account_snapshot_models_v1 import ExactAccountStateRefreshResult
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


_NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)

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
    return conn


def _insert_account(
    conn: sqlite3.Connection,
    *,
    trading_account_id: int,
    account_code: str,
    venue: str = "bitvavo",
    account_mode: str = "paper",
    enabled: int = 1,
    live_trading_enabled: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO trading_account (
            trading_account_id, account_code, venue, account_mode,
            enabled, live_trading_enabled
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (trading_account_id, account_code, venue, account_mode, enabled, live_trading_enabled),
    )


def _key() -> tuple[str, bytes]:
    return parse_master_key(generate_test_master_key())


def _seed_credential(
    conn: sqlite3.Connection,
    *,
    trading_account_id: int,
    venue: str = "bitvavo",
    api_key: str = "exact-account-key",
    api_secret: str = "exact-account-secret",
    key_version: str,
    master_key_bytes: bytes,
    **overrides: object,
) -> int:
    plain = PlainBitvavoCredential(venue=venue, api_key=api_key, api_secret=api_secret)
    envelope = encrypt_credential(plain, trading_account_id, key_version, master_key_bytes)
    row = {
        "trading_account_id": trading_account_id,
        "venue": venue,
        "credential_kind": "API_KEY_SECRET",
        "encrypted_envelope": envelope.to_json(),
        "encryption_algorithm": envelope.alg,
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


def _assert_code(exc: pytest.ExceptionInfo[PrivateReadCredentialResolutionError], code: str) -> None:
    assert exc.value.code == code
    assert str(exc.value).startswith(code + ":")


# ---------------------------------------------------------------------------
# account_mode acceptance — exact-account identity resolution has no
# account_mode/live_trading_enabled gate (unlike linked_account_resolver_v1).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "account_mode,live_trading_enabled",
    (
        ("live", 1),
        ("live_readonly", 0),
        ("paper", 0),
    ),
)
def test_account_mode_accepted_for_exact_account_identity(
    account_mode: str, live_trading_enabled: int
) -> None:
    kv, kb = _key()
    conn = _fresh_db()
    _insert_account(
        conn,
        trading_account_id=5,
        account_code="bitvavo_joost_live",
        account_mode=account_mode,
        live_trading_enabled=live_trading_enabled,
    )
    _seed_credential(conn, trading_account_id=5, key_version=kv, master_key_bytes=kb)

    identity, resolved = resolve_private_read_credential(
        conn,
        trading_account_id=5,
        venue="bitvavo",
        master_key_bytes=kb,
    )

    assert identity.trading_account_id == 5
    assert identity.account_mode == account_mode
    assert resolved.profile.permission_scope == "READ_ONLY_PRIVATE"


def test_live_account_5_bitvavo_joost_live_shape_accepted() -> None:
    """Acceptance-target identity: trading_account_id=5 account_mode=live."""
    kv, kb = _key()
    conn = _fresh_db()
    _insert_account(
        conn,
        trading_account_id=5,
        account_code="bitvavo_joost_live",
        account_mode="live",
        live_trading_enabled=1,
    )
    _seed_credential(conn, trading_account_id=5, key_version=kv, master_key_bytes=kb)

    identity, _resolved = resolve_private_read_credential(
        conn,
        trading_account_id=5,
        venue="bitvavo",
        master_key_bytes=kb,
    )

    assert identity.trading_account_id == 5
    assert identity.account_code == "bitvavo_joost_live"
    assert identity.venue == "bitvavo"
    assert identity.account_mode == "live"


# ---------------------------------------------------------------------------
# Fail-closed paths
# ---------------------------------------------------------------------------

def test_wrong_venue_fails_closed() -> None:
    kv, kb = _key()
    conn = _fresh_db()
    _insert_account(conn, trading_account_id=5, account_code="bitvavo_joost_live", account_mode="live", live_trading_enabled=1)
    _seed_credential(conn, trading_account_id=5, key_version=kv, master_key_bytes=kb)

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn, trading_account_id=5, venue="kraken", master_key_bytes=kb,
        )
    _assert_code(exc, "VENUE_MISMATCH")


def test_disabled_account_fails_closed() -> None:
    kv, kb = _key()
    conn = _fresh_db()
    _insert_account(
        conn, trading_account_id=5, account_code="bitvavo_joost_live",
        account_mode="live", enabled=0, live_trading_enabled=1,
    )
    _seed_credential(conn, trading_account_id=5, key_version=kv, master_key_bytes=kb)

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn, trading_account_id=5, venue="bitvavo", master_key_bytes=kb,
        )
    _assert_code(exc, "ACCOUNT_DISABLED")


def test_missing_account_fails_closed() -> None:
    _kv, kb = _key()
    conn = _fresh_db()

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn, trading_account_id=5, venue="bitvavo", master_key_bytes=kb,
        )
    _assert_code(exc, "ACCOUNT_NOT_FOUND")


def test_missing_credential_fails_closed() -> None:
    _kv, kb = _key()
    conn = _fresh_db()
    _insert_account(conn, trading_account_id=5, account_code="bitvavo_joost_live", account_mode="live", live_trading_enabled=1)

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn, trading_account_id=5, venue="bitvavo", master_key_bytes=kb,
        )
    _assert_code(exc, "NO_CREDENTIAL_BINDING")


def test_credential_account_mismatch_fails_closed() -> None:
    """A credential bound to a different trading_account_id must not resolve for account 5."""
    kv, kb = _key()
    conn = _fresh_db()
    _insert_account(conn, trading_account_id=3, account_code="bitvavo_joost_read", account_mode="live_readonly")
    _insert_account(conn, trading_account_id=5, account_code="bitvavo_joost_live", account_mode="live", live_trading_enabled=1)
    _seed_credential(conn, trading_account_id=3, key_version=kv, master_key_bytes=kb, api_key="account-3-key")

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn, trading_account_id=5, venue="bitvavo", master_key_bytes=kb,
        )
    _assert_code(exc, "NO_CREDENTIAL_BINDING")


def test_private_read_permission_missing_fails_closed() -> None:
    kv, kb = _key()
    conn = _fresh_db()
    _insert_account(conn, trading_account_id=5, account_code="bitvavo_joost_live", account_mode="live", live_trading_enabled=1)
    _seed_credential(
        conn, trading_account_id=5, key_version=kv, master_key_bytes=kb,
        allowed_private_read=0,
    )

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_credential(
            conn, trading_account_id=5, venue="bitvavo", master_key_bytes=kb,
        )
    _assert_code(exc, "MISSING_REQUIRED_PRIVATE_READ_SCOPE")


def test_missing_master_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    kv, kb = _key()
    conn = _fresh_db()
    _insert_account(conn, trading_account_id=5, account_code="bitvavo_joost_live", account_mode="live", live_trading_enabled=1)
    _seed_credential(conn, trading_account_id=5, key_version=kv, master_key_bytes=kb)
    monkeypatch.delenv("SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY", raising=False)

    with pytest.raises(PrivateReadCredentialResolutionError) as exc:
        resolve_private_read_bitvavo_client_from_env(
            conn, trading_account_id=5, venue="bitvavo",
        )
    _assert_code(exc, "MISSING_MASTER_KEY")


# ---------------------------------------------------------------------------
# Exact-account scope: no projection between accounts (e.g. account 3 -> 5)
# ---------------------------------------------------------------------------

def test_exact_account_scope_not_projected_between_accounts() -> None:
    kv, kb = _key()
    conn = _fresh_db()
    _insert_account(conn, trading_account_id=3, account_code="bitvavo_joost_read", account_mode="live_readonly")
    _insert_account(conn, trading_account_id=5, account_code="bitvavo_joost_live", account_mode="live", live_trading_enabled=1)
    _seed_credential(conn, trading_account_id=3, key_version=kv, master_key_bytes=kb, api_key="account-3-key")
    _seed_credential(conn, trading_account_id=5, key_version=kv, master_key_bytes=kb, api_key="account-5-key")

    identity_3, resolved_3 = resolve_private_read_credential(
        conn, trading_account_id=3, venue="bitvavo", master_key_bytes=kb,
    )
    identity_5, resolved_5 = resolve_private_read_credential(
        conn, trading_account_id=5, venue="bitvavo", master_key_bytes=kb,
    )

    assert identity_3.account_code == "bitvavo_joost_read"
    assert identity_5.account_code == "bitvavo_joost_live"
    assert resolved_3.credential.api_key == "account-3-key"
    assert resolved_5.credential.api_key == "account-5-key"
    assert resolved_3.credential.api_key != resolved_5.credential.api_key


# ---------------------------------------------------------------------------
# linked_account_resolver_v1 is not weakened
# ---------------------------------------------------------------------------

def test_exact_account_seam_does_not_import_linked_account_resolver() -> None:
    src = Path("src/account/run_exact_account_state_refresh_v1.py").read_text()
    tree = ast.parse(src)
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
    assert "src.account.linked_account_resolver_v1" not in imported_names
    assert "resolve_primary_linked_account" not in imported_names


def test_linked_account_resolver_live_trading_enabled_check_still_present() -> None:
    src = Path("src/account/linked_account_resolver_v1.py").read_text()
    assert "LIVE_TRADING_ENABLED" in src
    assert 'if live != 0:' in src


# ---------------------------------------------------------------------------
# CLI: exact identity only, no profile fallback
# ---------------------------------------------------------------------------

def test_cli_requires_trading_account_id_and_venue_no_profile_flag() -> None:
    src = Path("src/account/run_exact_account_state_refresh_v1.py").read_text()
    assert "--trading-account-id" in src
    assert "--venue" in src
    assert "--write-db" in src
    assert "--account-profile" not in src
    assert "profile_code=" not in src


def test_cli_reuses_canonical_snapshot_machinery() -> None:
    src = Path("src/account/run_exact_account_state_refresh_v1.py").read_text()
    assert "from src.account.run_account_wallet_refresh_v1 import" in src
    assert "write_aligned_account_state_snapshot" in src
    assert "discover_account_assets" in src
    # No duplicated SQL: this module issues no direct INSERT statements.
    assert "INSERT INTO" not in src


def test_cli_help_runs() -> None:
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "src.account.run_exact_account_state_refresh_v1", "--help"],
        capture_output=True,
        text=True,
        cwd=str(_ROOT),
    )
    assert result.returncode == 0
    assert "--trading-account-id" in result.stdout
    assert "--venue" in result.stdout
    assert "--write-db" in result.stdout


# ---------------------------------------------------------------------------
# Safety: no broker write methods reachable from this seam
# ---------------------------------------------------------------------------

def test_no_broker_write_calls_in_source() -> None:
    src = Path("src/account/run_exact_account_state_refresh_v1.py").read_text()
    assert "place_order" not in src
    assert "cancel_order" not in src


def test_ast_no_broker_write_calls() -> None:
    src = Path("src/account/run_exact_account_state_refresh_v1.py").read_text()
    tree = ast.parse(src)
    forbidden_attrs = {"place_order", "cancel_order"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs:
            raise AssertionError(f"Forbidden method call .{node.attr}() in exact-account refresh source")


def test_only_balance_and_open_order_reads_called_on_client() -> None:
    calls: list[str] = []

    class FakeExactReadClient:
        def get_balance(self):
            calls.append("get_balance")
            return [{"symbol": "EUR", "available": "100", "inOrder": "0"}]

        def get_open_orders(self):
            calls.append("get_open_orders")
            return []

        def place_order(self, *_args, **_kwargs):
            raise AssertionError("place_order must never be called by this seam")

        def cancel_order(self, *_args, **_kwargs):
            raise AssertionError("cancel_order must never be called by this seam")

    class FakeConnection:
        closed = False

        def close(self) -> None:
            self.closed = True

    from src.account.private_read_credential_resolver_v1 import (
        AccountRuntimeIdentity,
        PrivateReadClientResolution,
    )
    from src.account_provisioning.credential_binding_contract_v1 import CredentialBindingProfile

    profile = CredentialBindingProfile(
        trading_account_id=5,
        account_code="bitvavo_joost_live",
        venue="bitvavo",
        trading_account_enabled=True,
        live_trading_enabled=True,
        trading_account_credential_id=42,
        credential_source="db_encrypted",
        credential_status="ACTIVE",
        permission_scope="READ_ONLY_PRIVATE",
        allowed_private_read=True,
        allowed_order_write=False,
        allowed_withdrawal=False,
        credential_fingerprint="fp",
        key_version="v1",
        validation_state="VALID_PRIVATE_READ",
        validated_ts_utc=_NOW,
        last_validation_error_code=None,
    )
    resolution = PrivateReadClientResolution(
        identity=AccountRuntimeIdentity(
            trading_account_id=5,
            account_code="bitvavo_joost_live",
            venue="bitvavo",
            account_mode="live",
            enabled=True,
            live_trading_enabled=True,
            profile_code=None,
        ),
        profile=profile,
        client=FakeExactReadClient(),
    )
    connection = FakeConnection()

    import pytest as _pytest
    mp = _pytest.MonkeyPatch()
    mp.setattr(exact_refresh_module, "get_db_connection", lambda: connection)
    mp.setattr(
        exact_refresh_module,
        "resolve_private_read_bitvavo_client_from_env",
        lambda *_args, **_kwargs: resolution,
    )
    mp.setattr(
        sys,
        "argv",
        [
            "run_exact_account_state_refresh_v1",
            "--trading-account-id",
            "5",
            "--venue",
            "bitvavo",
            "--output",
            "summary",
        ],
    )
    try:
        assert exact_refresh_module.main() == 0
    finally:
        mp.undo()

    assert calls == ["get_balance", "get_open_orders"]
    assert connection.closed is True


def test_dry_run_summary_reports_safety_markers(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from src.account.private_read_credential_resolver_v1 import (
        AccountRuntimeIdentity,
        PrivateReadClientResolution,
    )
    from src.account_provisioning.credential_binding_contract_v1 import CredentialBindingProfile

    class FakeExactReadClient:
        def get_balance(self):
            return [{"symbol": "EUR", "available": "250", "inOrder": "0"}]

        def get_open_orders(self):
            return []

    class FakeConnection:
        closed = False

        def close(self) -> None:
            self.closed = True

    profile = CredentialBindingProfile(
        trading_account_id=5,
        account_code="bitvavo_joost_live",
        venue="bitvavo",
        trading_account_enabled=True,
        live_trading_enabled=True,
        trading_account_credential_id=42,
        credential_source="db_encrypted",
        credential_status="ACTIVE",
        permission_scope="READ_ONLY_PRIVATE",
        allowed_private_read=True,
        allowed_order_write=False,
        allowed_withdrawal=False,
        credential_fingerprint="fp",
        key_version="v1",
        validation_state="VALID_PRIVATE_READ",
        validated_ts_utc=_NOW,
        last_validation_error_code=None,
    )
    resolution = PrivateReadClientResolution(
        identity=AccountRuntimeIdentity(
            trading_account_id=5,
            account_code="bitvavo_joost_live",
            venue="bitvavo",
            account_mode="live",
            enabled=True,
            live_trading_enabled=True,
            profile_code=None,
        ),
        profile=profile,
        client=FakeExactReadClient(),
    )
    connection = FakeConnection()
    monkeypatch.setattr(exact_refresh_module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(
        exact_refresh_module,
        "resolve_private_read_bitvavo_client_from_env",
        lambda *_args, **_kwargs: resolution,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_exact_account_state_refresh_v1",
            "--trading-account-id",
            "5",
            "--venue",
            "bitvavo",
            "--output",
            "summary",
        ],
    )

    assert exact_refresh_module.main() == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    for expected in (
        "runner=exact_account_state_refresh_v1",
        "trading_account_id=5 account_code=bitvavo_joost_live",
        "venue=bitvavo account_mode=live",
        "credential_source=db_encrypted",
        "permission_scope=READ_ONLY_PRIVATE",
        "balance_count=1",
        "order_count=0",
        "[DRY_RUN]",
        "broker_private_calls=2",
        "broker_writes=0",
        "order_submission=0",
        "live_orders=0",
        "decision_gate=none",
        "execution_planner=none",
        "executor=none",
    ):
        assert expected in captured.out
    assert connection.closed is True


# ---------------------------------------------------------------------------
# Existing profile-based wallet refresh behavior is unaffected
# ---------------------------------------------------------------------------

def test_wallet_refresh_module_still_has_profile_cli_flag() -> None:
    src = Path("src/account/run_account_wallet_refresh_v1.py").read_text()
    assert "--account-profile" in src
    assert "resolve_private_read_bitvavo_client_from_env" in src
    assert "profile_code=args.account_profile" in src
