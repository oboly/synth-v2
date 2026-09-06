from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.decision_gate.strategy_owned_inventory_v1 import (
    StrategyOwnedInventoryError,
    StrategyOwnedInventoryEventV1,
    project_strategy_owned_inventory_v1,
)

NOW = datetime(2026, 9, 6, 1, 0, tzinfo=timezone.utc)


def _event(**changes: object) -> StrategyOwnedInventoryEventV1:
    values: dict[str, object] = dict(
        event_id="evt-1", trading_account_id=7, venue="bitvavo", market="SOL-EUR",
        strategy_bucket_id="AUTO_SHORTTF_FIB", strategy_id="fib", strategy_version="1",
        trade_id="trade-1", source_execution_plan_id="plan-1", source_fill_id="fill-1",
        side="BUY", filled_base_quantity=Decimal("4"), fill_notional_eur=Decimal("400"),
        occurred_ts_utc=NOW,
    )
    values.update(changes)
    return StrategyOwnedInventoryEventV1(**values)  # type: ignore[arg-type]


def test_two_strategies_can_own_same_market_independently() -> None:
    events = (
        _event(),
        _event(event_id="evt-2", source_fill_id="fill-2", strategy_bucket_id="LONG_TERM_MOONSHOT",
               strategy_id="moon", trade_id="trade-2", filled_base_quantity=Decimal("6")),
    )
    positions = project_strategy_owned_inventory_v1(events)
    assert [p.owned_base_quantity for p in positions] == [Decimal("4"), Decimal("6")]


def test_partial_sell_reduces_only_matching_lineage() -> None:
    events = (
        _event(),
        _event(event_id="evt-2", source_fill_id="fill-2", side="SELL",
               filled_base_quantity=Decimal("1.5"), fill_notional_eur=None),
    )
    position = project_strategy_owned_inventory_v1(events)[0]
    assert position.owned_base_quantity == Decimal("2.5")
    assert position.bought_base_quantity == Decimal("4")
    assert position.sold_base_quantity == Decimal("1.5")


def test_sell_cannot_consume_other_strategy_inventory() -> None:
    events = (
        _event(strategy_bucket_id="LONG_TERM_MOONSHOT", strategy_id="moon", trade_id="moon-1"),
        _event(event_id="evt-2", source_fill_id="fill-2", side="SELL",
               strategy_bucket_id="AUTO_SHORTTF_FIB", strategy_id="fib", trade_id="fib-1",
               filled_base_quantity=Decimal("1"), fill_notional_eur=None),
    )
    with pytest.raises(StrategyOwnedInventoryError, match="OVER_REDUCTION"):
        project_strategy_owned_inventory_v1(events)


def test_duplicate_fill_fails_closed_for_restart_replay() -> None:
    duplicate = _event(event_id="evt-2")
    with pytest.raises(StrategyOwnedInventoryError, match="DUPLICATE_STRATEGY_INVENTORY_SOURCE_FILL"):
        project_strategy_owned_inventory_v1((_event(), duplicate))
