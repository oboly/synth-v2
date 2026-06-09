"""
Integration tests for post-provisioning activation page creation.

Uses /tmp output root and an injected activation_renderer that writes
real HTML + JSON files — no broker calls, no MariaDB required.

Verifies:
  - all three required HTML pages created under /tmp
  - all six HTML + JSON files exist
  - all published files are mode 0644
  - Hugo HTML contains no /synth/accounts/joost/ cross-profile paths
  - failure of any required page yields refresh_pending=True
  - refresh_pending=False only when all pages succeed

broker_private_calls=0
broker_writes=0
order_submission=0
executor=none
"""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.account_provisioning.account_provisioning_service_v1 import (
    AccountProvisioningService,
    AuthenticatedProfileIdentity,
)
from src.account_provisioning.account_repository_v1 import SqliteAccountRepository
from src.account_provisioning.connect_bitvavo_v1 import (
    _REQUIRED_PAGE_STEMS,
    build_connect_bitvavo,
)
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
from src.account_provisioning.credential_validator_v1 import MockBitvavoCredentialValidator
from src.web.website_registration_v1 import SqliteWebsiteRegistrationRepository


_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
_DB_COUNTER = [0]


_SNAPSHOT_TABLES = """
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
CREATE TABLE IF NOT EXISTS broker_order_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_ts_utc TEXT NOT NULL,
    trading_account_id INTEGER NOT NULL,
    execution_intent_id INTEGER NULL,
    venue TEXT NOT NULL,
    symbol TEXT NOT NULL,
    broker_order_id TEXT NOT NULL,
    client_order_id TEXT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    limit_price_eur TEXT NULL,
    quantity_base TEXT NOT NULL,
    filled_quantity_base TEXT NOT NULL,
    remaining_quantity_base TEXT NOT NULL,
    broker_status TEXT NOT NULL,
    raw_json TEXT NOT NULL
);
"""


def _next_db() -> str:
    _DB_COUNTER[0] += 1
    return f"activation_pages_test_{_DB_COUNTER[0]}"


def _shared_conn(db_name: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_name}?mode=memory&cache=shared", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _seed_schema(db_name: str) -> sqlite3.Connection:
    conn = _shared_conn(db_name)
    SqliteWebsiteRegistrationRepository(conn).create_schema()
    SqliteAccountRepository(conn).create_schema()
    SqliteCredentialRepository(conn).create_schema()
    conn.executescript(_SNAPSHOT_TABLES)
    conn.commit()
    return conn


def _seed_fresh_profile(
    seed: sqlite3.Connection,
    *,
    master_key_bytes: bytes,
    kv: str,
    profile_code: str = "hugo",
) -> tuple[int, int]:
    """Seed profile with no account link yet. Returns (app_profile_id, ...)."""
    seed.execute(
        "INSERT OR IGNORE INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc)"
        " VALUES (?, ?, ?, ?)",
        (profile_code, "UTC", "NO_EXCHANGE_ACCOUNT_CONNECTED", "2026-06-09 12:00:00"),
    )
    seed.commit()
    pid = int(seed.execute(
        "SELECT app_profile_id FROM app_profile WHERE profile_code = ?", (profile_code,)
    ).fetchone()["app_profile_id"])
    return pid, 0


def _mock_client_ok() -> MagicMock:
    client = MagicMock()
    client.get_balance.return_value = [{"symbol": "EUR", "available": "500.00", "inOrder": "0"}]
    client.get_open_orders.return_value = []
    return client


def _mock_client_fail_balance() -> MagicMock:
    client = MagicMock()
    client.get_balance.side_effect = RuntimeError("balance API down")
    client.get_open_orders.return_value = []
    return client


def _make_file_renderer(output_root: Path, *, profile: str = "hugo") -> Any:
    """
    Returns an activation_renderer that writes real files to output_root.
    Writes wallet.html, open-orders-monitor.html, profit-plan.html and
    their JSON counterparts. All files set to mode 0644.
    Does not call get_connection() or any broker.
    """
    def renderer(*, profile_code: str, venue: str, output_root: Path) -> None:
        profile_dir = output_root / "accounts" / profile_code
        profile_dir.mkdir(parents=True, exist_ok=True)
        for stem in ("wallet", "open-orders-monitor", "profit-plan"):
            html = profile_dir / f"{stem}.html"
            jsn = profile_dir / f"{stem}.json"
            html.write_text(
                f"<!doctype html><html><body>"
                f"<a href='/synth/accounts/{profile_code}/{stem}.html'>{stem}</a>"
                f"</body></html>",
                encoding="utf-8",
            )
            html.chmod(0o644)
            jsn.write_text(json.dumps({"profile": profile_code, "page": stem}), encoding="utf-8")
            jsn.chmod(0o644)
        idx = profile_dir / "index.html"
        idx.write_text(
            f"<!doctype html><html><body>index for {profile_code}</body></html>",
            encoding="utf-8",
        )
        idx.chmod(0o644)

    return renderer


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


# ---------------------------------------------------------------------------
# Helper: build a connect callable with file renderer
# ---------------------------------------------------------------------------

def _build_connect(
    db_name: str,
    output_root: Path,
    *,
    client_factory=None,
    activation_renderer=None,
) -> tuple[Any, AccountProvisioningService, tuple[str, bytes]]:
    kv, kb = parse_master_key(generate_test_master_key())
    svc = AccountProvisioningService(
        credential_validator=MockBitvavoCredentialValidator(),
        master_key_version=kv,
        master_key_bytes=kb,
        account_repo_factory=SqliteAccountRepository,
        cred_repo_factory=SqliteCredentialRepository,
    )
    renderer = activation_renderer if activation_renderer is not None else _make_file_renderer(output_root)
    connect = build_connect_bitvavo(
        provisioning_service=svc,
        conn_factory=lambda: _shared_conn(db_name),
        master_key_bytes=kb,
        cred_repo_factory=SqliteCredentialRepository,
        bitvavo_client_factory=lambda ak, _as: (client_factory() if client_factory else _mock_client_ok()),
        activation_renderer=renderer,
        output_root=output_root,
    )
    return connect, svc, (kv, kb)


# ---------------------------------------------------------------------------
# Test: all three HTML + JSON pages created
# ---------------------------------------------------------------------------

def test_all_required_pages_created() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    pid, _ = _seed_fresh_profile(seed, master_key_bytes=b"\x00" * 32, kv="v1")
    kv, kb = parse_master_key(generate_test_master_key())

    with tempfile.TemporaryDirectory() as tmpdir:
        output_root = Path(tmpdir)
        connect, svc, _ = _build_connect(db, output_root)
        # Re-seed with correct master key
        seed2 = _seed_schema(_next_db())
        db2 = f"activation_pages_test_{_DB_COUNTER[0]}"
        seed2.execute(
            "INSERT OR IGNORE INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc)"
            " VALUES (?, ?, ?, ?)",
            ("hugo", "UTC", "NO_EXCHANGE_ACCOUNT_CONNECTED", "2026-06-09 12:00:00"),
        )
        seed2.commit()
        pid2 = int(seed2.execute("SELECT app_profile_id FROM app_profile WHERE profile_code = 'hugo'").fetchone()["app_profile_id"])
        kv2, kb2 = parse_master_key(generate_test_master_key())
        connect2, _, _ = _build_connect(db2, output_root)

        identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid2, profile_code="hugo")
        result = connect2(identity, "mock-valid-read-only-key", "test-secret", True, _NOW)

        assert result.ok is True
        profile_dir = output_root / "accounts" / "hugo"
        for stem in _REQUIRED_PAGE_STEMS:
            assert (profile_dir / f"{stem}.html").exists(), f"missing {stem}.html"
            assert (profile_dir / f"{stem}.json").exists(), f"missing {stem}.json"
        seed2.close()
    seed.close()


def test_all_required_pages_mode_0644() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    seed.execute(
        "INSERT OR IGNORE INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc)"
        " VALUES (?, ?, ?, ?)",
        ("hugo", "UTC", "NO_EXCHANGE_ACCOUNT_CONNECTED", "2026-06-09 12:00:00"),
    )
    seed.commit()
    pid = int(seed.execute("SELECT app_profile_id FROM app_profile WHERE profile_code = 'hugo'").fetchone()["app_profile_id"])

    with tempfile.TemporaryDirectory() as tmpdir:
        output_root = Path(tmpdir)
        connect, _, _ = _build_connect(db, output_root)
        identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
        result = connect(identity, "mock-valid-read-only-key", "test-secret", True, _NOW)

        assert result.ok is True
        profile_dir = output_root / "accounts" / "hugo"
        for stem in _REQUIRED_PAGE_STEMS:
            for ext in (".html", ".json"):
                p = profile_dir / f"{stem}{ext}"
                assert p.exists(), f"missing {stem}{ext}"
                assert _mode(p) == 0o644, f"{stem}{ext} mode is {oct(_mode(p))}, expected 0o644"
    seed.close()


def test_hugo_html_contains_no_joost_paths() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    seed.execute(
        "INSERT OR IGNORE INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc)"
        " VALUES (?, ?, ?, ?)",
        ("hugo", "UTC", "NO_EXCHANGE_ACCOUNT_CONNECTED", "2026-06-09 12:00:00"),
    )
    seed.commit()
    pid = int(seed.execute("SELECT app_profile_id FROM app_profile WHERE profile_code = 'hugo'").fetchone()["app_profile_id"])

    with tempfile.TemporaryDirectory() as tmpdir:
        output_root = Path(tmpdir)
        connect, _, _ = _build_connect(db, output_root)
        identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
        result = connect(identity, "mock-valid-read-only-key", "test-secret", True, _NOW)

        assert result.ok is True
        profile_dir = output_root / "accounts" / "hugo"
        for stem in _REQUIRED_PAGE_STEMS:
            html = profile_dir / f"{stem}.html"
            if html.exists():
                content = html.read_text(encoding="utf-8")
                assert "/synth/accounts/joost/" not in content, \
                    f"{stem}.html contains cross-profile path /synth/accounts/joost/"
    seed.close()


def test_refresh_pending_false_when_all_pages_succeed() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    seed.execute(
        "INSERT OR IGNORE INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc)"
        " VALUES (?, ?, ?, ?)",
        ("hugo", "UTC", "NO_EXCHANGE_ACCOUNT_CONNECTED", "2026-06-09 12:00:00"),
    )
    seed.commit()
    pid = int(seed.execute("SELECT app_profile_id FROM app_profile WHERE profile_code = 'hugo'").fetchone()["app_profile_id"])

    with tempfile.TemporaryDirectory() as tmpdir:
        output_root = Path(tmpdir)
        connect, _, _ = _build_connect(db, output_root)
        identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
        result = connect(identity, "mock-valid-read-only-key", "test-secret", True, _NOW)

        assert result.ok is True
        assert result.refresh_pending is False
        assert result.refresh_error_code is None
    seed.close()


def test_refresh_pending_true_when_snapshot_fails() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    seed.execute(
        "INSERT OR IGNORE INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc)"
        " VALUES (?, ?, ?, ?)",
        ("hugo", "UTC", "NO_EXCHANGE_ACCOUNT_CONNECTED", "2026-06-09 12:00:00"),
    )
    seed.commit()
    pid = int(seed.execute("SELECT app_profile_id FROM app_profile WHERE profile_code = 'hugo'").fetchone()["app_profile_id"])

    with tempfile.TemporaryDirectory() as tmpdir:
        output_root = Path(tmpdir)
        connect, _, _ = _build_connect(
            db, output_root, client_factory=_mock_client_fail_balance
        )
        identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
        result = connect(identity, "mock-valid-read-only-key", "test-secret", True, _NOW)

        assert result.ok is True
        assert result.refresh_pending is True
        assert result.refresh_error_code is not None
        # Pages must NOT have been created (snapshot failed, renderer not reached)
        profile_dir = output_root / "accounts" / "hugo"
        for stem in _REQUIRED_PAGE_STEMS:
            assert not (profile_dir / f"{stem}.html").exists(), \
                f"{stem}.html should not exist when snapshot failed"
    seed.close()


def test_refresh_pending_true_when_renderer_fails() -> None:
    db = _next_db()
    seed = _seed_schema(db)
    seed.execute(
        "INSERT OR IGNORE INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc)"
        " VALUES (?, ?, ?, ?)",
        ("hugo", "UTC", "NO_EXCHANGE_ACCOUNT_CONNECTED", "2026-06-09 12:00:00"),
    )
    seed.commit()
    pid = int(seed.execute("SELECT app_profile_id FROM app_profile WHERE profile_code = 'hugo'").fetchone()["app_profile_id"])

    def _failing(**_kwargs: Any) -> None:
        raise RuntimeError("disk full")

    with tempfile.TemporaryDirectory() as tmpdir:
        output_root = Path(tmpdir)
        connect, _, _ = _build_connect(db, output_root, activation_renderer=_failing)
        identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
        result = connect(identity, "mock-valid-read-only-key", "test-secret", True, _NOW)

        assert result.ok is True
        assert result.refresh_pending is True
        assert result.refresh_error_code == "ACTIVATION_RENDER_FAILED"
    seed.close()


# ---------------------------------------------------------------------------
# Safe retry: ACCOUNT_ALREADY_CONNECTED also creates all pages
# ---------------------------------------------------------------------------

def test_retry_creates_all_pages_on_already_connected() -> None:
    """Safe retry (already connected) must also produce all three required pages."""
    db = _next_db()
    seed = _seed_schema(db)
    kv, kb = parse_master_key(generate_test_master_key())

    # Seed fully connected profile
    seed.execute(
        "INSERT OR IGNORE INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc)"
        " VALUES (?, ?, ?, ?)",
        ("hugo", "UTC", "READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED", "2026-06-09 12:00:00"),
    )
    seed.commit()
    pid = int(seed.execute("SELECT app_profile_id FROM app_profile WHERE profile_code = 'hugo'").fetchone()["app_profile_id"])

    seed.execute(
        "INSERT INTO trading_account (account_code, venue, account_mode, enabled, live_trading_enabled, created_ts_utc)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        ("hugo-bitvavo", "bitvavo", "paper", 1, 0, "2026-06-09 12:00:00"),
    )
    seed.commit()
    ta_id = int(seed.execute(
        "SELECT trading_account_id FROM trading_account WHERE account_code = 'hugo-bitvavo'"
    ).fetchone()["trading_account_id"])

    plain = PlainBitvavoCredential(venue="bitvavo", api_key="hugo-api-key", api_secret="hugo-api-secret")
    envelope = encrypt_credential(plain, ta_id, kv, kb)
    fingerprint = compute_fingerprint("bitvavo", "hugo-api-key", kb)
    SqliteCredentialRepository(seed).insert_active_credential(
        trading_account_id=ta_id,
        venue="bitvavo",
        credential_kind=CREDENTIAL_KIND_API_KEY_SECRET,
        encrypted_envelope=envelope.to_json(),
        encryption_algorithm=envelope.alg,
        key_version=envelope.kv,
        credential_fingerprint=fingerprint,
        now_utc=_NOW,
        validation_state="VALID_PRIVATE_READ",
    )
    seed.execute(
        "INSERT INTO app_profile_trading_account_link"
        " (app_profile_id, trading_account_id, link_status, is_primary, created_ts_utc)"
        " VALUES (?, ?, 'ACTIVE', 1, ?)",
        (pid, ta_id, "2026-06-09 12:00:00"),
    )
    seed.commit()

    with tempfile.TemporaryDirectory() as tmpdir:
        output_root = Path(tmpdir)
        svc = AccountProvisioningService(
            credential_validator=MockBitvavoCredentialValidator(),
            master_key_version=kv,
            master_key_bytes=kb,
            account_repo_factory=SqliteAccountRepository,
            cred_repo_factory=SqliteCredentialRepository,
        )
        connect = build_connect_bitvavo(
            provisioning_service=svc,
            conn_factory=lambda: _shared_conn(db),
            master_key_bytes=kb,
            cred_repo_factory=SqliteCredentialRepository,
            bitvavo_client_factory=lambda ak, _as: _mock_client_ok(),
            activation_renderer=_make_file_renderer(output_root),
            output_root=output_root,
        )
        identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
        result = connect(identity, "mock-valid-read-only-key", "test-secret", True, _NOW)

        assert result.ok is True
        assert result.refresh_pending is False
        profile_dir = output_root / "accounts" / "hugo"
        for stem in _REQUIRED_PAGE_STEMS:
            assert (profile_dir / f"{stem}.html").exists(), f"missing {stem}.html on retry"
            assert _mode(profile_dir / f"{stem}.html") == 0o644
    seed.close()


# ---------------------------------------------------------------------------
# Architecture checks
# ---------------------------------------------------------------------------

def test_required_page_stems_covers_all_three_pages() -> None:
    assert "wallet" in _REQUIRED_PAGE_STEMS
    assert "open-orders-monitor" in _REQUIRED_PAGE_STEMS
    assert "profit-plan" in _REQUIRED_PAGE_STEMS
    assert len(_REQUIRED_PAGE_STEMS) == 3


def test_no_global_env_fallback_in_connect_module() -> None:
    source = Path("src/account_provisioning/connect_bitvavo_v1.py").read_text()
    assert "BITVAVO_API_KEY" not in source
    assert "BITVAVO_API_SECRET" not in source
    assert "os.getenv" not in source
    assert "os.environ" not in source


def test_no_broker_writes_in_connect_module() -> None:
    source = Path("src/account_provisioning/connect_bitvavo_v1.py").read_text()
    assert "place_order" not in source
    assert "cancel_order" not in source


if __name__ == "__main__":
    tests = [
        test_all_required_pages_created,
        test_all_required_pages_mode_0644,
        test_hugo_html_contains_no_joost_paths,
        test_refresh_pending_false_when_all_pages_succeed,
        test_refresh_pending_true_when_snapshot_fails,
        test_refresh_pending_true_when_renderer_fails,
        test_retry_creates_all_pages_on_already_connected,
        test_required_page_stems_covers_all_three_pages,
        test_no_global_env_fallback_in_connect_module,
        test_no_broker_writes_in_connect_module,
    ]
    for t in tests:
        t()
    print("ok")
