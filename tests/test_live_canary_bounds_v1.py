from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from src.executor.live_canary_bounds_v1 import (
    CANARY_MAX_NOTIONAL_EUR_CEILING,
    CANARY_MAX_ORDERS_PER_CYCLE_CEILING,
    ENV_MARKET,
    ENV_MAX_NOTIONAL_EUR,
    ENV_MAX_ORDERS_PER_CYCLE,
    ENV_TRADING_ACCOUNT_ID,
    ENV_VENUE,
    LiveCanaryBoundsError,
    LiveCanaryBoundsV1,
    LiveCanaryScopeDeniedError,
    assert_handoff_within_canary_scope_v1,
    assert_plan_notional_within_canary_bound_v1,
    clamp_batch_limit_to_canary_v1,
    load_live_canary_bounds_from_env_v1,
)


def _bounds(**changes: object) -> LiveCanaryBoundsV1:
    values: dict[str, object] = dict(
        version="v1",
        allowed_trading_account_id=3,
        allowed_venue="bitvavo",
        allowed_market="BTC-EUR",
        allowed_side="BUY",
        max_orders_per_cycle=1,
        max_notional_eur=Decimal("10"),
        kill_switch_required=True,
        withdrawal_permission=False,
    )
    values.update(changes)
    return LiveCanaryBoundsV1(**values)  # type: ignore[arg-type]


@dataclass
class _Handoff:
    trading_account_id: int
    venue: str
    market: str
    side: str


@dataclass
class _Leg:
    price: Decimal
    quantity: Decimal


def test_valid_canary_bounds_construct() -> None:
    bounds = _bounds()
    assert bounds.allowed_side == "BUY"
    assert bounds.kill_switch_required is True
    assert bounds.withdrawal_permission is False


@pytest.mark.parametrize(
    "changes",
    [
        {"allowed_side": "SELL"},
        {"max_orders_per_cycle": 2},
        {"max_orders_per_cycle": 0},
        {"max_notional_eur": Decimal("0")},
        {"max_notional_eur": CANARY_MAX_NOTIONAL_EUR_CEILING + Decimal("1")},
        {"kill_switch_required": False},
        {"withdrawal_permission": True},
        {"allowed_trading_account_id": 0},
        {"allowed_venue": ""},
        {"allowed_market": ""},
        {"version": "v2"},
    ],
)
def test_structurally_unsafe_canary_bounds_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(LiveCanaryBoundsError):
        _bounds(**changes)


def test_max_orders_per_cycle_cannot_exceed_hard_ceiling() -> None:
    assert CANARY_MAX_ORDERS_PER_CYCLE_CEILING == 1


def test_load_from_env_fails_closed_on_missing_values(monkeypatch) -> None:
    for name in (
        ENV_TRADING_ACCOUNT_ID,
        ENV_VENUE,
        ENV_MARKET,
        ENV_MAX_NOTIONAL_EUR,
        ENV_MAX_ORDERS_PER_CYCLE,
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(LiveCanaryBoundsError):
        load_live_canary_bounds_from_env_v1()


def test_load_from_env_resolves_explicit_values(monkeypatch) -> None:
    monkeypatch.setenv(ENV_TRADING_ACCOUNT_ID, "3")
    monkeypatch.setenv(ENV_VENUE, "bitvavo")
    monkeypatch.setenv(ENV_MARKET, "BTC-EUR")
    monkeypatch.setenv(ENV_MAX_NOTIONAL_EUR, "10")
    monkeypatch.delenv(ENV_MAX_ORDERS_PER_CYCLE, raising=False)
    bounds = load_live_canary_bounds_from_env_v1()
    assert bounds.allowed_trading_account_id == 3
    assert bounds.allowed_venue == "bitvavo"
    assert bounds.allowed_market == "BTC-EUR"
    assert bounds.max_notional_eur == Decimal("10")
    assert bounds.max_orders_per_cycle == 1


def test_wrong_account_market_or_side_blocks_handoff_scope() -> None:
    bounds = _bounds()
    assert_handoff_within_canary_scope_v1(
        bounds, _Handoff(trading_account_id=3, venue="bitvavo", market="BTC-EUR", side="BUY")
    )
    with pytest.raises(LiveCanaryScopeDeniedError):
        assert_handoff_within_canary_scope_v1(
            bounds, _Handoff(trading_account_id=4, venue="bitvavo", market="BTC-EUR", side="BUY")
        )
    with pytest.raises(LiveCanaryScopeDeniedError):
        assert_handoff_within_canary_scope_v1(
            bounds, _Handoff(trading_account_id=3, venue="bitvavo", market="ETH-EUR", side="BUY")
        )
    with pytest.raises(LiveCanaryScopeDeniedError):
        assert_handoff_within_canary_scope_v1(
            bounds, _Handoff(trading_account_id=3, venue="bitvavo", market="BTC-EUR", side="SELL")
        )


def test_max_notional_ceiling_cannot_be_exceeded() -> None:
    bounds = _bounds(max_notional_eur=Decimal("10"))
    assert_plan_notional_within_canary_bound_v1(
        bounds, [_Leg(price=Decimal("5"), quantity=Decimal("2"))]
    )
    with pytest.raises(LiveCanaryScopeDeniedError):
        assert_plan_notional_within_canary_bound_v1(
            bounds, [_Leg(price=Decimal("5"), quantity=Decimal("2.01"))]
        )


def test_clamp_batch_limit_truncates_deterministically() -> None:
    bounds = _bounds(max_orders_per_cycle=1)
    assert clamp_batch_limit_to_canary_v1(bounds, 100) == 1
    assert clamp_batch_limit_to_canary_v1(bounds, 1) == 1
    with pytest.raises(LiveCanaryBoundsError):
        clamp_batch_limit_to_canary_v1(bounds, 0)
