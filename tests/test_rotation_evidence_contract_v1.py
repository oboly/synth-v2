from datetime import UTC, datetime, timedelta

from src.features.evidence_contract_v1 import (
    EffectiveHorizon,
    EvidenceStatus,
    FreshnessState,
    LifecycleStatus,
    ReasonCode,
)
from src.features.rotation_evidence_contract_v1 import (
    COMPONENT_PER_ASSET_PRESSURE,
    FAMILY_ROTATION,
    INPUT_INTERVAL,
    LOOKBACK_HORIZON,
    MODEL_ID,
    ROTATION_STALE_AFTER,
    build_rotation_pressure_evidence,
)

# market_rotation_pressure_observation_v1.as_of_ts_utc is DATETIME(6),
# persisted naive-UTC (writer never attaches tzinfo before INSERT, same
# convention as structure_state/relative_strength_snapshot).
ASOF_NAIVE = datetime(2026, 1, 1, 11, 0, 0)
ASOF_AWARE = datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC)


def _row(**overrides):
    row = {
        "asset_id": 7,
        "market": "BTC-EUR",
        "source_snapshot_24h_id": 111,
        "source_snapshot_7d_id": 222,
        "as_of_ts_utc": ASOF_NAIVE,
        "model_version": "1.0",
        "raw_return_24h_pct": "2.500000",
        "raw_return_7d_pct": "5.100000",
        "score_total": "42.1300",
        "pressure_state": "ROTATION_IN",
        "phase_state": "ACCELERATING_IN",
    }
    row.update(overrides)
    return row


def test_valid_evidence_maps_family_component_and_horizon():
    evidence = build_rotation_pressure_evidence(_row(), evaluated_at=ASOF_AWARE)
    assert evidence.family == FAMILY_ROTATION
    assert evidence.component == COMPONENT_PER_ASSET_PRESSURE
    assert evidence.input_interval == INPUT_INTERVAL == "1h"
    assert evidence.lookback_horizon == LOOKBACK_HORIZON == "24h+168h"
    assert evidence.effective_horizon == EffectiveHorizon.REGIME
    assert evidence.observed_lifecycle.status == LifecycleStatus.UNMEASURED
    assert evidence.asof_ts == ASOF_AWARE


def test_rotation_stale_after_is_90_minutes():
    assert ROTATION_STALE_AFTER == timedelta(minutes=90)


def test_raw_score_and_state_preserved_exactly():
    evidence = build_rotation_pressure_evidence(_row(), evaluated_at=ASOF_AWARE)
    assert evidence.raw == {
        "score_total": "42.1300",
        "pressure_state": "ROTATION_IN",
        "phase_state": "ACCELERATING_IN",
        "raw_return_24h_pct": "2.500000",
        "raw_return_7d_pct": "5.100000",
    }


def test_valid_model_version_populates_identity():
    evidence = build_rotation_pressure_evidence(_row(), evaluated_at=ASOF_AWARE)
    assert evidence.model_id == MODEL_ID == "market_rotation_pressure_v1"
    assert evidence.model_version == "1.0"


def test_missing_model_version_fails_closed_and_does_not_fabricate():
    evidence = build_rotation_pressure_evidence(
        _row(model_version=None), evaluated_at=ASOF_AWARE
    )
    assert evidence.model_id is None
    assert evidence.model_version is None
    assert ReasonCode.MISSING_PROVENANCE in evidence.reason_codes
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA


def test_blank_model_version_fails_closed():
    evidence = build_rotation_pressure_evidence(
        _row(model_version="   "), evaluated_at=ASOF_AWARE
    )
    assert evidence.model_id is None
    assert evidence.model_version is None
    assert ReasonCode.MISSING_PROVENANCE in evidence.reason_codes


def test_unsupported_model_version_fails_closed_and_does_not_fabricate():
    evidence = build_rotation_pressure_evidence(
        _row(model_version="0.9"), evaluated_at=ASOF_AWARE
    )
    assert evidence.model_id is None
    assert evidence.model_version is None
    assert ReasonCode.UNSUPPORTED_MODEL_VERSION in evidence.reason_codes
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA


def test_missing_asof_fails_closed():
    evidence = build_rotation_pressure_evidence(
        _row(as_of_ts_utc=None), evaluated_at=ASOF_AWARE
    )
    assert evidence.freshness == FreshnessState.INSUFFICIENT_DATA
    assert ReasonCode.MISSING_ASOF_TS in evidence.reason_codes
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA


def test_naive_producer_timestamp_normalized_against_aware_evaluated_at():
    evidence = build_rotation_pressure_evidence(
        _row(as_of_ts_utc=ASOF_NAIVE), evaluated_at=ASOF_AWARE + timedelta(hours=1)
    )
    assert evidence.asof_ts == ASOF_AWARE
    assert ReasonCode.ASOF_AFTER_EVALUATION_TS not in evidence.reason_codes


def test_asof_after_evaluation_is_explicit_not_silently_fresh():
    evidence = build_rotation_pressure_evidence(
        _row(), evaluated_at=ASOF_AWARE - timedelta(hours=1)
    )
    assert evidence.freshness == FreshnessState.INSUFFICIENT_DATA
    assert ReasonCode.ASOF_AFTER_EVALUATION_TS in evidence.reason_codes


def test_fresh_at_recent_asof_and_active_when_otherwise_valid():
    """A recent, valid row (well inside 90m, valid model_version) resolves
    to FRESH and VALID -- i.e. it may become active/available downstream
    once all other canonical requirements pass, per the #547 Phase C owner
    decision."""
    evidence = build_rotation_pressure_evidence(
        _row(), evaluated_at=ASOF_AWARE + timedelta(minutes=5)
    )
    assert evidence.freshness == FreshnessState.FRESH
    assert ReasonCode.STALE_EVIDENCE not in evidence.reason_codes
    assert evidence.status == EvidenceStatus.VALID


def test_exact_90_minute_boundary_is_fresh():
    evidence = build_rotation_pressure_evidence(
        _row(), evaluated_at=ASOF_AWARE + ROTATION_STALE_AFTER
    )
    assert evidence.freshness == FreshnessState.FRESH
    assert evidence.status == EvidenceStatus.VALID


def test_90_minutes_plus_epsilon_is_stale():
    evidence = build_rotation_pressure_evidence(
        _row(),
        evaluated_at=ASOF_AWARE + ROTATION_STALE_AFTER + timedelta(microseconds=1),
    )
    assert evidence.freshness == FreshnessState.STALE
    assert ReasonCode.STALE_EVIDENCE in evidence.reason_codes
    assert evidence.status == EvidenceStatus.STALE


def test_freshness_cannot_be_supplied_by_arbitrary_caller_override():
    """`build_rotation_pressure_evidence` exposes no threshold/override
    parameter -- freshness is derived solely from the module's own
    `ROTATION_STALE_AFTER`, which has no caller-configurable staleness
    knob."""
    import inspect

    signature = inspect.signature(build_rotation_pressure_evidence)
    assert "stale_after_multiplier" not in signature.parameters
    assert "freshness" not in signature.parameters
    assert "freshness_override" not in signature.parameters
    assert "rotation_stale_after" not in signature.parameters


def test_replay_uses_supplied_row_not_current_wallclock():
    """A very old asof relative to the supplied `evaluated_at` resolves to
    STALE deterministically from the two supplied timestamps -- never from
    any internal wall-clock read (`evaluated_at` is a required argument
    with no default and no internal `now()` call exists in this module)."""
    evidence = build_rotation_pressure_evidence(
        _row(), evaluated_at=ASOF_AWARE + timedelta(days=400)
    )
    assert evidence.freshness == FreshnessState.STALE
    assert evidence.asof_ts == ASOF_AWARE
    assert evidence.status == EvidenceStatus.STALE


def test_aware_utc_asof_input_is_accepted_directly():
    """A row whose `as_of_ts_utc` already carries tzinfo (a hypothetical
    aware-UTC producer input, unlike the real naive-UTC column) must
    normalize and classify identically to the naive-UTC case."""
    evidence = build_rotation_pressure_evidence(
        _row(as_of_ts_utc=ASOF_AWARE), evaluated_at=ASOF_AWARE + timedelta(minutes=5)
    )
    assert evidence.asof_ts == ASOF_AWARE
    assert evidence.freshness == FreshnessState.FRESH
    assert evidence.status == EvidenceStatus.VALID


def test_no_wall_clock_read_in_module_source():
    """No implicit wall-clock fallback: this module must never call
    `datetime.now()`/`datetime.utcnow()` internally -- freshness is always
    derived solely from the caller-supplied `evaluated_at`."""
    import inspect

    import src.features.rotation_evidence_contract_v1 as module

    source = inspect.getsource(module)
    assert "datetime.now(" not in source
    assert ".utcnow()" not in source
    assert "utcnow(" not in source


def test_reason_codes_are_deterministic_across_calls():
    e1 = build_rotation_pressure_evidence(_row(), evaluated_at=ASOF_AWARE)
    e2 = build_rotation_pressure_evidence(_row(), evaluated_at=ASOF_AWARE)
    assert e1.reason_codes == e2.reason_codes
    assert e1.status == e2.status


def _imported_module_names() -> set[str]:
    import ast
    import inspect

    import src.features.rotation_evidence_contract_v1 as module

    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_no_593_or_rotation_flip_imports():
    """This adapter must only read the broad/regime V1 producer's output
    shape -- it must never import #593's faster-variant research modules or
    #449 Rotation Flip research."""
    imported = _imported_module_names()
    assert not any("multi_horizon_rotation" in name for name in imported)
    assert not any("rotation_flip" in name.lower() for name in imported)
    assert not any(name.startswith("src.research") for name in imported)


def test_no_account_or_execution_imports():
    imported = _imported_module_names()
    forbidden_substrings = (
        "decision_gate",
        "execution_planner",
        "executor",
        "src.selection",
        "broker",
    )
    for name in imported:
        assert not any(forbidden in name for forbidden in forbidden_substrings)
