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
from src.executor.paper_order_adapter_v1 import PaperMarketQuoteV1
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


class FixedQuoteProvider:
    def __init__(self, quote: PaperMarketQuoteV1 | None) -> None:
        self.quote = quote

    def latest_quote(self, *, market: str) -> PaperMarketQuoteV1 | None:
        return self.quote


def _marketable_quote(market: str = "BTC-EUR") -> PaperMarketQuoteV1:
    return PaperMarketQuoteV1(market=market, price=Decimal("99"), observed_ts_utc=NOW - timedelta(seconds=5))


def _run(
    plan: AutomaticBuyPlanV1,
    handoff: ExecutionHandoffV1,
    *,
    leg_repository: MemoryLegRepository | None = None,
    conn: FakeConnection | None = None,
    quote: PaperMarketQuoteV1 | None = "default",  # type: ignore[assignment]
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
        now_fn=lambda: NOW,
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
    quote = PaperMarketQuoteV1(market=plan.market, price=Decimal("1000"), observed_ts_utc=NOW - timedelta(seconds=5))
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


def test_sell_side_plan_is_rejected_before_the_plan_adapter_runs() -> None:
    plan = _plan(side="SELL")
    handoff = _handoff(_plan())  # any structurally valid BUY handoff; must never be reached
    with pytest.raises(AutomaticBuyPaperFillExecutionError, match="PLAN_SIDE_NOT_BUY"):
        _run(plan, handoff)
