"""
Activation rendering contract regression tests.

Covers:
  - OOM build_json_snapshot current signature (no broker_mode, has profile/account_code/etc.)
  - PP build_json_snapshot current signature (has broker_mode)
  - PP render_full_html current signature
  - _ActivationStageError carries stage name
  - Partial stage failure keeps refresh_pending=True with diagnostic code
  - All seven required files created on full success (index + wallet/json + oom/json + pp/json)
  - No partial success reported as complete

broker_private_calls=0
broker_writes=0
order_submission=0
executor=none
"""
from __future__ import annotations

import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.reporting.manual_short_trader_dashboard_v1 import (
    BrokerBalanceRow,
    BrokerOrderRow,
    build_all_sections,
    build_json_snapshot as oom_build_json,
)
from src.reporting.manual_short_trader_profit_plan_v1 import (
    build_json_snapshot as pp_build_json,
    render_full_html as pp_render_full_html,
)


# ---------------------------------------------------------------------------
# OOM build_json_snapshot — current signature contract
# ---------------------------------------------------------------------------

def test_oom_build_json_accepts_profile_kwargs() -> None:
    """build_json_snapshot must accept profile/account_code/trading_account_id/venue/market_count."""
    sections = build_all_sections([], [], {})
    snap = oom_build_json(
        sections,
        profile="hugo",
        account_code="hugo-bitvavo",
        trading_account_id=4,
        venue="bitvavo",
        market_count=3,
    )
    assert snap["profile"] == "hugo"
    assert snap["account_code"] == "hugo-bitvavo"
    assert snap["trading_account_id"] == 4
    assert snap["venue"] == "bitvavo"
    assert snap["market_count"] == 3


def test_oom_build_json_rejects_broker_mode() -> None:
    """broker_mode is NOT part of OOM build_json_snapshot — must raise TypeError."""
    import inspect
    sig = inspect.signature(oom_build_json)
    assert "broker_mode" not in sig.parameters, (
        "OOM build_json_snapshot must not accept broker_mode — "
        "this was the root cause of the activation crash"
    )


def test_oom_build_json_safety_markers_present() -> None:
    sections = build_all_sections([], [], {})
    snap = oom_build_json(sections)
    assert snap["broker_writes"] == 0
    assert snap["order_submission"] == 0
    assert snap["live_orders"] == 0
    assert snap["executor"] == "none"


def test_oom_build_json_market_count_override() -> None:
    """market_count kwarg overrides section length."""
    sections = build_all_sections([], [], {})
    snap = oom_build_json(sections, market_count=7)
    assert snap["market_count"] == 7


# ---------------------------------------------------------------------------
# PP build_json_snapshot — current signature contract
# ---------------------------------------------------------------------------

def test_pp_build_json_accepts_broker_mode() -> None:
    snap = pp_build_json([], broker_mode="db_snapshot")
    assert snap["broker_mode"] == "db_snapshot"


def test_pp_build_json_accepts_writer_and_render_ids() -> None:
    snap = pp_build_json([], writer_instance_id="w-id", render_id="r-id")
    assert snap["writer_instance_id"] == "w-id"
    assert snap["render_id"] == "r-id"


def test_pp_build_json_safety_markers_present() -> None:
    snap = pp_build_json([])
    assert snap["broker_writes"] == 0
    assert snap["order_submission"] == 0
    assert snap["executor"] == "none"


# ---------------------------------------------------------------------------
# PP render_full_html — current signature contract
# ---------------------------------------------------------------------------

def test_pp_render_full_html_accepts_broker_mode() -> None:
    html = pp_render_full_html([], broker_mode="db_snapshot")
    assert "db_snapshot" in html


def test_pp_render_full_html_accepts_storage_scope() -> None:
    html = pp_render_full_html([], storage_scope="hugo")
    assert "hugo" in html


def test_pp_render_full_html_accepts_nav_html() -> None:
    html = pp_render_full_html([], nav_html="<nav>test</nav>")
    assert "<nav>test</nav>" in html


# ---------------------------------------------------------------------------
# _ActivationStageError — carries stage name
# ---------------------------------------------------------------------------

def test_activation_stage_error_has_stage_attribute() -> None:
    from src.account_provisioning.connect_bitvavo_v1 import _ActivationStageError
    exc = _ActivationStageError(stage="wallet", profile_code="hugo")
    assert exc.stage == "wallet"
    assert "wallet" in str(exc)
    assert "hugo" in str(exc)
    assert "ACTIVATION_STAGE_FAILED" in str(exc)


def test_activation_stage_error_does_not_expose_secrets() -> None:
    from src.account_provisioning.connect_bitvavo_v1 import _ActivationStageError
    exc = _ActivationStageError(stage="open-orders-monitor", profile_code="hugo")
    msg = str(exc)
    assert "api_key" not in msg.lower()
    assert "api_secret" not in msg.lower()
    assert "password" not in msg.lower()


# ---------------------------------------------------------------------------
# Partial failure → refresh_pending=True
# ---------------------------------------------------------------------------

def _make_partial_renderer(fail_stage: str) -> Any:
    """Returns a renderer that succeeds on wallet+index but fails on the named stage."""
    def renderer(*, profile_code: str, venue: str, output_root: Path) -> None:
        profile_dir = output_root / "accounts" / profile_code
        profile_dir.mkdir(parents=True, exist_ok=True)
        for stem in ("wallet", "index"):
            p = profile_dir / f"{stem}.html"
            p.write_text(f"<!doctype html><body>{stem}</body>", encoding="utf-8")
            p.chmod(0o644)
            jsn = profile_dir / f"{stem}.json"
            jsn.write_text("{}", encoding="utf-8")
            jsn.chmod(0o644)
        if fail_stage == "open-orders-monitor":
            from src.account_provisioning.connect_bitvavo_v1 import _ActivationStageError
            raise _ActivationStageError(stage="open-orders-monitor", profile_code=profile_code)
        if fail_stage == "profit-plan":
            from src.account_provisioning.connect_bitvavo_v1 import _ActivationStageError
            raise _ActivationStageError(stage="profit-plan", profile_code=profile_code)
    return renderer


def _build_connect_with_renderer(renderer: Any, output_root: Path) -> Any:
    import sqlite3
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    from src.account_provisioning.account_provisioning_service_v1 import AccountProvisioningService
    from src.account_provisioning.account_repository_v1 import SqliteAccountRepository
    from src.account_provisioning.connect_bitvavo_v1 import build_connect_bitvavo
    from src.account_provisioning.credential_crypto_v1 import generate_test_master_key, parse_master_key
    from src.account_provisioning.credential_repository_v1 import SqliteCredentialRepository
    from src.account_provisioning.credential_validator_v1 import MockBitvavoCredentialValidator
    from src.web.website_registration_v1 import SqliteWebsiteRegistrationRepository

    _SNAPSHOT_DDL = """
    CREATE TABLE IF NOT EXISTS trading_account_balance_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_ts_utc TEXT NOT NULL,
        trading_account_id INTEGER NOT NULL, venue TEXT NOT NULL,
        currency_code TEXT NOT NULL, available_amount TEXT NOT NULL,
        reserved_amount TEXT NOT NULL, total_amount TEXT NOT NULL,
        source_name TEXT NOT NULL, raw_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS broker_order_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_ts_utc TEXT NOT NULL,
        trading_account_id INTEGER NOT NULL, execution_intent_id INTEGER NULL,
        venue TEXT NOT NULL, symbol TEXT NOT NULL, broker_order_id TEXT NOT NULL,
        client_order_id TEXT NULL, side TEXT NOT NULL, order_type TEXT NOT NULL,
        limit_price_eur TEXT NULL, quantity_base TEXT NOT NULL,
        filled_quantity_base TEXT NOT NULL, remaining_quantity_base TEXT NOT NULL,
        broker_status TEXT NOT NULL, raw_json TEXT NOT NULL
    );
    """

    import uuid
    db_name = f"rendering_contract_{uuid.uuid4().hex}"

    def shared_conn():
        c = sqlite3.connect(f"file:{db_name}?mode=memory&cache=shared", uri=True)
        c.row_factory = sqlite3.Row
        return c

    seed = shared_conn()
    SqliteWebsiteRegistrationRepository(seed).create_schema()
    SqliteAccountRepository(seed).create_schema()
    SqliteCredentialRepository(seed).create_schema()
    seed.executescript(_SNAPSHOT_DDL)
    seed.execute(
        "INSERT OR IGNORE INTO app_profile (profile_code, display_timezone, onboarding_state, created_ts_utc)"
        " VALUES (?, ?, ?, ?)",
        ("hugo", "UTC", "NO_EXCHANGE_ACCOUNT_CONNECTED", "2026-06-09 12:00:00"),
    )
    seed.commit()
    pid = int(seed.execute("SELECT app_profile_id FROM app_profile WHERE profile_code='hugo'").fetchone()["app_profile_id"])

    kv, kb = parse_master_key(generate_test_master_key())
    svc = AccountProvisioningService(
        credential_validator=MockBitvavoCredentialValidator(),
        master_key_version=kv,
        master_key_bytes=kb,
        account_repo_factory=SqliteAccountRepository,
        cred_repo_factory=SqliteCredentialRepository,
    )
    client = MagicMock()
    client.get_balance.return_value = [{"symbol": "EUR", "available": "500.00", "inOrder": "0"}]
    client.get_open_orders.return_value = []

    connect = build_connect_bitvavo(
        provisioning_service=svc,
        conn_factory=shared_conn,
        master_key_bytes=kb,
        cred_repo_factory=SqliteCredentialRepository,
        bitvavo_client_factory=lambda ak, _s: client,
        activation_renderer=renderer,
        output_root=output_root,
    )
    return connect, pid, seed


def test_partial_stage_failure_gives_refresh_pending_true() -> None:
    from datetime import UTC, datetime
    from src.account_provisioning.account_provisioning_service_v1 import AuthenticatedProfileIdentity

    with tempfile.TemporaryDirectory() as tmpdir:
        output_root = Path(tmpdir)
        renderer = _make_partial_renderer("open-orders-monitor")
        connect, pid, seed = _build_connect_with_renderer(renderer, output_root)
        identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
        result = connect(identity, "mock-valid-read-only-key", "secret", True, datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC))
        assert result.ok is True
        assert result.refresh_pending is True
        assert result.refresh_error_code == "ACTIVATION_RENDER_FAILED"
        seed.close()


def test_full_success_gives_refresh_pending_false_and_seven_files() -> None:
    from datetime import UTC, datetime
    from src.account_provisioning.account_provisioning_service_v1 import AuthenticatedProfileIdentity

    _REQUIRED = [
        "index.html",
        "wallet.html", "wallet.json",
        "open-orders-monitor.html", "open-orders-monitor.json",
        "profit-plan.html", "profit-plan.json",
    ]

    def _full_renderer(*, profile_code: str, venue: str, output_root: Path) -> None:
        d = output_root / "accounts" / profile_code
        d.mkdir(parents=True, exist_ok=True)
        for fname in _REQUIRED:
            p = d / fname
            p.write_text(f"<!-- {fname} -->", encoding="utf-8")
            p.chmod(0o644)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_root = Path(tmpdir)
        connect, pid, seed = _build_connect_with_renderer(_full_renderer, output_root)
        identity = AuthenticatedProfileIdentity(app_user_id=1, app_profile_id=pid, profile_code="hugo")
        result = connect(identity, "mock-valid-read-only-key", "secret", True, datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC))
        assert result.ok is True
        assert result.refresh_pending is False

        profile_dir = output_root / "accounts" / "hugo"
        for fname in _REQUIRED:
            assert (profile_dir / fname).exists(), f"missing {fname}"
        seed.close()


if __name__ == "__main__":
    tests = [
        test_oom_build_json_accepts_profile_kwargs,
        test_oom_build_json_rejects_broker_mode,
        test_oom_build_json_safety_markers_present,
        test_oom_build_json_market_count_override,
        test_pp_build_json_accepts_broker_mode,
        test_pp_build_json_accepts_writer_and_render_ids,
        test_pp_build_json_safety_markers_present,
        test_pp_render_full_html_accepts_broker_mode,
        test_pp_render_full_html_accepts_storage_scope,
        test_pp_render_full_html_accepts_nav_html,
        test_activation_stage_error_has_stage_attribute,
        test_activation_stage_error_does_not_expose_secrets,
        test_partial_stage_failure_gives_refresh_pending_true,
        test_full_success_gives_refresh_pending_false_and_seven_files,
    ]
    for t in tests:
        t()
    print("ok")
