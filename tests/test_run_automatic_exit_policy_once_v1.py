from __future__ import annotations

import fcntl
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import src.exit_policy.run_automatic_exit_policy_once_v1 as runner_module
from src.exit_policy.run_automatic_exit_policy_once_v1 import (
    RuntimeOwnershipError,
    default_lock_path,
    parse_args,
    run,
    run_cycle,
    validate_lock_path,
    verify_runtime_ownership,
)
from tests.automatic_exit_runtime_fixtures_v1 import (
    FakeConnection,
    TS,
    insert_balance,
    insert_complete_bundle,
    insert_exit_profile,
    insert_market_price,
    insert_permission,
    insert_position,
    insert_trading_account,
    insert_venue_constraint,
    seed_happy_path,
)


NOW = TS + timedelta(minutes=5)


def test_multi_account_cycle_isolation() -> None:
    conn = FakeConnection()
    seed_happy_path(conn, account_id=7)
    insert_trading_account(conn, account_id=9)
    insert_complete_bundle(conn, account_id=9)
    insert_position(conn, account_id=9, asset_id=102, symbol="ETH")
    insert_balance(conn, account_id=9, currency_code="ETH")
    insert_market_price(conn, symbol="ETH", market="ETH-EUR")
    insert_exit_profile(conn, profile_id="eth-profile", asset_id=102, market="ETH-EUR")
    insert_permission(conn, account_id=9)
    insert_venue_constraint(conn, market="ETH-EUR")

    summary = run_cycle(conn, venue="bitvavo", now=NOW)
    assert summary.accounts_considered == 2
    assert summary.items_considered == 2
    assert summary.items_failed == 0
    with conn.cursor() as cur:
        cur.execute("SELECT trading_account_id FROM automatic_exit_evaluation_audit_v1 ORDER BY trading_account_id")
        rows = cur.fetchall()
    assert [row["trading_account_id"] for row in rows] == [7, 9]


def test_item_local_failure_does_not_abort_unrelated_item() -> None:
    conn = FakeConnection()
    seed_happy_path(conn, account_id=7)  # healthy BTC item
    insert_trading_account(conn, account_id=9)
    insert_complete_bundle(conn, account_id=9)
    insert_position(conn, account_id=9, asset_id=102, symbol="ETH")
    # deliberately no balance row for account 9's ETH -> BALANCE_ROW_MISSING

    summary = run_cycle(conn, venue="bitvavo", now=NOW)
    assert summary.items_considered == 2
    assert summary.items_failed == 1
    assert any("BALANCE_ROW_MISSING" in failure for failure in summary.failures)
    with conn.cursor() as cur:
        cur.execute("SELECT trading_account_id FROM automatic_exit_evaluation_audit_v1")
        rows = cur.fetchall()
    assert [row["trading_account_id"] for row in rows] == [7]


def test_account_with_no_evidence_is_skipped_not_fatal() -> None:
    conn = FakeConnection()
    seed_happy_path(conn, account_id=7)
    insert_trading_account(conn, account_id=9)  # enabled, but no COMPLETE bundle at all

    summary = run_cycle(conn, venue="bitvavo", now=NOW)
    assert summary.accounts_considered == 2
    assert summary.accounts_skipped_no_evidence == 1
    assert summary.items_considered == 1


def test_deterministic_cycle_summary_shape() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    summary = run_cycle(conn, venue="bitvavo", now=NOW)
    payload = summary.as_dict()
    assert payload == {
        "accounts_considered": 1,
        "accounts_skipped_no_evidence": 0,
        "items_considered": 1,
        "items_no_action": 1,
        "items_non_actionable": 0,
        "items_denied": 0,
        "items_planner_rejected": 0,
        "items_staged": 0,
        "items_failed": 0,
        "audit_rows_inserted": 1,
        "audit_rows_idempotent": 0,
    }


def test_verify_runtime_ownership_passes_for_matching_registry(tmp_path: Path) -> None:
    registry_dir = tmp_path / "deploy" / "ownership"
    registry_dir.mkdir(parents=True)
    (registry_dir / "account_runtime_capability_ownership_v1.json").write_text(
        json.dumps({"capabilities": [{"capability_id": "AUTOMATIC_EXIT_POLICY_RUNTIME", "owner_host": "gurkdb"}]})
    )
    verify_runtime_ownership(repo_root=tmp_path, expect_owner_host="gurkdb")


def test_verify_runtime_ownership_fails_closed_on_mismatch(tmp_path: Path) -> None:
    registry_dir = tmp_path / "deploy" / "ownership"
    registry_dir.mkdir(parents=True)
    (registry_dir / "account_runtime_capability_ownership_v1.json").write_text(
        json.dumps({"capabilities": [{"capability_id": "AUTOMATIC_EXIT_POLICY_RUNTIME", "owner_host": "odroid"}]})
    )
    with pytest.raises(RuntimeOwnershipError, match="OWNERSHIP_HOST_MISMATCH"):
        verify_runtime_ownership(repo_root=tmp_path, expect_owner_host="gurkdb")


def test_verify_runtime_ownership_fails_closed_on_missing_registry(tmp_path: Path) -> None:
    with pytest.raises(RuntimeOwnershipError, match="OWNERSHIP_REGISTRY_UNREADABLE"):
        verify_runtime_ownership(repo_root=tmp_path, expect_owner_host="gurkdb")


def test_lock_path_under_tmp_is_rejected() -> None:
    with pytest.raises(ValueError, match="PrivateTmp"):
        validate_lock_path(Path("/tmp/automatic-exit-policy-runtime.lock"))


def test_default_lock_path_is_under_home_state_dir() -> None:
    path = default_lock_path()
    assert str(path).endswith(".local/state/synth/runtime/locks/automatic-exit-policy-runtime.lock")


def test_concurrent_lock_prevents_second_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    monkeypatch.setattr(runner_module, "get_db_connection", lambda: conn)

    lock_path = tmp_path / "automatic-exit-policy-runtime.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    held_handle = lock_path.open("a+b")
    fcntl.flock(held_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        args = parse_args([
            "--venue", "bitvavo", "--lock-file", str(lock_path), "--skip-ownership-check",
        ])
        exit_code = run(args)
    finally:
        fcntl.flock(held_handle.fileno(), fcntl.LOCK_UN)
        held_handle.close()

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "result=skipped_locked" in captured.out
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM automatic_exit_evaluation_audit_v1")
        assert cur.fetchone()["c"] == 0
