from __future__ import annotations

"""Deterministic boundary tests for the P2-B pure freshness evaluator.

Covers all four statuses (FRESH / STALE / MISSING / UNAVAILABLE), clock-skew
handling, frozen-static-page behavior, overall reduction, and account-action
suppression.  Every test injects ``now`` so nothing depends on wall-clock time.
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.operations.freshness_status_v1 import (
    ACCOUNT_OBSERVATION_CLASS_KEYS,
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
THRESHOLD = timedelta(minutes=15)


def test_fresh_within_threshold():
    observed = NOW - timedelta(minutes=5)
    result = evaluate_freshness(observed, NOW, THRESHOLD)
    assert result.status == FRESH
    assert result.reason == REASON_WITHIN_THRESHOLD
    assert result.is_fresh
    assert result.age_seconds == pytest.approx(300.0)


def test_fresh_exactly_at_threshold_boundary():
    observed = NOW - THRESHOLD
    result = evaluate_freshness(observed, NOW, THRESHOLD)
    assert result.status == FRESH


def test_stale_just_past_threshold():
    observed = NOW - THRESHOLD - timedelta(seconds=1)
    result = evaluate_freshness(observed, NOW, THRESHOLD)
    assert result.status == STALE
    assert result.reason == REASON_EXCEEDS_THRESHOLD


def test_missing_when_no_observation():
    result = evaluate_freshness(None, NOW, THRESHOLD)
    assert result.status == MISSING
    assert result.reason == REASON_NO_OBSERVATION
    assert result.age_seconds is None
    assert result.observed_ts_utc is None


def test_unavailable_when_source_absent():
    # An observation could even be present, but an unavailable source is
    # structurally reported as UNAVAILABLE, not FRESH.
    result = evaluate_freshness(NOW, NOW, THRESHOLD, source_available=False)
    assert result.status == UNAVAILABLE
    assert result.reason == REASON_SOURCE_UNAVAILABLE
    assert result.age_seconds is None


def test_future_timestamp_beyond_skew_is_stale_not_fresh():
    observed = NOW + timedelta(minutes=5)
    result = evaluate_freshness(observed, NOW, THRESHOLD)
    assert result.status == STALE
    assert result.reason == REASON_FUTURE_TIMESTAMP


def test_future_timestamp_within_skew_is_fresh():
    observed = NOW + timedelta(seconds=2)
    result = evaluate_freshness(
        observed, NOW, THRESHOLD, max_future_skew=timedelta(seconds=5)
    )
    assert result.status == FRESH


def test_naive_timestamp_assumed_utc():
    aware = evaluate_freshness(NOW - timedelta(minutes=5), NOW, THRESHOLD)
    naive = evaluate_freshness(
        datetime(2026, 7, 16, 19, 55, 0), NOW, THRESHOLD
    )
    assert naive.status == aware.status == FRESH
    assert naive.age_seconds == pytest.approx(aware.age_seconds)


def test_negative_threshold_rejected():
    with pytest.raises(ValueError):
        evaluate_freshness(NOW, NOW, timedelta(seconds=-1))


def test_frozen_static_page_ages_to_stale():
    # A stopped renderer's dashboard_generated_ts_utc is fixed; as `now`
    # advances the same absolute timestamp deterministically flips FRESH->STALE.
    generated = NOW
    assert evaluate_freshness(generated, NOW, THRESHOLD).status == FRESH
    later = NOW + timedelta(minutes=16)
    assert evaluate_freshness(generated, later, THRESHOLD).status == STALE


def test_observation_classes_all_fresh():
    observed = {key: NOW - timedelta(minutes=1) for key in (
        MARKET_PRICE, WALLET, POSITION, OPEN_ORDERS, DASHBOARD_GENERATED,
    )}
    report = evaluate_observation_classes(observed, NOW)
    assert report.overall_status == FRESH
    assert report.account_action_permitted is True
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
    report = evaluate_observation_classes(observed, NOW)
    assert report.overall_status == MISSING


def test_stale_account_suppresses_account_action():
    observed = {
        MARKET_PRICE: NOW,
        WALLET: NOW - timedelta(hours=1),  # stale account truth
        POSITION: NOW,
        OPEN_ORDERS: NOW,
        DASHBOARD_GENERATED: NOW,
    }
    report = evaluate_observation_classes(observed, NOW)
    assert report.status_of(WALLET) == STALE
    assert report.account_action_permitted is False


def test_missing_account_source_suppresses_account_action():
    observed = {
        MARKET_PRICE: NOW,
        WALLET: NOW,
        POSITION: None,
        OPEN_ORDERS: NOW,
        DASHBOARD_GENERATED: NOW,
    }
    report = evaluate_observation_classes(observed, NOW)
    assert report.account_action_permitted is False


def test_market_only_context_visible_while_account_suppressed():
    # Market context can stay FRESH under its own contract even when account
    # truth is stale; the two freshness contracts are independent.
    observed = {
        MARKET_PRICE: NOW,
        WALLET: NOW - timedelta(hours=1),
        POSITION: NOW - timedelta(hours=1),
        OPEN_ORDERS: NOW - timedelta(hours=1),
        DASHBOARD_GENERATED: NOW,
    }
    report = evaluate_observation_classes(observed, NOW)
    assert report.status_of(MARKET_PRICE) == FRESH
    assert report.account_action_permitted is False


def test_non_required_class_does_not_worsen_overall():
    specs = (
        ObservationClassSpec(MARKET_PRICE, THRESHOLD, required=True),
        ObservationClassSpec(DASHBOARD_GENERATED, THRESHOLD, required=False),
    )
    observed = {
        MARKET_PRICE: NOW,
        DASHBOARD_GENERATED: NOW - timedelta(hours=5),  # STALE but optional
    }
    report = evaluate_observation_classes(observed, NOW, specs)
    assert report.status_of(DASHBOARD_GENERATED) == STALE
    assert report.overall_status == FRESH


def test_unavailable_source_map_marks_class_unavailable():
    observed = {key: NOW for key in (
        MARKET_PRICE, WALLET, POSITION, OPEN_ORDERS, DASHBOARD_GENERATED,
    )}
    report = evaluate_observation_classes(
        observed, NOW, source_available={POSITION: False}
    )
    assert report.status_of(POSITION) == UNAVAILABLE
    assert report.account_action_permitted is False
    assert report.overall_status == UNAVAILABLE


def test_account_class_keys_are_subset_of_all_keys():
    from src.operations.freshness_status_v1 import OBSERVATION_CLASS_KEYS

    assert set(ACCOUNT_OBSERVATION_CLASS_KEYS).issubset(
        set(OBSERVATION_CLASS_KEYS)
    )
