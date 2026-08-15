from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.exit_policy.automatic_exit_runtime_contract_v1 import AutomaticExitRuntimeContractError
from src.exit_policy.automatic_exit_runtime_repository_v1 import (
    AutomaticExitRuntimeRepositoryError,
    NO_PERMISSION_ROW_IDENTITY,
    NO_VENUE_CONSTRAINT_ROW_IDENTITY,
    build_runtime_item_v1,
    load_blocking_conflict,
    load_eligible_trading_accounts,
    load_latest_complete_account_state_bundle,
    load_latest_market_price,
    load_positive_positions,
)
from tests.automatic_exit_runtime_fixtures_v1 import (
    FakeConnection,
    TS,
    insert_balance,
    insert_complete_bundle,
    insert_exit_profile,
    insert_market_price,
    insert_open_order,
    insert_permission,
    insert_position,
    insert_trading_account,
    insert_venue_constraint,
    seed_happy_path,
)


NOW = TS + timedelta(minutes=5)


def test_latest_fresh_complete_bundle_loads() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    assert bundle.account_state_snapshot_run_id == 1
    assert bundle.open_order_count == 0


def test_missing_bundle_fails_closed() -> None:
    conn = FakeConnection()
    insert_trading_account(conn)
    with pytest.raises(AutomaticExitRuntimeRepositoryError, match="ACCOUNT_STATE_BUNDLE_MISSING"):
        load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)


def test_stale_bundle_fails_closed() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    too_late = TS + timedelta(minutes=16)
    with pytest.raises(AutomaticExitRuntimeRepositoryError, match="ACCOUNT_STATE_BUNDLE_STALE"):
        load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=too_late)


def test_positive_positions_enumerated_and_zero_ignored() -> None:
    conn = FakeConnection()
    insert_trading_account(conn)
    bundle_ids = insert_complete_bundle(conn, position_count=2)
    insert_position(conn, quantity_base=Decimal("1.5"), available_quantity_base=Decimal("1.5"))
    insert_position(conn, asset_id=102, symbol="ETH", quantity_base=Decimal("0"), available_quantity_base=Decimal("0"))
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    positions = load_positive_positions(conn, bundle=bundle)
    assert len(positions) == 1
    assert positions[0].symbol == "BTC"


def test_position_count_mismatch_fails_closed() -> None:
    conn = FakeConnection()
    insert_trading_account(conn)
    insert_complete_bundle(conn, position_count=5)
    insert_position(conn)
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    with pytest.raises(AutomaticExitRuntimeRepositoryError, match="POSITION_SNAPSHOT_COUNT_MISMATCH"):
        load_positive_positions(conn, bundle=bundle)


def test_two_accounts_same_asset_isolated() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=7, account_code="account-a")
    insert_trading_account(conn, account_id=8, account_code="account-b")
    insert_complete_bundle(conn, account_id=7)
    insert_complete_bundle(conn, account_id=8)
    insert_position(conn, account_id=7, quantity_base=Decimal("1"), available_quantity_base=Decimal("1"))
    insert_position(conn, account_id=8, quantity_base=Decimal("2"), available_quantity_base=Decimal("2"))
    bundle_a = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    bundle_b = load_latest_complete_account_state_bundle(conn, trading_account_id=8, venue="bitvavo", now=NOW)
    positions_a = load_positive_positions(conn, bundle=bundle_a)
    positions_b = load_positive_positions(conn, bundle=bundle_b)
    assert positions_a[0].quantity_base == Decimal("1")
    assert positions_b[0].quantity_base == Decimal("2")


def test_zero_order_header_is_authoritative_no_conflict() -> None:
    conn = FakeConnection()
    insert_trading_account(conn)
    insert_complete_bundle(conn, order_count=0)
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    assert load_blocking_conflict(conn, bundle=bundle, market="BTC-EUR") is False


def test_nonzero_open_order_evidence_loads_and_flags_matching_market() -> None:
    conn = FakeConnection()
    insert_trading_account(conn)
    insert_complete_bundle(conn, order_count=1)
    insert_open_order(conn, market="BTC-EUR")
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    assert load_blocking_conflict(conn, bundle=bundle, market="BTC-EUR") is True
    assert load_blocking_conflict(conn, bundle=bundle, market="ETH-EUR") is False


def test_open_order_count_mismatch_fails_closed() -> None:
    conn = FakeConnection()
    insert_trading_account(conn)
    insert_complete_bundle(conn, order_count=3)
    insert_open_order(conn, market="BTC-EUR")
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    with pytest.raises(AutomaticExitRuntimeRepositoryError, match="OPEN_ORDER_SNAPSHOT_COUNT_MISMATCH"):
        load_blocking_conflict(conn, bundle=bundle, market="BTC-EUR")


def test_missing_balance_row_fails_closed() -> None:
    conn = FakeConnection()
    insert_trading_account(conn)
    insert_complete_bundle(conn)
    insert_position(conn)
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    positions = load_positive_positions(conn, bundle=bundle)
    with pytest.raises(AutomaticExitRuntimeRepositoryError, match="BALANCE_ROW_MISSING"):
        from src.exit_policy.automatic_exit_runtime_repository_v1 import load_balance_evidence
        load_balance_evidence(conn, bundle=bundle, currency_code=positions[0].symbol)


def test_negative_free_quantity_fails_closed() -> None:
    conn = FakeConnection()
    insert_trading_account(conn)
    insert_complete_bundle(conn)
    insert_position(conn)
    insert_balance(conn, available_amount=Decimal("-1"))
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    from src.exit_policy.automatic_exit_runtime_repository_v1 import load_balance_evidence
    with pytest.raises(AutomaticExitRuntimeRepositoryError, match="NEGATIVE_FREE_QUANTITY"):
        load_balance_evidence(conn, bundle=bundle, currency_code="BTC")


def test_stale_market_price_fails_closed() -> None:
    conn = FakeConnection()
    insert_market_price(conn, observed_ts_utc=TS)
    with pytest.raises(AutomaticExitRuntimeRepositoryError, match="MARKET_PRICE_SNAPSHOT_STALE"):
        load_latest_market_price(conn, venue="bitvavo", symbol="BTC", now=TS + timedelta(minutes=16))


def test_missing_market_price_fails_closed() -> None:
    conn = FakeConnection()
    with pytest.raises(AutomaticExitRuntimeRepositoryError, match="MARKET_PRICE_SNAPSHOT_MISSING"):
        load_latest_market_price(conn, venue="bitvavo", symbol="BTC", now=NOW)


def test_missing_exit_profile_fails_closed_via_build_runtime_item() -> None:
    conn = FakeConnection()
    insert_trading_account(conn)
    insert_complete_bundle(conn)
    insert_position(conn)
    insert_balance(conn)
    insert_market_price(conn)
    insert_permission(conn)
    insert_venue_constraint(conn)
    accounts = load_eligible_trading_accounts(conn, venue="bitvavo")
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    positions = load_positive_positions(conn, bundle=bundle)
    with pytest.raises(AutomaticExitRuntimeContractError, match="MISSING_OR_CONFLICTING_AUTOMATIC_EXIT_PROFILE"):
        build_runtime_item_v1(conn, account=accounts[0], bundle=bundle, position=positions[0], now=NOW)


def test_conflicting_exit_profiles_fail_closed_via_build_runtime_item() -> None:
    conn = FakeConnection()
    insert_trading_account(conn)
    insert_complete_bundle(conn)
    insert_position(conn)
    insert_balance(conn)
    insert_market_price(conn)
    insert_exit_profile(conn, profile_id="a")
    insert_exit_profile(conn, profile_id="b")
    insert_permission(conn)
    insert_venue_constraint(conn)
    accounts = load_eligible_trading_accounts(conn, venue="bitvavo")
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    positions = load_positive_positions(conn, bundle=bundle)
    with pytest.raises(AutomaticExitRuntimeContractError, match="MISSING_OR_CONFLICTING_AUTOMATIC_EXIT_PROFILE"):
        build_runtime_item_v1(conn, account=accounts[0], bundle=bundle, position=positions[0], now=NOW)


def test_permission_no_row_defaults_disabled() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM automatic_exit_account_permission_v1")
    accounts = load_eligible_trading_accounts(conn, venue="bitvavo")
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    positions = load_positive_positions(conn, bundle=bundle)
    item = build_runtime_item_v1(conn, account=accounts[0], bundle=bundle, position=positions[0], now=NOW)
    assert item.automatic_exit_execution_enabled is False
    assert item.automatic_exit_permission_id == NO_PERMISSION_ROW_IDENTITY


def test_valid_enabled_permission_resolves() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    accounts = load_eligible_trading_accounts(conn, venue="bitvavo")
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    positions = load_positive_positions(conn, bundle=bundle)
    item = build_runtime_item_v1(conn, account=accounts[0], bundle=bundle, position=positions[0], now=NOW)
    assert item.automatic_exit_execution_enabled is True
    assert isinstance(item.automatic_exit_permission_id, int)


def test_missing_venue_constraints_use_sentinel_and_stay_not_fresh() -> None:
    conn = FakeConnection()
    insert_trading_account(conn)
    insert_complete_bundle(conn)
    insert_position(conn)
    insert_balance(conn)
    insert_market_price(conn)
    insert_exit_profile(conn)
    insert_permission(conn)
    accounts = load_eligible_trading_accounts(conn, venue="bitvavo")
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    positions = load_positive_positions(conn, bundle=bundle)
    item = build_runtime_item_v1(conn, account=accounts[0], bundle=bundle, position=positions[0], now=NOW)
    assert item.venue_constraints.status == "MISSING"
    assert item.venue_constraint_id == NO_VENUE_CONSTRAINT_ROW_IDENTITY


def test_stale_venue_constraints_marked_stale() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM venue_execution_constraint")
    insert_venue_constraint(conn, metadata_synced_ts_utc=TS - timedelta(days=8))
    accounts = load_eligible_trading_accounts(conn, venue="bitvavo")
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    positions = load_positive_positions(conn, bundle=bundle)
    item = build_runtime_item_v1(conn, account=accounts[0], bundle=bundle, position=positions[0], now=NOW)
    assert item.venue_constraints.status == "STALE"
    assert isinstance(item.venue_constraint_id, int)


def test_multi_account_correctness_no_implicit_global_account() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=7)
    insert_trading_account(conn, account_id=9)
    accounts = load_eligible_trading_accounts(conn, venue="bitvavo")
    assert {a.trading_account_id for a in accounts} == {7, 9}
