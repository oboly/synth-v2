from __future__ import annotations

from datetime import UTC, datetime

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
