from __future__ import annotations

import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.decision_gate.strategy_owned_inventory_repository_v1 import (
    load_strategy_owned_inventory_events_v1,
)
from src.entry_policy.automatic_buy_paper_fill_execution_v1 import (
    AutomaticBuyPaperFillExecutionError,
    submit_and_reconcile_automatic_buy_paper_plan_v1,
)
from src.execution_planner.automatic_buy_execution_handoff_adapter_v1 import (
    adapt_automatic_buy_plan_to_approved_execution_plan_v1,
)
from src.execution_planner.automatic_buy_planner_v1 import (
    AutomaticBuyGateApprovalProvenanceV1,
    AutomaticBuyPlanLegV1,
    AutomaticBuyPlanV1,
)
from src.executor.execution_handoff_v1 import ExecutionHandoffV1
from src.executor.execution_leg_v1 import (
    ACTIVE,
    FILLED,
    PREPARED,
    RECONCILIATION_REQUIRED,
    REJECTED,
    SUBMISSION_UNCERTAIN,
    ExecutionLegConflictError,
    ExecutionLegV1,
)
from src.executor.broker_ack_classification_v1 import BrokerAckStateV1
from src.executor.paper_order_adapter_v1 import PaperMarketQuoteV1
from src.executor.paper_order_placement_repository_v1 import PaperOrderPlacementConflictError
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import FakeConnection

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
ACCOUNT_ID = 7


def _plan(**overrides: object) -> AutomaticBuyPlanV1:
    values: dict[str, object] = dict(
        trading_account_id=ACCOUNT_ID,
        venue="bitvavo",
        asset_id=42,
        market="BTC-EUR",
        side="BUY",
        final_quantity_base=Decimal("0.01"),
        legs=(
            AutomaticBuyPlanLegV1(1, "BUY", Decimal("100"), Decimal("0.01"), Decimal("1"), True, "GTC"),
        ),
        candidate_action="ENTER",
        candidate_reason_code="ENTRY_ZONE_REACHED",
        candidate_evidence_id="ev-1",
        strategy_id="strategy-a",
        strategy_version="1",
        setup_id="setup-1",
        strategy_bucket_id="SHORT_TERM_ROTATION",
        trade_id="automatic_buy_trade_id_v1:7:test-fixture",
        gate_approval=AutomaticBuyGateApprovalProvenanceV1("APPROVED", "OK", Decimal("10")),
        planner_version="automatic_buy_planner_v1",
        planning_ts_utc=NOW,
    )
    values.update(overrides)
    return AutomaticBuyPlanV1(**values)  # type: ignore[arg-type]


def _handoff(plan: AutomaticBuyPlanV1, *, executor_mode: str = "PAPER") -> ExecutionHandoffV1:
    approved = adapt_automatic_buy_plan_to_approved_execution_plan_v1(plan)
    return ExecutionHandoffV1(
        handoff_id=41,
        plan_source=approved.plan_source,
        plan_reference_id=approved.plan_reference_id,
        plan_content_hash=approved.content_hash,
        trading_account_id=approved.trading_account_id,
        venue=approved.venue,
        market=approved.market,
        side=approved.side,
        executor_mode=executor_mode,
        executor_identity="shared-executor-v1",
        runtime_owner="devlap",
        executor_credential_binding_id=None,
    )


class MemoryHandoffRepository:
    def __init__(self, handoff: ExecutionHandoffV1) -> None:
        self.handoff = handoff

    def find(self, handoff_id: int) -> ExecutionHandoffV1 | None:
        return self.handoff if self.handoff.handoff_id == handoff_id else None


class MemoryLegRepository:
    """Trimmed copy of the CAS test double in test_execution_submission_orchestrator_v1.py."""

    def __init__(self) -> None:
        self.rows: dict[int, ExecutionLegV1] = {}
        self.ids_by_key: dict[tuple[int, int], int] = {}
        self.next_id = 1
        self.lock = threading.Lock()

    def persist_prepared(self, leg: ExecutionLegV1) -> tuple[ExecutionLegV1, bool]:
        with self.lock:
            key = (leg.handoff_id, leg.leg_index)
            existing_id = self.ids_by_key.get(key)
            if existing_id is not None:
                existing = self.rows[existing_id]
                identity_fields = (
                    "handoff_id", "leg_index", "trading_account_id", "venue", "market",
                    "side", "client_order_id", "operator_id", "price", "quantity",
                )
                if any(getattr(existing, f) != getattr(leg, f) for f in identity_fields):
                    raise ExecutionLegConflictError("EXECUTION_LEG_IDENTITY_CONFLICT")
                return existing, False
            leg_id = self.next_id
            self.next_id += 1
            persisted = replace(leg, execution_leg_id=leg_id)
            self.rows[leg_id] = persisted
            self.ids_by_key[key] = leg_id
            return persisted, True

    def claim_submission(self, leg_id: int) -> tuple[ExecutionLegV1, bool]:
        with self.lock:
            leg = self.rows[leg_id]
            if leg.state != PREPARED:
                return leg, False
            claimed = replace(leg, state=SUBMISSION_UNCERTAIN)
            self.rows[leg_id] = claimed
            return claimed, True

    def mark_reconciliation_required(self, leg_id: int) -> ExecutionLegV1:
        with self.lock:
            leg = self.rows[leg_id]
            if leg.state == RECONCILIATION_REQUIRED:
                return leg
            if leg.state != SUBMISSION_UNCERTAIN:
                raise ExecutionLegConflictError("RECONCILIATION_REQUIRED_TRANSITION_CONFLICT")
            resolved = replace(leg, state=RECONCILIATION_REQUIRED)
            self.rows[leg_id] = resolved
            return resolved

    def mark_uncertain(self, leg_id: int) -> ExecutionLegV1:
        with self.lock:
            leg = self.rows[leg_id]
            if leg.state != SUBMISSION_UNCERTAIN:
                raise ExecutionLegConflictError("SUBMISSION_UNCERTAIN_TRANSITION_CONFLICT")
            return leg

    def persist_accepted(self, leg_id: int, state: str, broker_order_id: str, **evidence: object) -> ExecutionLegV1:
        return self._resolve(leg_id, state, broker_order_id, **evidence)

    def persist_closed(self, leg_id: int, state: str, broker_order_id: str | None = None, **evidence: object) -> ExecutionLegV1:
        return self._resolve(leg_id, state, broker_order_id, **evidence)

    def _resolve(self, leg_id: int, state: str, broker_order_id: str | None, **evidence: object) -> ExecutionLegV1:
        with self.lock:
            leg = self.rows[leg_id]
            if leg.state == state:
                return leg
            allowed = {SUBMISSION_UNCERTAIN}
            if evidence.get("from_reconciliation"):
                allowed.add(RECONCILIATION_REQUIRED)
            if leg.state not in allowed:
                raise ExecutionLegConflictError("EXECUTION_LEG_RESOLUTION_CONFLICT")
            resolved = replace(
                leg, state=state, broker_order_id=broker_order_id,
                broker_raw_status=evidence.get("broker_raw_status"),
                restatement_reason=evidence.get("restatement_reason"),
            )
            self.rows[leg_id] = resolved
            return resolved

    def find(self, leg_id: int) -> ExecutionLegV1 | None:
        with self.lock:
            return self.rows.get(leg_id)

    def find_by_handoff_and_index(self, handoff_id: int, leg_index: int) -> ExecutionLegV1 | None:
        with self.lock:
            leg_id = self.ids_by_key.get((handoff_id, leg_index))
            return None if leg_id is None else self.rows[leg_id]

    def resolve_paper_resting_fill_v1(
        self, leg_id: int, *, broker_order_id: str, broker_raw_status: str,
    ) -> ExecutionLegV1:
        with self.lock:
            leg = self.rows[leg_id]
            if leg.state == FILLED and leg.broker_order_id == broker_order_id:
                return leg
            if leg.state != ACTIVE or leg.broker_order_id != broker_order_id:
                raise ExecutionLegConflictError("PAPER_RESTING_FILL_TRANSITION_CONFLICT")
            resolved = replace(leg, state=FILLED, broker_raw_status=broker_raw_status)
            self.rows[leg_id] = resolved
            return resolved


class MemoryPlacementRepository:
    """In-memory double for ``PaperOrderPlacementRepositoryV1``, standing in
    for the durable store that survives a simulated crash between this
    adapter's acknowledgement and executor_execution_leg persistence."""

    def __init__(self, *, created_ts_utc: datetime = NOW - timedelta(hours=1)) -> None:
        self.rows: dict[tuple[str, str], dict[str, object]] = {}
        self._created_ts_utc = created_ts_utc

    def record_placement(self, *, market, client_order_id, side, price, quantity, ack):
        key = (market, client_order_id)
        existing = self.rows.get(key)
        if existing is not None:
            if (existing["side"], existing["price"], existing["quantity"]) != (side, price, quantity):
                raise PaperOrderPlacementConflictError("PAPER_ORDER_CLIENT_ORDER_ID_IDENTITY_CONFLICT")
            return existing["ack"]
        self.rows[key] = {
            "side": side, "price": price, "quantity": quantity, "ack": ack,
            "created_ts_utc": self._created_ts_utc,
        }
        return ack

    def find_placement_created_ts_utc(self, *, market, client_order_id):
        row = self.rows.get((market, client_order_id))
        return None if row is None else row["created_ts_utc"]

    def recover_existing_placement(self, *, market, client_order_id, side, price, quantity):
        row = self.rows.get((market, client_order_id))
        if row is None:
            return None
        if (row["side"], row["price"], row["quantity"]) != (side, price, quantity):
            raise PaperOrderPlacementConflictError("PAPER_ORDER_CLIENT_ORDER_ID_IDENTITY_CONFLICT")
        return row["ack"]

    def find_order_by_client_order_id(self, *, market, client_order_id):
        row = self.rows.get((market, client_order_id))
        return None if row is None else row["ack"]


class CrashOnceAfterAckLegRepository(MemoryLegRepository):
    """Simulates a process crash after the PAPER adapter's ACTIVE
    acknowledgement but before executor_execution_leg persistence: the first
    ``persist_accepted`` call (the write ``persist_order_ack`` makes right
    after ``place_order`` returns) raises instead of writing."""

    def __init__(self) -> None:
        super().__init__()
        self.crash_pending = True

    def persist_accepted(self, leg_id: int, state: str, broker_order_id: str, **evidence: object) -> ExecutionLegV1:
        if self.crash_pending:
            self.crash_pending = False
            raise ConnectionError("SIMULATED_CRASH_BEFORE_LEG_ACK_PERSISTENCE")
        return super().persist_accepted(leg_id, state, broker_order_id, **evidence)


class FixedQuoteProvider:
    def __init__(self, quote: PaperMarketQuoteV1 | None) -> None:
        self.quote = quote

    def latest_quote(self, *, market: str) -> PaperMarketQuoteV1 | None:
        return self.quote


def _marketable_quote(market: str = "BTC-EUR") -> PaperMarketQuoteV1:
    return PaperMarketQuoteV1(market=market, best_bid=Decimal("99"), best_ask=Decimal("99"), observed_ts_utc=NOW - timedelta(seconds=5))


def _run(
    plan: AutomaticBuyPlanV1,
    handoff: ExecutionHandoffV1,
    *,
    leg_repository: MemoryLegRepository | None = None,
    conn: FakeConnection | None = None,
    quote: PaperMarketQuoteV1 | None = "default",  # type: ignore[assignment]
    placement_repository: MemoryPlacementRepository | None = None,
    now: datetime = NOW,
):
    if quote == "default":
        quote = _marketable_quote(plan.market)
    return submit_and_reconcile_automatic_buy_paper_plan_v1(
        plan=plan,
        handoff=handoff,
        operator_id=73,
        handoff_repository=MemoryHandoffRepository(handoff),
        leg_repository=leg_repository or MemoryLegRepository(),
        conn=conn or FakeConnection(),
        quote_provider=FixedQuoteProvider(quote),
        max_quote_age_seconds=30,
        now_fn=lambda: now,
        placement_repository=placement_repository or MemoryPlacementRepository(),
    )


def test_crossed_post_only_buy_quote_is_rejected_and_reconciles_nothing() -> None:
    """#753 B5.5 review fix: automatic-BUY legs are always post-only, so a
    quote that would cross the book must be rejected, never fabricated as a
    fill -- and reconciliation must not run against a leg that never
    reached FILLED."""
    plan = _plan()
    handoff = _handoff(plan)
    conn = FakeConnection()
    result = _run(plan, handoff, conn=conn)  # default quote crosses the leg's limit price

    assert result.submission.leg_states == (REJECTED,)
    assert result.fills == ()
    assert load_strategy_owned_inventory_events_v1(conn, trading_account_id=ACCOUNT_ID) == ()


def test_replaying_an_already_filled_leg_does_not_duplicate_ownership_delta() -> None:
    """This V1 PAPER adapter never itself returns FILLED (see above), but the
    reconciliation bridge must still replay idempotently for any leg that is
    FILLED by whatever means -- this seeds one directly (bypassing the
    adapter's placement decision) to cover that bridge behavior independently
    of order-placement semantics."""
    plan = _plan()
    handoff = _handoff(plan)
    conn = FakeConnection()
    leg_repository = MemoryLegRepository()

    rejected = _run(plan, handoff, leg_repository=leg_repository, conn=conn)
    assert rejected.submission.leg_states == (REJECTED,)
    leg_id = leg_repository.ids_by_key[(handoff.handoff_id, 1)]
    rejected_leg = leg_repository.rows[leg_id]
    leg_repository.rows[leg_id] = replace(
        rejected_leg, state=FILLED, broker_order_id=f"paper-{rejected_leg.client_order_id}",
    )

    first = _run(plan, handoff, leg_repository=leg_repository, conn=conn)
    second = _run(plan, handoff, leg_repository=leg_repository, conn=conn)

    assert first.submission.leg_states == (FILLED,)
    assert first.fills[0].fact.fact_id == second.fills[0].fact.fact_id
    assert second.fills[0].event is None  # replay emits no new delta
    persisted = load_strategy_owned_inventory_events_v1(conn, trading_account_id=ACCOUNT_ID)
    assert len(persisted) == 1


def test_non_marketable_quote_leaves_leg_active_and_reconciles_nothing() -> None:
    plan = _plan()
    handoff = _handoff(plan)
    conn = FakeConnection()
    quote = PaperMarketQuoteV1(market=plan.market, best_bid=Decimal("1000"), best_ask=Decimal("1000"), observed_ts_utc=NOW - timedelta(seconds=5))
    result = _run(plan, handoff, conn=conn, quote=quote)

    assert result.submission.leg_states == (ACTIVE,)
    assert result.fills == ()
    assert load_strategy_owned_inventory_events_v1(conn, trading_account_id=ACCOUNT_ID) == ()


def test_missing_market_evidence_fails_closed_without_reconciliation() -> None:
    plan = _plan()
    handoff = _handoff(plan)
    conn = FakeConnection()
    result = _run(plan, handoff, conn=conn, quote=None)

    assert result.submission.leg_states == (SUBMISSION_UNCERTAIN,)
    assert result.fills == ()
    assert load_strategy_owned_inventory_events_v1(conn, trading_account_id=ACCOUNT_ID) == ()


def test_non_post_only_plan_is_rejected_before_submission() -> None:
    base = _plan()
    non_post_only_leg = replace(base.legs[0], post_only=False)
    plan = replace(base, legs=(non_post_only_leg,))
    handoff = _handoff(base)
    leg_repository = MemoryLegRepository()

    with pytest.raises(AutomaticBuyPaperFillExecutionError, match="PLAN_LEG_NOT_POST_ONLY"):
        _run(plan, handoff, leg_repository=leg_repository)

    assert leg_repository.rows == {}

def test_non_paper_handoff_is_rejected_before_any_submission() -> None:
    plan = _plan()
    handoff = _handoff(plan, executor_mode="DRY_RUN")
    with pytest.raises(AutomaticBuyPaperFillExecutionError, match="HANDOFF_NOT_PAPER_MODE"):
        _run(plan, handoff)


def test_crash_between_active_ack_and_leg_persistence_recovers_without_duplicate_placement() -> None:
    """#753 B5.5 PR #776 review fix: PaperOrderPlacementAdapterV1 acknowledged
    ACTIVE but find_order_by_client_order_id always reported None, so a crash
    between that acknowledgement and executor_execution_leg persistence
    dead-lettered the leg to RECONCILIATION_REQUIRED, losing the modeled
    active order. Simulate that exact crash window (a non-marketable BUY
    quote so place_order acknowledges ACTIVE, then persist_accepted -- the
    write right after the ack -- raises once) and assert a retry through the
    same shared submission orchestrator recovers the identical ACTIVE order
    (same broker_order_id) with no second place_order/duplicate modeled
    placement and no RECONCILIATION_REQUIRED dead end."""
    plan = _plan()
    handoff = _handoff(plan)
    conn = FakeConnection()
    leg_repository = CrashOnceAfterAckLegRepository()
    placement_repository = MemoryPlacementRepository()
    quote = PaperMarketQuoteV1(market=plan.market, best_bid=Decimal("90"), best_ask=Decimal("110"), observed_ts_utc=NOW - timedelta(seconds=5))

    with pytest.raises(ConnectionError, match="SIMULATED_CRASH_BEFORE_LEG_ACK_PERSISTENCE"):
        _run(plan, handoff, leg_repository=leg_repository, conn=conn, quote=quote, placement_repository=placement_repository)

    leg_id = leg_repository.ids_by_key[(handoff.handoff_id, 1)]
    crashed_leg = leg_repository.rows[leg_id]
    assert crashed_leg.state == SUBMISSION_UNCERTAIN
    assert crashed_leg.broker_order_id is None

    # The durable placement repository already recorded the acknowledged
    # ACTIVE order before the crash -- this is exactly what makes recovery
    # possible instead of a silent, unrecoverable dead-lettering.
    recorded = placement_repository.find_order_by_client_order_id(
        market=plan.market, client_order_id=crashed_leg.client_order_id,
    )
    assert recorded is not None
    assert recorded.state == BrokerAckStateV1.ACTIVE

    result = _run(plan, handoff, leg_repository=leg_repository, conn=conn, quote=quote, placement_repository=placement_repository)

    assert result.submission.leg_states == (ACTIVE,)
    recovered_leg = leg_repository.rows[leg_id]
    assert recovered_leg.state == ACTIVE
    assert recovered_leg.broker_order_id == recorded.broker_order_id
    assert result.fills == ()
    assert load_strategy_owned_inventory_events_v1(conn, trading_account_id=ACCOUNT_ID) == ()


def test_sell_side_plan_is_rejected_before_the_plan_adapter_runs() -> None:
    plan = _plan(side="SELL")
    handoff = _handoff(_plan())  # any structurally valid BUY handoff; must never be reached
    with pytest.raises(AutomaticBuyPaperFillExecutionError, match="PLAN_SIDE_NOT_BUY"):
        _run(plan, handoff)


# --- Issue #753 B8: PAPER resting-order ACTIVE -> FILLED reconciliation ---


class SequencedQuoteProvider:
    """Returns each quote in order, one per ``latest_quote`` call, so a test
    can prove a leg's resting-reconciliation quote lookup never happened
    (call count stays at the placement-only count) rather than merely
    happening to fail the price-through check."""

    def __init__(self, quotes: list[PaperMarketQuoteV1 | None]) -> None:
        self._quotes = list(quotes)
        self.calls = 0

    def latest_quote(self, *, market: str) -> PaperMarketQuoteV1 | None:
        self.calls += 1
        return self._quotes.pop(0)


def test_newly_placed_active_leg_does_not_fill_in_the_same_invocation() -> None:
    """A leg first placed ACTIVE by this call's own submission must not be
    eligible for resting reconciliation in the same call. Proven with a
    quote provider that would return a fill-through quote on a *second*
    call: if the guard were absent, this newly-placed leg would wrongly
    fill in the same invocation via that second call."""
    plan = _plan()
    handoff = _handoff(plan)
    conn = FakeConnection()
    leg_repository = MemoryLegRepository()
    placement_repository = MemoryPlacementRepository(created_ts_utc=NOW - timedelta(hours=1))
    non_crossing_at_placement = PaperMarketQuoteV1(
        market=plan.market, best_bid=Decimal("50"), best_ask=Decimal("1000"),
        observed_ts_utc=NOW - timedelta(seconds=5),
    )
    would_fill_through_if_reevaluated = PaperMarketQuoteV1(
        market=plan.market, best_bid=Decimal("50"), best_ask=Decimal("99"),
        observed_ts_utc=NOW - timedelta(seconds=5),
    )
    quote_provider = SequencedQuoteProvider(
        [non_crossing_at_placement, would_fill_through_if_reevaluated]
    )

    result = submit_and_reconcile_automatic_buy_paper_plan_v1(
        plan=plan, handoff=handoff, operator_id=73,
        handoff_repository=MemoryHandoffRepository(handoff),
        leg_repository=leg_repository, conn=conn,
        quote_provider=quote_provider, max_quote_age_seconds=30,
        now_fn=lambda: NOW, placement_repository=placement_repository,
    )

    assert result.submission.leg_states == (ACTIVE,)
    assert result.fills == ()
    assert quote_provider.calls == 1  # resting reconciliation never ran
    leg = leg_repository.find_by_handoff_and_index(handoff.handoff_id, 1)
    assert leg.state == ACTIVE
    assert load_strategy_owned_inventory_events_v1(conn, trading_account_id=ACCOUNT_ID) == ()


def test_resting_active_leg_at_exact_touch_remains_active_on_a_later_invocation() -> None:
    """Fill-on-through only, never fill-on-touch: a resting BUY leg with
    best_ask exactly equal to its limit price must remain ACTIVE, because V1
    has no queue-priority model."""
    plan = _plan()
    handoff = _handoff(plan)
    conn = FakeConnection()
    leg_repository = MemoryLegRepository()
    placement_repository = MemoryPlacementRepository(created_ts_utc=NOW - timedelta(hours=1))
    non_marketable_quote = PaperMarketQuoteV1(
        market=plan.market, best_bid=Decimal("50"), best_ask=Decimal("1000"),
        observed_ts_utc=NOW - timedelta(seconds=5),
    )
    first = _run(
        plan, handoff, leg_repository=leg_repository, conn=conn,
        quote=non_marketable_quote, placement_repository=placement_repository,
    )
    assert first.submission.leg_states == (ACTIVE,)

    touch_ts = NOW + timedelta(minutes=1)
    touch_quote = PaperMarketQuoteV1(
        market=plan.market, best_bid=Decimal("50"), best_ask=Decimal("100"),
        observed_ts_utc=touch_ts - timedelta(seconds=5),
    )
    second = _run(
        plan, handoff, leg_repository=leg_repository, conn=conn,
        quote=touch_quote, placement_repository=placement_repository, now=touch_ts,
    )

    assert second.submission.leg_states == (ACTIVE,)
    assert second.fills == ()
    leg = leg_repository.find_by_handoff_and_index(handoff.handoff_id, 1)
    assert leg.state == ACTIVE
    assert load_strategy_owned_inventory_events_v1(conn, trading_account_id=ACCOUNT_ID) == ()


def test_resting_active_leg_fills_on_later_price_through_exactly_once_and_replay_is_idempotent() -> None:
    plan = _plan()
    handoff = _handoff(plan)
    conn = FakeConnection()
    leg_repository = MemoryLegRepository()
    placement_repository = MemoryPlacementRepository(created_ts_utc=NOW - timedelta(hours=1))
    non_marketable_quote = PaperMarketQuoteV1(
        market=plan.market, best_bid=Decimal("50"), best_ask=Decimal("1000"),
        observed_ts_utc=NOW - timedelta(seconds=5),
    )
    first = _run(
        plan, handoff, leg_repository=leg_repository, conn=conn,
        quote=non_marketable_quote, placement_repository=placement_repository,
    )
    assert first.submission.leg_states == (ACTIVE,)

    through_ts = NOW + timedelta(minutes=2)
    through_quote = PaperMarketQuoteV1(
        market=plan.market, best_bid=Decimal("50"), best_ask=Decimal("99"),
        observed_ts_utc=through_ts - timedelta(seconds=5),
    )
    second = _run(
        plan, handoff, leg_repository=leg_repository, conn=conn,
        quote=through_quote, placement_repository=placement_repository, now=through_ts,
    )

    # submission.leg_states reflects only submit_execution_plan's own
    # snapshot (the leg was already ACTIVE and short-circuits there); the
    # resting-order reconciliation this test targets runs after and is
    # observed through the persisted leg and the emitted fill/event below.
    assert second.submission.leg_states == (ACTIVE,)
    assert len(second.fills) == 1
    assert second.fills[0].event is not None
    leg = leg_repository.find_by_handoff_and_index(handoff.handoff_id, 1)
    assert leg.state == FILLED
    persisted = load_strategy_owned_inventory_events_v1(conn, trading_account_id=ACCOUNT_ID)
    assert len(persisted) == 1

    replay_ts = through_ts + timedelta(minutes=1)
    third = _run(
        plan, handoff, leg_repository=leg_repository, conn=conn,
        quote=through_quote, placement_repository=placement_repository, now=replay_ts,
    )

    assert third.submission.leg_states == (FILLED,)
    assert third.fills[0].fact.fact_id == second.fills[0].fact.fact_id
    assert third.fills[0].event is None  # replay emits no new ownership delta
    persisted_after_replay = load_strategy_owned_inventory_events_v1(conn, trading_account_id=ACCOUNT_ID)
    assert len(persisted_after_replay) == 1


def test_resting_active_leg_quote_not_later_than_placement_fails_closed_without_state_change() -> None:
    plan = _plan()
    handoff = _handoff(plan)
    conn = FakeConnection()
    leg_repository = MemoryLegRepository()
    placement_created_ts_utc = NOW - timedelta(hours=1)
    placement_repository = MemoryPlacementRepository(created_ts_utc=placement_created_ts_utc)
    non_marketable_quote = PaperMarketQuoteV1(
        market=plan.market, best_bid=Decimal("50"), best_ask=Decimal("1000"),
        observed_ts_utc=NOW - timedelta(seconds=5),
    )
    first = _run(
        plan, handoff, leg_repository=leg_repository, conn=conn,
        quote=non_marketable_quote, placement_repository=placement_repository,
    )
    assert first.submission.leg_states == (ACTIVE,)

    later_now = NOW + timedelta(minutes=5)
    stale_relative_to_placement_quote = PaperMarketQuoteV1(
        market=plan.market, best_bid=Decimal("50"), best_ask=Decimal("99"),
        observed_ts_utc=placement_created_ts_utc,  # not strictly later than placement
    )
    second = _run(
        plan, handoff, leg_repository=leg_repository, conn=conn,
        quote=stale_relative_to_placement_quote, placement_repository=placement_repository,
        now=later_now,
    )

    assert second.submission.leg_states == (ACTIVE,)
    assert second.fills == ()
    leg = leg_repository.find_by_handoff_and_index(handoff.handoff_id, 1)
    assert leg.state == ACTIVE
    assert load_strategy_owned_inventory_events_v1(conn, trading_account_id=ACCOUNT_ID) == ()


def test_resting_active_leg_missing_placement_evidence_fails_closed_without_state_change() -> None:
    """No recorded placement created_ts_utc for this identity (e.g. a
    mismatched/foreign handoff seam) must fail closed, not fabricate a
    resting-since time."""
    plan = _plan()
    handoff = _handoff(plan)
    conn = FakeConnection()
    leg_repository = MemoryLegRepository()
    non_marketable_quote = PaperMarketQuoteV1(
        market=plan.market, best_bid=Decimal("50"), best_ask=Decimal("1000"),
        observed_ts_utc=NOW - timedelta(seconds=5),
    )
    placement_repository = MemoryPlacementRepository()
    first = _run(
        plan, handoff, leg_repository=leg_repository, conn=conn,
        quote=non_marketable_quote, placement_repository=placement_repository,
    )
    assert first.submission.leg_states == (ACTIVE,)

    # A fresh placement repository has no record of this identity's
    # created_ts_utc for the second call, simulating missing evidence.
    empty_placement_repository = MemoryPlacementRepository()
    later_now = NOW + timedelta(minutes=5)
    through_quote = PaperMarketQuoteV1(
        market=plan.market, best_bid=Decimal("50"), best_ask=Decimal("99"),
        observed_ts_utc=later_now - timedelta(seconds=5),
    )
    second = _run(
        plan, handoff, leg_repository=leg_repository, conn=conn,
        quote=through_quote, placement_repository=empty_placement_repository, now=later_now,
    )

    assert second.submission.leg_states == (ACTIVE,)
    assert second.fills == ()
    assert load_strategy_owned_inventory_events_v1(conn, trading_account_id=ACCOUNT_ID) == ()


def test_resting_active_leg_stale_quote_fails_closed_without_state_change() -> None:
    plan = _plan()
    handoff = _handoff(plan)
    conn = FakeConnection()
    leg_repository = MemoryLegRepository()
    placement_repository = MemoryPlacementRepository(created_ts_utc=NOW - timedelta(hours=1))
    non_marketable_quote = PaperMarketQuoteV1(
        market=plan.market, best_bid=Decimal("50"), best_ask=Decimal("1000"),
        observed_ts_utc=NOW - timedelta(seconds=5),
    )
    first = _run(
        plan, handoff, leg_repository=leg_repository, conn=conn,
        quote=non_marketable_quote, placement_repository=placement_repository,
    )
    assert first.submission.leg_states == (ACTIVE,)

    later_now = NOW + timedelta(minutes=5)
    stale_quote = PaperMarketQuoteV1(
        market=plan.market, best_bid=Decimal("50"), best_ask=Decimal("99"),
        observed_ts_utc=later_now - timedelta(seconds=31),
    )
    second = _run(
        plan, handoff, leg_repository=leg_repository, conn=conn,
        quote=stale_quote, placement_repository=placement_repository, now=later_now,
    )

    assert second.submission.leg_states == (ACTIVE,)
    assert second.fills == ()
    leg = leg_repository.find_by_handoff_and_index(handoff.handoff_id, 1)
    assert leg.state == ACTIVE


def test_resting_active_leg_future_quote_fails_closed_without_state_change() -> None:
    plan = _plan()
    handoff = _handoff(plan)
    conn = FakeConnection()
    leg_repository = MemoryLegRepository()
    placement_repository = MemoryPlacementRepository(created_ts_utc=NOW - timedelta(hours=1))
    non_marketable_quote = PaperMarketQuoteV1(
        market=plan.market, best_bid=Decimal("50"), best_ask=Decimal("1000"),
        observed_ts_utc=NOW - timedelta(seconds=5),
    )
    first = _run(
        plan, handoff, leg_repository=leg_repository, conn=conn,
        quote=non_marketable_quote, placement_repository=placement_repository,
    )
    assert first.submission.leg_states == (ACTIVE,)

    later_now = NOW + timedelta(minutes=5)
    future_quote = PaperMarketQuoteV1(
        market=plan.market, best_bid=Decimal("50"), best_ask=Decimal("99"),
        observed_ts_utc=later_now + timedelta(seconds=5),
    )
    second = _run(
        plan, handoff, leg_repository=leg_repository, conn=conn,
        quote=future_quote, placement_repository=placement_repository, now=later_now,
    )

    assert second.submission.leg_states == (ACTIVE,)
    assert second.fills == ()
    leg = leg_repository.find_by_handoff_and_index(handoff.handoff_id, 1)
    assert leg.state == ACTIVE


def test_resting_active_leg_mismatched_market_quote_fails_closed_without_state_change() -> None:
    plan = _plan()
    handoff = _handoff(plan)
    conn = FakeConnection()
    leg_repository = MemoryLegRepository()
    placement_repository = MemoryPlacementRepository(created_ts_utc=NOW - timedelta(hours=1))
    non_marketable_quote = PaperMarketQuoteV1(
        market=plan.market, best_bid=Decimal("50"), best_ask=Decimal("1000"),
        observed_ts_utc=NOW - timedelta(seconds=5),
    )
    first = _run(
        plan, handoff, leg_repository=leg_repository, conn=conn,
        quote=non_marketable_quote, placement_repository=placement_repository,
    )
    assert first.submission.leg_states == (ACTIVE,)

    later_now = NOW + timedelta(minutes=5)
    mismatched_market_quote = PaperMarketQuoteV1(
        market="ETH-EUR", best_bid=Decimal("50"), best_ask=Decimal("99"),
        observed_ts_utc=later_now - timedelta(seconds=5),
    )
    second = _run(
        plan, handoff, leg_repository=leg_repository, conn=conn,
        quote=mismatched_market_quote, placement_repository=placement_repository, now=later_now,
    )

    assert second.submission.leg_states == (ACTIVE,)
    assert second.fills == ()
    leg = leg_repository.find_by_handoff_and_index(handoff.handoff_id, 1)
    assert leg.state == ACTIVE
