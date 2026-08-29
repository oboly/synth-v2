"""Issue #588: canonical append-only grant path for
``automatic_exit_live_decision_gate_permission_v1``.

Covers eligibility (account existence/enabled/mode/live_trading_enabled),
idempotency, conflict/overlap fail-closed behavior, revocation interaction,
append-only immutability (no UPDATE/DELETE ever issued), rollback on insert
failure, and strict multi-account isolation.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from src.decision_gate.automatic_exit_live_permission_grant_v1 import (
    CHECK_STATE_ALREADY_GRANTED,
    CHECK_STATE_READY_TO_GRANT,
    REASON_ACCOUNT_DISABLED,
    REASON_ACCOUNT_NOT_LIVE_MODE,
    REASON_CONFLICTING_LIVE_PERMISSION_STATE,
    REASON_LIVE_TRADING_NOT_ENABLED,
    REASON_OK,
    REASON_OVERLAPPING_LIVE_PERMISSION_STATE,
    REASON_UNKNOWN_TRADING_ACCOUNT,
    AutomaticExitLivePermissionGrantError,
    AutomaticExitLivePermissionGrantRequestV1,
    apply_automatic_exit_live_permission_grant_v1,
    check_automatic_exit_live_permission_grant_v1,
)
from src.decision_gate.automatic_exit_live_permission_repository_v1 import (
    load_automatic_exit_live_permission_history_v1,
)
from tests.automatic_exit_runtime_fixtures_v1 import (
    TS,
    FakeConnection,
    insert_live_permission,
    insert_live_permission_revocation,
    insert_trading_account,
)

ACCOUNT = 5
OTHER_ACCOUNT_2 = 2
OTHER_ACCOUNT_3 = 3


def _live_ready_account(conn: FakeConnection, *, account_id: int = ACCOUNT) -> None:
    insert_trading_account(
        conn, account_id=account_id, account_mode="live", enabled=True, live_trading_enabled=True,
    )


def _request(*, account_id: int = ACCOUNT, requested_ts_utc=TS) -> AutomaticExitLivePermissionGrantRequestV1:
    return AutomaticExitLivePermissionGrantRequestV1(
        trading_account_id=account_id,
        requested_ts_utc=requested_ts_utc,
        permission_version="1",
        source_provenance="operator_cli_grant_v1",
    )


def test_check_when_no_grant_exists_reports_ready() -> None:
    conn = FakeConnection()
    _live_ready_account(conn)
    result = check_automatic_exit_live_permission_grant_v1(conn, request=_request())
    assert result.check_state == CHECK_STATE_READY_TO_GRANT
    assert result.reason_code == REASON_OK
    assert result.existing_permission_id is None


def test_check_does_not_write() -> None:
    conn = FakeConnection()
    _live_ready_account(conn)
    check_automatic_exit_live_permission_grant_v1(conn, request=_request())
    rows = load_automatic_exit_live_permission_history_v1(conn, trading_account_id=ACCOUNT)
    assert rows == ()


def test_apply_first_grant_inserts_row() -> None:
    conn = FakeConnection()
    _live_ready_account(conn)
    result = apply_automatic_exit_live_permission_grant_v1(conn, request=_request())
    assert result.idempotent is False
    assert result.trading_account_id == ACCOUNT
    rows = load_automatic_exit_live_permission_history_v1(conn, trading_account_id=ACCOUNT)
    assert len(rows) == 1
    row = rows[0]
    assert row.permission_id == result.permission_id
    assert row.live_execution_permitted is True
    assert row.effective_from_ts_utc == TS
    assert row.effective_until_ts_utc is None
    assert row.permission_version == "1"
    assert row.source_provenance == "operator_cli_grant_v1"


def test_apply_idempotent_already_granted_does_not_insert_second_row() -> None:
    conn = FakeConnection()
    _live_ready_account(conn)
    first = apply_automatic_exit_live_permission_grant_v1(conn, request=_request())
    second = apply_automatic_exit_live_permission_grant_v1(conn, request=_request(requested_ts_utc=TS + timedelta(hours=1)))
    assert second.idempotent is True
    assert second.permission_id == first.permission_id
    rows = load_automatic_exit_live_permission_history_v1(conn, trading_account_id=ACCOUNT)
    assert len(rows) == 1


def test_check_already_granted_reports_existing_id() -> None:
    conn = FakeConnection()
    _live_ready_account(conn)
    granted = apply_automatic_exit_live_permission_grant_v1(conn, request=_request())
    result = check_automatic_exit_live_permission_grant_v1(conn, request=_request(requested_ts_utc=TS + timedelta(hours=1)))
    assert result.check_state == CHECK_STATE_ALREADY_GRANTED
    assert result.existing_permission_id == granted.permission_id


def test_unknown_trading_account_fails_closed() -> None:
    conn = FakeConnection()
    with pytest.raises(AutomaticExitLivePermissionGrantError) as exc:
        apply_automatic_exit_live_permission_grant_v1(conn, request=_request(account_id=999))
    assert exc.value.args[0] == REASON_UNKNOWN_TRADING_ACCOUNT


def test_disabled_account_fails_closed() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=ACCOUNT, account_mode="live", enabled=False, live_trading_enabled=True)
    check = check_automatic_exit_live_permission_grant_v1(conn, request=_request())
    assert check.check_state == "BLOCKED"
    assert check.reason_code == REASON_ACCOUNT_DISABLED
    with pytest.raises(AutomaticExitLivePermissionGrantError) as exc:
        apply_automatic_exit_live_permission_grant_v1(conn, request=_request())
    assert exc.value.args[0] == REASON_ACCOUNT_DISABLED


def test_non_live_account_mode_fails_closed() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=ACCOUNT, account_mode="paper", enabled=True, live_trading_enabled=True)
    with pytest.raises(AutomaticExitLivePermissionGrantError) as exc:
        apply_automatic_exit_live_permission_grant_v1(conn, request=_request())
    assert exc.value.args[0] == REASON_ACCOUNT_NOT_LIVE_MODE


def test_live_trading_not_enabled_fails_closed() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=ACCOUNT, account_mode="live", enabled=True, live_trading_enabled=False)
    with pytest.raises(AutomaticExitLivePermissionGrantError) as exc:
        apply_automatic_exit_live_permission_grant_v1(conn, request=_request())
    assert exc.value.args[0] == REASON_LIVE_TRADING_NOT_ENABLED


def test_conflicting_history_fails_closed() -> None:
    conn = FakeConnection()
    _live_ready_account(conn)
    insert_live_permission(conn, account_id=ACCOUNT, live_execution_permitted=True)
    insert_live_permission(conn, account_id=ACCOUNT, live_execution_permitted=False)
    with pytest.raises(AutomaticExitLivePermissionGrantError) as exc:
        apply_automatic_exit_live_permission_grant_v1(conn, request=_request())
    assert exc.value.args[0] == REASON_CONFLICTING_LIVE_PERMISSION_STATE


def test_active_deny_fact_blocks_grant() -> None:
    conn = FakeConnection()
    _live_ready_account(conn)
    insert_live_permission(conn, account_id=ACCOUNT, live_execution_permitted=False)
    with pytest.raises(AutomaticExitLivePermissionGrantError) as exc:
        apply_automatic_exit_live_permission_grant_v1(conn, request=_request())
    assert exc.value.args[0] == REASON_CONFLICTING_LIVE_PERMISSION_STATE
    rows = load_automatic_exit_live_permission_history_v1(conn, trading_account_id=ACCOUNT)
    assert len(rows) == 1  # unchanged: no new row appended


def test_revocation_history_interaction_allows_grant_after_revoked_deny() -> None:
    conn = FakeConnection()
    _live_ready_account(conn)
    deny_id = insert_live_permission(
        conn, account_id=ACCOUNT, live_execution_permitted=False, effective_from_ts_utc=TS - timedelta(days=2),
    )
    insert_live_permission_revocation(
        conn, permission_id=deny_id, account_id=ACCOUNT, effective_ts_utc=TS - timedelta(days=1),
    )
    result = apply_automatic_exit_live_permission_grant_v1(conn, request=_request())
    assert result.idempotent is False
    rows = load_automatic_exit_live_permission_history_v1(conn, trading_account_id=ACCOUNT)
    assert len(rows) == 2


def test_future_dated_row_causes_overlap_block() -> None:
    conn = FakeConnection()
    _live_ready_account(conn)
    insert_live_permission(
        conn, account_id=ACCOUNT, live_execution_permitted=True, effective_from_ts_utc=TS + timedelta(days=1),
    )
    with pytest.raises(AutomaticExitLivePermissionGrantError) as exc:
        apply_automatic_exit_live_permission_grant_v1(conn, request=_request())
    assert exc.value.args[0] == REASON_OVERLAPPING_LIVE_PERMISSION_STATE


def test_rollback_on_insert_failure_leaves_no_row() -> None:
    conn = FakeConnection()
    _live_ready_account(conn)

    real_cursor_factory = conn.cursor

    class _FailingCursor:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, params=()):
            if sql.strip().startswith("INSERT INTO automatic_exit_live_decision_gate_permission_v1"):
                raise RuntimeError("simulated insert failure")
            return self._inner.execute(sql, params)

        def fetchone(self):
            return self._inner.fetchone()

        def fetchall(self):
            return self._inner.fetchall()

        @property
        def lastrowid(self):
            return self._inner.lastrowid

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    conn.cursor = lambda: _FailingCursor(real_cursor_factory())  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="simulated insert failure"):
        apply_automatic_exit_live_permission_grant_v1(conn, request=_request())
    conn.rollback()

    conn.cursor = real_cursor_factory  # type: ignore[method-assign]
    rows = load_automatic_exit_live_permission_history_v1(conn, trading_account_id=ACCOUNT)
    assert rows == ()


def test_account_2_and_3_never_touched() -> None:
    conn = FakeConnection()
    _live_ready_account(conn, account_id=ACCOUNT)
    insert_trading_account(conn, account_id=OTHER_ACCOUNT_2, account_mode="live", enabled=True, live_trading_enabled=True)
    insert_trading_account(conn, account_id=OTHER_ACCOUNT_3, account_mode="live", enabled=True, live_trading_enabled=True)
    apply_automatic_exit_live_permission_grant_v1(conn, request=_request(account_id=ACCOUNT))
    assert load_automatic_exit_live_permission_history_v1(conn, trading_account_id=OTHER_ACCOUNT_2) == ()
    assert load_automatic_exit_live_permission_history_v1(conn, trading_account_id=OTHER_ACCOUNT_3) == ()


def test_append_only_no_update_or_delete_ever_issued() -> None:
    """Grant + idempotent replay must never emit an UPDATE/DELETE statement."""
    conn = FakeConnection()
    _live_ready_account(conn)
    executed_sql: list[str] = []
    real_cursor_factory = conn.cursor

    class _RecordingCursor:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, params=()):
            executed_sql.append(sql)
            return self._inner.execute(sql, params)

        def fetchone(self):
            return self._inner.fetchone()

        def fetchall(self):
            return self._inner.fetchall()

        @property
        def lastrowid(self):
            return self._inner.lastrowid

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    conn.cursor = lambda: _RecordingCursor(real_cursor_factory())  # type: ignore[method-assign]
    apply_automatic_exit_live_permission_grant_v1(conn, request=_request())
    apply_automatic_exit_live_permission_grant_v1(conn, request=_request(requested_ts_utc=TS + timedelta(hours=1)))
    conn.cursor = real_cursor_factory  # type: ignore[method-assign]

    assert not any(sql.strip().upper().startswith("UPDATE") for sql in executed_sql)
    assert not any(sql.strip().upper().startswith("DELETE") for sql in executed_sql)


def test_no_executor_credential_kill_switch_side_effects() -> None:
    """The service/CLI must not import executor/credential/kill-switch modules."""
    import ast

    import src.decision_gate.automatic_exit_live_permission_grant_v1 as grant_module
    import src.decision_gate.run_grant_automatic_exit_live_permission_v1 as cli_module

    forbidden_prefixes = ("src.executor", "src.credential", "src.kill_switch")
    for module in (grant_module, cli_module):
        source = module.__file__
        assert source is not None
        with open(source, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=source)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not any(name.startswith(prefix) for name in imported for prefix in forbidden_prefixes)
