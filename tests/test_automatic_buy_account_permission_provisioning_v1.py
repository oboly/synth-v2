from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.decision_gate.automatic_buy_account_permission_provisioning_v1 import (
    AutomaticBuyAccountPermissionConflictError,
    AutomaticBuyAccountPermissionProvisioningError,
    AutomaticBuyAccountPermissionProvisioningRequestV1,
    provision_automatic_buy_account_permission_v1,
)
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import (
    FakeConnection,
    insert_buy_permission,
    insert_trading_account,
)

TS = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def _request(**overrides: object) -> AutomaticBuyAccountPermissionProvisioningRequestV1:
    fields: dict[str, object] = dict(
        account_code="hugo-bitvavo",
        venue="bitvavo",
        execution_enabled=True,
        effective_from_ts_utc=TS,
        source_provenance="issue_498_acceptance",
    )
    fields.update(overrides)
    return AutomaticBuyAccountPermissionProvisioningRequestV1(**fields)


def test_create_provisions_one_row_resolved_by_account_code() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")

    result = provision_automatic_buy_account_permission_v1(conn, request=_request())

    assert result.trading_account_id == 4
    assert result.idempotent is False
    assert result.automatic_buy_account_permission_id > 0


def test_idempotent_same_value_rerun_returns_existing_row_no_new_insert() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")

    first = provision_automatic_buy_account_permission_v1(conn, request=_request())
    second = provision_automatic_buy_account_permission_v1(conn, request=_request())

    assert first.idempotent is False
    assert second.idempotent is True
    assert second.automatic_buy_account_permission_id == first.automatic_buy_account_permission_id

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM automatic_buy_account_permission_v1", ())
        assert cur.fetchone()["c"] == 1


def test_conflicting_rerun_with_different_value_fails_closed() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")
    provision_automatic_buy_account_permission_v1(conn, request=_request(execution_enabled=True))

    with pytest.raises(AutomaticBuyAccountPermissionConflictError):
        provision_automatic_buy_account_permission_v1(conn, request=_request(execution_enabled=False))

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM automatic_buy_account_permission_v1", ())
        assert cur.fetchone()["c"] == 1


def test_disabled_permission_provisions_successfully() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")

    result = provision_automatic_buy_account_permission_v1(conn, request=_request(execution_enabled=False))

    assert result.idempotent is False


def test_unknown_account_rejected() -> None:
    conn = FakeConnection()
    with pytest.raises(AutomaticBuyAccountPermissionProvisioningError, match="UNKNOWN_TRADING_ACCOUNT"):
        provision_automatic_buy_account_permission_v1(conn, request=_request())


class _MultiMatchCursor:
    def __enter__(self) -> "_MultiMatchCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        return None

    def fetchall(self) -> list[dict[str, object]]:
        return [{"trading_account_id": 1}, {"trading_account_id": 2}]


class _MultiMatchConnection:
    """A duplicate (account_code, venue) binding should never occur given the
    real `uq_trading_account_code` UNIQUE constraint, but the resolver must
    still fail closed rather than trust `LIMIT 1` to silently pick one."""

    def cursor(self) -> _MultiMatchCursor:
        return _MultiMatchCursor()


def test_duplicate_account_identity_binding_rejected_not_silently_resolved() -> None:
    with pytest.raises(
        AutomaticBuyAccountPermissionProvisioningError, match="AMBIGUOUS_TRADING_ACCOUNT_IDENTITY",
    ):
        provision_automatic_buy_account_permission_v1(_MultiMatchConnection(), request=_request())


def test_offset_aware_timestamp_normalized_to_utc_before_resolution_and_insert() -> None:
    from datetime import timedelta, timezone as _timezone

    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")
    offset_ts = TS.astimezone(_timezone(timedelta(hours=2)))
    assert offset_ts.utcoffset() != timedelta(0)

    result = provision_automatic_buy_account_permission_v1(conn, request=_request(effective_from_ts_utc=offset_ts))

    with conn.cursor() as cur:
        cur.execute(
            "SELECT effective_from_ts_utc FROM automatic_buy_account_permission_v1 WHERE automatic_buy_account_permission_id = %s",
            (result.automatic_buy_account_permission_id,),
        )
        stored = cur.fetchone()["effective_from_ts_utc"]
    assert stored.replace(tzinfo=UTC) == TS

    # A rerun using the equivalent UTC instant (not the offset form) must
    # resolve to the same normalized identity and be treated as idempotent.
    rerun = provision_automatic_buy_account_permission_v1(conn, request=_request(effective_from_ts_utc=TS))
    assert rerun.idempotent is True
    assert rerun.automatic_buy_account_permission_id == result.automatic_buy_account_permission_id


def test_invalid_source_provenance_rejected() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")

    with pytest.raises(AutomaticBuyAccountPermissionProvisioningError):
        provision_automatic_buy_account_permission_v1(conn, request=_request(source_provenance="   "))


def test_multi_account_isolation() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")
    insert_trading_account(conn, account_id=1, account_code="paper_sell_only_preview", venue="bitvavo", account_mode="paper")

    result_a = provision_automatic_buy_account_permission_v1(conn, request=_request(account_code="hugo-bitvavo"))
    result_b = provision_automatic_buy_account_permission_v1(
        conn, request=_request(account_code="paper_sell_only_preview", execution_enabled=False),
    )

    assert result_a.trading_account_id != result_b.trading_account_id
    assert result_a.automatic_buy_account_permission_id != result_b.automatic_buy_account_permission_id

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM automatic_buy_account_permission_v1", ())
        assert cur.fetchone()["c"] == 2


def test_ambiguous_persisted_state_fails_closed_without_inserting() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")
    insert_buy_permission(conn, account_id=4, execution_enabled=True, effective_from_ts_utc=TS)
    insert_buy_permission(conn, account_id=4, execution_enabled=False, effective_from_ts_utc=TS)

    with pytest.raises(AutomaticBuyAccountPermissionProvisioningError):
        provision_automatic_buy_account_permission_v1(conn, request=_request())


def test_future_dated_existing_row_blocks_new_open_ended_insert() -> None:
    """A row that starts after `now` but isn't active yet must still block a
    new open-ended row -- otherwise both become simultaneously active once
    the future row's start passes, and the runtime resolver goes ambiguous."""
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")
    future_start = TS + timedelta(days=7)
    insert_buy_permission(conn, account_id=4, effective_from_ts_utc=future_start)

    with pytest.raises(
        AutomaticBuyAccountPermissionConflictError, match="FUTURE_AUTOMATIC_BUY_ACCOUNT_PERMISSION_OVERLAP",
    ):
        provision_automatic_buy_account_permission_v1(conn, request=_request(effective_from_ts_utc=TS))

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM automatic_buy_account_permission_v1", ())
        assert cur.fetchone()["c"] == 1


def test_future_dated_row_revoked_shortly_after_its_own_start_still_blocks_insert() -> None:
    """A future row that becomes active and is only revoked afterward still had
    a real (if brief) overlap window with an indefinitely open-ended candidate
    starting earlier, so it must still be treated as a conflict."""
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")
    future_start = TS + timedelta(days=7)
    permission_id = insert_buy_permission(conn, account_id=4, effective_from_ts_utc=future_start)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO automatic_buy_account_permission_revocation_v1 "
            "(automatic_buy_account_permission_id, trading_account_id, revocation_version, effective_ts_utc, actor, reason) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (permission_id, 4, "1", future_start + timedelta(days=1), "operator", "revoked shortly after activation"),
        )

    with pytest.raises(
        AutomaticBuyAccountPermissionConflictError, match="FUTURE_AUTOMATIC_BUY_ACCOUNT_PERMISSION_OVERLAP",
    ):
        provision_automatic_buy_account_permission_v1(conn, request=_request(effective_from_ts_utc=TS))


def test_malformed_revocation_at_or_before_its_own_row_start_is_rejected() -> None:
    """The contract requires a revocation to strictly post-date its row's own
    start; a revocation timestamped at-or-before that is corrupt persisted
    state and must fail closed, never be silently tolerated."""
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")
    future_start = TS + timedelta(days=7)
    permission_id = insert_buy_permission(conn, account_id=4, effective_from_ts_utc=future_start)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO automatic_buy_account_permission_revocation_v1 "
            "(automatic_buy_account_permission_id, trading_account_id, revocation_version, effective_ts_utc, actor, reason) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (permission_id, 4, "1", future_start, "operator", "invalid: not strictly after row start"),
        )

    with pytest.raises(AutomaticBuyAccountPermissionProvisioningError):
        provision_automatic_buy_account_permission_v1(conn, request=_request(effective_from_ts_utc=TS))


def test_provisioned_row_resolves_end_to_end_via_canonical_474_resolver() -> None:
    from src.decision_gate.automatic_buy_account_permission_contract_v1 import (
        resolve_automatic_buy_account_permission_v1,
    )
    from src.decision_gate.automatic_buy_account_permission_repository_v1 import (
        load_automatic_buy_account_permission_history_v1,
        load_automatic_buy_account_permission_revocation_history_v1,
    )

    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")
    provision_automatic_buy_account_permission_v1(conn, request=_request())

    rows = load_automatic_buy_account_permission_history_v1(conn, trading_account_id=4)
    revocations = load_automatic_buy_account_permission_revocation_history_v1(conn, trading_account_id=4)
    resolved = resolve_automatic_buy_account_permission_v1(rows, revocations, trading_account_id=4, at=TS)
    assert resolved is not None
    assert resolved.execution_enabled is True


def test_no_broker_executor_or_order_import() -> None:
    import src.decision_gate.automatic_buy_account_permission_provisioning_v1 as module

    with open(module.__file__) as fh:
        import_lines = [line for line in fh if line.lstrip().startswith(("import ", "from "))]
    for line in import_lines:
        lowered = line.lower()
        for forbidden in ("broker", "executor", "order_submission", "credential"):
            assert forbidden not in lowered, line
