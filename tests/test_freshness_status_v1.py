from __future__ import annotations

"""Deterministic boundary tests for the P2-B pure freshness classifier.

Covers all four statuses (FRESH / STALE / MISSING / UNAVAILABLE), threshold
boundary, clock-skew / future timestamps, fail-closed naive rejection,
frozen-static-page behavior, and overall reduction.  Thresholds are always
explicit (named test fixtures); the module ships no defaults.  Every test
injects ``now`` so nothing depends on wall-clock time.  Tests also assert the
module exposes no permission / decision surface.
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.operations import freshness_status_v1 as fs
from src.operations.freshness_status_v1 import (
    DASHBOARD_GENERATED,
    FRESH,
    MARKET_PRICE,
    MISSING,
    OPEN_ORDERS,
    POSITION,
    REASON_EXCEEDS_THRESHOLD,
    REASON_FUTURE_TIMESTAMP,
    REASON_NO_OBSERVATION,
    REASON_SOURCE_UNAVAILABLE,
    REASON_WITHIN_THRESHOLD,
    STALE,
    UNAVAILABLE,
    WALLET,
    ObservationClassSpec,
    evaluate_freshness,
    evaluate_observation_classes,
)

NOW = datetime(2026, 7, 16, 20, 0, 0, tzinfo=UTC)
# Named test-only threshold; the module defines no per-class defaults.
FIXTURE_THRESHOLD = timedelta(minutes=15)


def test_fresh_within_threshold():
    observed = NOW - timedelta(minutes=5)
    result = evaluate_freshness(observed, NOW, FIXTURE_THRESHOLD)
    assert result.status == FRESH
    assert result.reason == REASON_WITHIN_THRESHOLD
    assert result.is_fresh
    assert result.age_seconds == pytest.approx(300.0)


def test_fresh_exactly_at_threshold_boundary():
    observed = NOW - FIXTURE_THRESHOLD
    assert evaluate_freshness(observed, NOW, FIXTURE_THRESHOLD).status == FRESH


def test_stale_just_past_threshold():
    observed = NOW - FIXTURE_THRESHOLD - timedelta(seconds=1)
    result = evaluate_freshness(observed, NOW, FIXTURE_THRESHOLD)
    assert result.status == STALE
    assert result.reason == REASON_EXCEEDS_THRESHOLD


def test_missing_when_no_observation():
    result = evaluate_freshness(None, NOW, FIXTURE_THRESHOLD)
    assert result.status == MISSING
    assert result.reason == REASON_NO_OBSERVATION
    assert result.age_seconds is None
    assert result.observed_ts_utc is None


def test_unavailable_when_source_absent():
    result = evaluate_freshness(NOW, NOW, FIXTURE_THRESHOLD, source_available=False)
    assert result.status == UNAVAILABLE
    assert result.reason == REASON_SOURCE_UNAVAILABLE
    assert result.age_seconds is None


def test_future_timestamp_beyond_skew_is_stale_not_fresh():
    observed = NOW + timedelta(minutes=5)
    result = evaluate_freshness(observed, NOW, FIXTURE_THRESHOLD)
    assert result.status == STALE
    assert result.reason == REASON_FUTURE_TIMESTAMP


def test_future_timestamp_within_skew_is_fresh():
    observed = NOW + timedelta(seconds=2)
    result = evaluate_freshness(
        observed, NOW, FIXTURE_THRESHOLD, max_future_skew=timedelta(seconds=5)
    )
    assert result.status == FRESH


def test_naive_observed_ts_rejected_fail_closed():
    with pytest.raises(ValueError):
        evaluate_freshness(datetime(2026, 7, 16, 19, 55, 0), NOW, FIXTURE_THRESHOLD)


def test_naive_now_rejected_fail_closed():
    with pytest.raises(ValueError):
        evaluate_freshness(
            NOW - timedelta(minutes=5),
            datetime(2026, 7, 16, 20, 0, 0),
            FIXTURE_THRESHOLD,
        )


def test_negative_threshold_rejected():
    with pytest.raises(ValueError):
        evaluate_freshness(NOW, NOW, timedelta(seconds=-1))


def test_frozen_static_page_ages_to_stale():
    # A stopped renderer's dashboard_generated_ts_utc is fixed; as `now`
    # advances the same absolute timestamp deterministically flips FRESH->STALE.
    generated = NOW
    assert evaluate_freshness(generated, NOW, FIXTURE_THRESHOLD).status == FRESH
    later = NOW + timedelta(minutes=16)
    assert evaluate_freshness(generated, later, FIXTURE_THRESHOLD).status == STALE


def _all_class_specs(threshold=FIXTURE_THRESHOLD):
    return tuple(
        ObservationClassSpec(key, threshold)
        for key in (MARKET_PRICE, WALLET, POSITION, OPEN_ORDERS, DASHBOARD_GENERATED)
    )


def test_observation_classes_all_fresh():
    observed = {
        key: NOW - timedelta(minutes=1)
        for key in (MARKET_PRICE, WALLET, POSITION, OPEN_ORDERS, DASHBOARD_GENERATED)
    }
    report = evaluate_observation_classes(observed, NOW, _all_class_specs())
    assert report.overall_status == FRESH
    assert set(report.results) == {
        MARKET_PRICE, WALLET, POSITION, OPEN_ORDERS, DASHBOARD_GENERATED,
    }


def test_overall_status_is_worst_required():
    observed = {
        MARKET_PRICE: NOW - timedelta(minutes=1),
        WALLET: NOW - timedelta(hours=2),  # STALE
        POSITION: None,                    # MISSING (worse than STALE)
        OPEN_ORDERS: NOW - timedelta(minutes=1),
        DASHBOARD_GENERATED: NOW,
    }
    report = evaluate_observation_classes(observed, NOW, _all_class_specs())
    assert report.status_of(WALLET) == STALE
    assert report.overall_status == MISSING


def test_optional_class_does_not_worsen_overall():
    specs = (
        ObservationClassSpec(MARKET_PRICE, FIXTURE_THRESHOLD, required=True),
        ObservationClassSpec(DASHBOARD_GENERATED, FIXTURE_THRESHOLD, required=False),
    )
    observed = {
        MARKET_PRICE: NOW,
        DASHBOARD_GENERATED: NOW - timedelta(hours=5),  # STALE but optional
    }
    report = evaluate_observation_classes(observed, NOW, specs)
    assert report.status_of(DASHBOARD_GENERATED) == STALE
    assert report.overall_status == FRESH


def test_unavailable_source_map_marks_class_unavailable():
    observed = {
        key: NOW
        for key in (MARKET_PRICE, WALLET, POSITION, OPEN_ORDERS, DASHBOARD_GENERATED)
    }
    report = evaluate_observation_classes(
        observed, NOW, _all_class_specs(), source_available={POSITION: False}
    )
    assert report.status_of(POSITION) == UNAVAILABLE
    assert report.overall_status == UNAVAILABLE


def test_no_permission_or_decision_surface_exists():
    # The classifier must expose freshness only — no account/permission/gate.
    public = set(dir(fs))
    forbidden = {
        "account_action_permitted",
        "ACCOUNT_OBSERVATION_CLASS_KEYS",
        "account_statuses",
        "account_permitted",
    }
    assert public.isdisjoint(forbidden)
    # ObservationFreshnessReport carries no permission field.
    from dataclasses import fields

    report_fields = {f.name for f in fields(fs.ObservationFreshnessReport)}
    assert report_fields == {"overall_status", "results"}
    assert not any(
        "permit" in name or "permission" in name or "allow" in name
        for name in report_fields
    )
