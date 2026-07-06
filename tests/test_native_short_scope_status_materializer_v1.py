from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.market_data.native_short_fib_context_v1 import (
    PRIMARY_LIFECYCLE_COMPLETED,
    PRIMARY_LIFECYCLE_INVALIDATED,
    STATUS_AVAILABLE,
    NativeShortContextRow,
)
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapLifecycleEventType
from src.market_data.native_short_map_materializer_v1 import (
    REASON_PRIOR_REJECTION_UNCHANGED,
    REASON_STRUCTURE_UNCHANGED,
    ScopeMaterializationResult,
)
from src.market_data.native_short_scope_status_materializer_v1 import (
    CONTRACT_VERSION,
    NativeShortRunBuilder,
    build_configuration_unavailable_observation,
    build_normal_observation,
    decide_genuine_lifecycle_transition,
    map_geometry_action,
)
from src.market_data.native_short_scope_status_projection_v1 import MapFact
from src.market_data.native_short_scope_status_v1 import NativeShortScopeSourceState

_AS_OF = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def _map(map_id: int = 1, cycle_id: str = "cyc1") -> MapFact:
    return MapFact(map_id=map_id, published_at_utc=_AS_OF - timedelta(hours=5), map_cycle_id=cycle_id)


def _context_row(*, lifecycle_state: str, map_cycle_id: str = "cyc1") -> NativeShortContextRow:
    return NativeShortContextRow(
        symbol="BTC",
        venue="bitvavo",
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
        context_status=STATUS_AVAILABLE,
        map_cycle_id=map_cycle_id,
        anchor_start_ts_utc=_AS_OF - timedelta(days=10),
        anchor_end_ts_utc=_AS_OF - timedelta(days=5),
        anchor_low_price=None,
        anchor_high_price=None,
        breakout_gate_price=None,
        latest_primary_close_ts_utc=_AS_OF - timedelta(hours=1),
        latest_support_close_ts_utc=_AS_OF - timedelta(minutes=20),
        latest_primary_close_price=None,
        ext_1_272_price=None,
        ext_1_618_price=None,
        ext_2_000_price=None,
        active_target_levels=(),
        previous_target_levels=(),
        reload_r382_price=None,
        reload_r500_price=None,
        reload_r618_price=None,
        reload_r786_price=None,
        invalidation_price=None,
        primary_4h_lifecycle_state=lifecycle_state,
        supporting_1h_state="ALIGNED_WITH_4H",
        context_freshness_status="FRESH",
        max_primary_high_since_anchor=None,
        min_primary_low_since_anchor=None,
        source_name="native_short_fib_context_v1",
        source_version="0.1",
        source_primary_ref="obs_market_candle:4h",
        source_support_ref="obs_market_candle:1h",
        current_map_status="CURRENT_ACTIVE_MAP",
        previous_map_cycle_id="",
        previous_map_lifecycle_state="",
        rollover_state="SINGLE_MAP",
        selection_reason="Single active map selected",
        source_primary_candle_count=73,
        source_support_candle_count=219,
    )


# --- NativeShortRunBuilder: terminal-fields-once guarantee ------------------


def test_run_builder_started_record_has_no_terminal_fields() -> None:
    builder = NativeShortRunBuilder(
        run_uuid="00000000-0000-0000-0000-000000000001",
        runner_name="runner",
        runner_version="0.1",
        contract_version=CONTRACT_VERSION,
        trigger_type="MANUAL",
        started_at_utc=_AS_OF,
        requested_scope_count=3,
    )
    started = builder.started_record()
    assert started.terminal_status is None
    assert started.finished_at_utc is None
    assert started.requested_scope_count == 3


def test_run_builder_aggregates_scope_outcomes_and_finishes_once() -> None:
    builder = NativeShortRunBuilder(
        run_uuid="00000000-0000-0000-0000-000000000001",
        runner_name="runner",
        runner_version="0.1",
        contract_version=CONTRACT_VERSION,
        trigger_type="MANUAL",
        started_at_utc=_AS_OF,
        requested_scope_count=3,
    )
    builder.record_scope_outcome(published_map=True)
    builder.record_scope_outcome(lifecycle_event_appended=True)
    builder.record_scope_outcome(failed=True)

    finished = builder.finish(finished_at_utc=_AS_OF + timedelta(seconds=5))
    assert finished.observed_scope_count == 3
    assert finished.published_map_count == 1
    assert finished.lifecycle_event_count == 1
    assert finished.failed_scope_count == 1
    assert finished.terminal_status == "FINISHED"
    assert finished.finished_at_utc == _AS_OF + timedelta(seconds=5)


def test_run_builder_rejects_second_finish() -> None:
    builder = NativeShortRunBuilder(
        run_uuid="00000000-0000-0000-0000-000000000001",
        runner_name="runner",
        runner_version="0.1",
        contract_version=CONTRACT_VERSION,
        trigger_type="MANUAL",
        started_at_utc=_AS_OF,
        requested_scope_count=1,
    )
    builder.finish(finished_at_utc=_AS_OF)
    with pytest.raises(ValueError, match="RUN_ALREADY_FINISHED"):
        builder.finish(finished_at_utc=_AS_OF)


def test_run_builder_rejects_recording_after_finish() -> None:
    builder = NativeShortRunBuilder(
        run_uuid="00000000-0000-0000-0000-000000000001",
        runner_name="runner",
        runner_version="0.1",
        contract_version=CONTRACT_VERSION,
        trigger_type="MANUAL",
        started_at_utc=_AS_OF,
        requested_scope_count=1,
    )
    builder.finish(finished_at_utc=_AS_OF)
    with pytest.raises(ValueError, match="RUN_ALREADY_FINISHED"):
        builder.record_scope_outcome()


# --- genuine lifecycle transition decision ----------------------------------


def test_no_transition_when_no_selected_map() -> None:
    row = _context_row(lifecycle_state=PRIMARY_LIFECYCLE_INVALIDATED)
    assert decide_genuine_lifecycle_transition(
        selected_map=None, context_row=row, existing_lifecycle_event_types_for_map=frozenset()
    ) is None


def test_no_transition_when_no_context_row() -> None:
    assert decide_genuine_lifecycle_transition(
        selected_map=_map(), context_row=None, existing_lifecycle_event_types_for_map=frozenset()
    ) is None


def test_no_transition_when_context_evaluates_a_different_map_cycle() -> None:
    row = _context_row(lifecycle_state=PRIMARY_LIFECYCLE_INVALIDATED, map_cycle_id="different-cycle")
    assert decide_genuine_lifecycle_transition(
        selected_map=_map(cycle_id="cyc1"), context_row=row, existing_lifecycle_event_types_for_map=frozenset()
    ) is None


def test_invalidated_transition_decided_once() -> None:
    row = _context_row(lifecycle_state=PRIMARY_LIFECYCLE_INVALIDATED)
    decision = decide_genuine_lifecycle_transition(
        selected_map=_map(), context_row=row, existing_lifecycle_event_types_for_map=frozenset()
    )
    assert decision == NativeShortMapLifecycleEventType.INVALIDATED

    # Already recorded: must not decide again (append-once guarantee).
    decision_again = decide_genuine_lifecycle_transition(
        selected_map=_map(),
        context_row=row,
        existing_lifecycle_event_types_for_map=frozenset({"INVALIDATED"}),
    )
    assert decision_again is None


def test_completed_transition_decided_once() -> None:
    row = _context_row(lifecycle_state=PRIMARY_LIFECYCLE_COMPLETED)
    decision = decide_genuine_lifecycle_transition(
        selected_map=_map(), context_row=row, existing_lifecycle_event_types_for_map=frozenset()
    )
    assert decision == NativeShortMapLifecycleEventType.COMPLETED

    decision_again = decide_genuine_lifecycle_transition(
        selected_map=_map(),
        context_row=row,
        existing_lifecycle_event_types_for_map=frozenset({"COMPLETED"}),
    )
    assert decision_again is None


def test_no_transition_for_ordinary_non_terminal_lifecycle_state() -> None:
    row = _context_row(lifecycle_state="TARGET_ACTIVE")
    decision = decide_genuine_lifecycle_transition(
        selected_map=_map(), context_row=row, existing_lifecycle_event_types_for_map=frozenset()
    )
    assert decision is None


def test_no_expired_detection_exists_anywhere() -> None:
    """No deterministic EXPIRED predicate exists in the codebase; this
    function must never invent one, even if asked about an EXPIRED-shaped
    context state string."""
    row = _context_row(lifecycle_state="EXPIRED")
    decision = decide_genuine_lifecycle_transition(
        selected_map=_map(), context_row=row, existing_lifecycle_event_types_for_map=frozenset()
    )
    assert decision is None


# --- geometry action mapping --------------------------------------------------


def test_geometry_action_published() -> None:
    result = ScopeMaterializationResult(symbol="BTC", attempted=True, status="published", dry_run=False, map_id=1)
    assert map_geometry_action(result) == "PUBLISHED_NEW_MAP"


def test_geometry_action_unchanged() -> None:
    result = ScopeMaterializationResult(
        symbol="BTC", attempted=True, status="skipped", dry_run=False, reason_code=REASON_STRUCTURE_UNCHANGED
    )
    assert map_geometry_action(result) == "UNCHANGED_GEOMETRY"


def test_geometry_action_rejected_context() -> None:
    result = ScopeMaterializationResult(
        symbol="BTC",
        attempted=True,
        status="skipped",
        dry_run=False,
        reason_code=REASON_PRIOR_REJECTION_UNCHANGED,
        generation_event_type="REJECTED",
    )
    assert map_geometry_action(result) == "REJECTED_CONTEXT"


def test_geometry_action_no_map_available_fallback() -> None:
    result = ScopeMaterializationResult(symbol="BTC", attempted=False, status="skipped", dry_run=False)
    assert map_geometry_action(result) == "NO_MAP_AVAILABLE"


# --- observation builders ----------------------------------------------------


def test_build_configuration_unavailable_observation_is_valid() -> None:
    from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey

    record = build_configuration_unavailable_observation(
        key=NativeShortMapScopeKey(venue="bitvavo", symbol="BTC"),
        run_id=1,
        run_uuid="00000000-0000-0000-0000-000000000001",
        observed_at_utc=_AS_OF,
    )
    assert record.observation_status == "SKIPPED_CONFIGURATION_UNAVAILABLE"
    assert record.observation_reason_code == "NO_ELIGIBLE_CADENCE_CONFIG"
    assert record.cadence_contract_version is None


def test_build_normal_observation_records_map_ids_and_lifecycle_event() -> None:
    from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey

    result = ScopeMaterializationResult(
        symbol="BTC", attempted=True, status="skipped", dry_run=False, reason_code=REASON_STRUCTURE_UNCHANGED, map_id=1
    )
    record = build_normal_observation(
        key=NativeShortMapScopeKey(venue="bitvavo", symbol="BTC"),
        run_id=1,
        run_uuid="00000000-0000-0000-0000-000000000001",
        observed_at_utc=_AS_OF,
        cadence_contract_version="v1",
        source_state=NativeShortScopeSourceState.SOURCE_CURRENT,
        primary_source_freshness_limit_seconds=43200,
        supporting_source_freshness_limit_seconds=10800,
        geometry_action=map_geometry_action(result),
        result=result,
        current_map_id_before=1,
        current_map_id_after=1,
        lifecycle_event_id=99,
        lifecycle_state_before="MAP_ACTIVE",
        lifecycle_state_after="MAP_INVALIDATED",
        primary_latest_candle_ts_utc=_AS_OF - timedelta(hours=1),
        supporting_latest_candle_ts_utc=_AS_OF - timedelta(minutes=20),
        context_status=STATUS_AVAILABLE,
        source_primary_candle_count=73,
        source_support_candle_count=219,
    )
    assert record.observation_status == "EVALUATED"
    assert record.current_map_id_before == 1
    assert record.current_map_id_after == 1
    assert record.lifecycle_event_id == 99
    assert record.lifecycle_state_after == "MAP_INVALIDATED"
    assert record.geometry_action == "UNCHANGED_GEOMETRY"


# --- boundary scan -------------------------------------------------------------


def test_materializer_module_imports_no_forbidden_layers() -> None:
    source = Path("src/market_data/native_short_scope_status_materializer_v1.py").read_text(encoding="utf-8")
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


def test_materializer_module_has_no_wallclock_calls() -> None:
    """AST-based (not raw-text) check: the module's own docstrings legitimately
    *describe* this boundary in prose, so a substring scan would false-positive
    on the documentation itself. What must never appear is an actual call
    expression invoking datetime.now()/utcnow()/NOW()."""
    source = Path("src/market_data/native_short_scope_status_materializer_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        assert name not in ("now", "utcnow", "NOW"), ast.dump(node)
