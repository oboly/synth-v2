"""Issue #753 Phase B3: handoff application-seam tests.

Proves DRY_RUN/PAPER route through ExecutionHandoffRepositoryV1.intake, LIVE
routes through .intake_live_authorized, unsupported executor_mode fails
closed, and duplicate evaluation of the exact same decision resolves to the
same handoff row (replay-safe, no duplicate executable handoff) via the
shared #206 repository's existing identity path -- this seam adds no
duplicate-detection logic of its own. All persistence is an in-memory fake;
no real DB, no broker.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pymysql.err import IntegrityError

from src.decision_gate.fib_map_bound_exit_decision_v1 import (
    FibMapBoundExitMarketEvidenceV1,
    FibMapBoundExitProgressionV1,
    evaluate_fib_map_bound_exit_decision_v1,
)
from src.decision_gate.fib_map_bound_trade_v1 import FibMapBoundTradeV1
from src.decision_gate.strategy_owned_inventory_v1 import StrategyOwnedInventoryPositionV1
from src.execution_planner.fib_map_bound_exit_execution_handoff_application_v1 import (
    FibMapBoundExitExecutorModeError,
    submit_fib_map_bound_exit_plan_to_execution_handoff_v1,
)
from src.execution_planner.fib_map_bound_exit_planner_v1 import (
    FibMapBoundExitPlanningContextV1,
    build_fib_map_bound_exit_plan_v1,
)
from src.executor.execution_credential_scope_v1 import CredentialScopeBinding
from src.executor.execution_handoff_v1 import ExecutionHandoffRepositoryV1
from src.executor.execution_live_authority_v1 import ExecutionLiveAuthorityDeniedError
from src.market_rules.venue_execution_constraints_v1 import STATUS_FRESH, VenueExecutionConstraints

NOW = datetime(2026, 9, 6, 9, 45, tzinfo=UTC)


def _binding(**changes: object) -> FibMapBoundTradeV1:
    values: dict[str, object] = dict(
        binding_id="bind-1", trading_account_id=1, venue="bitvavo", market="SOL-EUR",
        strategy_bucket_id="AUTO_SHORTTF_FIB", strategy_id="shorttf_fib",
        strategy_version="1", trade_id="trade-1", source_execution_plan_id="plan-1",
        source_buy_fill_id="fill-1", native_map_id="native-map-7", map_cycle_id="cycle-7",
        map_structure_hash="abc123", map_source_name="native_short_fib_context_snapshot_v1",
        map_source_version="0.1", map_asof_ts_utc=NOW, map_published_at_utc=NOW,
        anchor_start_ts_utc=NOW, anchor_end_ts_utc=NOW,
        anchor_low_price=Decimal("100"), anchor_high_price=Decimal("200"),
        breakout_gate_price=Decimal("210"), invalidation_price=Decimal("95"),
        target_levels=(Decimal("220"), Decimal("240"), Decimal("260")),
        target_ladder_semantics_version="FIB_MAP_BOUND_V1",
        bound_ts_utc=NOW,
    )
    values.update(changes)
    return FibMapBoundTradeV1(**values)  # type: ignore[arg-type]


def _owned(binding: FibMapBoundTradeV1, **changes: object) -> StrategyOwnedInventoryPositionV1:
    values: dict[str, object] = dict(
        trading_account_id=binding.trading_account_id, venue=binding.venue,
        market=binding.market, strategy_bucket_id=binding.strategy_bucket_id,
        strategy_id=binding.strategy_id, strategy_version=binding.strategy_version,
        trade_id=binding.trade_id, owned_base_quantity=Decimal("9"),
        bought_base_quantity=Decimal("9"), sold_base_quantity=Decimal("0"),
        cost_notional_eur=None,
    )
    values.update(changes)
    return StrategyOwnedInventoryPositionV1(**values)  # type: ignore[arg-type]


def _constraints(**overrides: object) -> VenueExecutionConstraints:
    values: dict[str, object] = dict(
        venue="bitvavo", market="SOL-EUR", tick_size=Decimal("0.05"), qty_step_size=Decimal("0.1"),
        min_base_quantity=Decimal("0.1"), min_quote_notional=Decimal("5"), supported_order_types=("limit",),
        supported_time_in_force=("GTC",), source_provenance="PUBLIC", metadata_synced_ts_utc=NOW,
        status=STATUS_FRESH,
    )
    values.update(overrides)
    return VenueExecutionConstraints(**values)  # type: ignore[arg-type]


def _context(**overrides: object) -> FibMapBoundExitPlanningContextV1:
    values: dict[str, object] = dict(venue_constraints=_constraints(), planning_ts_utc=NOW)
    values.update(overrides)
    return FibMapBoundExitPlanningContextV1(**values)  # type: ignore[arg-type]


def _plan(price: Decimal = Decimal("220")):
    binding = _binding()
    owned = _owned(binding)
    decision = evaluate_fib_map_bound_exit_decision_v1(
        binding=binding, owned_position=owned,
        progression=FibMapBoundExitProgressionV1(consumed_target_indices=frozenset()),
        market_evidence=FibMapBoundExitMarketEvidenceV1(current_price=price, price_observed_ts_utc=NOW),
        evaluation_ts_utc=NOW,
    )
    return build_fib_map_bound_exit_plan_v1(decision=decision, binding=binding, context=_context())


class FakeCredentialRepository:
    def __init__(self, *, binding_id: int = 3) -> None:
        self.binding_id = binding_id
        self.calls: list[dict[str, object]] = []

    def resolve(self, **kwargs) -> CredentialScopeBinding:
        self.calls.append(kwargs)
        return CredentialScopeBinding(
            executor_credential_binding_id=self.binding_id,
            trading_account_credential_id=11,
            trading_account_id=int(kwargs["trading_account_id"]),
            venue=str(kwargs["venue"]),
            permission_scope="TRADE_EXECUTION",
            executor_identity=str(kwargs["executor_identity"]),
            runtime_owner=str(kwargs["runtime_owner"]),
            credential_status="ACTIVE",
            credential_source="ENCRYPTED_DB",
            allowed_order_write=True,
            allowed_withdrawal=False,
        )


class FakeLiveAuthorityRepository:
    def __init__(self, *, permitted: bool = True) -> None:
        self.permitted = permitted
        self.calls: list[dict[str, object]] = []

    def resolve_effective(self, **kwargs):
        self.calls.append(kwargs)
        if not self.permitted:
            raise ExecutionLiveAuthorityDeniedError("EXECUTION_LIVE_AUTHORITY_NOT_GRANTED")
        return object()


class FakeKillSwitchRepository:
    def __init__(self, *, engaged: bool = False) -> None:
        self.engaged = engaged
        self.calls = 0

    def is_engaged(self) -> bool:
        self.calls += 1
        return self.engaged


class MemoryCursor:
    def __init__(self, database: "MemoryDatabase") -> None:
        self.database = database
        self.lastrowid = 0
        self.selected: dict[str, object] | None = None

    def execute(self, sql: str, params: list[object]) -> None:
        if sql.startswith("INSERT INTO executor_execution_handoff ("):
            key = (str(params[0]), str(params[1]))
            if key in self.database.rows:
                raise IntegrityError(1062, "duplicate plan reference")
            handoff_id = self.database.next_id
            self.database.next_id += 1
            self.lastrowid = handoff_id
            self.database.rows[key] = {
                "executor_execution_handoff_id": handoff_id,
                "plan_source": params[0], "plan_reference_id": params[1], "plan_content_hash": params[2],
                "trading_account_id": params[3], "venue": params[4], "market": params[5], "side": params[6],
                "executor_mode": params[7], "executor_identity": params[8], "runtime_owner": params[9],
                "executor_credential_binding_id": params[10],
            }
            return
        if sql.startswith("INSERT INTO executor_execution_handoff_plan_leg"):
            return
        if sql.startswith("INSERT INTO executor_execution_handoff_consumption"):
            return
        if "WHERE plan_source=%s AND plan_reference_id=%s" in sql:
            self.selected = self.database.rows.get((str(params[0]), str(params[1])))
            return
        raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self.selected


class MemoryContext:
    def __init__(self, database: "MemoryDatabase") -> None:
        self.cursor = MemoryCursor(database)

    def __enter__(self) -> MemoryCursor:
        return self.cursor

    def __exit__(self, *_args) -> None:
        return None


class MemoryDatabase:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, object]] = {}
        self.next_id = 1

    def cursor_factory(self, **_kwargs) -> MemoryContext:
        return MemoryContext(self)


def _repository(
    *, database: MemoryDatabase | None = None, credentials=None, authority=None, kill_switch=None,
) -> ExecutionHandoffRepositoryV1:
    return ExecutionHandoffRepositoryV1(
        cursor_factory=(database or MemoryDatabase()).cursor_factory,
        credential_scope_repository=credentials or FakeCredentialRepository(),
        live_authority_repository=authority or FakeLiveAuthorityRepository(),
        kill_switch_repository=kill_switch or FakeKillSwitchRepository(),
    )


# --- Mode routing --------------------------------------------------------


def test_dry_run_uses_ordinary_intake() -> None:
    database = MemoryDatabase()
    handoff = submit_fib_map_bound_exit_plan_to_execution_handoff_v1(
        plan=_plan(), executor_mode="DRY_RUN", executor_identity="shared-executor-v1",
        runtime_owner="devlap", handoff_repository=_repository(database=database),
    )
    assert handoff.executor_mode == "DRY_RUN"
    assert len(database.rows) == 1


def test_paper_uses_ordinary_intake() -> None:
    database = MemoryDatabase()
    handoff = submit_fib_map_bound_exit_plan_to_execution_handoff_v1(
        plan=_plan(), executor_mode="PAPER", executor_identity="shared-executor-v1",
        runtime_owner="devlap", handoff_repository=_repository(database=database),
    )
    assert handoff.executor_mode == "PAPER"
    assert len(database.rows) == 1


def test_live_uses_intake_live_authorized_not_ordinary_intake() -> None:
    database = MemoryDatabase()
    authority = FakeLiveAuthorityRepository(permitted=True)
    handoff = submit_fib_map_bound_exit_plan_to_execution_handoff_v1(
        plan=_plan(), executor_mode="LIVE", executor_identity="shared-executor-v1",
        runtime_owner="devlap", handoff_repository=_repository(database=database, authority=authority),
    )
    assert handoff.executor_mode == "LIVE"
    assert len(authority.calls) == 1


def test_unsupported_mode_fails_closed() -> None:
    with pytest.raises(FibMapBoundExitExecutorModeError, match="UNSUPPORTED_EXECUTOR_MODE"):
        submit_fib_map_bound_exit_plan_to_execution_handoff_v1(
            plan=_plan(), executor_mode="SANDBOX", executor_identity="shared-executor-v1",
            runtime_owner="devlap", handoff_repository=_repository(),
        )


# --- Replay determinism / idempotency --------------------------------------


def test_duplicate_evaluation_of_the_same_decision_does_not_create_a_duplicate_handoff() -> None:
    database = MemoryDatabase()
    repository = _repository(database=database)
    plan_first_evaluation = _plan()
    plan_second_evaluation = _plan()  # simulates a re-run of the same evaluation cycle

    first = submit_fib_map_bound_exit_plan_to_execution_handoff_v1(
        plan=plan_first_evaluation, executor_mode="PAPER", executor_identity="shared-executor-v1",
        runtime_owner="devlap", handoff_repository=repository,
    )
    second = submit_fib_map_bound_exit_plan_to_execution_handoff_v1(
        plan=plan_second_evaluation, executor_mode="PAPER", executor_identity="shared-executor-v1",
        runtime_owner="devlap", handoff_repository=repository,
    )
    assert first == second
    assert len(database.rows) == 1


def test_credential_and_live_authority_denial_remain_206_owned() -> None:
    authority = FakeLiveAuthorityRepository(permitted=False)
    from src.executor.execution_handoff_v1 import ExecutionHandoffDeniedError

    with pytest.raises(ExecutionHandoffDeniedError):
        submit_fib_map_bound_exit_plan_to_execution_handoff_v1(
            plan=_plan(), executor_mode="LIVE", executor_identity="shared-executor-v1",
            runtime_owner="devlap", handoff_repository=_repository(authority=authority),
        )
