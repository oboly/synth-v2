from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.decision_gate.strategy_bucket_account_config_provisioning_v1 import (
    StrategyBucketAccountConfigConflictError,
    StrategyBucketAccountConfigProvisioningError,
    StrategyBucketAccountConfigProvisioningRequestV1,
    provision_strategy_bucket_account_config_v1,
)
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import (
    FakeConnection,
    insert_bucket_config,
    insert_trading_account,
)

TS = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def _request(**overrides: object) -> StrategyBucketAccountConfigProvisioningRequestV1:
    fields: dict[str, object] = dict(
        account_code="hugo-bitvavo",
        venue="bitvavo",
        strategy_bucket_id="SHORT_TERM_ROTATION",
        is_enabled=True,
        risk_profile="standard",
        max_position_amount_eur=Decimal("250"),
        max_bucket_amount_eur=Decimal("1000"),
        max_asset_exposure_pct=Decimal("50"),
        max_open_positions=5,
        allow_new_entries=True,
        allow_reduce_reviews=True,
        effective_from_ts_utc=TS,
        source_provenance="issue_498_acceptance",
    )
    fields.update(overrides)
    return StrategyBucketAccountConfigProvisioningRequestV1(**fields)


def test_create_provisions_one_row_resolved_by_account_code() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")

    result = provision_strategy_bucket_account_config_v1(conn, request=_request())

    assert result.trading_account_id == 4
    assert result.idempotent is False
    assert result.strategy_bucket_account_config_id > 0


def test_idempotent_same_value_rerun_returns_existing_row_no_new_insert() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")

    first = provision_strategy_bucket_account_config_v1(conn, request=_request())
    second = provision_strategy_bucket_account_config_v1(conn, request=_request())

    assert first.idempotent is False
    assert second.idempotent is True
    assert second.strategy_bucket_account_config_id == first.strategy_bucket_account_config_id

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM strategy_bucket_account_config_v1", ())
        assert cur.fetchone()["c"] == 1


def test_conflicting_rerun_with_different_values_fails_closed() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")
    provision_strategy_bucket_account_config_v1(conn, request=_request())

    with pytest.raises(StrategyBucketAccountConfigConflictError):
        provision_strategy_bucket_account_config_v1(
            conn, request=_request(max_position_amount_eur=Decimal("500")),
        )

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM strategy_bucket_account_config_v1", ())
        assert cur.fetchone()["c"] == 1


def test_disabled_bucket_provisions_successfully() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")

    result = provision_strategy_bucket_account_config_v1(
        conn, request=_request(is_enabled=False, allow_new_entries=False, allow_reduce_reviews=False),
    )

    assert result.idempotent is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_position_amount_eur", Decimal("-1")),
        ("max_position_amount_eur", Decimal("0")),
        ("max_bucket_amount_eur", Decimal("-100")),
        ("max_asset_exposure_pct", Decimal("0")),
        ("max_asset_exposure_pct", Decimal("101")),
        ("max_open_positions", 0),
        ("max_open_positions", -3),
    ],
)
def test_invalid_or_negative_limits_rejected(field: str, value: object) -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")

    with pytest.raises(StrategyBucketAccountConfigProvisioningError):
        provision_strategy_bucket_account_config_v1(conn, request=_request(**{field: value}))

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM strategy_bucket_account_config_v1", ())
        assert cur.fetchone()["c"] == 0


def test_unknown_account_rejected() -> None:
    conn = FakeConnection()
    with pytest.raises(StrategyBucketAccountConfigProvisioningError, match="UNKNOWN_TRADING_ACCOUNT"):
        provision_strategy_bucket_account_config_v1(conn, request=_request())


@pytest.mark.parametrize("bad_bucket_id", ["", "   ", "has space", "bad/slash", "x" * 65])
def test_unknown_or_malformed_strategy_bucket_identity_rejected(bad_bucket_id: str) -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")

    with pytest.raises(StrategyBucketAccountConfigProvisioningError):
        provision_strategy_bucket_account_config_v1(conn, request=_request(strategy_bucket_id=bad_bucket_id))


def test_multi_account_isolation() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")
    insert_trading_account(conn, account_id=1, account_code="paper_sell_only_preview", venue="bitvavo", account_mode="paper")

    result_a = provision_strategy_bucket_account_config_v1(conn, request=_request(account_code="hugo-bitvavo"))
    result_b = provision_strategy_bucket_account_config_v1(
        conn, request=_request(account_code="paper_sell_only_preview", max_position_amount_eur=Decimal("999")),
    )

    assert result_a.trading_account_id != result_b.trading_account_id
    assert result_a.strategy_bucket_account_config_id != result_b.strategy_bucket_account_config_id

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM strategy_bucket_account_config_v1", ())
        assert cur.fetchone()["c"] == 2


def test_conflicting_ambiguous_persisted_state_fails_closed_without_inserting() -> None:
    """Two pre-existing overlapping rows (corrupt/legacy state) must never be papered over."""
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")
    insert_bucket_config(conn, account_id=4, strategy_bucket_id="SHORT_TERM_ROTATION", effective_from_ts_utc=TS)
    insert_bucket_config(conn, account_id=4, strategy_bucket_id="SHORT_TERM_ROTATION", effective_from_ts_utc=TS)

    with pytest.raises(StrategyBucketAccountConfigProvisioningError):
        provision_strategy_bucket_account_config_v1(conn, request=_request())


def test_future_dated_existing_row_blocks_new_open_ended_insert() -> None:
    """A row that starts after `now` but isn't active yet must still block a
    new open-ended row -- otherwise both become simultaneously active once
    the future row's start passes, and the runtime resolver goes ambiguous."""
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")
    future_start = TS + timedelta(days=7)
    insert_bucket_config(
        conn, account_id=4, strategy_bucket_id="SHORT_TERM_ROTATION", effective_from_ts_utc=future_start,
    )

    with pytest.raises(StrategyBucketAccountConfigConflictError, match="FUTURE_STRATEGY_BUCKET_ACCOUNT_CONFIG_OVERLAP"):
        provision_strategy_bucket_account_config_v1(conn, request=_request(effective_from_ts_utc=TS))

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM strategy_bucket_account_config_v1", ())
        assert cur.fetchone()["c"] == 1


def test_future_dated_row_revoked_shortly_after_its_own_start_still_blocks_insert() -> None:
    """A future row that becomes active and is only revoked afterward still had
    a real (if brief) overlap window with an indefinitely open-ended candidate
    starting earlier, so it must still be treated as a conflict."""
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")
    future_start = TS + timedelta(days=7)
    config_id = insert_bucket_config(
        conn, account_id=4, strategy_bucket_id="SHORT_TERM_ROTATION", effective_from_ts_utc=future_start,
    )
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO strategy_bucket_account_config_revocation_v1 "
            "(strategy_bucket_account_config_id, trading_account_id, revocation_version, effective_ts_utc, actor, reason) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (config_id, 4, "1", future_start + timedelta(days=1), "operator", "revoked shortly after activation"),
        )

    with pytest.raises(StrategyBucketAccountConfigConflictError, match="FUTURE_STRATEGY_BUCKET_ACCOUNT_CONFIG_OVERLAP"):
        provision_strategy_bucket_account_config_v1(conn, request=_request(effective_from_ts_utc=TS))


def test_malformed_revocation_at_or_before_its_own_row_start_is_rejected() -> None:
    """The contract requires a revocation to strictly post-date its row's own
    start; a revocation timestamped at-or-before that is corrupt persisted
    state and must fail closed, never be silently tolerated."""
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")
    future_start = TS + timedelta(days=7)
    config_id = insert_bucket_config(
        conn, account_id=4, strategy_bucket_id="SHORT_TERM_ROTATION", effective_from_ts_utc=future_start,
    )
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO strategy_bucket_account_config_revocation_v1 "
            "(strategy_bucket_account_config_id, trading_account_id, revocation_version, effective_ts_utc, actor, reason) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (config_id, 4, "1", future_start, "operator", "invalid: not strictly after row start"),
        )

    with pytest.raises(StrategyBucketAccountConfigProvisioningError):
        provision_strategy_bucket_account_config_v1(conn, request=_request(effective_from_ts_utc=TS))


def test_future_row_for_different_bucket_does_not_block_insert() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")
    insert_bucket_config(
        conn, account_id=4, strategy_bucket_id="OTHER_BUCKET", effective_from_ts_utc=TS + timedelta(days=7),
    )

    result = provision_strategy_bucket_account_config_v1(
        conn, request=_request(strategy_bucket_id="SHORT_TERM_ROTATION", effective_from_ts_utc=TS),
    )
    assert result.idempotent is False


def test_provisioned_row_resolves_end_to_end_via_canonical_279_resolver() -> None:
    """#471/#474 compatibility: what this writer inserts must be exactly what the runtime resolver accepts."""
    from src.decision_gate.strategy_bucket_account_config_contract_v1 import resolve_strategy_bucket_account_config_v1
    from src.decision_gate.strategy_bucket_account_config_repository_v1 import (
        load_strategy_bucket_account_config_revocations_v1,
        load_strategy_bucket_account_config_rows_v1,
    )

    conn = FakeConnection()
    insert_trading_account(conn, account_id=4, account_code="hugo-bitvavo", venue="bitvavo", account_mode="paper")
    provision_strategy_bucket_account_config_v1(conn, request=_request())

    rows = load_strategy_bucket_account_config_rows_v1(conn, trading_account_id=4)
    revocations = load_strategy_bucket_account_config_revocations_v1(conn, trading_account_id=4)
    resolved = resolve_strategy_bucket_account_config_v1(
        rows, revocations, trading_account_id=4, strategy_bucket_id="SHORT_TERM_ROTATION", at=TS,
    )
    assert resolved.is_enabled is True
    assert resolved.max_position_amount_eur == Decimal("250")


def test_no_broker_executor_or_order_import() -> None:
    import src.decision_gate.strategy_bucket_account_config_provisioning_v1 as module

    with open(module.__file__) as fh:
        import_lines = [line for line in fh if line.lstrip().startswith(("import ", "from "))]
    for line in import_lines:
        lowered = line.lower()
        for forbidden in ("broker", "executor", "order_submission", "credential"):
            assert forbidden not in lowered, line
