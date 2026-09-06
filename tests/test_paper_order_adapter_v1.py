from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.executor.broker_ack_classification_v1 import BrokerAckStateV1
from src.executor.execution_leg_v1 import ACTIVE, FILLED, PREPARED, ExecutionLegV1
from src.executor.paper_order_adapter_v1 import (
    PaperMarketEvidenceUnavailableError,
    PaperMarketQuoteV1,
    PaperOrderPlacementAdapterV1,
    paper_broker_cumulative_fill_evidence_from_leg_v1,
)
from src.executor.paper_order_placement_repository_v1 import PaperOrderPlacementConflictError

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
MARKET = "BTC-EUR"


class FixedQuoteProvider:
    def __init__(self, quote: PaperMarketQuoteV1 | None) -> None:
        self.quote = quote
        self.calls = 0

    def latest_quote(self, *, market: str) -> PaperMarketQuoteV1 | None:
        self.calls += 1
        return self.quote


class MemoryPlacementRepository:
    """In-memory test double mirroring ``PaperOrderPlacementRepositoryV1``'s
    (market, client_order_id) uniqueness/idempotency/conflict contract."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, object]] = {}

    def record_placement(self, *, market, client_order_id, side, price, quantity, ack):
        key = (market, client_order_id)
        existing = self.rows.get(key)
        if existing is not None:
            if (existing["side"], existing["price"], existing["quantity"]) != (side, price, quantity):
                raise PaperOrderPlacementConflictError("PAPER_ORDER_CLIENT_ORDER_ID_IDENTITY_CONFLICT")
            return existing["ack"]
        self.rows[key] = {"side": side, "price": price, "quantity": quantity, "ack": ack}
        return ack

    def find_order_by_client_order_id(self, *, market, client_order_id):
        row = self.rows.get((market, client_order_id))
        return None if row is None else row["ack"]


def _adapter(
    quote: PaperMarketQuoteV1 | None,
    *,
    max_age: int = 30,
    now: datetime = NOW,
    placement_repository: MemoryPlacementRepository | None = None,
) -> PaperOrderPlacementAdapterV1:
    return PaperOrderPlacementAdapterV1(
        quote_provider=FixedQuoteProvider(quote),
        max_quote_age_seconds=max_age,
        now_fn=lambda: now,
        placement_repository=placement_repository or MemoryPlacementRepository(),
    )


def _place(adapter: PaperOrderPlacementAdapterV1, *, side: str = "BUY", price: Decimal = Decimal("100")):
    return adapter.place_order(
        market=MARKET, side=side, price=price, quantity=Decimal("0.01"),
        client_order_id="client-1", operator_id=1,
    )


def test_crossed_post_only_buy_is_rejected_not_filled() -> None:
    """Every leg reaching this adapter is post-only (#753 B5.5 review fix):
    a BUY quote at or below the limit price would cross the book, so a real
    exchange rejects the post-only order outright instead of filling it."""
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("100"), observed_ts_utc=NOW - timedelta(seconds=5))
    adapter = _adapter(quote)
    ack = _place(adapter, side="BUY", price=Decimal("100"))
    assert ack.state == BrokerAckStateV1.REJECTED
    assert ack.broker_order_id is None


def test_non_marketable_buy_stays_active() -> None:
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("101"), observed_ts_utc=NOW - timedelta(seconds=5))
    adapter = _adapter(quote)
    ack = _place(adapter, side="BUY", price=Decimal("100"))
    assert ack.state == BrokerAckStateV1.ACTIVE


def test_crossed_post_only_sell_is_rejected_not_filled() -> None:
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("100"), best_ask=Decimal("101"), observed_ts_utc=NOW - timedelta(seconds=5))
    adapter = _adapter(quote)
    ack = _place(adapter, side="SELL", price=Decimal("100"))
    assert ack.state == BrokerAckStateV1.REJECTED
    assert ack.broker_order_id is None


def test_buy_uses_ask_not_bid_at_spread_boundary() -> None:
    quote = PaperMarketQuoteV1(
        market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("101"),
        observed_ts_utc=NOW - timedelta(seconds=5),
    )
    assert _place(_adapter(quote), side="BUY", price=Decimal("100")).state == BrokerAckStateV1.ACTIVE
    assert _place(_adapter(quote), side="BUY", price=Decimal("101")).state == BrokerAckStateV1.REJECTED


def test_sell_uses_bid_not_ask_at_spread_boundary() -> None:
    quote = PaperMarketQuoteV1(
        market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("101"),
        observed_ts_utc=NOW - timedelta(seconds=5),
    )
    assert _place(_adapter(quote), side="SELL", price=Decimal("100")).state == BrokerAckStateV1.ACTIVE
    assert _place(_adapter(quote), side="SELL", price=Decimal("99")).state == BrokerAckStateV1.REJECTED


@pytest.mark.parametrize(
    "quote",
    [
        None,
        PaperMarketQuoteV1(market="ETH-EUR", best_bid=Decimal("99"), best_ask=Decimal("99"), observed_ts_utc=NOW),  # market mismatch
        PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("-1"), best_ask=Decimal("1"), observed_ts_utc=NOW),  # malformed bid
        PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("101"), best_ask=Decimal("100"), observed_ts_utc=NOW),  # inverted spread
        PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("100"), observed_ts_utc=NOW + timedelta(seconds=5)),  # future
        PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("100"), observed_ts_utc=NOW - timedelta(seconds=120)),  # stale
    ],
)
def test_missing_or_conflicting_evidence_fails_closed(quote: PaperMarketQuoteV1 | None) -> None:
    adapter = _adapter(quote, max_age=30)
    with pytest.raises(PaperMarketEvidenceUnavailableError):
        _place(adapter)


def test_find_order_reports_no_order_when_none_was_ever_placed() -> None:
    adapter = _adapter(None)
    assert adapter.find_order_by_client_order_id(market=MARKET, client_order_id="client-1") is None


def test_find_order_recovers_acknowledged_active_order_after_crash_window() -> None:
    """#753 B5.5 PR #776 review fix: a crash between this adapter's ACTIVE
    acknowledgement and executor_execution_leg persistence must not lose the
    modeled active order. Simulate that crash window by placing the order,
    discarding the returned ack (as if the caller never got to persist it),
    then retrying via find_order_by_client_order_id exactly like
    execution_order_reconciliation_v1.reconcile_execution_leg does -- it must
    recover the same acknowledged ACTIVE order, not report None."""
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("101"), observed_ts_utc=NOW - timedelta(seconds=5))
    repository = MemoryPlacementRepository()
    adapter = _adapter(quote, placement_repository=repository)

    placed = _place(adapter, side="BUY", price=Decimal("100"))
    assert placed.state == BrokerAckStateV1.ACTIVE

    # A fresh adapter instance models the orchestrator's next attempt after a
    # crash, sharing only the durable placement repository -- exactly what
    # find_order_by_client_order_id must be able to recover from.
    retry_adapter = _adapter(quote, placement_repository=repository)
    recovered = retry_adapter.find_order_by_client_order_id(market=MARKET, client_order_id="client-1")
    assert recovered is not None
    assert recovered.state == BrokerAckStateV1.ACTIVE
    assert recovered.broker_order_id == placed.broker_order_id == "paper-client-1"


def test_find_order_recovers_acknowledged_rejected_order() -> None:
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("100"), observed_ts_utc=NOW - timedelta(seconds=5))
    repository = MemoryPlacementRepository()
    adapter = _adapter(quote, placement_repository=repository)

    placed = _place(adapter, side="BUY", price=Decimal("100"))
    assert placed.state == BrokerAckStateV1.REJECTED

    recovered = adapter.find_order_by_client_order_id(market=MARKET, client_order_id="client-1")
    assert recovered is not None
    assert recovered.state == BrokerAckStateV1.REJECTED
    assert recovered.broker_order_id is None


def test_replaying_the_same_client_order_id_is_idempotent() -> None:
    """A second place_order for the identical (market, client_order_id,
    side, price, quantity) must not re-decide against possibly different
    current market evidence; it returns the already-recorded ack."""
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("101"), observed_ts_utc=NOW - timedelta(seconds=5))
    repository = MemoryPlacementRepository()
    adapter = _adapter(quote, placement_repository=repository)

    first = _place(adapter, side="BUY", price=Decimal("100"))
    second = _place(adapter, side="BUY", price=Decimal("100"))
    assert first == second
    assert first.state == BrokerAckStateV1.ACTIVE


def test_reusing_client_order_id_for_a_conflicting_order_fails_closed() -> None:
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("101"), observed_ts_utc=NOW - timedelta(seconds=5))
    repository = MemoryPlacementRepository()
    adapter = _adapter(quote, placement_repository=repository)

    _place(adapter, side="BUY", price=Decimal("100"))
    with pytest.raises(PaperOrderPlacementConflictError):
        _place(adapter, side="BUY", price=Decimal("100.5"))


def test_no_broker_or_network_import_in_adapter_module() -> None:
    import ast

    import src.executor.paper_order_adapter_v1 as module

    with open(module.__file__, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    for forbidden in ("bitvavo", "requests", "httpx", "socket", "credential"):
        assert not any(forbidden in name.lower() for name in imported_modules)


def _leg(**overrides: object) -> ExecutionLegV1:
    base = ExecutionLegV1(
        execution_leg_id=1,
        handoff_id=41,
        leg_index=1,
        trading_account_id=7,
        venue="bitvavo",
        market=MARKET,
        side="BUY",
        client_order_id="client-1",
        operator_id=1,
        price=Decimal("100"),
        quantity=Decimal("0.01"),
        state=FILLED,
        broker_order_id="paper-client-1",
    )
    return replace(base, **overrides)


def test_fill_evidence_is_deterministic_for_the_same_leg() -> None:
    leg = _leg()
    first = paper_broker_cumulative_fill_evidence_from_leg_v1(leg, observed_ts_utc=NOW)
    second = paper_broker_cumulative_fill_evidence_from_leg_v1(leg, observed_ts_utc=NOW + timedelta(minutes=5))
    assert first.source_snapshot_id == second.source_snapshot_id
    assert first.cumulative_filled_base_quantity == second.cumulative_filled_base_quantity == Decimal("0.01")


def test_fill_evidence_differs_for_a_different_leg_identity() -> None:
    leg_a = _leg()
    leg_b = _leg(execution_leg_id=2, client_order_id="client-2", broker_order_id="paper-client-2")
    evidence_a = paper_broker_cumulative_fill_evidence_from_leg_v1(leg_a, observed_ts_utc=NOW)
    evidence_b = paper_broker_cumulative_fill_evidence_from_leg_v1(leg_b, observed_ts_utc=NOW)
    assert evidence_a.source_snapshot_id != evidence_b.source_snapshot_id


@pytest.mark.parametrize("state", [ACTIVE, PREPARED])
def test_fill_evidence_requires_filled_state(state: str) -> None:
    leg = _leg(state=state)
    with pytest.raises(ValueError, match="REQUIRES_FILLED_LEG"):
        paper_broker_cumulative_fill_evidence_from_leg_v1(leg, observed_ts_utc=NOW)


def test_fill_evidence_requires_broker_order_id() -> None:
    leg = _leg(broker_order_id=None)
    with pytest.raises(ValueError, match="REQUIRES_BROKER_ORDER_ID"):
        paper_broker_cumulative_fill_evidence_from_leg_v1(leg, observed_ts_utc=NOW)
