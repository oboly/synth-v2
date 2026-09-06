from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.decision_gate.automatic_buy_fill_reconciliation_v1 import (
    AutomaticBuyFillPlanIdentityV1,
    AutomaticBuyFillReconciliationError,
    reconcile_automatic_buy_paper_fill_v1,
    resolve_automatic_buy_fill_lineage_v1,
)
from src.decision_gate.automatic_buy_fill_reconciliation_persistence_v1 import (
    reconcile_and_persist_automatic_buy_paper_fill_v1,
)
from src.decision_gate.strategy_owned_fill_reconciliation_v1 import (
    BrokerCumulativeFillEvidenceV1,
    StrategyOwnedFillReconciliationError,
)
from src.decision_gate.strategy_owned_inventory_repository_v1 import (
    load_strategy_owned_inventory_events_v1,
)
from src.decision_gate.strategy_owned_inventory_v1 import project_strategy_owned_inventory_v1
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import FakeConnection
from tests.test_strategy_owned_inventory_v1 import _event

NOW = datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)


def _identity(**changes: object) -> AutomaticBuyFillPlanIdentityV1:
    values: dict[str, object] = dict(
        trading_account_id=7, venue="bitvavo", market="SOL-EUR",
        strategy_bucket_id="AUTO_SHORTTF_FIB", strategy_id="fib", strategy_version="1",
        genesis_trade_id="automatic_buy_trade_id_v1:7:genesis-digest",
        source_execution_plan_id="automatic_buy_v1:7:evidence-1:plan-digest",
        source_order_id="order-1",
    )
    values.update(changes)
    return AutomaticBuyFillPlanIdentityV1(**values)  # type: ignore[arg-type]


def _evidence(snapshot: str, cumulative: str, ts: datetime = NOW) -> BrokerCumulativeFillEvidenceV1:
    return BrokerCumulativeFillEvidenceV1(
        source_snapshot_id=snapshot,
        cumulative_filled_base_quantity=Decimal(cumulative),
        observed_ts_utc=ts,
    )


def test_genesis_enter_uses_plan_trade_id_and_matches_770_lineage() -> None:
    fact, event = reconcile_automatic_buy_paper_fill_v1(
        identity=_identity(), evidence=_evidence("snap-1", "2"),
        prior_facts=(), prior_inventory_events=(),
    )
    assert event is not None
    assert event.trade_id == "automatic_buy_trade_id_v1:7:genesis-digest"
    assert (event.trading_account_id, event.venue, event.market) == (7, "bitvavo", "SOL-EUR")
    assert (event.strategy_bucket_id, event.strategy_id, event.strategy_version) == (
        "AUTO_SHORTTF_FIB", "fib", "1",
    )
    assert event.source_execution_plan_id == "automatic_buy_v1:7:evidence-1:plan-digest"
    assert event.side == "BUY" and event.filled_base_quantity == Decimal("2")
    assert fact.trade_id == event.trade_id


def test_re_enter_continues_open_position_trade_id_instead_of_fragmenting() -> None:
    open_event = _event(filled_base_quantity=Decimal("3"))  # trade_id="trade-1", still open
    re_enter_identity = _identity(
        genesis_trade_id="automatic_buy_trade_id_v1:7:re-enter-digest",
        source_order_id="order-2",
    )
    lineage = resolve_automatic_buy_fill_lineage_v1(
        identity=re_enter_identity, prior_inventory_events=(open_event,),
    )
    assert lineage.trade_id == "trade-1"  # reused, not the fresh genesis id

    _, event = reconcile_automatic_buy_paper_fill_v1(
        identity=re_enter_identity, evidence=_evidence("snap-2", "1.5"),
        prior_facts=(), prior_inventory_events=(open_event,),
    )
    assert event is not None and event.trade_id == "trade-1"
    positions = project_strategy_owned_inventory_v1((open_event, event))
    assert len(positions) == 1
    assert positions[0].owned_base_quantity == Decimal("4.5")


def test_new_lineage_after_full_exit_does_not_reuse_closed_trade_id() -> None:
    closed_events = (
        _event(filled_base_quantity=Decimal("3")),
        _event(event_id="evt-2", source_fill_id="fill-2", side="SELL", filled_base_quantity=Decimal("3")),
    )
    identity = _identity(genesis_trade_id="automatic_buy_trade_id_v1:7:new-cycle-digest")
    lineage = resolve_automatic_buy_fill_lineage_v1(
        identity=identity, prior_inventory_events=closed_events,
    )
    assert lineage.trade_id == "automatic_buy_trade_id_v1:7:new-cycle-digest"


def test_ambiguous_multiple_open_positions_for_same_lineage_fails_closed() -> None:
    events = (
        _event(filled_base_quantity=Decimal("3")),
        _event(
            event_id="evt-2", source_fill_id="fill-2", trade_id="trade-2",
            filled_base_quantity=Decimal("1"),
        ),
    )
    with pytest.raises(AutomaticBuyFillReconciliationError, match="AMBIGUOUS_OPEN_STRATEGY_OWNED_POSITION"):
        resolve_automatic_buy_fill_lineage_v1(identity=_identity(), prior_inventory_events=events)


@pytest.mark.parametrize(
    "field,value",
    [
        ("venue", ""),
        ("strategy_bucket_id", "   "),
        ("strategy_id", ""),
        ("strategy_version", ""),
        ("genesis_trade_id", ""),
        ("source_execution_plan_id", ""),
        ("source_order_id", ""),
    ],
)
def test_missing_lineage_field_fails_closed(field: str, value: str) -> None:
    with pytest.raises(AutomaticBuyFillReconciliationError, match="INVALID_AUTOMATIC_BUY_FILL_IDENTITY"):
        resolve_automatic_buy_fill_lineage_v1(
            identity=_identity(**{field: value}), prior_inventory_events=(),
        )


def test_invalid_trading_account_id_fails_closed() -> None:
    with pytest.raises(AutomaticBuyFillReconciliationError, match="INVALID_TRADING_ACCOUNT_ID"):
        resolve_automatic_buy_fill_lineage_v1(
            identity=_identity(trading_account_id=0), prior_inventory_events=(),
        )


def test_mismatched_lineage_on_same_order_fails_closed_via_752() -> None:
    reconcile_automatic_buy_paper_fill_v1(
        identity=_identity(), evidence=_evidence("snap-1", "2"),
        prior_facts=(), prior_inventory_events=(),
    )
    fact1, _ = reconcile_automatic_buy_paper_fill_v1(
        identity=_identity(), evidence=_evidence("snap-1", "2"),
        prior_facts=(), prior_inventory_events=(),
    )
    with pytest.raises(StrategyOwnedFillReconciliationError, match="SOURCE_ORDER_LINEAGE_CONFLICT"):
        reconcile_automatic_buy_paper_fill_v1(
            identity=_identity(strategy_bucket_id="LONG_TERM_MOONSHOT"),
            evidence=_evidence("snap-2", "3"),
            prior_facts=(fact1,), prior_inventory_events=(),
        )


def test_unrelated_manual_fill_never_gains_automatic_buy_strategy_ownership() -> None:
    """A manual/unrelated fill lineage is never merged into an automatic-BUY
    strategy's open position just because it shares account/venue/market --
    RE_ENTER continuity only matches on the exact strategy_bucket_id/
    strategy_id/strategy_version lineage, never on market alone."""
    automatic_buy_open = _event(filled_base_quantity=Decimal("3"))  # strategy_bucket_id=AUTO_SHORTTF_FIB
    manual_identity = _identity(
        strategy_bucket_id="MANUAL_DESK", strategy_id="manual",
        genesis_trade_id="manual-trade-1", source_order_id="manual-order-1",
    )
    lineage = resolve_automatic_buy_fill_lineage_v1(
        identity=manual_identity, prior_inventory_events=(automatic_buy_open,),
    )
    assert lineage.trade_id == "manual-trade-1"  # own genesis, not the automatic-BUY trade_id

    _, event = reconcile_automatic_buy_paper_fill_v1(
        identity=manual_identity, evidence=_evidence("snap-manual", "2"),
        prior_facts=(), prior_inventory_events=(automatic_buy_open,),
    )
    positions = project_strategy_owned_inventory_v1((automatic_buy_open, event))
    fib_position = next(p for p in positions if p.strategy_bucket_id == "AUTO_SHORTTF_FIB")
    manual_position = next(p for p in positions if p.strategy_bucket_id == "MANUAL_DESK")
    assert fib_position.owned_base_quantity == Decimal("3")  # unchanged by the manual fill
    assert manual_position.owned_base_quantity == Decimal("2")
    assert manual_position.trade_id == "manual-trade-1"


def test_persistence_writes_fact_and_event_and_replay_is_idempotent() -> None:
    conn = FakeConnection()
    identity = _identity()

    fact1, event1 = reconcile_and_persist_automatic_buy_paper_fill_v1(
        conn, identity=identity, evidence=_evidence("snap-1", "2"),
    )
    assert event1 is not None
    persisted_events = load_strategy_owned_inventory_events_v1(conn, trading_account_id=7)
    assert len(persisted_events) == 1
    assert persisted_events[0].event_id == event1.event_id

    fact2, event2 = reconcile_and_persist_automatic_buy_paper_fill_v1(
        conn, identity=identity, evidence=_evidence("snap-1", "2"),
    )
    assert fact2 == fact1
    assert event2 is None
    persisted_events_after_replay = load_strategy_owned_inventory_events_v1(conn, trading_account_id=7)
    assert len(persisted_events_after_replay) == 1  # no duplicate row on replay

    fact3, event3 = reconcile_and_persist_automatic_buy_paper_fill_v1(
        conn, identity=identity, evidence=_evidence("snap-2", "5"),
    )
    assert event3 is not None and event3.filled_base_quantity == Decimal("3")
    persisted_events_final = load_strategy_owned_inventory_events_v1(conn, trading_account_id=7)
    assert len(persisted_events_final) == 2
