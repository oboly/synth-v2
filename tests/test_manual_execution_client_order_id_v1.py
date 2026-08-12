from __future__ import annotations

import pytest

from src.executor.manual_execution_client_order_id_v1 import derive_client_order_id


def test_same_persisted_leg_yields_same_client_order_id() -> None:
    kwargs = dict(
        plan_snapshot_id=701, leg_index=1, trading_account_id=1, venue="bitvavo", market="BTC-EUR"
    )
    assert derive_client_order_id(**kwargs) == derive_client_order_id(**kwargs)


def test_different_leg_index_yields_different_id() -> None:
    base = dict(plan_snapshot_id=701, trading_account_id=1, venue="bitvavo", market="BTC-EUR")
    assert derive_client_order_id(leg_index=1, **base) != derive_client_order_id(leg_index=2, **base)


def test_different_plan_snapshot_yields_different_id() -> None:
    base = dict(leg_index=1, trading_account_id=1, venue="bitvavo", market="BTC-EUR")
    assert derive_client_order_id(plan_snapshot_id=701, **base) != derive_client_order_id(
        plan_snapshot_id=702, **base
    )


def test_different_account_venue_or_market_yields_different_id() -> None:
    base = dict(plan_snapshot_id=701, leg_index=1)
    a = derive_client_order_id(trading_account_id=1, venue="bitvavo", market="BTC-EUR", **base)
    b = derive_client_order_id(trading_account_id=2, venue="bitvavo", market="BTC-EUR", **base)
    c = derive_client_order_id(trading_account_id=1, venue="kraken", market="BTC-EUR", **base)
    d = derive_client_order_id(trading_account_id=1, venue="bitvavo", market="ETH-EUR", **base)
    assert len({a, b, c, d}) == 4


def test_is_a_valid_uuid_string() -> None:
    import uuid

    value = derive_client_order_id(
        plan_snapshot_id=701, leg_index=1, trading_account_id=1, venue="bitvavo", market="BTC-EUR"
    )
    assert str(uuid.UUID(value)) == value


@pytest.mark.parametrize("bad_kwargs", [
    dict(plan_snapshot_id=0, leg_index=1, trading_account_id=1, venue="bitvavo", market="BTC-EUR"),
    dict(plan_snapshot_id=701, leg_index=0, trading_account_id=1, venue="bitvavo", market="BTC-EUR"),
    dict(plan_snapshot_id=701, leg_index=1, trading_account_id=0, venue="bitvavo", market="BTC-EUR"),
    dict(plan_snapshot_id=701, leg_index=1, trading_account_id=1, venue="", market="BTC-EUR"),
    dict(plan_snapshot_id=701, leg_index=1, trading_account_id=1, venue="bitvavo", market=""),
])
def test_invalid_identity_fails_closed(bad_kwargs: dict) -> None:
    with pytest.raises(ValueError):
        derive_client_order_id(**bad_kwargs)
