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
    insert_asset,
    insert_balance,
    bind_account_market,
    insert_complete_bundle,
    insert_exit_profile,
    insert_market_price,
    insert_permission,
    insert_position,
    insert_trading_account,
    insert_venue_market,
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
    bind_account_market(conn, account_id=9, venue_market_id=insert_venue_market(conn, asset_id=102, symbol="ETH", market="ETH-EUR"))
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
    insert_asset(conn, asset_id=102, symbol="ETH")
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
        "items_manual_action_required": 0,
        "items_not_executable": 0,
        "audit_rows_inserted": 1,
        "audit_rows_idempotent": 0,
    }


def test_mixed_automated_and_manual_account_snapshot_does_not_fail_manual_item() -> None:
    """Issue #653: a MANUAL_RFQ position (e.g. MDT) must not be ITEM_FAILED for
    missing automated market identity, while the automated position alongside
    it is unaffected."""
    conn = FakeConnection()
    seed_happy_path(conn, account_id=7)  # AUTOMATED BTC position, unchanged behavior
    insert_asset(conn, asset_id=1372, symbol="MDT", execution_mode="MANUAL_RFQ")
    insert_position(
        conn, account_id=7, asset_id=1372, symbol="MDT",
        quantity_base=Decimal("40"), available_quantity_base=Decimal("40"),
    )
    insert_balance(conn, account_id=7, currency_code="MDT", available_amount=Decimal("40"))
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE account_state_snapshot_run_v1 SET position_snapshot_count = %s WHERE trading_account_id = %s",
            (2, 7),
        )

    summary = run_cycle(conn, venue="bitvavo", now=NOW)

    assert summary.items_considered == 2
    assert summary.items_failed == 0
    assert not any("POSITION_MARKET_IDENTITY_MISSING" in failure for failure in summary.failures)
    assert summary.items_manual_action_required == 1
    assert summary.items_not_executable == 0
    assert any(
        "MANUAL_ACTION_REQUIRED" in line and "symbol=MDT" in line and "held_quantity_base=40" in line
        for line in summary.manual_actions
    )
    # The automated BTC position still reaches the audit table unchanged.
    with conn.cursor() as cur:
        cur.execute("SELECT asset_id FROM automatic_exit_evaluation_audit_v1")
        rows = cur.fetchall()
    assert [row["asset_id"] for row in rows] == [101]


def test_none_execution_mode_is_not_counted_as_item_failed() -> None:
    conn = FakeConnection()
    seed_happy_path(conn, account_id=7)
    insert_asset(conn, asset_id=301, symbol="DELISTED", execution_mode="NONE")
    insert_position(
        conn, account_id=7, asset_id=301, symbol="DELISTED",
        quantity_base=Decimal("5"), available_quantity_base=Decimal("5"),
    )
    insert_balance(conn, account_id=7, currency_code="DELISTED", available_amount=Decimal("5"))
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE account_state_snapshot_run_v1 SET position_snapshot_count = %s WHERE trading_account_id = %s",
            (2, 7),
        )

    summary = run_cycle(conn, venue="bitvavo", now=NOW)

    assert summary.items_failed == 0
    assert summary.items_not_executable == 1
    assert any("NOT_EXECUTABLE" in line and "symbol=DELISTED" in line for line in summary.manual_actions)


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
    with pytest.raises(ValueError, match="canonical runtime lock"):
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

    assert exit_code != 0
    captured = capsys.readouterr()
    assert "result=lock_unavailable" in captured.err
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM automatic_exit_evaluation_audit_v1")
        assert cur.fetchone()["c"] == 0


def test_lock_is_released_after_normal_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    connections = [FakeConnection(), FakeConnection()]
    for conn in connections:
        seed_happy_path(conn)
    monkeypatch.setattr(runner_module, "get_db_connection", lambda: connections.pop(0))
    args = parse_args(["--lock-file", str(tmp_path / "runtime.lock"), "--skip-ownership-check"])
    assert run(args) == 0
    assert run(args) == 0


def test_runtime_service_is_bounded_oneshot_without_executor_or_credentials() -> None:
    unit = (Path(__file__).resolve().parents[1] / "deploy/systemd/synth-automatic-exit-policy-runtime.service").read_text()
    assert "Type=oneshot" in unit
    assert "Restart=no" in unit
    assert "TimeoutStartSec=10min" in unit
    assert "ConditionHost=gurkdb" in unit
    assert unit.count("ExecStart=") == 1
    assert "executor" not in unit.lower()
    assert "CREDENTIAL" not in unit
