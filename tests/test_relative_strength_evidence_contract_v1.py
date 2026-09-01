from datetime import UTC, datetime, timedelta

from src.features.evidence_contract_v1 import (
    EvidenceStatus,
    FreshnessState,
    ReasonCode,
)
from src.features.relative_strength_evidence_contract_v1 import (
    COMPONENT_CROSS_SECTIONAL_RANK,
    FAMILY_RELATIVE_STRENGTH,
    INPUT_INTERVAL,
    build_cross_sectional_rank_evidence,
)

ASOF = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def _row(**overrides):
    row = {
        "snapshot_ts_utc": ASOF,
        "asset_id": 7,
        "lookback_days": 7,
        "return_pct": "3.140000",
        "rank_value": 2,
        "universe_size": 10,
        "rank_pct": "0.900000",
        "zscore": "1.230000",
    }
    row.update(overrides)
    return row


def test_valid_fresh_evidence_preserves_raw_numeric_values():
    evidence = build_cross_sectional_rank_evidence(
        _row(), evaluated_at=ASOF + timedelta(hours=1)
    )
    assert evidence.family == FAMILY_RELATIVE_STRENGTH
    assert evidence.component == COMPONENT_CROSS_SECTIONAL_RANK
    assert evidence.input_interval == INPUT_INTERVAL
    assert evidence.lookback_horizon == "7d"
    assert evidence.asof_ts == ASOF
    assert evidence.freshness == FreshnessState.FRESH
    assert evidence.raw == {
        "return_pct": "3.140000",
        "rank_value": 2,
        "rank_pct": "0.900000",
        "zscore": "1.230000",
    }
    # No model_id/model_version supplied -> missing provenance, fails closed.
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA
    assert ReasonCode.MISSING_PROVENANCE in evidence.reason_codes


def test_stale_evidence():
    evidence = build_cross_sectional_rank_evidence(
        _row(), evaluated_at=ASOF + timedelta(days=3)
    )
    assert evidence.freshness == FreshnessState.STALE
    # Staleness compounds with missing provenance/unmapped horizon, so the
    # top-level status remains fail-closed even though `freshness` itself
    # distinctly reports STALE rather than INSUFFICIENT_DATA.
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA
    assert ReasonCode.STALE_EVIDENCE in evidence.reason_codes


def test_missing_asof():
    evidence = build_cross_sectional_rank_evidence(
        _row(snapshot_ts_utc=None), evaluated_at=ASOF
    )
    assert evidence.freshness == FreshnessState.INSUFFICIENT_DATA
    assert ReasonCode.MISSING_ASOF_TS in evidence.reason_codes
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA


def test_missing_provenance_by_default():
    evidence = build_cross_sectional_rank_evidence(_row(), evaluated_at=ASOF)
    assert evidence.model_id is None
    assert evidence.model_version is None
    assert ReasonCode.MISSING_PROVENANCE in evidence.reason_codes


def test_explicit_provenance_removes_missing_provenance_reason():
    evidence = build_cross_sectional_rank_evidence(
        _row(),
        evaluated_at=ASOF,
        model_id="relative_strength_snapshot",
        model_version="1.0",
    )
    assert evidence.model_id == "relative_strength_snapshot"
    assert evidence.model_version == "1.0"
    assert ReasonCode.MISSING_PROVENANCE not in evidence.reason_codes
    # effective_horizon is still unmapped, so status remains fail-closed.
    assert ReasonCode.UNMAPPED_HORIZON in evidence.reason_codes
    assert evidence.status == EvidenceStatus.INSUFFICIENT_DATA


def test_lookback_horizon_maps_persisted_lookback_days():
    evidence = build_cross_sectional_rank_evidence(
        _row(lookback_days=14), evaluated_at=ASOF
    )
    assert evidence.lookback_horizon == "14d"


def test_replay_uses_supplied_row_not_current_wallclock():
    evidence = build_cross_sectional_rank_evidence(
        _row(), evaluated_at=ASOF - timedelta(days=400)
    )
    assert evidence.freshness == FreshnessState.STALE
    assert evidence.asof_ts == ASOF


def test_reason_codes_are_deterministic_across_calls():
    e1 = build_cross_sectional_rank_evidence(_row(), evaluated_at=ASOF)
    e2 = build_cross_sectional_rank_evidence(_row(), evaluated_at=ASOF)
    assert e1.reason_codes == e2.reason_codes
    assert e1.status == e2.status
