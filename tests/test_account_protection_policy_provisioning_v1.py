from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.decision_gate.account_protection_contract_v1 import (
    ACTION_BUY,
    REASON_PROTECTION_CONFIGURATION_UNRESOLVED,
    STATE_BLOCKED,
    STATE_PERMITTED,
)
from src.decision_gate.account_protection_evaluation_v1 import evaluate_account_protection_for_automatic_exit_v1
from src.decision_gate.account_protection_policy_contract_v1 import POLICY_CONFIG_CONTRACT_VERSION
from src.decision_gate.account_protection_policy_provisioning_v1 import (
    AccountProtectionPolicyConflictError,
    AccountProtectionPolicyProvisioningError,
    AccountProtectionPolicyProvisioningRequestV1,
    provision_account_protection_policy_v1,
)
from src.decision_gate.account_protection_policy_repository_v1 import load_account_protection_policy_config_rows_v1
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import FakeConnection, insert_trading_account

TS = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def _request(**overrides: object) -> AccountProtectionPolicyProvisioningRequestV1:
    fields: dict[str, object] = {
        "account_code": "hugo-bitvavo",
        "venue": "bitvavo",
        "config_version": POLICY_CONFIG_CONTRACT_VERSION,
        "configuration_version": "issue-504-policy-v1",
        "max_account_drawdown": None,
        "max_daily_realized_loss": None,
        "max_repeated_stoploss_streak": None,
        "max_metric_age_seconds": 900,
        "effective_from_ts_utc": TS,
        "effective_until_ts_utc": None,
        "source_provenance": "issue_504_test",
    }
    fields.update(overrides)
    return AccountProtectionPolicyProvisioningRequestV1(**fields)  # type: ignore[arg-type]


def _account(conn: FakeConnection, *, account_id: int = 4, account_code: str = "hugo-bitvavo") -> None:
    insert_trading_account(conn, account_id=account_id, account_code=account_code, venue="bitvavo", account_mode="paper")


def test_create_appends_explicit_neutral_policy_by_canonical_account_identity() -> None:
    conn = FakeConnection()
    _account(conn)
    result = provision_account_protection_policy_v1(conn, request=_request())
    assert result.trading_account_id == 4
    assert result.account_protection_policy_config_id > 0
    assert result.idempotent is False


def test_exact_idempotent_rerun_returns_existing_row_without_insert() -> None:
    conn = FakeConnection()
    _account(conn)
    first = provision_account_protection_policy_v1(conn, request=_request())
    second = provision_account_protection_policy_v1(conn, request=_request())
    assert second.idempotent is True
    assert second.account_protection_policy_config_id == first.account_protection_policy_config_id
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM account_protection_policy_config_v1", ())
        assert cur.fetchone()["c"] == 1


def test_conflicting_rerun_fails_closed_without_second_append() -> None:
    conn = FakeConnection()
    _account(conn)
    provision_account_protection_policy_v1(conn, request=_request())
    with pytest.raises(AccountProtectionPolicyConflictError, match="CONFLICTING_PROTECTION_CONFIGURATION"):
        provision_account_protection_policy_v1(conn, request=_request(max_daily_realized_loss=Decimal("20")))
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM account_protection_policy_config_v1", ())
        assert cur.fetchone()["c"] == 1


def test_future_dated_row_blocks_new_open_ended_insert() -> None:
    """A row scheduled to start later still blocks a new open-ended row:
    since the new row never ends, it would become simultaneously active
    with the future row once that row's own start passes, making the #318
    resolver ambiguous. Mirrors the exact gap Codex flagged twice on the
    sibling #498 provisioning writers (PR #499/#503)."""
    conn = FakeConnection()
    _account(conn)
    future_start = TS + timedelta(days=7)
    provision_account_protection_policy_v1(conn, request=_request(effective_from_ts_utc=future_start))

    with pytest.raises(AccountProtectionPolicyConflictError, match="OVERLAPPING_PROTECTION_CONFIGURATION"):
        provision_account_protection_policy_v1(conn, request=_request(effective_from_ts_utc=TS))

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM account_protection_policy_config_v1", ())
        assert cur.fetchone()["c"] == 1


def test_sequential_bounded_windows_do_not_conflict() -> None:
    """A window that starts exactly when the prior one ends is legitimate
    scheduling, not an overlap, and must be allowed."""
    conn = FakeConnection()
    _account(conn)
    first = provision_account_protection_policy_v1(
        conn, request=_request(effective_from_ts_utc=TS, effective_until_ts_utc=TS + timedelta(hours=1)),
    )
    second = provision_account_protection_policy_v1(
        conn,
        request=_request(
            effective_from_ts_utc=TS + timedelta(hours=1),
            configuration_version="issue-504-policy-v2",
            max_daily_realized_loss=Decimal("50"),
        ),
    )
    assert first.idempotent is False
    assert second.idempotent is False
    assert second.account_protection_policy_config_id != first.account_protection_policy_config_id


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"config_version": "999"}, "UNSUPPORTED_PROTECTION_CONFIGURATION_VERSION"),
        ({"configuration_version": "   "}, "INVALID_PROTECTION_CONFIGURATION_VERSION_LABEL"),
        ({"max_account_drawdown": Decimal("0")}, "INVALID_MAX_ACCOUNT_DRAWDOWN"),
        ({"max_daily_realized_loss": Decimal("NaN")}, "INVALID_MAX_DAILY_REALIZED_LOSS"),
        ({"max_repeated_stoploss_streak": 0}, "INVALID_MAX_REPEATED_STOPLOSS_STREAK"),
        ({"max_metric_age_seconds": -1}, "INVALID_MAX_METRIC_AGE_SECONDS"),
        ({"effective_until_ts_utc": TS}, "INVALID_PROTECTION_CONFIGURATION_WINDOW"),
    ],
)
def test_invalid_policy_values_fail_before_insert(overrides: dict[str, object], reason: str) -> None:
    conn = FakeConnection()
    _account(conn)
    with pytest.raises(AccountProtectionPolicyProvisioningError, match=reason):
        provision_account_protection_policy_v1(conn, request=_request(**overrides))


def test_unknown_account_fails_closed() -> None:
    with pytest.raises(AccountProtectionPolicyProvisioningError, match="UNKNOWN_TRADING_ACCOUNT"):
        provision_account_protection_policy_v1(FakeConnection(), request=_request())


class _AmbiguousCursor:
    def __enter__(self) -> "_AmbiguousCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        return None

    def fetchall(self) -> list[dict[str, object]]:
        return [{"trading_account_id": 1}, {"trading_account_id": 2}]


class _AmbiguousConnection:
    def cursor(self) -> _AmbiguousCursor:
        return _AmbiguousCursor()


def test_ambiguous_account_identity_fails_closed() -> None:
    with pytest.raises(AccountProtectionPolicyProvisioningError, match="AMBIGUOUS_TRADING_ACCOUNT_IDENTITY"):
        provision_account_protection_policy_v1(_AmbiguousConnection(), request=_request())


class _SqlCapturingCursor:
    def __init__(self, real_cursor: object, sink: list[str]) -> None:
        self._real = real_cursor
        self._sink = sink

    def __enter__(self) -> "_SqlCapturingCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> "_SqlCapturingCursor":
        self._sink.append(sql)
        self._real.execute(sql, params)  # type: ignore[attr-defined]
        return self

    def fetchone(self) -> object:
        return self._real.fetchone()  # type: ignore[attr-defined]

    def fetchall(self) -> object:
        return self._real.fetchall()  # type: ignore[attr-defined]

    @property
    def lastrowid(self) -> int:
        return self._real.lastrowid  # type: ignore[attr-defined]


class _SqlCapturingConnection:
    def __init__(self, inner: FakeConnection) -> None:
        self._inner = inner
        self.executed_sql: list[str] = []

    def cursor(self) -> _SqlCapturingCursor:
        return _SqlCapturingCursor(self._inner.cursor(), self.executed_sql)


def test_account_resolution_takes_a_row_lock_to_serialize_concurrent_provisioning() -> None:
    """Codex review on PR #506: two concurrent callers could both observe "no
    policy yet" and both insert an overlapping row, since nothing serialized
    the read-check-insert sequence. ``_resolve_trading_account_id`` now locks
    the matched ``trading_account`` row with ``FOR UPDATE`` inside the
    caller's (autocommit=False) transaction, so a second concurrent call for
    the same account blocks there until the first commits or rolls back --
    guaranteeing it always sees the first's result before doing its own
    conflict check. A real cross-connection blocking test belongs in the
    gated disposable-MariaDB suite (SQLite has no row-level locking to
    exercise here); this asserts the lock is actually requested, matching
    this repo's existing FOR UPDATE test convention (see e.g.
    test_native_short_map_scope_seed_canary_v1.py)."""
    conn = FakeConnection()
    _account(conn)
    wrapped = _SqlCapturingConnection(conn)

    provision_account_protection_policy_v1(wrapped, request=_request())

    account_lookup_sql = [sql for sql in wrapped.executed_sql if "FROM trading_account" in sql]
    assert account_lookup_sql, "account resolution query was never executed"
    assert all("FOR UPDATE" in sql for sql in account_lookup_sql)


def test_multi_account_rows_are_strictly_isolated() -> None:
    conn = FakeConnection()
    _account(conn, account_id=4, account_code="hugo-bitvavo")
    _account(conn, account_id=9, account_code="paper-review")
    a = provision_account_protection_policy_v1(conn, request=_request())
    b = provision_account_protection_policy_v1(
        conn, request=_request(account_code="paper-review", configuration_version="issue-504-policy-b"),
    )
    assert a.trading_account_id != b.trading_account_id
    assert len(load_account_protection_policy_config_rows_v1(conn, trading_account_id=4)) == 1
    assert len(load_account_protection_policy_config_rows_v1(conn, trading_account_id=9)) == 1


class _RawParamCapturingCursor:
    def __init__(self, real_cursor: object, sink: list[datetime]) -> None:
        self._real = real_cursor
        self._sink = sink

    def __enter__(self) -> "_RawParamCapturingCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> "_RawParamCapturingCursor":
        self._sink.extend(value for value in params if isinstance(value, datetime))
        self._real.execute(sql, params)  # type: ignore[attr-defined]
        return self

    def fetchone(self) -> object:
        return self._real.fetchone()  # type: ignore[attr-defined]

    def fetchall(self) -> object:
        return self._real.fetchall()  # type: ignore[attr-defined]

    @property
    def lastrowid(self) -> int:
        return self._real.lastrowid  # type: ignore[attr-defined]


class _RawParamCapturingConnection:
    def __init__(self, inner: FakeConnection) -> None:
        self._inner = inner
        self.captured_datetimes: list[datetime] = []

    def cursor(self) -> _RawParamCapturingCursor:
        return _RawParamCapturingCursor(self._inner.cursor(), self.captured_datetimes)


def test_offset_aware_window_is_normalized_to_utc_before_compare_and_insert() -> None:
    conn = FakeConnection()
    _account(conn)
    wrapped = _RawParamCapturingConnection(conn)
    offset = timezone(timedelta(hours=2))
    result = provision_account_protection_policy_v1(
        wrapped,
        request=_request(
            effective_from_ts_utc=TS.astimezone(offset),
            effective_until_ts_utc=(TS + timedelta(hours=1)).astimezone(offset),
        ),
    )
    repeat = provision_account_protection_policy_v1(
        wrapped, request=_request(effective_until_ts_utc=TS + timedelta(hours=1)),
    )
    assert result.idempotent is False
    assert repeat.idempotent is True
    assert wrapped.captured_datetimes
    assert all(value.utcoffset() == timedelta(0) for value in wrapped.captured_datetimes)


def test_provisioned_row_is_consumed_by_unchanged_318_evaluator() -> None:
    conn = FakeConnection()
    _account(conn)
    provision_account_protection_policy_v1(conn, request=_request())
    outcome = evaluate_account_protection_for_automatic_exit_v1(
        conn, trading_account_id=4, asset_id=1, requested_action=ACTION_BUY,
        account_state_observed_ts_utc=TS, evaluation_ts_utc=TS,
    )
    assert outcome.decision_state == STATE_PERMITTED


def test_missing_config_stays_blocked_in_the_exact_318_evaluator() -> None:
    conn = FakeConnection()
    _account(conn)
    outcome = evaluate_account_protection_for_automatic_exit_v1(
        conn, trading_account_id=4, asset_id=1, requested_action=ACTION_BUY,
        account_state_observed_ts_utc=TS, evaluation_ts_utc=TS,
    )
    assert outcome.decision_state == STATE_BLOCKED
    assert outcome.reason_code == REASON_PROTECTION_CONFIGURATION_UNRESOLVED


def test_no_broker_client_or_order_import() -> None:
    import src.decision_gate.account_protection_policy_provisioning_v1 as module

    for line in open(module.__file__):
        if line.lstrip().startswith(("import ", "from ")):
            assert all(token not in line.lower() for token in ("broker", "executor", "order", "client")), line
