from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.executor.broker_ack_classification_v1 import BrokerAckStateV1, OrderAckV1
from src.executor.execution_handoff_v1 import RUNTIME_MODE_PAPER, ExecutionHandoffV1
from src.executor.execution_leg_v1 import ACTIVE, FILLED, PREPARED, ExecutionLegConflictError, ExecutionLegV1
from src.executor.paper_order_adapter_v1 import PaperMarketEvidenceUnavailableError, PaperMarketQuoteV1
from src.executor.paper_order_placement_repository_v1 import PaperOrderPlacementRecordV1
from src.executor.paper_resting_order_reconciliation_v1 import (
    PAPER_RAW_STATUS_FILLED_PRICE_THROUGH,
    PaperRestingHandoffMismatchError,
    PaperRestingLegNotReconcilableError,
    PaperRestingPlacementEvidenceError,
    reconcile_paper_resting_leg_v1,
)

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
MARKET = "BTC-EUR"
PLACED_AT = NOW - timedelta(seconds=30)
BROKER_ORDER_ID = "paper-client-1"


class FixedQuoteProvider:
    def __init__(self, quote: PaperMarketQuoteV1 | None) -> None:
        self.quote = quote
        self.calls = 0

    def latest_quote(self, *, market: str) -> PaperMarketQuoteV1 | None:
        self.calls += 1
        return self.quote


class FakePlacementRepository:
    def __init__(self, record: PaperOrderPlacementRecordV1 | None) -> None:
        self.record = record
        self.calls = 0

    def find_placement_record(
        self, *, market: str, client_order_id: str
    ) -> PaperOrderPlacementRecordV1 | None:
        self.calls += 1
        return self.record


class FakeHandoffRepository:
    def __init__(self, handoff: ExecutionHandoffV1 | None) -> None:
        self.handoff = handoff
        self.calls = 0

    def find(self, handoff_id: int) -> ExecutionHandoffV1 | None:
        self.calls += 1
        if self.handoff is None or self.handoff.handoff_id != handoff_id:
            return None
        return self.handoff


class FakeLegRepository:
    """Minimal double mirroring
    ``ExecutionLegRepositoryV1.mark_active_filled_price_through_v1``'s
    guarded-CAS/idempotent-replay/conflict contract, without a database."""

    def __init__(self, leg: ExecutionLegV1) -> None:
        self.leg = leg
        self.calls = 0

    def find(self, leg_id: int) -> ExecutionLegV1 | None:
        return self.leg if self.leg.execution_leg_id == leg_id else None

    def mark_active_filled_price_through_v1(
        self, leg_id: int, *, expected_broker_order_id: str, broker_raw_status: str,
    ) -> ExecutionLegV1:
        self.calls += 1
        assert leg_id == self.leg.execution_leg_id
        if self.leg.state == FILLED and self.leg.broker_order_id == expected_broker_order_id:
            return self.leg
        if self.leg.state != ACTIVE or self.leg.broker_order_id != expected_broker_order_id:
            raise ExecutionLegConflictError("ACTIVE_FILLED_PRICE_THROUGH_TRANSITION_CONFLICT")
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
        broker_order_id=BROKER_ORDER_ID,
        broker_raw_status="PAPER_ACTIVE_SUBMISSION_TIME_ONLY_NOT_CROSSED",
    )
    return replace(base, **overrides)


def _handoff(**overrides: object) -> ExecutionHandoffV1:
    base = ExecutionHandoffV1(
        handoff_id=41,
        plan_source="automatic_buy_v1",
        plan_reference_id="ref-1",
        plan_content_hash="hash-1",
        trading_account_id=7,
        venue="bitvavo",
        market=MARKET,
        side="BUY",
        executor_mode=RUNTIME_MODE_PAPER,
        executor_identity="shared-executor-v1",
        runtime_owner="devlap",
        executor_credential_binding_id=None,
    )
    return replace(base, **overrides)


def _placement(**overrides: object) -> PaperOrderPlacementRecordV1:
    base = PaperOrderPlacementRecordV1(
        market=MARKET,
        client_order_id="client-1",
        side="BUY",
        price=Decimal("100"),
        quantity=Decimal("0.01"),
        ack=OrderAckV1(
            broker_order_id=BROKER_ORDER_ID,
            state=BrokerAckStateV1.ACTIVE,
            broker_raw_status="PAPER_ACTIVE_SUBMISSION_TIME_ONLY_NOT_CROSSED",
        ),
        created_ts_utc=PLACED_AT,
    )
    return replace(base, **overrides)


def _reconcile(
    leg: ExecutionLegV1,
    quote: PaperMarketQuoteV1 | None,
    *,
    handoff: ExecutionHandoffV1 | None = None,
    placement: PaperOrderPlacementRecordV1 | None = "default",  # type: ignore[assignment]
    max_age: int = 30,
    now: datetime = NOW,
    leg_repository: FakeLegRepository | None = None,
    placement_repository: FakePlacementRepository | None = None,
):
    if placement == "default":
        placement = _placement()
    return reconcile_paper_resting_leg_v1(
        leg,
        handoff_repository=FakeHandoffRepository(handoff or _handoff()),
        quote_provider=FixedQuoteProvider(quote),
        placement_repository=placement_repository or FakePlacementRepository(placement),
        max_quote_age_seconds=max_age,
        now_fn=lambda: now,
        leg_repository=leg_repository or FakeLegRepository(leg),
    )


def test_buy_fills_when_ask_strictly_below_the_resting_limit() -> None:
    leg = _leg(side="BUY", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("98"), best_ask=Decimal("99"), observed_ts_utc=NOW - timedelta(seconds=5))
    leg_repository = FakeLegRepository(leg)

    result = _reconcile(leg, quote, leg_repository=leg_repository)

    assert result.state == FILLED
    assert result.broker_raw_status == PAPER_RAW_STATUS_FILLED_PRICE_THROUGH
    assert result.broker_order_id == BROKER_ORDER_ID
    assert leg_repository.calls == 1


def test_buy_stays_active_on_exact_equality_touch() -> None:
    """Strict price-through only: equality leaves the leg ACTIVE because
    queue priority is unknown."""
    leg = _leg(side="BUY", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("100"), observed_ts_utc=NOW - timedelta(seconds=5))
    leg_repository = FakeLegRepository(leg)

    result = _reconcile(leg, quote, leg_repository=leg_repository)

    assert result.state == ACTIVE
    assert result == leg
    assert leg_repository.calls == 0


def test_buy_stays_active_when_ask_has_not_reached_the_limit() -> None:
    leg = _leg(side="BUY", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("100.01"), observed_ts_utc=NOW - timedelta(seconds=5))
    leg_repository = FakeLegRepository(leg)

    result = _reconcile(leg, quote, leg_repository=leg_repository)

    assert result.state == ACTIVE
    assert leg_repository.calls == 0


def test_sell_fills_when_bid_strictly_above_the_resting_limit() -> None:
    leg = _leg(side="SELL", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("101"), best_ask=Decimal("102"), observed_ts_utc=NOW - timedelta(seconds=5))
    placement = _placement(side="SELL")
    result = _reconcile(leg, quote, handoff=_handoff(side="SELL"), placement=placement)
    assert result.state == FILLED


def test_sell_stays_active_on_exact_equality_touch() -> None:
    leg = _leg(side="SELL", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("100"), best_ask=Decimal("101"), observed_ts_utc=NOW - timedelta(seconds=5))
    placement = _placement(side="SELL")
    result = _reconcile(leg, quote, handoff=_handoff(side="SELL"), placement=placement)
    assert result.state == ACTIVE
    assert result == leg


def test_sell_stays_active_when_bid_has_not_reached_the_limit() -> None:
    leg = _leg(side="SELL", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99.99"), best_ask=Decimal("101"), observed_ts_utc=NOW - timedelta(seconds=5))
    placement = _placement(side="SELL")
    result = _reconcile(leg, quote, handoff=_handoff(side="SELL"), placement=placement)
    assert result.state == ACTIVE


def test_already_filled_leg_replays_idempotently_without_requiring_evidence() -> None:
    leg = _leg(state=FILLED, broker_raw_status=PAPER_RAW_STATUS_FILLED_PRICE_THROUGH)
    provider_quote = FixedQuoteProvider(None)  # would fail closed if ever consulted
    placement_repository = FakePlacementRepository(None)  # would fail closed if ever consulted
    leg_repository = FakeLegRepository(leg)

    result = reconcile_paper_resting_leg_v1(
        leg,
        handoff_repository=FakeHandoffRepository(_handoff()),
        quote_provider=provider_quote,
        placement_repository=placement_repository,
        max_quote_age_seconds=30,
        now_fn=lambda: NOW,
        leg_repository=leg_repository,
    )

    assert result is leg
    assert provider_quote.calls == 0
    assert placement_repository.calls == 0
    assert leg_repository.calls == 0


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
def test_missing_or_bad_market_evidence_fails_closed_and_leaves_leg_active(quote: PaperMarketQuoteV1 | None) -> None:
    leg = _leg(side="BUY", price=Decimal("100"))
    leg_repository = FakeLegRepository(leg)

    with pytest.raises(PaperMarketEvidenceUnavailableError):
        _reconcile(leg, quote, leg_repository=leg_repository)

    assert leg_repository.calls == 0
    assert leg_repository.leg.state == ACTIVE


def test_quote_at_placement_timestamp_leaves_leg_active() -> None:
    """Equal-placement evidence must not change structural state: a quote
    observed at the exact placement instant cannot prove any market movement
    since the order started resting."""
    leg = _leg(side="BUY", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("98"), best_ask=Decimal("99"), observed_ts_utc=PLACED_AT)
    leg_repository = FakeLegRepository(leg)

    with pytest.raises(PaperRestingPlacementEvidenceError, match="PAPER_MARKET_EVIDENCE_NOT_AFTER_PLACEMENT"):
        _reconcile(leg, quote, leg_repository=leg_repository)

    assert leg_repository.calls == 0
    assert leg_repository.leg.state == ACTIVE


def test_quote_before_placement_timestamp_leaves_leg_active() -> None:
    leg = _leg(side="BUY", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("98"), best_ask=Decimal("99"), observed_ts_utc=PLACED_AT - timedelta(seconds=1))
    leg_repository = FakeLegRepository(leg)

    with pytest.raises(PaperRestingPlacementEvidenceError, match="PAPER_MARKET_EVIDENCE_NOT_AFTER_PLACEMENT"):
        _reconcile(leg, quote, max_age=60, leg_repository=leg_repository)

    assert leg_repository.leg.state == ACTIVE


def test_missing_placement_record_fails_closed_and_leaves_leg_active() -> None:
    leg = _leg(side="BUY", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("98"), best_ask=Decimal("99"), observed_ts_utc=NOW - timedelta(seconds=5))
    leg_repository = FakeLegRepository(leg)

    with pytest.raises(PaperRestingPlacementEvidenceError, match="PAPER_PLACEMENT_RECORD_MISSING"):
        _reconcile(leg, quote, placement=None, leg_repository=leg_repository)

    assert leg_repository.calls == 0
    assert leg_repository.leg.state == ACTIVE


@pytest.mark.parametrize(
    "conflicting_placement",
    [
        _placement(price=Decimal("101")),
        _placement(quantity=Decimal("0.02")),
        _placement(side="SELL"),
        _placement(ack=OrderAckV1(broker_order_id="paper-other", state=BrokerAckStateV1.ACTIVE)),
    ],
)
def test_conflicting_placement_identity_fails_closed_and_leaves_leg_active(
    conflicting_placement: PaperOrderPlacementRecordV1,
) -> None:
    leg = _leg(side="BUY", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("98"), best_ask=Decimal("99"), observed_ts_utc=NOW - timedelta(seconds=5))
    leg_repository = FakeLegRepository(leg)

    with pytest.raises(PaperRestingPlacementEvidenceError, match="PAPER_PLACEMENT_IDENTITY_MISMATCH"):
        _reconcile(leg, quote, placement=conflicting_placement, leg_repository=leg_repository)

    assert leg_repository.leg.state == ACTIVE


def test_non_active_placement_state_fails_closed_and_leaves_leg_active() -> None:
    """Identity (including ``broker_order_id``) matches, but the recorded
    placement state is not ``ACTIVE`` -- a defense-in-depth guard distinct
    from the identity check above."""
    leg = _leg(side="BUY", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("98"), best_ask=Decimal("99"), observed_ts_utc=NOW - timedelta(seconds=5))
    placement = _placement(
        ack=OrderAckV1(broker_order_id=BROKER_ORDER_ID, state=BrokerAckStateV1.CANCELED, broker_raw_status="PAPER_CANCELED"),
    )
    leg_repository = FakeLegRepository(leg)

    with pytest.raises(PaperRestingPlacementEvidenceError, match="PAPER_PLACEMENT_NOT_ACTIVE"):
        _reconcile(leg, quote, placement=placement, leg_repository=leg_repository)

    assert leg_repository.leg.state == ACTIVE


def test_non_paper_handoff_is_rejected_without_reading_market_or_placement_evidence() -> None:
    leg = _leg(side="BUY", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("98"), best_ask=Decimal("99"), observed_ts_utc=NOW - timedelta(seconds=5))
    handoff = _handoff(executor_mode="DRY_RUN")
    leg_repository = FakeLegRepository(leg)
    quote_provider = FixedQuoteProvider(quote)
    placement_repository = FakePlacementRepository(_placement())

    with pytest.raises(PaperRestingHandoffMismatchError, match="PAPER_RESTING_RECONCILIATION_REQUIRES_PAPER_HANDOFF"):
        reconcile_paper_resting_leg_v1(
            leg, handoff_repository=FakeHandoffRepository(handoff), quote_provider=quote_provider,
            placement_repository=placement_repository, max_quote_age_seconds=30,
            now_fn=lambda: NOW, leg_repository=leg_repository,
        )

    assert quote_provider.calls == 0
    assert placement_repository.calls == 0
    assert leg_repository.calls == 0
    assert leg_repository.leg.state == ACTIVE


def test_missing_persisted_handoff_is_rejected_before_quote_or_placement() -> None:
    leg = _leg()
    quote_provider = FixedQuoteProvider(
        PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("98"), best_ask=Decimal("99"), observed_ts_utc=NOW - timedelta(seconds=5))
    )
    placement_repository = FakePlacementRepository(_placement())
    leg_repository = FakeLegRepository(leg)
    with pytest.raises(PaperRestingHandoffMismatchError, match="HANDOFF_NOT_FOUND"):
        reconcile_paper_resting_leg_v1(
            leg, handoff_repository=FakeHandoffRepository(None), quote_provider=quote_provider,
            placement_repository=placement_repository, max_quote_age_seconds=30,
            now_fn=lambda: NOW, leg_repository=leg_repository,
        )
    assert quote_provider.calls == 0
    assert placement_repository.calls == 0
    assert leg_repository.calls == 0


@pytest.mark.parametrize(
    "handoff_overrides",
    [
        {"trading_account_id": 8},
        {"venue": "kraken"},
        {"market": "ETH-EUR"},
        {"side": "SELL"},
    ],
)
def test_handoff_identity_mismatch_is_rejected(handoff_overrides: dict) -> None:
    leg = _leg(side="BUY", price=Decimal("100"))
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("98"), best_ask=Decimal("99"), observed_ts_utc=NOW - timedelta(seconds=5))
    handoff = _handoff(**handoff_overrides)
    leg_repository = FakeLegRepository(leg)

    with pytest.raises(PaperRestingHandoffMismatchError, match="PAPER_RESTING_RECONCILIATION_HANDOFF_IDENTITY_MISMATCH"):
        _reconcile(leg, quote, handoff=handoff, leg_repository=leg_repository)

    assert leg_repository.leg.state == ACTIVE


def test_stale_caller_broker_order_identity_fails_before_transition() -> None:
    """Compare-and-swap identity guard: if the leg repository's current row
    no longer carries the exact ``broker_order_id`` the caller's own read
    saw, the transition must conflict rather than blindly writing FILLED
    over a leg whose broker identity changed underneath the caller."""
    leg = _leg(side="BUY", price=Decimal("100"), broker_order_id=BROKER_ORDER_ID)
    stale_repository_leg = replace(leg, broker_order_id="paper-a-different-order")
    leg_repository = FakeLegRepository(stale_repository_leg)
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("98"), best_ask=Decimal("99"), observed_ts_utc=NOW - timedelta(seconds=5))

    with pytest.raises(PaperRestingLegNotReconcilableError, match="EXECUTION_LEG_IDENTITY_MISMATCH"):
        _reconcile(leg, quote, leg_repository=leg_repository)


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
    for forbidden in ("bitvavo", "requests", "httpx", "socket", "credential_adapter", "broker_client"):
        assert not any(forbidden in name.lower() for name in imported_modules)

@pytest.mark.parametrize("invalid_max_age", [True, False, 0, -1, 1.5, "30", None])
def test_invalid_max_quote_age_configuration_fails_closed_before_quote(invalid_max_age: object) -> None:
    leg = _leg()
    provider = FixedQuoteProvider(
        PaperMarketQuoteV1(
            market=MARKET, best_bid=Decimal("98"), best_ask=Decimal("99"),
            observed_ts_utc=NOW - timedelta(seconds=5),
        )
    )
    with pytest.raises(ValueError, match="max_quote_age_seconds must be a positive integer"):
        reconcile_paper_resting_leg_v1(
            leg,
            handoff_repository=FakeHandoffRepository(_handoff()),
            quote_provider=provider,
            placement_repository=FakePlacementRepository(_placement()),
            max_quote_age_seconds=invalid_max_age,  # type: ignore[arg-type]
            now_fn=lambda: NOW,
            leg_repository=FakeLegRepository(leg),
        )
    assert provider.calls == 0
