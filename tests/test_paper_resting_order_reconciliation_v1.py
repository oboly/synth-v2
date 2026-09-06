from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.executor.execution_leg_v1 import ACTIVE, FILLED, PREPARED, ExecutionLegConflictError, ExecutionLegV1
from src.executor.paper_order_adapter_v1 import PaperMarketEvidenceUnavailableError, PaperMarketQuoteV1
from src.executor.paper_resting_order_reconciliation_v1 import (
    PAPER_RAW_STATUS_FILLED_ON_TOUCH,
    PaperRestingLegNotReconcilableError,
    reconcile_paper_resting_leg_v1,
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


class FakeLegRepository:
    """Minimal double mirroring ``ExecutionLegRepositoryV1.mark_active_filled_on_touch``'s
    guarded-CAS/idempotent-replay/conflict contract, without a database."""

    def __init__(self, leg: ExecutionLegV1) -> None:
        self.leg = leg
        self.calls = 0

    def mark_active_filled_on_touch(self, leg_id: int, *, broker_raw_status: str) -> ExecutionLegV1:
        self.calls += 1
        assert leg_id == self.leg.execution_leg_id
        if self.leg.state == FILLED:
            return self.leg
        if self.leg.state != ACTIVE:
            raise ExecutionLegConflictError("ACTIVE_FILLED_ON_TOUCH_TRANSITION_CONFLICT")
        self.leg = replace(
            self.leg, state=FILLED, broker_raw_status=broker_raw_status, last_reconciled_ts_utc=NOW,
        )
        return self.leg


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
        state=ACTIVE,
        broker_order_id="paper-client-1",
        broker_raw_status="PAPER_ACTIVE_SUBMISSION_TIME_ONLY_NOT_CROSSED",
    )
    return replace(base, **overrides)


def _reconcile(
    leg: ExecutionLegV1,
    quote: PaperMarketQuoteV1 | None,
    *,
    max_age: int = 30,
    now: datetime = NOW,
    repository: FakeLegRepository | None = None,
):
    return reconcile_paper_resting_leg_v1(
        leg,
        quote_provider=FixedQuoteProvider(quote),
        max_quote_age_seconds=max_age,
        now_fn=lambda: now,
        leg_repository=repository or FakeLegRepository(leg),
    )


def test_buy_fills_when_ask_touches_the_resting_limit_exact_threshold() -> None:
    leg = _leg(side="BUY", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("100"), observed_ts_utc=NOW - timedelta(seconds=5))
    repository = FakeLegRepository(leg)

    result = _reconcile(leg, quote, repository=repository)

    assert result.state == FILLED
    assert result.broker_raw_status == PAPER_RAW_STATUS_FILLED_ON_TOUCH
    assert result.broker_order_id == "paper-client-1"
    assert repository.calls == 1


def test_buy_fills_when_ask_crosses_below_the_resting_limit() -> None:
    leg = _leg(side="BUY", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("98"), best_ask=Decimal("99"), observed_ts_utc=NOW - timedelta(seconds=5))
    assert _reconcile(leg, quote).state == FILLED


def test_buy_stays_active_when_ask_has_not_touched_the_limit() -> None:
    leg = _leg(side="BUY", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("100.01"), observed_ts_utc=NOW - timedelta(seconds=5))
    repository = FakeLegRepository(leg)

    result = _reconcile(leg, quote, repository=repository)

    assert result.state == ACTIVE
    assert result == leg
    assert repository.calls == 0


def test_sell_fills_when_bid_touches_the_resting_limit_exact_threshold() -> None:
    leg = _leg(side="SELL", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("100"), best_ask=Decimal("101"), observed_ts_utc=NOW - timedelta(seconds=5))
    assert _reconcile(leg, quote).state == FILLED


def test_sell_stays_active_when_bid_has_not_touched_the_limit() -> None:
    leg = _leg(side="SELL", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99.99"), best_ask=Decimal("101"), observed_ts_utc=NOW - timedelta(seconds=5))
    result = _reconcile(leg, quote)
    assert result.state == ACTIVE
    assert result == leg


def test_already_filled_leg_replays_idempotently_without_requiring_a_fresh_quote() -> None:
    leg = _leg(state=FILLED, broker_raw_status=PAPER_RAW_STATUS_FILLED_ON_TOUCH)
    provider = FixedQuoteProvider(None)  # would fail closed if it were ever consulted
    repository = FakeLegRepository(leg)

    result = reconcile_paper_resting_leg_v1(
        leg, quote_provider=provider, max_quote_age_seconds=30, now_fn=lambda: NOW,
        leg_repository=repository,
    )

    assert result is leg
    assert provider.calls == 0
    assert repository.calls == 0


@pytest.mark.parametrize("state", [PREPARED, "SUBMISSION_UNCERTAIN", "REJECTED", "CANCELED"])
def test_non_active_non_filled_leg_is_not_reconcilable(state: str) -> None:
    leg = _leg(state=state)
    with pytest.raises(PaperRestingLegNotReconcilableError):
        _reconcile(leg, PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("100"), observed_ts_utc=NOW))


@pytest.mark.parametrize(
    "quote",
    [
        None,
        PaperMarketQuoteV1(market="ETH-EUR", best_bid=Decimal("99"), best_ask=Decimal("100"), observed_ts_utc=NOW),  # market mismatch
        PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("-1"), best_ask=Decimal("1"), observed_ts_utc=NOW),  # malformed
        PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("101"), best_ask=Decimal("100"), observed_ts_utc=NOW),  # inverted spread
        PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("100"), observed_ts_utc=NOW + timedelta(seconds=5)),  # future
        PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("100"), observed_ts_utc=NOW - timedelta(seconds=120)),  # stale
    ],
)
def test_missing_or_bad_evidence_fails_closed_and_leaves_leg_untouched(quote: PaperMarketQuoteV1 | None) -> None:
    leg = _leg(side="BUY", price=Decimal("100"))
    repository = FakeLegRepository(leg)

    with pytest.raises(PaperMarketEvidenceUnavailableError):
        _reconcile(leg, quote, repository=repository)

    assert repository.calls == 0
    assert repository.leg.state == ACTIVE


def test_no_broker_or_network_import_in_reconciliation_module() -> None:
    import ast

    import src.executor.paper_resting_order_reconciliation_v1 as module

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
    for forbidden in ("bitvavo", "requests", "httpx", "socket", "credential", "broker"):
        assert not any(forbidden in name.lower() for name in imported_modules)
