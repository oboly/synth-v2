from datetime import UTC, datetime, timedelta

from src.features.evidence_contract_v1 import (
    EvidenceStatus,
    FreshnessState,
    ReasonCode,
)
from src.features.structure_evidence_contract_v1 import (
    COMPONENT_PULLBACK,
    COMPONENT_RANGE,
    COMPONENT_RECLAIM,
    COMPONENT_TREND,
    FAMILY_PRICE_STRUCTURE,
    FAMILY_RELATIVE_STRENGTH,
    build_price_structure_evidence,
    build_reclaim_evidence,
    build_structure_component_evidence,
)

# Persisted structure_state rows are naive-UTC: run_structure_state_engine.py
# strips tzinfo before INSERT (`asof_ts_utc.replace(tzinfo=None)`).
ASOF_NAIVE = datetime(2026, 1, 1, 4, 0, 0)
ASOF_AWARE = datetime(2026, 1, 1, 4, 0, 0, tzinfo=UTC)


def _row(**overrides):
    row = {
        "asset_id": 42,
        "venue": "bitvavo",
        "interval_code": "4h",
        "asof_ts_utc": ASOF_NAIVE,
        "trend_state": "UPTREND_STRONG",
        "trend_score": "0.812345",
        "pullback_state": "NO_PULLBACK",
        "pullback_score": "0.000000",
        "reclaim_state": "RECLAIM_CONFIRMED",
        "reclaim_score": "0.812000",
        "range_state": "RANGE",
        "range_score": "0.5",
        "engine_name": "structure_state_engine",
        "engine_version": "1.2",
    }
    row.update(overrides)
    return row


def test_valid_evidence_preserves_raw_state_and_score():
    evidence = build_structure_component_evidence(
        _row(),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF_AWARE + timedelta(minutes=30),
    )
    assert evidence.raw == {"state": "UPTREND_STRONG", "score": "0.812345"}
    assert evidence.asof_ts == ASOF_AWARE
    assert evidence.input_interval == "4h"
    assert evidence.model_id == "structure_state_engine"
    assert evidence.model_version == "1.2"
    # freshness has no reviewed producer rule yet, and effective_horizon is
    # unmapped, so the evidence still fails closed even with valid identity.
    assert evidence.freshness == FreshnessState.UNKNOWN
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA
    assert ReasonCode.UNMAPPED_HORIZON in evidence.reason_codes
    assert ReasonCode.FRESHNESS_NOT_OWNER_DEFINED in evidence.reason_codes


def test_missing_asof():
    evidence = build_structure_component_evidence(
        _row(asof_ts_utc=None),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF_AWARE,
    )
    assert evidence.freshness == FreshnessState.INSUFFICIENT_DATA
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA
    assert ReasonCode.MISSING_ASOF_TS in evidence.reason_codes


def test_asof_after_evaluation_is_explicit_not_silently_fresh():
    evidence = build_structure_component_evidence(
        _row(),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF_AWARE - timedelta(hours=1),
    )
    assert evidence.freshness == FreshnessState.INSUFFICIENT_DATA
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA
    assert ReasonCode.ASOF_AFTER_EVALUATION_TS in evidence.reason_codes


def test_horizon_mismatch_unknown_interval_fails_closed():
    evidence = build_structure_component_evidence(
        _row(interval_code="2w"),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF_AWARE,
    )
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA
    assert ReasonCode.UNKNOWN_INPUT_INTERVAL in evidence.reason_codes


def test_naive_producer_timestamp_normalized_against_aware_evaluated_at():
    """Regression: comparing the real naive-UTC persisted asof against an
    aware `evaluated_at` must not raise TypeError, and must resolve
    deterministically."""
    evidence = build_structure_component_evidence(
        _row(asof_ts_utc=ASOF_NAIVE),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF_AWARE + timedelta(hours=1),
    )
    assert evidence.asof_ts == ASOF_AWARE
    assert evidence.freshness == FreshnessState.UNKNOWN
    assert ReasonCode.ASOF_AFTER_EVALUATION_TS not in evidence.reason_codes


def test_missing_engine_name_fails_closed():
    evidence = build_structure_component_evidence(
        _row(engine_name=None),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF_AWARE,
    )
    assert evidence.model_id is None
    assert ReasonCode.MISSING_ENGINE_NAME in evidence.reason_codes
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA


def test_unexpected_engine_name_fails_closed_and_does_not_fabricate_model_id():
    evidence = build_structure_component_evidence(
        _row(engine_name="some_other_engine"),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF_AWARE,
    )
    assert evidence.model_id is None
    assert ReasonCode.UNEXPECTED_ENGINE_NAME in evidence.reason_codes
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA


def test_missing_engine_version_fails_closed():
    evidence = build_structure_component_evidence(
        _row(engine_version=None),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF_AWARE,
    )
    assert evidence.model_version is None
    assert ReasonCode.MISSING_ENGINE_VERSION in evidence.reason_codes
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA


def test_unsupported_model_version_fails_closed_and_does_not_fabricate():
    evidence = build_structure_component_evidence(
        _row(engine_version="0.9"),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF_AWARE,
    )
    assert evidence.model_version is None
    assert ReasonCode.UNSUPPORTED_MODEL_VERSION in evidence.reason_codes
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA


def test_valid_engine_name_and_version_populate_model_identity():
    evidence = build_structure_component_evidence(
        _row(engine_name="structure_state_engine", engine_version="1.2"),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF_AWARE,
    )
    assert evidence.model_id == "structure_state_engine"
    assert evidence.model_version == "1.2"
    assert ReasonCode.MISSING_ENGINE_NAME not in evidence.reason_codes
    assert ReasonCode.UNEXPECTED_ENGINE_NAME not in evidence.reason_codes
    assert ReasonCode.MISSING_ENGINE_VERSION not in evidence.reason_codes
    assert ReasonCode.UNSUPPORTED_MODEL_VERSION not in evidence.reason_codes


def test_replay_uses_supplied_row_not_current_wallclock():
    evidence = build_structure_component_evidence(
        _row(),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF_AWARE + timedelta(days=400),
    )
    assert evidence.asof_ts == ASOF_AWARE
    assert evidence.freshness == FreshnessState.UNKNOWN


def test_reason_codes_are_deterministic_across_calls():
    e1 = build_structure_component_evidence(
        _row(), COMPONENT_TREND, family=FAMILY_PRICE_STRUCTURE, evaluated_at=ASOF_AWARE
    )
    e2 = build_structure_component_evidence(
        _row(), COMPONENT_TREND, family=FAMILY_PRICE_STRUCTURE, evaluated_at=ASOF_AWARE
    )
    assert e1.reason_codes == e2.reason_codes
    assert e1.status == e2.status


def test_build_price_structure_evidence_covers_trend_pullback_range():
    evidence_by_component = build_price_structure_evidence(
        _row(), evaluated_at=ASOF_AWARE
    )
    assert set(evidence_by_component.keys()) == {
        COMPONENT_TREND,
        COMPONENT_PULLBACK,
        COMPONENT_RANGE,
    }
    assert evidence_by_component[COMPONENT_TREND].raw["state"] == "UPTREND_STRONG"
    assert evidence_by_component[COMPONENT_RANGE].raw["state"] == "RANGE"
    for evidence in evidence_by_component.values():
        assert evidence.family == FAMILY_PRICE_STRUCTURE


def test_build_reclaim_evidence_is_relative_strength_family():
    evidence = build_reclaim_evidence(_row(), evaluated_at=ASOF_AWARE)
    assert evidence.family == FAMILY_RELATIVE_STRENGTH
    assert evidence.component == COMPONENT_RECLAIM
    assert evidence.raw == {"state": "RECLAIM_CONFIRMED", "score": "0.812000"}
