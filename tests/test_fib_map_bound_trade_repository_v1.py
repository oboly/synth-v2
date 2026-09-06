"""Issue #753 B6: persistence-boundary tests for
``src/decision_gate/fib_map_bound_trade_repository_v1.py``.

All persistence is an in-memory fake keyed the same way as the real unique
constraints (``binding_id``, lineage, source fill) so IntegrityError-driven
conflict resolution is exercised the same way it would run against MariaDB.
No real DB, no broker, no execution.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pymysql.err import IntegrityError

from src.decision_gate.fib_map_bound_trade_repository_v1 import (
    FibMapBoundTradeConflictError,
    FibMapBoundTradeRepositoryError,
    FibMapBoundTradeRepositoryV1,
)
from src.decision_gate.fib_map_bound_trade_v1 import FibMapBoundTradeV1

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
        target_levels=(Decimal("227.2"), Decimal("261.8"), Decimal("300")),
        target_ladder_semantics_version="FIB_MAP_BOUND_V1",
        bound_ts_utc=NOW,
    )
    values.update(changes)
    return FibMapBoundTradeV1(**values)  # type: ignore[arg-type]


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

    def corrupt(self, binding_id: str, *, column: str, value: object) -> None:
        row = self.by_binding_id[binding_id]
        row[column] = value


def make_repository(database: MemoryDatabase | None = None) -> tuple[FibMapBoundTradeRepositoryV1, MemoryDatabase]:
    database = database or MemoryDatabase()
    return FibMapBoundTradeRepositoryV1(cursor_factory=database.cursor_factory), database


def test_insert_persists_and_round_trips_exact_binding():
    repo, database = make_repository()
    binding = _binding()
    result = repo.record_fib_map_bound_trade_v1(binding=binding)
    assert result == binding
    assert len(database.by_binding_id) == 1

    loaded = repo.load_by_binding_id(binding_id="bind-1")
    assert loaded == binding


def test_load_by_lineage_matches_exact_lineage_only():
    repo, _ = make_repository()
    binding = _binding()
    repo.record_fib_map_bound_trade_v1(binding=binding)

    found = repo.load_by_lineage(
        trading_account_id=1, venue="bitvavo", market="SOL-EUR",
        strategy_bucket_id="AUTO_SHORTTF_FIB", strategy_id="shorttf_fib",
        strategy_version="1", trade_id="trade-1",
    )
    assert found == binding

    missing = repo.load_by_lineage(
        trading_account_id=1, venue="bitvavo", market="SOL-EUR",
        strategy_bucket_id="AUTO_SHORTTF_FIB", strategy_id="shorttf_fib",
        strategy_version="1", trade_id="trade-2",
    )
    assert missing is None


def test_load_by_source_fill_matches_exact_fill_only():
    repo, _ = make_repository()
    binding = _binding()
    repo.record_fib_map_bound_trade_v1(binding=binding)

    found = repo.load_by_source_fill(trading_account_id=1, venue="bitvavo", source_buy_fill_id="fill-1")
    assert found == binding

    missing = repo.load_by_source_fill(trading_account_id=1, venue="bitvavo", source_buy_fill_id="fill-2")
    assert missing is None


def test_identical_replay_is_idempotent_no_duplicate_row():
    repo, database = make_repository()
    binding = _binding()
    first = repo.record_fib_map_bound_trade_v1(binding=binding)
    second = repo.record_fib_map_bound_trade_v1(binding=_binding())
    assert first == second == binding
    assert len(database.by_binding_id) == 1


def test_conflicting_lineage_with_different_content_fails_closed():
    repo, _ = make_repository()
    repo.record_fib_map_bound_trade_v1(binding=_binding())
    conflicting = _binding(
        binding_id="bind-2", source_buy_fill_id="fill-2",
        native_map_id="native-map-8", map_cycle_id="cycle-8",
    )
    with pytest.raises(FibMapBoundTradeConflictError, match="FIB_MAP_BOUND_TRADE_LINEAGE_CONFLICT"):
        repo.record_fib_map_bound_trade_v1(binding=conflicting)


def test_conflicting_source_fill_with_different_content_fails_closed():
    repo, _ = make_repository()
    repo.record_fib_map_bound_trade_v1(binding=_binding())
    conflicting = _binding(
        binding_id="bind-2", trade_id="trade-2",
        native_map_id="native-map-8", map_cycle_id="cycle-8",
    )
    with pytest.raises(FibMapBoundTradeConflictError, match="FIB_MAP_BOUND_TRADE_SOURCE_FILL_CONFLICT"):
        repo.record_fib_map_bound_trade_v1(binding=conflicting)


def test_conflicting_binding_id_with_different_content_fails_closed():
    repo, _ = make_repository()
    repo.record_fib_map_bound_trade_v1(binding=_binding())
    conflicting = _binding(
        trade_id="trade-2", source_buy_fill_id="fill-2",
        native_map_id="native-map-8", map_cycle_id="cycle-8",
    )
    with pytest.raises(FibMapBoundTradeConflictError, match="FIB_MAP_BOUND_TRADE_BINDING_ID_CONFLICT"):
        repo.record_fib_map_bound_trade_v1(binding=conflicting)


def test_malformed_persisted_json_fails_closed_on_load():
    repo, database = make_repository()
    repo.record_fib_map_bound_trade_v1(binding=_binding())
    database.corrupt("bind-1", column="target_levels_json", value="{not valid json")
    with pytest.raises(FibMapBoundTradeRepositoryError, match="INVALID_PERSISTED_FIB_MAP_BOUND_TRADE"):
        repo.load_by_binding_id(binding_id="bind-1")


def test_malformed_persisted_row_missing_field_fails_closed_on_load():
    repo, database = make_repository()
    repo.record_fib_map_bound_trade_v1(binding=_binding())
    del database.by_binding_id["bind-1"]["market"]
    with pytest.raises(FibMapBoundTradeRepositoryError, match="INVALID_PERSISTED_FIB_MAP_BOUND_TRADE"):
        repo.load_by_binding_id(binding_id="bind-1")


def test_null_persisted_identity_fails_closed_on_load():
    repo, database = make_repository()
    repo.record_fib_map_bound_trade_v1(binding=_binding())
    database.corrupt("bind-1", column="native_map_id", value=None)
    with pytest.raises(FibMapBoundTradeRepositoryError, match="INVALID_PERSISTED_FIB_MAP_BOUND_TRADE"):
        repo.load_by_binding_id(binding_id="bind-1")


def test_empty_target_levels_json_list_fails_closed_on_load():
    repo, database = make_repository()
    repo.record_fib_map_bound_trade_v1(binding=_binding())
    database.corrupt("bind-1", column="target_levels_json", value=json.dumps([]))
    with pytest.raises(FibMapBoundTradeRepositoryError, match="INVALID_PERSISTED_FIB_MAP_BOUND_TRADE"):
        repo.load_by_binding_id(binding_id="bind-1")


def test_numeric_target_levels_json_fails_closed_on_load():
    repo, database = make_repository()
    repo.record_fib_map_bound_trade_v1(binding=_binding())
    database.corrupt("bind-1", column="target_levels_json", value=json.dumps([227.2]))
    with pytest.raises(FibMapBoundTradeRepositoryError, match="INVALID_PERSISTED_FIB_MAP_BOUND_TRADE"):
        repo.load_by_binding_id(binding_id="bind-1")


def test_target_levels_decimal_fidelity_round_trips_through_json():
    repo, _ = make_repository()
    binding = _binding(target_levels=(Decimal("227.200000000000000001"), Decimal("261.8"), Decimal("300")))
    repo.record_fib_map_bound_trade_v1(binding=binding)
    loaded = repo.load_by_binding_id(binding_id="bind-1")
    assert loaded is not None
    assert loaded.target_levels == binding.target_levels
    assert all(isinstance(level, Decimal) for level in loaded.target_levels)


def test_decimal_36_18_boundary_prices_persist_exactly():
    repo, database = make_repository()
    binding = _binding(
        anchor_low_price=Decimal("1.000000000000000001"),
        anchor_high_price=Decimal("999999999999999998"),
        breakout_gate_price=Decimal("999999999999999999.999999999999999999"),
        invalidation_price=Decimal("0.000000000000000001"),
        target_levels=(Decimal("1000000000000000000"),),
    )
    repo.record_fib_map_bound_trade_v1(binding=binding)
    persisted = database.by_binding_id["bind-1"]
    assert persisted["breakout_gate_price"] == binding.breakout_gate_price
    assert persisted["invalidation_price"] == binding.invalidation_price


def test_price_with_excess_scale_fails_before_insert():
    repo, database = make_repository()
    binding = _binding(invalidation_price=Decimal("0.0000000000000000001"))
    with pytest.raises(FibMapBoundTradeRepositoryError, match="FIB_MAP_BOUND_TRADE_PRICE_OUT_OF_RANGE"):
        repo.record_fib_map_bound_trade_v1(binding=binding)
    assert database.by_binding_id == {}


def test_price_with_excess_integer_digits_fails_before_insert():
    repo, database = make_repository()
    binding = _binding(
        breakout_gate_price=Decimal("1000000000000000000"),
        target_levels=(Decimal("1000000000000000001"),),
    )
    with pytest.raises(FibMapBoundTradeRepositoryError, match="FIB_MAP_BOUND_TRADE_PRICE_OUT_OF_RANGE"):
        repo.record_fib_map_bound_trade_v1(binding=binding)
    assert database.by_binding_id == {}


def test_non_utc_offset_timestamps_normalize_before_insert_and_replay_idempotently():
    repo, database = make_repository()
    plus_two = timezone(timedelta(hours=2))
    local_time = datetime(2026, 9, 6, 11, 45, tzinfo=plus_two)
    binding = _binding(
        map_asof_ts_utc=local_time, map_published_at_utc=local_time,
        anchor_start_ts_utc=local_time, anchor_end_ts_utc=local_time, bound_ts_utc=local_time,
    )

    first = repo.record_fib_map_bound_trade_v1(binding=binding)
    persisted = database.by_binding_id["bind-1"]
    for column in (
        "map_asof_ts_utc", "map_published_at_utc", "anchor_start_ts_utc",
        "anchor_end_ts_utc", "bound_ts_utc",
    ):
        assert persisted[column] == NOW.replace(tzinfo=None)
        assert persisted[column].tzinfo is None

    replay = repo.record_fib_map_bound_trade_v1(binding=binding)
    assert replay == _binding()
    loaded = repo.load_by_binding_id(binding_id="bind-1")
    assert loaded == _binding()
    assert first == binding


def test_naive_persisted_timestamps_are_restored_as_utc_aware():
    repo, database = make_repository()
    binding = _binding()
    repo.record_fib_map_bound_trade_v1(binding=binding)
    naive_now = NOW.replace(tzinfo=None)
    for column in (
        "map_asof_ts_utc", "map_published_at_utc", "anchor_start_ts_utc",
        "anchor_end_ts_utc", "bound_ts_utc",
    ):
        database.corrupt("bind-1", column=column, value=naive_now)

    loaded = repo.load_by_binding_id(binding_id="bind-1")
    assert loaded is not None
    assert loaded.bound_ts_utc == NOW
    assert loaded.bound_ts_utc.tzinfo is not None
    assert loaded.map_asof_ts_utc == NOW


def test_invalid_lookup_arguments_fail_closed():
    repo, _ = make_repository()
    with pytest.raises(FibMapBoundTradeRepositoryError, match="INVALID_FIB_MAP_BOUND_TRADE_LOOKUP"):
        repo.load_by_binding_id(binding_id="")
    with pytest.raises(FibMapBoundTradeRepositoryError, match="INVALID_FIB_MAP_BOUND_TRADE_LOOKUP"):
        repo.load_by_source_fill(trading_account_id=0, venue="bitvavo", source_buy_fill_id="fill-1")
