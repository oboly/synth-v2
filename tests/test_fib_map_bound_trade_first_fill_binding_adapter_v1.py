"""Issue #753 B7: tests for
``src/decision_gate/fib_map_bound_trade_first_fill_binding_adapter_v1.py``.

Uses the same in-memory fake persistence as
``tests/test_fib_map_bound_trade_repository_v1.py`` (keyed identically to the
real unique constraints) so conflict/idempotent-replay behavior is exercised
through the real B6 repository, not re-implemented here. No real DB, no
broker, no execution.
"""
from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pymysql.err import IntegrityError

from src.decision_gate.fib_map_bound_trade_first_fill_binding_adapter_v1 import (
    CanonicalFibMapEvidenceV1,
    FibMapBoundTradeBindingAdapterError,
    bind_fib_map_bound_trade_on_first_fill_v1,
    build_fib_map_bound_trade_v1_from_first_fill,
    derive_fib_map_bound_trade_binding_id_v1,
)
from src.decision_gate.fib_map_bound_trade_repository_v1 import (
    FibMapBoundTradeConflictError,
    FibMapBoundTradeRepositoryV1,
)
from src.decision_gate.fib_map_bound_trade_v1 import FibMapBoundTradeError
from src.decision_gate.strategy_owned_inventory_v1 import StrategyOwnedInventoryEventV1

FILL_TS = datetime(2026, 9, 6, 9, 45, tzinfo=UTC)


def _fill_event(**changes: object) -> StrategyOwnedInventoryEventV1:
    values: dict[str, object] = dict(
        event_id="event-1", trading_account_id=1, venue="bitvavo", market="SOL-EUR",
        strategy_bucket_id="AUTO_SHORTTF_FIB", strategy_id="shorttf_fib",
        strategy_version="1", trade_id="trade-1", source_execution_plan_id="plan-1",
        source_fill_id="fill-1", side="BUY", filled_base_quantity=Decimal("10"),
        fill_notional_eur=Decimal("1000"), occurred_ts_utc=FILL_TS,
    )
    values.update(changes)
    return StrategyOwnedInventoryEventV1(**values)  # type: ignore[arg-type]


def _map_evidence(**changes: object) -> CanonicalFibMapEvidenceV1:
    values: dict[str, object] = dict(
        venue="bitvavo", market="SOL-EUR", native_map_id="native-map-7",
        map_cycle_id="cycle-7", map_structure_hash="abc123",
        map_source_name="native_short_fib_context_snapshot_v1", map_source_version="0.1",
        map_asof_ts_utc=FILL_TS, map_published_at_utc=FILL_TS,
        anchor_start_ts_utc=FILL_TS - timedelta(days=10), anchor_end_ts_utc=FILL_TS,
        anchor_low_price=Decimal("100"), anchor_high_price=Decimal("200"),
        breakout_gate_price=Decimal("210"), invalidation_price=Decimal("95"),
        target_levels=(Decimal("227.2"), Decimal("261.8"), Decimal("300")),
        target_ladder_semantics_version="FIB_MAP_BOUND_V1",
    )
    values.update(changes)
    return CanonicalFibMapEvidenceV1(**values)  # type: ignore[arg-type]


_INSERT_COLUMNS = [
    "binding_id", "trading_account_id", "venue", "market", "strategy_bucket_id",
    "strategy_id", "strategy_version", "trade_id", "source_execution_plan_id",
    "source_buy_fill_id", "native_map_id", "map_cycle_id", "map_structure_hash",
    "map_source_name", "map_source_version", "map_asof_ts_utc", "map_published_at_utc",
    "anchor_start_ts_utc", "anchor_end_ts_utc", "anchor_low_price", "anchor_high_price",
    "breakout_gate_price", "invalidation_price", "target_levels_json",
    "target_ladder_semantics_version", "bound_ts_utc",
]


class MemoryCursor:
    def __init__(self, database: "MemoryDatabase") -> None:
        self.database = database
        self.selected: dict[str, object] | None = None

    def execute(self, sql: str, params) -> None:
        if sql.strip().startswith("INSERT INTO fib_map_bound_trade_v1"):
            row = dict(zip(_INSERT_COLUMNS, params))
            binding_id = str(row["binding_id"])
            lineage = (
                row["trading_account_id"], row["venue"], row["market"],
                row["strategy_bucket_id"], row["strategy_id"],
                row["strategy_version"], row["trade_id"],
            )
            source_fill = (row["trading_account_id"], row["venue"], row["source_buy_fill_id"])
            if (
                binding_id in self.database.by_binding_id
                or lineage in self.database.by_lineage
                or source_fill in self.database.by_source_fill
            ):
                raise IntegrityError(1062, "duplicate key")
            self.database.by_binding_id[binding_id] = row
            self.database.by_lineage[lineage] = row
            self.database.by_source_fill[source_fill] = row
            return
        if "WHERE binding_id = %s" in sql:
            self.selected = self.database.by_binding_id.get(str(params[0]))
            return
        if "WHERE trading_account_id = %s AND venue = %s AND market = %s" in sql:
            self.selected = self.database.by_lineage.get(tuple(params))
            return
        if "WHERE trading_account_id = %s AND venue = %s AND source_buy_fill_id = %s" in sql:
            self.selected = self.database.by_source_fill.get(tuple(params))
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
        self.by_binding_id: dict[str, dict[str, object]] = {}
        self.by_lineage: dict[tuple, dict[str, object]] = {}
        self.by_source_fill: dict[tuple, dict[str, object]] = {}

    def cursor_factory(self, **_kwargs) -> MemoryContext:
        return MemoryContext(self)


def make_repository() -> tuple[FibMapBoundTradeRepositoryV1, MemoryDatabase]:
    database = MemoryDatabase()
    return FibMapBoundTradeRepositoryV1(cursor_factory=database.cursor_factory), database


def test_happy_path_binds_and_persists_full_target_ladder():
    repo, database = make_repository()
    fill = _fill_event()
    evidence = _map_evidence()

    bound = bind_fib_map_bound_trade_on_first_fill_v1(
        fill_event=fill, map_evidence=evidence, repository=repo,
    )

    assert bound.trade_id == "trade-1"
    assert bound.source_execution_plan_id == "plan-1"
    assert bound.source_buy_fill_id == "fill-1"
    assert bound.bound_ts_utc == FILL_TS
    assert bound.target_levels == evidence.target_levels
    assert len(database.by_binding_id) == 1
    assert bound.binding_id == derive_fib_map_bound_trade_binding_id_v1(
        fill_event=fill, map_evidence=evidence,
    )


def test_replay_with_identical_evidence_is_idempotent_no_duplicate_row():
    repo, database = make_repository()
    fill = _fill_event()
    evidence = _map_evidence()

    first = bind_fib_map_bound_trade_on_first_fill_v1(
        fill_event=fill, map_evidence=evidence, repository=repo,
    )
    second = bind_fib_map_bound_trade_on_first_fill_v1(
        fill_event=fill, map_evidence=evidence, repository=repo,
    )

    assert first == second
    assert len(database.by_binding_id) == 1


def test_identity_mismatch_between_fill_and_map_evidence_fails_closed():
    repo, _ = make_repository()
    fill = _fill_event(market="SOL-EUR")
    evidence = _map_evidence(market="BTC-EUR")

    with pytest.raises(FibMapBoundTradeBindingAdapterError, match="FIB_MAP_EVIDENCE_IDENTITY_MISMATCH"):
        bind_fib_map_bound_trade_on_first_fill_v1(fill_event=fill, map_evidence=evidence, repository=repo)


def test_stale_map_evidence_fails_closed():
    fill = _fill_event()
    evidence = _map_evidence(map_asof_ts_utc=FILL_TS - timedelta(hours=13))

    with pytest.raises(FibMapBoundTradeBindingAdapterError, match="FIB_MAP_EVIDENCE_STALE"):
        build_fib_map_bound_trade_v1_from_first_fill(fill_event=fill, map_evidence=evidence)


def test_future_map_evidence_relative_to_fill_fails_closed():
    fill = _fill_event()
    evidence = _map_evidence(map_asof_ts_utc=FILL_TS + timedelta(minutes=1))

    with pytest.raises(FibMapBoundTradeBindingAdapterError, match="FIB_MAP_EVIDENCE_FROM_THE_FUTURE"):
        build_fib_map_bound_trade_v1_from_first_fill(fill_event=fill, map_evidence=evidence)


def test_structurally_invalid_map_evidence_fails_closed_via_b1_validator():
    fill = _fill_event()
    evidence = _map_evidence(anchor_high_price=Decimal("50"))  # high <= low

    with pytest.raises(FibMapBoundTradeError, match="INVALID_FIB_MAP_ANCHOR_GEOMETRY"):
        build_fib_map_bound_trade_v1_from_first_fill(fill_event=fill, map_evidence=evidence)



@pytest.mark.parametrize(
    "changes",
    (
        {"event_id": ""},
        {"filled_base_quantity": Decimal("0")},
        {"filled_base_quantity": Decimal("-1")},
    ),
)
def test_malformed_first_fill_event_fails_closed_before_binding(changes: dict[str, object]):
    fill = _fill_event(**changes)
    evidence = _map_evidence()

    with pytest.raises(FibMapBoundTradeBindingAdapterError, match="INVALID_FIRST_FILL_EVENT"):
        build_fib_map_bound_trade_v1_from_first_fill(fill_event=fill, map_evidence=evidence)

def test_source_fill_that_is_not_a_buy_fails_closed():
    fill = _fill_event(side="SELL")
    evidence = _map_evidence()

    with pytest.raises(FibMapBoundTradeBindingAdapterError, match="SOURCE_FILL_NOT_BUY_SIDE"):
        build_fib_map_bound_trade_v1_from_first_fill(fill_event=fill, map_evidence=evidence)


def test_already_bound_conflict_with_different_map_evidence_fails_closed():
    repo, _ = make_repository()
    fill = _fill_event()
    bind_fib_map_bound_trade_on_first_fill_v1(
        fill_event=fill, map_evidence=_map_evidence(), repository=repo,
    )

    rolled_evidence = _map_evidence(native_map_id="native-map-8", map_cycle_id="cycle-8")
    with pytest.raises(FibMapBoundTradeConflictError, match="FIB_MAP_BOUND_TRADE_LINEAGE_CONFLICT"):
        bind_fib_map_bound_trade_on_first_fill_v1(
            fill_event=fill, map_evidence=rolled_evidence, repository=repo,
        )


def test_target_ladder_freezes_full_ladder_not_a_currently_active_subset():
    fill = _fill_event()
    full_ladder = (Decimal("227.2"), Decimal("261.8"), Decimal("300"))
    evidence = _map_evidence(target_levels=full_ladder)

    bound = build_fib_map_bound_trade_v1_from_first_fill(fill_event=fill, map_evidence=evidence)

    assert bound.target_levels == full_ladder
    assert len(bound.target_levels) == 3


def test_no_broker_or_execution_imports():
    source = Path("src/decision_gate/fib_map_bound_trade_first_fill_binding_adapter_v1.py").read_text()
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)

    forbidden_prefixes = ("src.executor", "src.execution_planner", "src.broker")
    violations = [
        module for module in imported_modules
        if any(module.startswith(prefix) for prefix in forbidden_prefixes)
    ]
    assert violations == []
