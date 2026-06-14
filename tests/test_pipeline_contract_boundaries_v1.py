"""
Architecture guard tests for Bundle 1 — Pipeline Contracts.

These tests enforce that market-context contracts stay market-only
and carry no forbidden dependencies or order-action semantics.
"""
from __future__ import annotations

import ast
import dataclasses
import json
import typing
from pathlib import Path

ROOT = Path(__file__).parent.parent

FORBIDDEN_IMPORT_FRAGMENTS = [
    "decision_gate",
    "execution_planner",
    "executor",
    "agents",
    "src.execution",      # broker client layer
    "reporting",
    "dashboard",
    "view",
    "apps",
    "account",
    "balance",
    "order_submit",
    "broker",
]

ORDER_ACTION_TERMS = {"BUY", "SELL", "SUBMIT", "EXECUTE", "PLACE", "ORDER"}


def _collect_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
                for alias in node.names:
                    names.append(f"{node.module}.{alias.name}")
            for alias in node.names:
                names.append(alias.name)
    return names


# ---------------------------------------------------------------------------
# Forbidden import guards
# ---------------------------------------------------------------------------

def test_market_context_package_has_no_forbidden_imports():
    for path in sorted((ROOT / "src" / "market_context").rglob("*.py")):
        imports = _collect_imports(path)
        for imp in imports:
            for fragment in FORBIDDEN_IMPORT_FRAGMENTS:
                assert fragment not in imp, (
                    f"{path.relative_to(ROOT)} must not import '{fragment}' — found in '{imp}'"
                )


def test_fib_navigation_map_no_forbidden_imports():
    path = ROOT / "src" / "market_data" / "fib_navigation_map_v1.py"
    imports = _collect_imports(path)
    for imp in imports:
        for fragment in FORBIDDEN_IMPORT_FRAGMENTS:
            assert fragment not in imp, (
                f"fib_navigation_map_v1.py must not import '{fragment}' — found in '{imp}'"
            )


# ---------------------------------------------------------------------------
# Sentinel value presence
# ---------------------------------------------------------------------------

def test_navigation_regime_sentinel_values_present():
    from src.market_context.contracts_v1 import NavigationRegime
    values = {v.value for v in NavigationRegime}
    assert "NO_DATA" in values
    assert "STALE" in values
    assert "LOW_CONFIDENCE" in values


def test_local_ma_atr_state_sentinel_and_canonical_values_present():
    from src.market_context.contracts_v1 import LocalMaAtrState
    values = {v.value for v in LocalMaAtrState}
    assert "NO_DATA" in values
    assert "STALE" in values
    assert "LOW_CONFIDENCE" in values
    assert "ABOVE_BREATHLINE" in values
    assert "TESTING_BREATHLINE" in values
    assert "BELOW_BREATHLINE" in values
    assert "RECLAIMING_BREATHLINE" in values
    assert "EXTENDED_ABOVE_BREATHLINE" in values
    assert "SPIKE_COOLING" in values


def test_impulse_health_state_sentinel_and_canonical_values_present():
    from src.market_context.contracts_v1 import ImpulseHealthState
    values = {v.value for v in ImpulseHealthState}
    assert "NO_DATA" in values
    assert "STALE" in values
    assert "LOW_CONFIDENCE" in values
    assert "HEALTHY_IMPULSE" in values
    assert "BLOW_OFF_SPIKE" in values
    assert "DISTRIBUTION_RISK" in values
    assert "COOLING_PULLBACK" in values
    assert "SECOND_BUMP_POSSIBLE" in values
    assert "FAILED_RECLAIM" in values


def test_timing_state_sentinel_and_canonical_values_present():
    from src.market_context.contracts_v1 import TimingState
    values = {v.value for v in TimingState}
    assert "NO_DATA" in values
    assert "STALE" in values
    assert "LOW_CONFIDENCE" in values
    assert "WAIT_FOR_PULLBACK" in values
    assert "WAIT_FOR_BREAKOUT" in values
    assert "WAIT_FOR_RECLAIM" in values
    assert "RECLAIM_CONFIRMED" in values
    assert "BREAKOUT_CONFIRMED" in values
    assert "PULLBACK_ENTRY_ZONE" in values
    assert "NO_CHASE_EXTENDED" in values
    assert "TOO_LATE" in values
    assert "FAILED_RECLAIM" in values


def test_freshness_state_sentinel_and_canonical_values_present():
    from src.market_context.contracts_v1 import FreshnessState
    values = {v.value for v in FreshnessState}
    assert "NO_DATA" in values
    assert "STALE" in values
    assert "LOW_CONFIDENCE" in values
    assert "FRESH" in values


def test_fib_map_state_matches_existing_fib_navigation_map_constants():
    from src.market_context.contracts_v1 import FibMapState
    from src.market_data.fib_navigation_map_v1 import (
        MAP_STATE_EMERGENCY_REBUILT,
        MAP_STATE_EXHAUSTED,
        MAP_STATE_FALLBACK,
        MAP_STATE_FRESH,
        MAP_STATE_LOW_CONFIDENCE,
        MAP_STATE_NO_DATA,
        MAP_STATE_STALE,
    )

    assert FibMapState.FRESH.value == MAP_STATE_FRESH
    assert FibMapState.STALE.value == MAP_STATE_STALE
    assert FibMapState.EXHAUSTED.value == MAP_STATE_EXHAUSTED
    assert FibMapState.FALLBACK.value == MAP_STATE_FALLBACK
    assert FibMapState.EMERGENCY_REBUILT.value == MAP_STATE_EMERGENCY_REBUILT
    assert FibMapState.NO_DATA.value == MAP_STATE_NO_DATA
    assert FibMapState.LOW_CONFIDENCE.value == MAP_STATE_LOW_CONFIDENCE


def test_fib_map_confidence_values_present():
    from src.market_context.contracts_v1 import FibMapConfidence

    values = {v.value for v in FibMapConfidence}
    assert values == {"HIGH", "MEDIUM", "LOW", "NONE"}


# ---------------------------------------------------------------------------
# JSON safety
# ---------------------------------------------------------------------------

def test_all_enum_values_are_json_safe():
    from src.market_context.contracts_v1 import (
        FibMapConfidence,
        FibMapState,
        FreshnessState,
        ImpulseHealthState,
        LocalMaAtrState,
        NavigationRegime,
        TimingState,
    )
    for enum_cls in (
        FibMapState,
        FibMapConfidence,
        NavigationRegime,
        LocalMaAtrState,
        ImpulseHealthState,
        TimingState,
        FreshnessState,
    ):
        for member in enum_cls:
            json.dumps(member.value)  # must not raise


def test_market_navigation_state_is_json_safe():
    from src.market_context.contracts_v1 import (
        FibMapConfidence,
        FibMapState,
        FreshnessState,
        ImpulseHealthState,
        LocalMaAtrState,
        MarketNavigationState,
        NavigationRegime,
        TimingState,
    )
    state = MarketNavigationState(
        symbol="TEST",
        navigation_regime=NavigationRegime.NO_DATA,
        fib_map_state=FibMapState.NO_DATA,
        fib_map_confidence=FibMapConfidence.NONE,
        local_ma_atr_state=LocalMaAtrState.NO_DATA,
        impulse_health_state=ImpulseHealthState.NO_DATA,
        timing_state=TimingState.NO_DATA,
        freshness_state=FreshnessState.NO_DATA,
        warnings=(),
        computed_at_utc="2026-06-12T00:00:00Z",
    )
    payload = dataclasses.asdict(state)
    json.dumps(payload)  # must not raise


# ---------------------------------------------------------------------------
# Aggregate dataclass structure
# ---------------------------------------------------------------------------

def test_market_navigation_state_is_aggregate_dataclass():
    from src.market_context.contracts_v1 import (
        FibMapConfidence,
        FibMapState,
        MarketNavigationState,
    )

    assert dataclasses.is_dataclass(MarketNavigationState)
    fields_by_name = {f.name: f for f in dataclasses.fields(MarketNavigationState)}
    type_hints = typing.get_type_hints(MarketNavigationState)
    required = {
        "symbol",
        "navigation_regime",
        "fib_map_state",
        "fib_map_confidence",
        "local_ma_atr_state",
        "impulse_health_state",
        "timing_state",
        "freshness_state",
        "warnings",
        "computed_at_utc",
    }
    assert required == set(fields_by_name)
    assert type_hints["fib_map_state"] is FibMapState
    assert type_hints["fib_map_confidence"] is FibMapConfidence


# ---------------------------------------------------------------------------
# No order-action semantics in navigation enums
# ---------------------------------------------------------------------------

def test_market_navigation_enums_contain_no_order_action_semantics():
    from src.market_context.contracts_v1 import (
        FibMapConfidence,
        FibMapState,
        FreshnessState,
        ImpulseHealthState,
        LocalMaAtrState,
        NavigationRegime,
        TimingState,
    )
    for enum_cls in (
        FibMapState,
        FibMapConfidence,
        NavigationRegime,
        LocalMaAtrState,
        ImpulseHealthState,
        TimingState,
        FreshnessState,
    ):
        for member in enum_cls:
            for term in ORDER_ACTION_TERMS:
                assert term not in member.value, (
                    f"{enum_cls.__name__}.{member.name} contains order-action term '{term}'"
                )
