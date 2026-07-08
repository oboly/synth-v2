from __future__ import annotations

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey
from src.market_data.native_short_map_level_status_v1 import (
    NativeShortMapLevelEvaluationReference,
    NativeShortMapLevelLifecycleState,
    NativeShortMapLevelRole,
    NativeShortMapLevelSide,
    NativeShortMapLevelStatusRecord,
    NativeShortMapLevelStatusValidationError,
    NativeShortMapLevelTickRuleSource,
    NativeShortMapLevelTickRuleStatus,
)
from src.market_data.native_short_scope_status_v1 import (
    NativeShortScopeActionabilityState,
    NativeShortScopeMapLifecycleState,
    NativeShortScopeStatusCode,
)

MIGRATION_PATH = Path("db/migrations/20260708_native_short_map_level_status_persistence_v1.sql")


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _scope_key() -> NativeShortMapScopeKey:
    return NativeShortMapScopeKey(
        venue="bitvavo",
        symbol="NEAR",
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
    )


def _record(**overrides: object) -> NativeShortMapLevelStatusRecord:
    values: dict[str, object] = {
        "key": _scope_key(),
        "current_map_id": 123,
        "map_cycle_id": "NEAR|SHORT|4h|2026-07-01T00:00:00+00:00|2026-07-02T00:00:00+00:00",
        "canonical_map_level_role": NativeShortMapLevelRole.SELL_EXT_1_272,
        "side": NativeShortMapLevelSide.SELL,
        "canonical_unrounded_price": Decimal("3.141592653589"),
        "canonical_tick_rounded_price": Decimal("3.14160"),
        "tick_rule_status": NativeShortMapLevelTickRuleStatus.TICK_RULE_APPLIED,
        "tick_rule_source": NativeShortMapLevelTickRuleSource.TICK_RULE_FROM_DB,
        "level_lifecycle_state": NativeShortMapLevelLifecycleState.ACTIVE,
        "level_status_as_of_utc": datetime(2026, 7, 8, 0, 0, tzinfo=UTC),
        "evaluation_reference": NativeShortMapLevelEvaluationReference.PRIMARY_4H_CLOSED_CANDLES,
        "reason_code": "NO_PRIMARY_HIGH_REACHED_LEVEL",
        "projection_scope_status_code": NativeShortScopeStatusCode.CURRENT_EVALUATION,
        "projection_map_lifecycle_state": NativeShortScopeMapLifecycleState.MAP_ACTIVE,
        "projection_actionability_state": NativeShortScopeActionabilityState.ACTIONABLE_ACTIVE_MAP,
        "rebuilt_at_utc": datetime(2026, 7, 8, 0, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return NativeShortMapLevelStatusRecord(**values)  # type: ignore[arg-type]


def test_migration_creates_only_rebuildable_level_status_table() -> None:
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS native_short_map_level_status_v1" in sql
    assert sql.count("CREATE TABLE IF NOT EXISTS") == 1
    assert "INSERT INTO native_short_map_v1" not in sql
    assert "INSERT INTO native_short_map_generation_event_v1" not in sql
    assert "INSERT INTO native_short_map_lifecycle_event_v1" not in sql


def test_migration_uses_full_scope_key_and_projection_selected_map_identity() -> None:
    sql = _sql()
    full_key = "venue,\n        symbol,\n        quote_currency,\n        fib_trading_horizon,\n        primary_interval,\n        supporting_interval"
    assert "UNIQUE KEY uq_native_short_map_level_status_v1_identity" in sql
    assert full_key in sql
    assert "current_map_id" in sql
    assert "canonical_map_level_role" in sql
    assert "canonical_unrounded_price" in sql
    assert "CONSTRAINT fk_native_short_map_level_status_v1_map_scope" in sql
    assert "REFERENCES native_short_map_v1" in sql
    assert "map_cycle_id   VARCHAR(255) NOT NULL" in sql


def test_migration_has_closed_domains_reasons_and_terminal_gates() -> None:
    sql = _sql()
    for required in (
        "SELL_EXT_1_272",
        "SELL_EXT_1_618",
        "SELL_EXT_2_000",
        "CHECK (side = 'SELL')",
        "ACTIVE",
        "REACHED",
        "PASSED",
        "COMPLETED",
        "HISTORICAL",
        "NO_PRIMARY_HIGH_REACHED_LEVEL",
        "PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE",
        "PRIMARY_CLOSE_PASSED_LEVEL",
        "PRIMARY_4H_CLOSED_CANDLES",
        "MAP_LIFECYCLE_EVENT",
        "CURRENT_EVALUATION",
        "ACTIONABLE_ACTIVE_MAP",
        "MAP_COMPLETED",
        "MAP_INVALIDATED",
        "MAP_EXPIRED",
    ):
        assert required in sql
    assert "CONSTRAINT chk_native_short_map_level_status_v1_dynamic_reason" in sql


def test_migration_preserves_tick_evidence_without_using_it_as_lifecycle_identity() -> None:
    sql = _sql()
    assert "canonical_tick_rounded_price DECIMAL(30,12) NULL" in sql
    assert "tick_rule_status" in sql
    assert "tick_rule_source" in sql
    assert "MISSING_TICK_RULE" in sql
    assert "TICK_RULE_FROM_DB" in sql
    assert "TICK_RULE_FROM_STATIC" in sql
    unique_section = sql.split("UNIQUE KEY uq_native_short_map_level_status_v1_identity", 1)[1]
    unique_section = unique_section.split(")", 1)[0]
    assert "canonical_unrounded_price" in unique_section
    assert "canonical_tick_rounded_price" not in unique_section


def test_migration_introduces_no_forbidden_layer_references() -> None:
    sql = _sql().lower()
    for forbidden in (
        "sys" + "temd",
        " ti" + "mer",
        " ser" + "vice",
        "sub" + "process",
        "bro" + "ker",
        "acc" + "ount",
        "wal" + "let",
        "exec" + "utor",
        "exec" + "ution_planner",
        "decision" + "_gate",
        "src.reporting",
    ):
        assert forbidden not in sql


def test_level_status_record_identity_is_deterministic_for_same_map_level() -> None:
    first = _record()
    second = _record()
    assert first.map_level_identity_key() == second.map_level_identity_key()
    assert first.scope_level_identity_key() == second.scope_level_identity_key()
    assert first.map_level_identity_key() == "123|SELL_EXT_1_272|SELL|3.141592653589"


def test_changed_projection_selected_map_produces_distinct_level_identity() -> None:
    first = _record(current_map_id=123, map_cycle_id="cycle-a")
    second = _record(current_map_id=456, map_cycle_id="cycle-b")
    assert first.map_level_identity_key() != second.map_level_identity_key()
    assert first.map_cycle_id != second.map_cycle_id


def test_missing_tick_rule_requires_null_rounded_price_and_missing_source() -> None:
    record = _record(
        canonical_tick_rounded_price=None,
        tick_rule_status=NativeShortMapLevelTickRuleStatus.MISSING_TICK_RULE,
        tick_rule_source=NativeShortMapLevelTickRuleSource.MISSING_TICK_RULE,
    )
    assert record.canonical_tick_rounded_price is None

    with pytest.raises(NativeShortMapLevelStatusValidationError):
        _record(
            canonical_tick_rounded_price=Decimal("3.14160"),
            tick_rule_status=NativeShortMapLevelTickRuleStatus.MISSING_TICK_RULE,
            tick_rule_source=NativeShortMapLevelTickRuleSource.MISSING_TICK_RULE,
        )


@pytest.mark.parametrize(
    "state,reason",
    [
        (NativeShortMapLevelLifecycleState.ACTIVE, "NO_PRIMARY_HIGH_REACHED_LEVEL"),
        (NativeShortMapLevelLifecycleState.REACHED, "PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE"),
        (NativeShortMapLevelLifecycleState.PASSED, "PRIMARY_CLOSE_PASSED_LEVEL"),
    ],
)
def test_dynamic_states_require_current_active_projection_gate(
    state: NativeShortMapLevelLifecycleState,
    reason: str,
) -> None:
    _record(level_lifecycle_state=state, reason_code=reason)
    with pytest.raises(NativeShortMapLevelStatusValidationError):
        _record(
            level_lifecycle_state=state,
            reason_code=reason,
            projection_scope_status_code=NativeShortScopeStatusCode.SOURCE_STALE,
        )


@pytest.mark.parametrize(
    "state,bad_reason",
    [
        (NativeShortMapLevelLifecycleState.ACTIVE, "PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE"),
        (NativeShortMapLevelLifecycleState.REACHED, "PRIMARY_CLOSE_PASSED_LEVEL"),
        (NativeShortMapLevelLifecycleState.PASSED, "NO_PRIMARY_HIGH_REACHED_LEVEL"),
    ],
)
def test_dynamic_states_require_state_specific_reason_code(
    state: NativeShortMapLevelLifecycleState,
    bad_reason: str,
) -> None:
    with pytest.raises(NativeShortMapLevelStatusValidationError):
        _record(level_lifecycle_state=state, reason_code=bad_reason)


def test_completed_state_requires_map_terminal_completion() -> None:
    record = _record(
        level_lifecycle_state=NativeShortMapLevelLifecycleState.COMPLETED,
        evaluation_reference=NativeShortMapLevelEvaluationReference.MAP_LIFECYCLE_EVENT,
        reason_code="MAP_COMPLETED",
        projection_scope_status_code=NativeShortScopeStatusCode.MAP_COMPLETED,
        projection_map_lifecycle_state=NativeShortScopeMapLifecycleState.MAP_COMPLETED,
        projection_actionability_state=NativeShortScopeActionabilityState.TERMINAL_MAP,
    )
    assert record.level_lifecycle_state == NativeShortMapLevelLifecycleState.COMPLETED


@pytest.mark.parametrize(
    "map_state,reason",
    [
        (NativeShortScopeMapLifecycleState.MAP_INVALIDATED, "MAP_INVALIDATED"),
        (NativeShortScopeMapLifecycleState.MAP_EXPIRED, "MAP_EXPIRED"),
    ],
)
def test_historical_state_requires_invalidated_or_expired_selected_map(
    map_state: NativeShortScopeMapLifecycleState,
    reason: str,
) -> None:
    record = _record(
        level_lifecycle_state=NativeShortMapLevelLifecycleState.HISTORICAL,
        evaluation_reference=NativeShortMapLevelEvaluationReference.MAP_LIFECYCLE_EVENT,
        reason_code=reason,
        projection_scope_status_code=NativeShortScopeStatusCode.MAP_INVALIDATED,
        projection_map_lifecycle_state=map_state,
        projection_actionability_state=NativeShortScopeActionabilityState.TERMINAL_MAP,
    )
    assert record.level_lifecycle_state == NativeShortMapLevelLifecycleState.HISTORICAL


def test_new_type_module_imports_no_forbidden_layers() -> None:
    source = Path("src/market_data/native_short_map_level_status_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    for module_name in imported_modules:
        for forbidden in (
            "src.bro" + "ker",
            "src.acc" + "ount",
            "src.exec" + "utor",
            "src.exec" + "ution",
            "src.exec" + "ution_planner",
            "src.decision" + "_gate",
            "src.reporting",
        ):
            assert not module_name.startswith(forbidden), module_name
