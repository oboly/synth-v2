import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.decision_gate.automatic_exit_live_permission_contract_v1 import (
    AutomaticExitLiveDecisionGatePermissionRevocationV1,
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


def _revocation(**changes: object) -> AutomaticExitLiveDecisionGatePermissionRevocationV1:
    values: dict[str, object] = dict(
        revocation_id=1, permission_id=1, trading_account_id=7,
        revocation_version="1", effective_ts_utc=NOW, actor="operator-v1", reason="superseded",
    )
    values.update(changes)
    return AutomaticExitLiveDecisionGatePermissionRevocationV1(**values)  # type: ignore[arg-type]


def test_no_row_denies_by_returning_none() -> None:
    assert resolve_automatic_exit_live_decision_gate_permission_v1((), trading_account_id=7, at=NOW) is None


def test_single_active_row_resolves_with_its_flag() -> None:
    granted = resolve_automatic_exit_live_decision_gate_permission_v1((_row(),), trading_account_id=7, at=NOW)
    assert granted is not None and granted.live_execution_permitted is True

    denied = resolve_automatic_exit_live_decision_gate_permission_v1(
        (_row(live_execution_permitted=False),), trading_account_id=7, at=NOW,
    )
    assert denied is not None and denied.live_execution_permitted is False


def test_wrong_account_row_never_leaks_permission() -> None:
    """A row belonging to a different account must not leak into this lookup."""
    result = resolve_automatic_exit_live_decision_gate_permission_v1(
        (_row(trading_account_id=8),), trading_account_id=7, at=NOW,
    )
    assert result is None


def test_overlapping_non_revoked_rows_fail_closed() -> None:
    rows = (_row(permission_id=1), _row(permission_id=2))
    with pytest.raises(AutomaticExitLivePermissionContractError, match="CONFLICTING_AUTOMATIC_EXIT_LIVE_PERMISSION"):
        resolve_automatic_exit_live_decision_gate_permission_v1(rows, trading_account_id=7, at=NOW)


def test_unsupported_permission_version_fails_closed() -> None:
    with pytest.raises(AutomaticExitLivePermissionContractError, match="INVALID_OR_UNSUPPORTED_AUTOMATIC_EXIT_LIVE_PERMISSION"):
        resolve_automatic_exit_live_decision_gate_permission_v1(
            (_row(permission_version="2"),), trading_account_id=7, at=NOW,
        )


def test_malformed_window_or_provenance_fails_closed() -> None:
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
    assert resolve_automatic_exit_live_decision_gate_permission_v1((row,), trading_account_id=7, at=NOW) is None


def test_future_dated_grant_not_yet_effective_denies() -> None:
    row = _row(effective_from_ts_utc=NOW + timedelta(days=1))
    assert resolve_automatic_exit_live_decision_gate_permission_v1((row,), trading_account_id=7, at=NOW) is None


def test_invalid_lookup_arguments_fail_closed() -> None:
    with pytest.raises(AutomaticExitLivePermissionContractError, match="INVALID_LIVE_PERMISSION_LOOKUP"):
        resolve_automatic_exit_live_decision_gate_permission_v1((), trading_account_id=0, at=NOW)
    with pytest.raises(AutomaticExitLivePermissionContractError, match="INVALID_LIVE_PERMISSION_LOOKUP"):
        resolve_automatic_exit_live_decision_gate_permission_v1((), trading_account_id=7, at=NOW.replace(tzinfo=None))


# --- Revocation lifecycle -----------------------------------------------


def test_open_ended_permission_can_be_revoked_immutably() -> None:
    """An open-ended TRUE permission is revoked via an immutable fact, never mutation."""
    permission = _row(effective_until_ts_utc=None)
    revocation = _revocation(effective_ts_utc=NOW - timedelta(hours=1))
    result = resolve_automatic_exit_live_decision_gate_permission_v1(
        (permission,), (revocation,), trading_account_id=7, at=NOW,
    )
    assert result is None


def test_permission_inactive_at_and_after_effective_revocation_timestamp() -> None:
    permission = _row(effective_until_ts_utc=None)
    revoke_at = NOW
    revocation = _revocation(effective_ts_utc=revoke_at)
    at_revocation = resolve_automatic_exit_live_decision_gate_permission_v1(
        (permission,), (revocation,), trading_account_id=7, at=revoke_at,
    )
    after_revocation = resolve_automatic_exit_live_decision_gate_permission_v1(
        (permission,), (revocation,), trading_account_id=7, at=revoke_at + timedelta(seconds=1),
    )
    assert at_revocation is None
    assert after_revocation is None


def test_future_revocation_does_not_revoke_early() -> None:
    permission = _row(effective_until_ts_utc=None)
    revocation = _revocation(effective_ts_utc=NOW + timedelta(days=1))
    result = resolve_automatic_exit_live_decision_gate_permission_v1(
        (permission,), (revocation,), trading_account_id=7, at=NOW,
    )
    assert result is not None and result.live_execution_permitted is True


def test_future_revocation_does_not_block_later_immediate_revocation() -> None:
    permission = _row(effective_until_ts_utc=None)
    future_revocation = _revocation(revocation_id=1, effective_ts_utc=NOW + timedelta(days=7))
    immediate_revocation = _revocation(revocation_id=2, effective_ts_utc=NOW)
    result = resolve_automatic_exit_live_decision_gate_permission_v1(
        (permission,), (future_revocation, immediate_revocation), trading_account_id=7, at=NOW,
    )
    assert result is None


def test_malformed_revocation_fails_closed() -> None:
    permission = _row()
    # Dangling reference.
    with pytest.raises(AutomaticExitLivePermissionContractError, match="INVALID_AUTOMATIC_EXIT_LIVE_PERMISSION_REVOCATION"):
        resolve_automatic_exit_live_decision_gate_permission_v1(
            (permission,), (_revocation(permission_id=999),), trading_account_id=7, at=NOW,
        )
    # effective_ts_utc at/before the permission's own effective_from.
    with pytest.raises(AutomaticExitLivePermissionContractError, match="INVALID_AUTOMATIC_EXIT_LIVE_PERMISSION_REVOCATION"):
        resolve_automatic_exit_live_decision_gate_permission_v1(
            (permission,), (_revocation(effective_ts_utc=permission.effective_from_ts_utc),),
            trading_account_id=7, at=NOW,
        )
    # Empty actor/reason.
    with pytest.raises(AutomaticExitLivePermissionContractError, match="INVALID_AUTOMATIC_EXIT_LIVE_PERMISSION_REVOCATION"):
        resolve_automatic_exit_live_decision_gate_permission_v1(
            (permission,), (_revocation(actor="   "),), trading_account_id=7, at=NOW,
        )


def test_unsupported_revocation_version_fails_closed() -> None:
    permission = _row()
    with pytest.raises(AutomaticExitLivePermissionContractError, match="UNSUPPORTED_AUTOMATIC_EXIT_LIVE_PERMISSION_REVOCATION_VERSION"):
        resolve_automatic_exit_live_decision_gate_permission_v1(
            (permission,), (_revocation(revocation_version="2"),), trading_account_id=7, at=NOW,
        )


def test_cross_account_revocation_fails_closed_defense_in_depth() -> None:
    """The DB composite FK rejects this structurally; the resolver still validates defensively.

    A revocation whose own denormalized trading_account_id (7, matching the
    lookup account) disagrees with the account actually owning the
    permission row it references (99) is a corrupt cross-account reference.
    """
    other_account_permission = _row(permission_id=1, trading_account_id=99)
    mismatched_revocation = _revocation(permission_id=1, trading_account_id=7)
    with pytest.raises(AutomaticExitLivePermissionContractError, match="AUTOMATIC_EXIT_LIVE_PERMISSION_REVOCATION_ACCOUNT_MISMATCH"):
        resolve_automatic_exit_live_decision_gate_permission_v1(
            (other_account_permission,), (mismatched_revocation,), trading_account_id=7, at=NOW,
        )


def test_replay_deterministic_independent_of_row_ordering() -> None:
    permission = _row(effective_until_ts_utc=None)
    future_revocation = _revocation(revocation_id=1, effective_ts_utc=NOW + timedelta(days=7))
    immediate_revocation = _revocation(revocation_id=2, effective_ts_utc=NOW - timedelta(hours=1))
    forward = resolve_automatic_exit_live_decision_gate_permission_v1(
        (permission,), (future_revocation, immediate_revocation), trading_account_id=7, at=NOW,
    )
    backward = resolve_automatic_exit_live_decision_gate_permission_v1(
        (permission,), (immediate_revocation, future_revocation), trading_account_id=7, at=NOW,
    )
    assert forward == backward == None  # noqa: E711 (explicit None-equality readability)


def test_account_a_revocation_cannot_affect_account_b_permission() -> None:
    permission_a = _row(permission_id=1, trading_account_id=7, effective_until_ts_utc=None)
    permission_b = _row(permission_id=2, trading_account_id=8, effective_until_ts_utc=None)
    revocation_a = _revocation(revocation_id=1, permission_id=1, trading_account_id=7, effective_ts_utc=NOW - timedelta(hours=1))
    result_a = resolve_automatic_exit_live_decision_gate_permission_v1(
        (permission_a, permission_b), (revocation_a,), trading_account_id=7, at=NOW,
    )
    result_b = resolve_automatic_exit_live_decision_gate_permission_v1(
        (permission_a, permission_b), (revocation_a,), trading_account_id=8, at=NOW,
    )
    assert result_a is None
    assert result_b is not None and result_b.live_execution_permitted is True


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


def test_evaluation_seam_has_no_broker_credential_or_executor_imports() -> None:
    tree = ast.parse((Path("src/decision_gate") / "automatic_exit_live_permission_evaluation_v1.py").read_text())
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
