from decimal import Decimal

from src.decision_gate.strategy_owned_inventory_repository_v1 import (
    append_strategy_owned_inventory_event_v1,
    load_strategy_owned_inventory_events_v1,
)
from src.decision_gate.strategy_owned_inventory_v1 import project_strategy_owned_inventory_v1
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import FakeConnection, TS
from tests.test_strategy_owned_inventory_v1 import _event


def test_persist_load_and_replay_survives_restart_boundary() -> None:
    conn = FakeConnection()
    buy = _event(occurred_ts_utc=TS)
    sell = _event(
        event_id="evt-2", source_fill_id="fill-2", side="SELL",
        filled_base_quantity=Decimal("1.25"), fill_notional_eur=None, occurred_ts_utc=TS,
    )
    append_strategy_owned_inventory_event_v1(conn, event=buy)
    append_strategy_owned_inventory_event_v1(conn, event=sell)

    reloaded = load_strategy_owned_inventory_events_v1(conn, trading_account_id=7)
    assert len(reloaded) == 2
    position = project_strategy_owned_inventory_v1(reloaded)[0]
    assert position.owned_base_quantity == Decimal("2.75")
    assert position.sold_base_quantity == Decimal("1.25")
