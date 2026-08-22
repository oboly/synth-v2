from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.decision_gate.automatic_buy_account_allocation_evidence_repository_v1 import (
    AutomaticBuyAccountAllocationEvidenceRepositoryError,
    load_automatic_buy_account_allocation_evidence_v1,
)
from src.decision_gate.strategy_bucket_account_config_contract_v1 import StrategyBucketAccountConfigV1
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import (
    TS,
    FakeConnection,
    bind_account_market,
    insert_balance,
    insert_buy_permission,
    insert_complete_bundle,
    insert_market_price,
    insert_position,
    insert_trading_account,
    insert_venue_market,
    seed_happy_path,
)

DEFAULT_ARGS = dict(
    trading_account_id=7,
    venue="bitvavo",
    asset_id=101,
    market="BTC-EUR",
    strategy_bucket_id="SHORT_TERM_ROTATION",
    evaluation_ts_utc=TS,
)


def _resolved_config(**overrides: object) -> StrategyBucketAccountConfigV1:
    base = dict(
        trading_account_id=7,
        strategy_bucket_id="SHORT_TERM_ROTATION",
        is_enabled=True,
        risk_profile="standard",
        max_position_amount_eur=Decimal("250"),
        max_bucket_amount_eur=Decimal("1000"),
        max_asset_exposure_pct=Decimal("50"),
        max_open_positions=5,
        allow_new_entries=True,
        allow_reduce_reviews=True,
    )
    base.update(overrides)
    return StrategyBucketAccountConfigV1(**base)  # type: ignore[arg-type]


def test_no_caller_override_parameters_exist() -> None:
    """Structural proof: the loader signature has no parameter through which
    a caller could supply account_enabled/account_mode/live_trading_enabled/
    automatic_buy_execution_enabled/free_quote_balance_eur/current_bucket_amount_eur/
    current_open_positions/current_asset_exposure_pct -- every one of these
    is derived internally from canonical sources only."""
    forbidden = {
        "account_enabled", "account_mode", "live_trading_enabled",
        "automatic_buy_execution_enabled", "free_quote_balance_eur",
        "current_bucket_amount_eur", "current_open_positions", "current_asset_exposure_pct",
    }
    sig = inspect.signature(load_automatic_buy_account_allocation_evidence_v1)
    assert forbidden.isdisjoint(sig.parameters)


def test_paper_account_happy_path_is_approvable_evidence() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    evidence = load_automatic_buy_account_allocation_evidence_v1(
        conn, resolved_bucket_config=_resolved_config(), **DEFAULT_ARGS,
    )
    assert evidence.account_enabled is True
    assert evidence.account_mode == "paper"
    assert evidence.live_trading_enabled is False
    assert evidence.automatic_buy_execution_enabled is True
    assert evidence.free_quote_balance_eur == Decimal("1000")
    assert evidence.blocking_conflict is False
    assert evidence.current_open_positions == 0
    assert evidence.current_bucket_amount_eur == Decimal("0")
    assert evidence.current_asset_exposure_pct == Decimal("0")
    assert evidence.proposed_position_amount_eur == Decimal("250")


def test_live_account_binds_trading_account_flags_verbatim() -> None:
    conn = FakeConnection()
    insert_trading_account(conn, account_mode="live", live_trading_enabled=True)
    insert_complete_bundle(conn)
    venue_market_id = insert_venue_market(conn)
    bind_account_market(conn, venue_market_id=venue_market_id)
    insert_balance(conn)
    evidence = load_automatic_buy_account_allocation_evidence_v1(
        conn, resolved_bucket_config=_resolved_config(), **DEFAULT_ARGS,
    )
    assert evidence.account_mode == "live"
    assert evidence.live_trading_enabled is True


def test_live_account_with_flag_false_binds_verbatim_not_rejected_here() -> None:
    """Production account 3 shape: account_mode=live, live_trading_enabled=0.
    The projection must bind this faithfully; automatic_buy_gate_v1 is the
    layer that rejects it (REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT)."""
    conn = FakeConnection()
    insert_trading_account(conn, account_mode="live", live_trading_enabled=False)
    insert_complete_bundle(conn)
    venue_market_id = insert_venue_market(conn)
    bind_account_market(conn, venue_market_id=venue_market_id)
    insert_balance(conn)
    evidence = load_automatic_buy_account_allocation_evidence_v1(
        conn, resolved_bucket_config=_resolved_config(), **DEFAULT_ARGS,
    )
    assert evidence.account_mode == "live"
    assert evidence.live_trading_enabled is False


def test_trading_account_not_found_fails_closed() -> None:
    conn = FakeConnection()
    with pytest.raises(AutomaticBuyAccountAllocationEvidenceRepositoryError) as excinfo:
        load_automatic_buy_account_allocation_evidence_v1(
            conn, resolved_bucket_config=_resolved_config(), **DEFAULT_ARGS,
        )
    assert excinfo.value.args[0] == "TRADING_ACCOUNT_NOT_FOUND"


def test_missing_account_state_bundle_fails_closed() -> None:
    conn = FakeConnection()
    insert_trading_account(conn)
    venue_market_id = insert_venue_market(conn)
    bind_account_market(conn, venue_market_id=venue_market_id)
    with pytest.raises(AutomaticBuyAccountAllocationEvidenceRepositoryError) as excinfo:
        load_automatic_buy_account_allocation_evidence_v1(
            conn, resolved_bucket_config=_resolved_config(), **DEFAULT_ARGS,
        )
    assert excinfo.value.args[0] == "ACCOUNT_STATE_BUNDLE_MISSING"


def test_stale_account_state_bundle_fails_closed() -> None:
    conn = FakeConnection()
    insert_trading_account(conn)
    insert_complete_bundle(conn, snapshot_ts_utc=TS - timedelta(hours=2))
    venue_market_id = insert_venue_market(conn)
    bind_account_market(conn, venue_market_id=venue_market_id)
    insert_balance(conn)
    with pytest.raises(AutomaticBuyAccountAllocationEvidenceRepositoryError) as excinfo:
        load_automatic_buy_account_allocation_evidence_v1(
            conn,
            resolved_bucket_config=_resolved_config(),
            max_account_state_age_seconds=900,
            **DEFAULT_ARGS,
        )
    assert excinfo.value.args[0] == "ACCOUNT_STATE_BUNDLE_STALE"


def test_missing_balance_row_fails_closed() -> None:
    conn = FakeConnection()
    insert_trading_account(conn)
    insert_complete_bundle(conn)
    venue_market_id = insert_venue_market(conn)
    bind_account_market(conn, venue_market_id=venue_market_id)
    with pytest.raises(AutomaticBuyAccountAllocationEvidenceRepositoryError) as excinfo:
        load_automatic_buy_account_allocation_evidence_v1(
            conn, resolved_bucket_config=_resolved_config(), **DEFAULT_ARGS,
        )
    assert excinfo.value.args[0] == "FREE_QUOTE_BALANCE_ROW_MISSING"


def test_candidate_market_identity_mismatch_fails_closed() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    with pytest.raises(AutomaticBuyAccountAllocationEvidenceRepositoryError) as excinfo:
        load_automatic_buy_account_allocation_evidence_v1(
            conn,
            resolved_bucket_config=_resolved_config(),
            **{**DEFAULT_ARGS, "market": "ETH-EUR"},
        )
    assert excinfo.value.args[0] == "CANDIDATE_MARKET_IDENTITY_MISMATCH"


def test_open_position_valuation_is_deterministic() -> None:
    conn = FakeConnection()
    seed_happy_path(conn, position_count=1)
    insert_position(conn, asset_id=101, quantity_base=Decimal("1.5"))
    insert_market_price(conn, market="BTC-EUR", price=Decimal("50000"))
    evidence = load_automatic_buy_account_allocation_evidence_v1(
        conn, resolved_bucket_config=_resolved_config(), **DEFAULT_ARGS,
    )
    expected_value = Decimal("1.5") * Decimal("50000")
    assert evidence.current_open_positions == 1
    assert evidence.current_bucket_amount_eur == expected_value
    expected_nav = expected_value + Decimal("1000")
    assert evidence.current_asset_exposure_pct == min(Decimal("100"), (expected_value * 100) / expected_nav)


def test_asset_exposure_zero_when_candidate_asset_not_held() -> None:
    conn = FakeConnection()
    seed_happy_path(conn, position_count=1)
    other_asset_venue_market_id = insert_venue_market(conn, market="ETH-EUR", asset_id=202, symbol="ETH")
    bind_account_market(conn, venue_market_id=other_asset_venue_market_id)
    insert_position(conn, asset_id=202, symbol="ETH", quantity_base=Decimal("2"))
    insert_market_price(conn, market="ETH-EUR", symbol="ETH", price=Decimal("2000"))
    evidence = load_automatic_buy_account_allocation_evidence_v1(
        conn, resolved_bucket_config=_resolved_config(), **DEFAULT_ARGS,
    )
    assert evidence.current_open_positions == 1
    assert evidence.current_bucket_amount_eur == Decimal("4000")
    assert evidence.current_asset_exposure_pct == Decimal("0")


def test_unresolved_asset_market_binding_fails_closed() -> None:
    conn = FakeConnection()
    seed_happy_path(conn, position_count=1)
    insert_position(conn, asset_id=303, symbol="XRP", quantity_base=Decimal("10"))
    with pytest.raises(AutomaticBuyAccountAllocationEvidenceRepositoryError) as excinfo:
        load_automatic_buy_account_allocation_evidence_v1(
            conn, resolved_bucket_config=_resolved_config(), **DEFAULT_ARGS,
        )
    assert excinfo.value.args[0] == "ASSET_MARKET_BINDING_MISSING"


def test_non_eur_quote_currency_fails_closed() -> None:
    conn = FakeConnection()
    seed_happy_path(conn, position_count=1)
    usdt_venue_market_id = insert_venue_market(
        conn, market="XRP-USDT", asset_id=303, symbol="XRP", quote_currency="USDT",
    )
    bind_account_market(conn, venue_market_id=usdt_venue_market_id)
    insert_position(conn, asset_id=303, symbol="XRP", quantity_base=Decimal("10"))
    with pytest.raises(AutomaticBuyAccountAllocationEvidenceRepositoryError) as excinfo:
        load_automatic_buy_account_allocation_evidence_v1(
            conn, resolved_bucket_config=_resolved_config(), **DEFAULT_ARGS,
        )
    assert excinfo.value.args[0] == "UNSUPPORTED_POSITION_QUOTE_CURRENCY"


def test_missing_market_price_for_held_position_fails_closed() -> None:
    conn = FakeConnection()
    seed_happy_path(conn, position_count=1)
    insert_position(conn, asset_id=101, quantity_base=Decimal("1"))
    with pytest.raises(AutomaticBuyAccountAllocationEvidenceRepositoryError) as excinfo:
        load_automatic_buy_account_allocation_evidence_v1(
            conn, resolved_bucket_config=_resolved_config(), **DEFAULT_ARGS,
        )
    assert excinfo.value.args[0] == "POSITION_MARKET_PRICE_MISSING"


def test_stale_market_price_for_held_position_fails_closed() -> None:
    conn = FakeConnection()
    seed_happy_path(conn, position_count=1)
    insert_position(conn, asset_id=101, quantity_base=Decimal("1"))
    insert_market_price(conn, market="BTC-EUR", price=Decimal("50000"), observed_ts_utc=TS - timedelta(hours=2))
    with pytest.raises(AutomaticBuyAccountAllocationEvidenceRepositoryError) as excinfo:
        load_automatic_buy_account_allocation_evidence_v1(
            conn, resolved_bucket_config=_resolved_config(), max_market_price_age_seconds=900, **DEFAULT_ARGS,
        )
    assert excinfo.value.args[0] == "POSITION_MARKET_PRICE_STALE"


def test_execution_enabled_false_with_no_permission_row() -> None:
    conn = FakeConnection()
    insert_trading_account(conn)
    insert_complete_bundle(conn)
    venue_market_id = insert_venue_market(conn)
    bind_account_market(conn, venue_market_id=venue_market_id)
    insert_balance(conn)
    evidence = load_automatic_buy_account_allocation_evidence_v1(
        conn, resolved_bucket_config=_resolved_config(), **DEFAULT_ARGS,
    )
    assert evidence.automatic_buy_execution_enabled is False


def test_execution_enabled_reflects_disabled_permission_row() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM automatic_buy_account_permission_v1")
    insert_buy_permission(conn, execution_enabled=False)
    evidence = load_automatic_buy_account_allocation_evidence_v1(
        conn, resolved_bucket_config=_resolved_config(), **DEFAULT_ARGS,
    )
    assert evidence.automatic_buy_execution_enabled is False


def test_proposed_position_amount_bound_to_config_ceiling() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    evidence = load_automatic_buy_account_allocation_evidence_v1(
        conn, resolved_bucket_config=_resolved_config(max_position_amount_eur=Decimal("77")), **DEFAULT_ARGS,
    )
    assert evidence.proposed_position_amount_eur == Decimal("77")


def test_proposed_position_amount_zero_when_bucket_config_unresolved() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    evidence = load_automatic_buy_account_allocation_evidence_v1(
        conn, resolved_bucket_config=None, **DEFAULT_ARGS,
    )
    assert evidence.proposed_position_amount_eur == Decimal("0")


def test_proposed_position_amount_zero_when_config_ceiling_unset() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    evidence = load_automatic_buy_account_allocation_evidence_v1(
        conn, resolved_bucket_config=_resolved_config(max_position_amount_eur=None), **DEFAULT_ARGS,
    )
    assert evidence.proposed_position_amount_eur == Decimal("0")


def test_blocking_conflict_true_when_open_order_in_candidate_market() -> None:
    from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import insert_open_order

    conn = FakeConnection()
    insert_trading_account(conn)
    insert_complete_bundle(conn, order_count=1)
    venue_market_id = insert_venue_market(conn)
    bind_account_market(conn, venue_market_id=venue_market_id)
    insert_balance(conn)
    insert_open_order(conn, market="BTC-EUR")
    evidence = load_automatic_buy_account_allocation_evidence_v1(
        conn, resolved_bucket_config=_resolved_config(), **DEFAULT_ARGS,
    )
    assert evidence.blocking_conflict is True
