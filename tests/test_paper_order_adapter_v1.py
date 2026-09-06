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

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
MARKET = "BTC-EUR"


class FixedQuoteProvider:
    def __init__(self, quote: PaperMarketQuoteV1 | None) -> None:
        self.quote = quote
        self.calls = 0

    def latest_quote(self, *, market: str) -> PaperMarketQuoteV1 | None:
        self.calls += 1
        return self.quote


def _adapter(quote: PaperMarketQuoteV1 | None, *, max_age: int = 30, now: datetime = NOW) -> PaperOrderPlacementAdapterV1:
    return PaperOrderPlacementAdapterV1(
        quote_provider=FixedQuoteProvider(quote),
        max_quote_age_seconds=max_age,
        now_fn=lambda: now,
    )


def _place(adapter: PaperOrderPlacementAdapterV1, *, side: str = "BUY", price: Decimal = Decimal("100")):
    return adapter.place_order(
        market=MARKET, side=side, price=price, quantity=Decimal("0.01"),
        client_order_id="client-1", operator_id=1,
    )


def test_marketable_buy_fills_deterministically() -> None:
    quote = PaperMarketQuoteV1(market=MARKET, price=Decimal("99"), observed_ts_utc=NOW - timedelta(seconds=5))
    adapter = _adapter(quote)
    ack = _place(adapter, side="BUY", price=Decimal("100"))
    assert ack.state == BrokerAckStateV1.FILLED
    assert ack.broker_order_id == "paper-client-1"


def test_non_marketable_buy_stays_active() -> None:
    quote = PaperMarketQuoteV1(market=MARKET, price=Decimal("101"), observed_ts_utc=NOW - timedelta(seconds=5))
    adapter = _adapter(quote)
    ack = _place(adapter, side="BUY", price=Decimal("100"))
    assert ack.state == BrokerAckStateV1.ACTIVE


def test_marketable_sell_fills_deterministically() -> None:
    quote = PaperMarketQuoteV1(market=MARKET, price=Decimal("101"), observed_ts_utc=NOW - timedelta(seconds=5))
    adapter = _adapter(quote)
    ack = _place(adapter, side="SELL", price=Decimal("100"))
    assert ack.state == BrokerAckStateV1.FILLED


@pytest.mark.parametrize(
    "quote",
    [
        None,
        PaperMarketQuoteV1(market="ETH-EUR", price=Decimal("99"), observed_ts_utc=NOW),  # market mismatch
        PaperMarketQuoteV1(market=MARKET, price=Decimal("-1"), observed_ts_utc=NOW),  # malformed price
        PaperMarketQuoteV1(market=MARKET, price=Decimal("99"), observed_ts_utc=NOW + timedelta(seconds=5)),  # future
        PaperMarketQuoteV1(market=MARKET, price=Decimal("99"), observed_ts_utc=NOW - timedelta(seconds=120)),  # stale
    ],
)
def test_missing_or_conflicting_evidence_fails_closed(quote: PaperMarketQuoteV1 | None) -> None:
    adapter = _adapter(quote, max_age=30)
    with pytest.raises(PaperMarketEvidenceUnavailableError):
        _place(adapter)


def test_find_order_never_reports_a_placed_order() -> None:
    adapter = _adapter(None)
    assert adapter.find_order_by_client_order_id(market=MARKET, client_order_id="client-1") is None


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
