from datetime import UTC, datetime, timedelta

from src.features.evidence_contract_v1 import (
    EvidenceStatus,
    FreshnessState,
    ReasonCode,
    compute_freshness,
    interval_to_seconds,
    normalize_to_utc,
    resolve_status,
    validate_input_interval,
)


def test_interval_to_seconds_known():
    assert interval_to_seconds("1h") == 3600
    assert interval_to_seconds("4h") == 14400
    assert interval_to_seconds("1d") == 86400


def test_interval_to_seconds_unknown_returns_none():
    assert interval_to_seconds("2w") is None
    assert interval_to_seconds(None) is None


def test_validate_input_interval_known_is_clean():
    assert validate_input_interval("4h") == ()


def test_validate_input_interval_unknown_flags_reason_code():
    assert validate_input_interval("2w") == (ReasonCode.UNKNOWN_INPUT_INTERVAL,)
    assert validate_input_interval(None) == (ReasonCode.UNKNOWN_INPUT_INTERVAL,)


def test_normalize_to_utc_none():
    assert normalize_to_utc(None) is None


def test_normalize_to_utc_naive_is_interpreted_as_utc():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    normalized = normalize_to_utc(naive)
    assert normalized == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert normalized.tzinfo is UTC


def test_normalize_to_utc_aware_non_utc_is_converted():
    from datetime import timezone

    plus_two = timezone(timedelta(hours=2))
    aware = datetime(2026, 1, 1, 14, 0, 0, tzinfo=plus_two)
    normalized = normalize_to_utc(aware)
    assert normalized == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_compute_freshness_missing_asof():
    normalized_asof, freshness, reasons = compute_freshness(
        asof_ts=None,
        evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert normalized_asof is None
    assert freshness == FreshnessState.INSUFFICIENT_DATA
    assert reasons == (ReasonCode.MISSING_ASOF_TS,)


def test_compute_freshness_present_asof_is_unknown_not_fresh_or_stale():
    asof = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    normalized_asof, freshness, reasons = compute_freshness(
        asof_ts=asof,
        evaluated_at=asof + timedelta(minutes=5),
    )
    # No producer has a reviewed staleness rule, so freshness must not be
    # invented as FRESH/STALE from age alone.
    assert normalized_asof == asof
    assert freshness == FreshnessState.UNKNOWN
    assert reasons == (ReasonCode.FRESHNESS_NOT_OWNER_DEFINED,)


def test_compute_freshness_far_future_asof_still_unknown_not_fresh():
    asof = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    normalized_asof, freshness, reasons = compute_freshness(
        asof_ts=asof,
        evaluated_at=asof + timedelta(days=400),
    )
    assert freshness == FreshnessState.UNKNOWN
    assert reasons == (ReasonCode.FRESHNESS_NOT_OWNER_DEFINED,)


def test_compute_freshness_asof_after_evaluation_is_insufficient_data():
    asof = datetime(2026, 1, 1, 5, 0, tzinfo=UTC)
    evaluated_at = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    normalized_asof, freshness, reasons = compute_freshness(
        asof_ts=asof,
        evaluated_at=evaluated_at,
    )
    assert freshness == FreshnessState.INSUFFICIENT_DATA
    assert reasons == (ReasonCode.ASOF_AFTER_EVALUATION_TS,)


def test_compute_freshness_normalizes_naive_asof_against_aware_evaluated_at():
    naive_asof = datetime(2026, 1, 1, 0, 0, 0)
    aware_evaluated_at = datetime(2026, 1, 1, 0, 5, 0, tzinfo=UTC)
    normalized_asof, freshness, reasons = compute_freshness(
        asof_ts=naive_asof,
        evaluated_at=aware_evaluated_at,
    )
    assert normalized_asof == datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert freshness == FreshnessState.UNKNOWN
    assert reasons == (ReasonCode.FRESHNESS_NOT_OWNER_DEFINED,)


def test_compute_freshness_with_stale_after_fresh_within_window():
    asof = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    normalized_asof, freshness, reasons = compute_freshness(
        asof_ts=asof,
        evaluated_at=asof + timedelta(minutes=30),
        stale_after=timedelta(hours=1),
    )
    assert normalized_asof == asof
    assert freshness == FreshnessState.FRESH
    assert reasons == ()


def test_compute_freshness_with_stale_after_fresh_at_exact_boundary():
    asof = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    stale_after = timedelta(hours=1)
    _, freshness, reasons = compute_freshness(
        asof_ts=asof,
        evaluated_at=asof + stale_after,
        stale_after=stale_after,
    )
    assert freshness == FreshnessState.FRESH
    assert reasons == ()


def test_compute_freshness_with_stale_after_stale_past_window():
    asof = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    stale_after = timedelta(hours=1)
    _, freshness, reasons = compute_freshness(
        asof_ts=asof,
        evaluated_at=asof + stale_after + timedelta(seconds=1),
        stale_after=stale_after,
    )
    assert freshness == FreshnessState.STALE
    assert reasons == (ReasonCode.STALE_EVIDENCE,)


def test_compute_freshness_stale_after_none_preserves_unknown_default():
    """Callers that never opt in (any producer without a reviewed rule)
    keep receiving UNKNOWN -- the new parameter is additive, not a
    behavior change for existing unreviewed adapters."""
    asof = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    _, freshness, reasons = compute_freshness(
        asof_ts=asof,
        evaluated_at=asof + timedelta(minutes=5),
    )
    assert freshness == FreshnessState.UNKNOWN
    assert reasons == (ReasonCode.FRESHNESS_NOT_OWNER_DEFINED,)


def test_compute_freshness_future_asof_fails_closed_even_with_stale_after():
    """A future asof is a data-integrity contradiction, not a staleness
    judgement -- it must stay INSUFFICIENT_DATA even when a producer-owned
    `stale_after` is supplied, never silently FRESH."""
    asof = datetime(2026, 1, 1, 5, 0, tzinfo=UTC)
    evaluated_at = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    _, freshness, reasons = compute_freshness(
        asof_ts=asof,
        evaluated_at=evaluated_at,
        stale_after=timedelta(hours=1),
    )
    assert freshness == FreshnessState.INSUFFICIENT_DATA
    assert reasons == (ReasonCode.ASOF_AFTER_EVALUATION_TS,)


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


def test_resolve_status_unknown_freshness_is_insufficient_data():
    status, reasons = resolve_status(
        freshness=FreshnessState.UNKNOWN,
        extra_reason_codes=(ReasonCode.FRESHNESS_NOT_OWNER_DEFINED,),
    )
    assert status == EvidenceStatus.INSUFFICIENT_DATA
    assert reasons == (ReasonCode.FRESHNESS_NOT_OWNER_DEFINED,)
