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

ASOF = datetime(2026, 1, 1, 4, 0, 0, tzinfo=UTC)


def _row(**overrides):
    row = {
        "asset_id": 42,
        "venue": "bitvavo",
        "interval_code": "4h",
        "asof_ts_utc": ASOF,
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


def test_valid_fresh_evidence_preserves_raw_state_and_score():
    evidence = build_structure_component_evidence(
        _row(),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF + timedelta(minutes=30),
    )
    assert evidence.freshness == FreshnessState.FRESH
    assert evidence.raw == {"state": "UPTREND_STRONG", "score": "0.812345"}
    assert evidence.asof_ts == ASOF
    assert evidence.input_interval == "4h"
    # effective_horizon is not yet owner-declared for this producer, so the
    # evidence fails closed even though freshness is FRESH.
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA
    assert ReasonCode.UNMAPPED_HORIZON in evidence.reason_codes
    assert ReasonCode.STALE_EVIDENCE not in evidence.reason_codes


def test_stale_evidence():
    evidence = build_structure_component_evidence(
        _row(),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF + timedelta(hours=9),
    )
    assert evidence.freshness == FreshnessState.STALE
    # Staleness compounds with the still-unmapped effective_horizon gap, so
    # the top-level status remains fail-closed even though `freshness`
    # itself distinctly reports STALE rather than INSUFFICIENT_DATA.
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA
    assert ReasonCode.STALE_EVIDENCE in evidence.reason_codes
    assert ReasonCode.UNMAPPED_HORIZON in evidence.reason_codes


def test_missing_asof():
    evidence = build_structure_component_evidence(
        _row(asof_ts_utc=None),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF,
    )
    assert evidence.freshness == FreshnessState.INSUFFICIENT_DATA
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA
    assert ReasonCode.MISSING_ASOF_TS in evidence.reason_codes


def test_horizon_mismatch_unknown_interval_fails_closed():
    evidence = build_structure_component_evidence(
        _row(interval_code="2w"),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF,
    )
    assert evidence.freshness == FreshnessState.UNKNOWN
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA
    assert ReasonCode.UNKNOWN_INPUT_INTERVAL in evidence.reason_codes


def test_missing_provenance_when_engine_version_absent():
    evidence = build_structure_component_evidence(
        _row(engine_version=None),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF,
    )
    assert evidence.model_id is None
    assert ReasonCode.UNSUPPORTED_MODEL_VERSION in evidence.reason_codes
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA


def test_unsupported_model_version_fails_closed():
    evidence = build_structure_component_evidence(
        _row(engine_version="0.9"),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=ASOF,
    )
    assert ReasonCode.UNSUPPORTED_MODEL_VERSION in evidence.reason_codes
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA


def test_replay_uses_supplied_row_not_current_wallclock():
    far_future_wallclock_is_never_consulted = ASOF - timedelta(days=400)
    evidence = build_structure_component_evidence(
        _row(),
        COMPONENT_TREND,
        family=FAMILY_PRICE_STRUCTURE,
        evaluated_at=far_future_wallclock_is_never_consulted,
    )
    # A negative age (asof after evaluated_at) must never be treated as
    # fresh/current truth for a historical replay call.
    assert evidence.freshness == FreshnessState.STALE
    assert evidence.asof_ts == ASOF


def test_reason_codes_are_deterministic_across_calls():
    e1 = build_structure_component_evidence(
        _row(), COMPONENT_TREND, family=FAMILY_PRICE_STRUCTURE, evaluated_at=ASOF
    )
    e2 = build_structure_component_evidence(
        _row(), COMPONENT_TREND, family=FAMILY_PRICE_STRUCTURE, evaluated_at=ASOF
    )
    assert e1.reason_codes == e2.reason_codes
    assert e1.status == e2.status


def test_build_price_structure_evidence_covers_trend_pullback_range():
    evidence_by_component = build_price_structure_evidence(_row(), evaluated_at=ASOF)
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
    evidence = build_reclaim_evidence(_row(), evaluated_at=ASOF)
    assert evidence.family == FAMILY_RELATIVE_STRENGTH
    assert evidence.component == COMPONENT_RECLAIM
    assert evidence.raw == {"state": "RECLAIM_CONFIRMED", "score": "0.812000"}
