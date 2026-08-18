import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.decision_gate.automatic_exit_live_permission_contract_v1 import (
    AutomaticExitLiveDecisionGatePermissionV1,
    AutomaticExitLivePermissionContractError,
    resolve_automatic_exit_live_decision_gate_permission_v1,
)


NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


def _row(**changes: object) -> AutomaticExitLiveDecisionGatePermissionV1:
    values: dict[str, object] = dict(
        permission_id=1, trading_account_id=7, live_execution_permitted=True,
        effective_from_ts_utc=NOW - timedelta(days=1), effective_until_ts_utc=None,
        permission_version="1", source_provenance="manual_review",
    )
    values.update(changes)
    return AutomaticExitLiveDecisionGatePermissionV1(**values)  # type: ignore[arg-type]


def test_no_row_denies() -> None:
    assert resolve_automatic_exit_live_decision_gate_permission_v1((), trading_account_id=7, at=NOW) is False


def test_single_active_row_grants_or_denies_by_flag() -> None:
    assert resolve_automatic_exit_live_decision_gate_permission_v1((_row(),), trading_account_id=7, at=NOW) is True
    assert resolve_automatic_exit_live_decision_gate_permission_v1(
        (_row(live_execution_permitted=False),), trading_account_id=7, at=NOW,
    ) is False


def test_wrong_account_row_never_grants_permission() -> None:
    """A row belonging to a different account must not leak permission to this lookup."""
    result = resolve_automatic_exit_live_decision_gate_permission_v1(
        (_row(trading_account_id=8),), trading_account_id=7, at=NOW,
    )
    assert result is False


def test_overlapping_rows_fail_closed() -> None:
    rows = (_row(permission_id=1), _row(permission_id=2))
    with pytest.raises(AutomaticExitLivePermissionContractError, match="CONFLICTING_AUTOMATIC_EXIT_LIVE_PERMISSION"):
        resolve_automatic_exit_live_decision_gate_permission_v1(rows, trading_account_id=7, at=NOW)


def test_unsupported_version_fails_closed() -> None:
    with pytest.raises(AutomaticExitLivePermissionContractError, match="INVALID_OR_UNSUPPORTED_AUTOMATIC_EXIT_LIVE_PERMISSION"):
        resolve_automatic_exit_live_decision_gate_permission_v1(
            (_row(permission_version="2"),), trading_account_id=7, at=NOW,
        )


def test_malformed_window_fails_closed() -> None:
    with pytest.raises(AutomaticExitLivePermissionContractError):
        resolve_automatic_exit_live_decision_gate_permission_v1(
            (_row(effective_until_ts_utc=NOW - timedelta(days=2)),), trading_account_id=7, at=NOW,
        )
    with pytest.raises(AutomaticExitLivePermissionContractError):
        resolve_automatic_exit_live_decision_gate_permission_v1(
            (_row(source_provenance=""),), trading_account_id=7, at=NOW,
        )


def test_effective_window_expiry_denies_after_close() -> None:
    row = _row(effective_from_ts_utc=NOW - timedelta(days=2), effective_until_ts_utc=NOW - timedelta(days=1))
    assert resolve_automatic_exit_live_decision_gate_permission_v1((row,), trading_account_id=7, at=NOW) is False


def test_future_dated_grant_not_yet_effective_denies() -> None:
    row = _row(effective_from_ts_utc=NOW + timedelta(days=1))
    assert resolve_automatic_exit_live_decision_gate_permission_v1((row,), trading_account_id=7, at=NOW) is False


def test_non_overlapping_history_resolves_current_row_only() -> None:
    """Superseding a permission (close old row, insert new one) must resolve the current row, not raise."""
    old = _row(permission_id=1, live_execution_permitted=False, effective_until_ts_utc=NOW - timedelta(hours=1))
    new = _row(permission_id=2, live_execution_permitted=True, effective_from_ts_utc=NOW - timedelta(hours=1))
    assert resolve_automatic_exit_live_decision_gate_permission_v1((old, new), trading_account_id=7, at=NOW) is True


def test_invalid_lookup_arguments_fail_closed() -> None:
    with pytest.raises(AutomaticExitLivePermissionContractError, match="INVALID_LIVE_PERMISSION_LOOKUP"):
        resolve_automatic_exit_live_decision_gate_permission_v1((), trading_account_id=0, at=NOW)
    with pytest.raises(AutomaticExitLivePermissionContractError, match="INVALID_LIVE_PERMISSION_LOOKUP"):
        resolve_automatic_exit_live_decision_gate_permission_v1((), trading_account_id=7, at=NOW.replace(tzinfo=None))


def test_contract_module_has_no_db_broker_credential_or_executor_imports() -> None:
    tree = ast.parse((Path("src/decision_gate") / "automatic_exit_live_permission_contract_v1.py").read_text())
    imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    ]
    assert not any(
        any(word in name for word in ("executor", "broker", "credential", "kill_switch", "manual_execution"))
        for name in imports
    )


def test_repository_module_has_no_broker_credential_or_executor_imports() -> None:
    tree = ast.parse((Path("src/decision_gate") / "automatic_exit_live_permission_repository_v1.py").read_text())
    imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    ]
    assert not any(
        any(word in name for word in ("executor", "broker", "credential", "kill_switch", "manual_execution"))
        for name in imports
    )
