from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.decision_gate.fib_map_bound_trade_v1 import (
    FibMapBoundTradeError,
    FibMapBoundTradeV1,
    assert_fib_map_binding_set_immutable_v1,
    validate_fib_map_bound_trade_v1,
)

NOW = datetime(2026, 9, 6, 9, 45, tzinfo=UTC)


def _binding(**changes):
    values = dict(
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
    return FibMapBoundTradeV1(**values)


def test_valid_binding_accepts_canonical_shorttf_truth():
    validate_fib_map_bound_trade_v1(_binding())


def test_new_map_cannot_rebind_existing_trade_lineage():
    first = _binding()
    second = _binding(
        binding_id="bind-2", source_buy_fill_id="fill-2",
        native_map_id="native-map-8", map_cycle_id="cycle-8",
    )
    with pytest.raises(FibMapBoundTradeError, match="FIB_MAP_BINDING_ALREADY_EXISTS"):
        assert_fib_map_binding_set_immutable_v1((first, second))


def test_missing_targets_fail_closed():
    with pytest.raises(FibMapBoundTradeError, match="FIB_MAP_TARGETS_REQUIRED"):
        validate_fib_map_bound_trade_v1(_binding(target_levels=()))


def test_invalid_anchor_geometry_fails_closed():
    with pytest.raises(FibMapBoundTradeError, match="INVALID_FIB_MAP_ANCHOR_GEOMETRY"):
        validate_fib_map_bound_trade_v1(
            _binding(anchor_low_price=Decimal("200"), anchor_high_price=Decimal("100"))
        )


def test_duplicate_binding_id_fails_closed():
    first = _binding()
    duplicate = _binding(trade_id="trade-2", source_buy_fill_id="fill-2")
    with pytest.raises(FibMapBoundTradeError, match="DUPLICATE_FIB_MAP_BINDING_ID"):
        assert_fib_map_binding_set_immutable_v1((first, duplicate))
