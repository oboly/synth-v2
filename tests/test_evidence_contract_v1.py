from datetime import UTC, datetime, timedelta

from src.features.evidence_contract_v1 import (
    EvidenceStatus,
    FreshnessState,
    ReasonCode,
    compute_freshness,
    interval_to_seconds,
    resolve_status,
)


def test_interval_to_seconds_known():
    assert interval_to_seconds("1h") == 3600
    assert interval_to_seconds("4h") == 14400
    assert interval_to_seconds("1d") == 86400


def test_interval_to_seconds_unknown_returns_none():
    assert interval_to_seconds("2w") is None
    assert interval_to_seconds(None) is None


def test_compute_freshness_missing_asof():
    freshness, reasons = compute_freshness(
        asof_ts=None,
        evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
        input_interval="1h",
    )
    assert freshness == FreshnessState.INSUFFICIENT_DATA
    assert reasons == (ReasonCode.MISSING_ASOF_TS,)


def test_compute_freshness_unknown_interval():
    freshness, reasons = compute_freshness(
        asof_ts=datetime(2026, 1, 1, tzinfo=UTC),
        evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
        input_interval="2w",
    )
    assert freshness == FreshnessState.UNKNOWN
    assert reasons == (ReasonCode.UNKNOWN_INPUT_INTERVAL,)


def test_compute_freshness_fresh():
    asof = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    evaluated_at = asof + timedelta(hours=1)
    freshness, reasons = compute_freshness(
        asof_ts=asof,
        evaluated_at=evaluated_at,
        input_interval="1h",
        stale_after_multiplier=2.0,
    )
    assert freshness == FreshnessState.FRESH
    assert reasons == ()


def test_compute_freshness_stale():
    asof = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    evaluated_at = asof + timedelta(hours=3)
    freshness, reasons = compute_freshness(
        asof_ts=asof,
        evaluated_at=evaluated_at,
        input_interval="1h",
        stale_after_multiplier=2.0,
    )
    assert freshness == FreshnessState.STALE
    assert reasons == (ReasonCode.STALE_EVIDENCE,)


def test_compute_freshness_future_asof_is_stale_not_fresh():
    asof = datetime(2026, 1, 1, 5, 0, tzinfo=UTC)
    evaluated_at = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    freshness, reasons = compute_freshness(
        asof_ts=asof,
        evaluated_at=evaluated_at,
        input_interval="1h",
    )
    assert freshness == FreshnessState.STALE
    assert reasons == (ReasonCode.STALE_EVIDENCE,)


def test_resolve_status_valid():
    status, reasons = resolve_status(freshness=FreshnessState.FRESH)
    assert status == EvidenceStatus.VALID
    assert reasons == ()


def test_resolve_status_stale():
    status, reasons = resolve_status(
        freshness=FreshnessState.STALE,
        extra_reason_codes=(ReasonCode.STALE_EVIDENCE,),
    )
    assert status == EvidenceStatus.STALE
    assert reasons == (ReasonCode.STALE_EVIDENCE,)


def test_resolve_status_insufficient_data_from_extra_reason_codes():
    status, reasons = resolve_status(
        freshness=FreshnessState.FRESH,
        extra_reason_codes=(ReasonCode.UNMAPPED_HORIZON,),
    )
    assert status == EvidenceStatus.INSUFFICIENT_DATA
    assert reasons == (ReasonCode.UNMAPPED_HORIZON,)


def test_resolve_status_missing_asof_takes_precedence():
    status, reasons = resolve_status(freshness=FreshnessState.INSUFFICIENT_DATA)
    assert status == EvidenceStatus.INSUFFICIENT_DATA
