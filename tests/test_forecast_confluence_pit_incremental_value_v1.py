import inspect
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import src.research.forecast_confluence_pit_cohort_audit_v1 as cohort_audit
import src.research.run_forecast_confluence_pit_incremental_value_v1 as incremental_value
from src.research.run_forecast_confluence_pit_incremental_value_v1 import (
    CANONICAL_BASELINE_LEDGER_SHA256,
    CANONICAL_BASELINE_OUTCOME_COUNT,
    CANONICAL_ENRICHED_LEDGER_SHA256,
    CANONICAL_ENRICHED_OUTCOME_COUNT,
    CANONICAL_FORECAST_COUNT,
    CANONICAL_LEDGER_DIR,
    RANKING_MINIMUM_N,
    CanonicalLedgers,
    IdentityGuardError,
    bootstrap_paired_mean_delta_ci,
    bootstrap_two_sample_mean_diff_ci,
    build_analysis,
    build_metric_records,
    build_neutralization_records,
    build_neutralization_recommendation,
    build_paired_records,
    by_horizon_section,
    classify_neutralization_attribution,
    diff_identity_sets,
    load_canonical_ledgers,
    neutralization_coverage,
    neutralization_effect,
    neutralization_grouped_section,
    paired_summary,
    reconcile_with_canonical,
    sector_code_section,
    verify_canonical_digest,
    verify_metric_record_identity,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _row() -> dict:
    return {
        "asof_ts_utc": datetime(2026, 8, 1), "map_id": 7, "market": "AAA", "venue": "bitvavo",
        "reference_price": 100, "trend_score": .8, "setup_score": .8, "compass_score": .8,
        "volume_score": .8, "distance_entry_to_target_pct": .8, "rotation_pressure_score": None,
        "sector_rotation_score": None,
    }


def _candles() -> dict[str, list[dict]]:
    start = datetime(2026, 8, 1)
    return {"AAA": [
        {"close_ts_utc": start + timedelta(hours=4), "close_price": 101, "high_price": 102, "low_price": 99},
        {"close_ts_utc": start + timedelta(hours=24), "close_price": 102, "high_price": 103, "low_price": 98},
        {"close_ts_utc": start + timedelta(hours=168), "close_price": 103, "high_price": 104, "low_price": 97},
    ]}


def test_canonical_baseline_digest_matches_committed_ledger() -> None:
    root = REPO_ROOT / CANONICAL_LEDGER_DIR
    data = (root / "baseline_outcome_identity_ledger_v1.jsonl").read_bytes()
    verify_canonical_digest(data, expected_sha256=CANONICAL_BASELINE_LEDGER_SHA256, label="baseline_outcome_identity_ledger")


def test_canonical_enriched_digest_matches_committed_ledger() -> None:
    root = REPO_ROOT / CANONICAL_LEDGER_DIR
    data = (root / "enriched_outcome_identity_ledger_v1.jsonl").read_bytes()
    verify_canonical_digest(data, expected_sha256=CANONICAL_ENRICHED_LEDGER_SHA256, label="enriched_outcome_identity_ledger")


def test_load_canonical_ledgers_reads_committed_counts() -> None:
    canonical = load_canonical_ledgers(REPO_ROOT / CANONICAL_LEDGER_DIR)
    assert len(canonical.forecasts) == CANONICAL_FORECAST_COUNT
    assert len(canonical.baseline_outcomes) == CANONICAL_BASELINE_OUTCOME_COUNT
    assert len(canonical.enriched_outcomes) == CANONICAL_ENRICHED_OUTCOME_COUNT


def test_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(IdentityGuardError):
        verify_canonical_digest(b"not the real bytes", expected_sha256=CANONICAL_BASELINE_LEDGER_SHA256, label="baseline_outcome_identity_ledger")


def test_canonical_helper_is_reused_not_duplicated() -> None:
    assert incremental_value.build_identity_ledgers is cohort_audit.build_identity_ledgers
    source = inspect.getsource(incremental_value)
    assert "def forecast_identity(" not in source
    assert "def build_identity_ledgers(" not in source
    assert "def outcome_with_exclusion(" not in source
    assert "def assess(" not in source


def test_exact_semantic_identity_equality_reconciles_with_zero_diff() -> None:
    canonical_forecasts, canonical_outcomes, _ = cohort_audit.build_identity_ledgers([_row()], _candles())
    canonical = CanonicalLedgers(
        forecasts=canonical_forecasts,
        baseline_outcomes=canonical_outcomes["baseline"],
        enriched_outcomes=canonical_outcomes["enriched"],
    )
    analysis_input = reconcile_with_canonical(canonical, [_row()], _candles())
    assert analysis_input.canonical_only_count == 0
    assert analysis_input.reconstructed_only_count == 0
    assert analysis_input.forecast_count == len(canonical_forecasts)
    assert analysis_input.baseline_outcome_count == len(canonical_outcomes["baseline"])
    assert analysis_input.enriched_outcome_count == len(canonical_outcomes["enriched"])


def test_identity_mismatch_missing_mode_field_fails_closed() -> None:
    """Reproduces the original bug shape: an identity row omitting `mode`."""
    canonical_forecasts, canonical_outcomes, _ = cohort_audit.build_identity_ledgers([_row()], _candles())
    corrupted_baseline = [{k: v for k, v in row.items() if k != "mode"} for row in canonical_outcomes["baseline"]]
    canonical = CanonicalLedgers(
        forecasts=canonical_forecasts,
        baseline_outcomes=corrupted_baseline,
        enriched_outcomes=canonical_outcomes["enriched"],
    )
    with pytest.raises(IdentityGuardError):
        reconcile_with_canonical(canonical, [_row()], _candles())


def test_diff_identity_sets_detects_asymmetric_mismatch() -> None:
    canonical = [{"a": 1, "mode": "baseline"}]
    reconstructed = [{"a": 1, "mode": "enriched"}]
    canonical_only, reconstructed_only = diff_identity_sets(canonical, reconstructed)
    assert canonical_only == 1
    assert reconstructed_only == 1


def _identity(map_id: int, horizon_hours: int, endpoint: str) -> dict:
    return {
        "venue": "bitvavo", "market": "AAA", "forecast_as_of_utc": "2026-08-01T00:00:00Z",
        "map_id": map_id, "horizon_hours": horizon_hours, "endpoint_close_ts_utc": endpoint,
    }


def _metric_record(*, map_id: int, horizon_hours: int, endpoint: str, return_pct: float, rotation_pressure_state: str = "UNAVAILABLE", sector_rotation_state: str = "UNAVAILABLE", signal_combination: str = "momentum") -> dict:
    return {
        **_identity(map_id, horizon_hours, endpoint),
        "return_pct": return_pct, "direction_hit": return_pct > 0,
        "mfe_pct": abs(return_pct) + 1, "mae_pct": abs(return_pct),
        "confidence_bucket": "MEDIUM", "signal_combination": signal_combination,
        "rotation_pressure_state": rotation_pressure_state, "sector_rotation_state": sector_rotation_state,
        "sector_code": "UNAVAILABLE", "rotation_pressure_score": None, "sector_rotation_score": None,
    }


# --- strict paired identity matching ---


def test_pairing_matches_only_on_full_identity_and_drops_unmatched() -> None:
    baseline = [
        _metric_record(map_id=1, horizon_hours=4, endpoint="2026-08-01T04:00:00Z", return_pct=1.0),
        _metric_record(map_id=2, horizon_hours=4, endpoint="2026-08-01T04:00:00Z", return_pct=2.0),  # baseline-only
    ]
    enriched = [
        _metric_record(map_id=1, horizon_hours=4, endpoint="2026-08-01T04:00:00Z", return_pct=3.0),
        _metric_record(map_id=3, horizon_hours=4, endpoint="2026-08-01T04:00:00Z", return_pct=9.0),  # enriched-only
    ]
    pairs = build_paired_records(baseline, enriched)
    assert len(pairs) == 1
    assert pairs[0]["return_delta_pct"] == 2.0


def test_pairing_requires_exact_horizon_and_endpoint_match() -> None:
    baseline = [_metric_record(map_id=1, horizon_hours=4, endpoint="2026-08-01T04:00:00Z", return_pct=1.0)]
    enriched = [_metric_record(map_id=1, horizon_hours=24, endpoint="2026-08-02T00:00:00Z", return_pct=1.0)]
    assert build_paired_records(baseline, enriched) == []


# --- horizon segmentation ---


def test_horizon_segmentation_reports_all_three_canonical_horizons() -> None:
    def _row() -> dict:
        return {
            "asof_ts_utc": datetime(2026, 8, 1), "map_id": 7, "market": "AAA", "venue": "bitvavo",
            "reference_price": 100, "trend_score": .8, "setup_score": .8, "compass_score": .8,
            "volume_score": .8, "distance_entry_to_target_pct": .8, "rotation_pressure_score": None,
            "sector_rotation_score": None, "pressure_state": None, "sector_rotation_state": None,
            "sector_code": None,
        }

    start = datetime(2026, 8, 1)
    candles = {"AAA": [
        {"close_ts_utc": start + timedelta(hours=4), "close_price": 101, "high_price": 102, "low_price": 99},
        {"close_ts_utc": start + timedelta(hours=24), "close_price": 102, "high_price": 103, "low_price": 98},
        {"close_ts_utc": start + timedelta(hours=168), "close_price": 103, "high_price": 104, "low_price": 97},
    ]}
    records = build_metric_records([_row()], candles)
    pairs = build_paired_records(records["baseline"], records["enriched"])
    section = by_horizon_section(records["baseline"], records["enriched"], pairs)
    assert set(section.keys()) == {"4", "24", "168"}
    assert sum(v["paired"]["paired_outcome_count"] for v in section.values()) == len(pairs)


# --- sample-floor handling ---


def test_sample_floor_separates_ranked_from_exploratory() -> None:
    baseline = [_metric_record(map_id=i, horizon_hours=4, endpoint="2026-08-01T04:00:00Z", return_pct=1.0) for i in range(RANKING_MINIMUM_N)]
    for r in baseline:
        r["sector_code"] = "BIG"
    small = [_metric_record(map_id=1000 + i, horizon_hours=4, endpoint="2026-08-01T04:00:00Z", return_pct=1.0) for i in range(RANKING_MINIMUM_N - 1)]
    for r in small:
        r["sector_code"] = "SMALL"
    all_baseline = baseline + small
    all_enriched = [dict(r) for r in all_baseline]
    pairs = build_paired_records(all_baseline, all_enriched)
    section = sector_code_section(all_baseline, all_enriched, pairs)
    assert "BIG" in section["ranked"]
    assert "SMALL" in section["exploratory"]
    assert "SMALL" not in section["ranked"]


# --- deterministic bootstrap ---


def test_bootstrap_ci_is_deterministic_with_fixed_seed() -> None:
    pairs = [{"return_delta_pct": v} for v in [0.5, -0.3, 1.2, 0.0, -0.7, 0.4, 0.9, -1.1, 0.2, 0.6]]
    first = bootstrap_paired_mean_delta_ci(pairs, seed=1234, resamples=200)
    second = bootstrap_paired_mean_delta_ci(pairs, seed=1234, resamples=200)
    assert first == second


def test_bootstrap_ci_empty_pairs_is_zero() -> None:
    result = bootstrap_paired_mean_delta_ci([])
    assert result["ci_95"] == [0.0, 0.0]
    assert result["n"] == 0


# --- artifact determinism ---


def test_artifact_json_is_byte_identical_across_runs() -> None:
    def _row() -> dict:
        return {
            "asof_ts_utc": datetime(2026, 8, 1), "map_id": 7, "market": "AAA", "venue": "bitvavo",
            "reference_price": 100, "trend_score": .8, "setup_score": .8, "compass_score": .8,
            "volume_score": .8, "distance_entry_to_target_pct": .8, "rotation_pressure_score": None,
            "sector_rotation_score": None, "pressure_state": None, "sector_rotation_state": None,
            "sector_code": None,
        }

    start = datetime(2026, 8, 1)
    candles = {"AAA": [
        {"close_ts_utc": start + timedelta(hours=4), "close_price": 101, "high_price": 102, "low_price": 99},
        {"close_ts_utc": start + timedelta(hours=24), "close_price": 102, "high_price": 103, "low_price": 98},
        {"close_ts_utc": start + timedelta(hours=168), "close_price": 103, "high_price": 104, "low_price": 97},
    ]}
    canonical_forecasts, canonical_outcomes, _ = cohort_audit.build_identity_ledgers([_row()], candles)
    canonical = CanonicalLedgers(forecasts=canonical_forecasts, baseline_outcomes=canonical_outcomes["baseline"], enriched_outcomes=canonical_outcomes["enriched"])
    records = build_metric_records([_row()], candles)
    neutralization_records = build_neutralization_records([_row()], candles)

    def _build() -> bytes:
        analysis = build_analysis(canonical=canonical, baseline_records=records["baseline"], enriched_records=records["enriched"], neutralization_records=neutralization_records, start=start, end=start + timedelta(days=1), venue="bitvavo")
        return json.dumps(analysis, sort_keys=True).encode("utf-8")

    assert _build() == _build()


# --- future-leakage assertion ---


def test_future_leakage_assertion_is_present_and_asserts_no_leakage() -> None:
    def _row() -> dict:
        return {
            "asof_ts_utc": datetime(2026, 8, 1), "map_id": 7, "market": "AAA", "venue": "bitvavo",
            "reference_price": 100, "trend_score": .8, "setup_score": .8, "compass_score": .8,
            "volume_score": .8, "distance_entry_to_target_pct": .8, "rotation_pressure_score": None,
            "sector_rotation_score": None, "pressure_state": None, "sector_rotation_state": None,
            "sector_code": None,
        }

    start = datetime(2026, 8, 1)
    candles = {"AAA": [
        {"close_ts_utc": start + timedelta(hours=4), "close_price": 101, "high_price": 102, "low_price": 99},
        {"close_ts_utc": start + timedelta(hours=24), "close_price": 102, "high_price": 103, "low_price": 98},
        {"close_ts_utc": start + timedelta(hours=168), "close_price": 103, "high_price": 104, "low_price": 97},
    ]}
    canonical_forecasts, canonical_outcomes, _ = cohort_audit.build_identity_ledgers([_row()], candles)
    canonical = CanonicalLedgers(forecasts=canonical_forecasts, baseline_outcomes=canonical_outcomes["baseline"], enriched_outcomes=canonical_outcomes["enriched"])
    records = build_metric_records([_row()], candles)
    neutralization_records = build_neutralization_records([_row()], candles)
    analysis = build_analysis(canonical=canonical, baseline_records=records["baseline"], enriched_records=records["enriched"], neutralization_records=neutralization_records, start=start, end=start + timedelta(days=1), venue="bitvavo")
    leakage = analysis["future_leakage"]
    assert leakage["asserted"] is True
    assert leakage["later_feature_rows_used"] == 0
    assert leakage["breathline_used"] is False
    assert leakage["current_state_substitution"] is False


# --- canonical identity guard remains intact for metric records ---


def test_metric_record_identity_guard_passes_for_matching_canonical() -> None:
    def _row() -> dict:
        return {
            "asof_ts_utc": datetime(2026, 8, 1), "map_id": 7, "market": "AAA", "venue": "bitvavo",
            "reference_price": 100, "trend_score": .8, "setup_score": .8, "compass_score": .8,
            "volume_score": .8, "distance_entry_to_target_pct": .8, "rotation_pressure_score": None,
            "sector_rotation_score": None, "pressure_state": None, "sector_rotation_state": None,
            "sector_code": None,
        }

    start = datetime(2026, 8, 1)
    candles = {"AAA": [
        {"close_ts_utc": start + timedelta(hours=4), "close_price": 101, "high_price": 102, "low_price": 99},
        {"close_ts_utc": start + timedelta(hours=24), "close_price": 102, "high_price": 103, "low_price": 98},
        {"close_ts_utc": start + timedelta(hours=168), "close_price": 103, "high_price": 104, "low_price": 97},
    ]}
    canonical_forecasts, canonical_outcomes, _ = cohort_audit.build_identity_ledgers([_row()], candles)
    records = build_metric_records([_row()], candles)
    verify_metric_record_identity(canonical_outcomes["baseline"], records["baseline"])
    verify_metric_record_identity(canonical_outcomes["enriched"], records["enriched"])


def test_metric_record_identity_guard_fails_closed_on_drift() -> None:
    def _row() -> dict:
        return {
            "asof_ts_utc": datetime(2026, 8, 1), "map_id": 7, "market": "AAA", "venue": "bitvavo",
            "reference_price": 100, "trend_score": .8, "setup_score": .8, "compass_score": .8,
            "volume_score": .8, "distance_entry_to_target_pct": .8, "rotation_pressure_score": None,
            "sector_rotation_score": None, "pressure_state": None, "sector_rotation_state": None,
            "sector_code": None,
        }

    start = datetime(2026, 8, 1)
    candles = {"AAA": [
        {"close_ts_utc": start + timedelta(hours=4), "close_price": 101, "high_price": 102, "low_price": 99},
        {"close_ts_utc": start + timedelta(hours=24), "close_price": 102, "high_price": 103, "low_price": 98},
        {"close_ts_utc": start + timedelta(hours=168), "close_price": 103, "high_price": 104, "low_price": 97},
    ]}
    canonical_forecasts, canonical_outcomes, _ = cohort_audit.build_identity_ledgers([_row()], candles)
    records = build_metric_records([_row()], candles)
    drifted = [dict(r) for r in records["baseline"]]
    drifted[0]["horizon_hours"] = 999
    with pytest.raises(IdentityGuardError):
        verify_metric_record_identity(canonical_outcomes["baseline"], drifted)


# --- paired_summary sanity ---


def test_paired_summary_classifies_improved_worsened_unchanged() -> None:
    pairs = [
        {"return_delta_pct": 1.0, "direction_hit_delta": 1, "mfe_delta_pct": 0.1, "mae_delta_pct": 0.0},
        {"return_delta_pct": -1.0, "direction_hit_delta": -1, "mfe_delta_pct": 0.0, "mae_delta_pct": 0.1},
        {"return_delta_pct": 0.0, "direction_hit_delta": 0, "mfe_delta_pct": 0.0, "mae_delta_pct": 0.0},
    ]
    summary = paired_summary(pairs)
    assert summary["improved_count"] == 1
    assert summary["worsened_count"] == 1
    assert summary["unchanged_count"] == 1
    assert summary["paired_outcome_count"] == 3


# --- retained vs neutralized partition (abstention/filtering analysis) ---


def _retained_row() -> dict:
    """Baseline and enriched agree LONG (no rotation/sector data): RETAINED."""
    return {
        "asof_ts_utc": datetime(2026, 8, 1), "map_id": 1, "market": "AAA", "venue": "bitvavo",
        "reference_price": 100, "trend_score": .8, "setup_score": .8, "compass_score": .8,
        "volume_score": .8, "distance_entry_to_target_pct": .8, "rotation_pressure_score": None,
        "sector_rotation_score": None, "pressure_state": None, "sector_rotation_state": None,
        "sector_code": None,
    }


def _neutralized_row() -> dict:
    """Baseline LONG (MEDIUM confidence); strongly negative rotation/sector scores push enriched to NEUTRAL."""
    return {
        "asof_ts_utc": datetime(2026, 8, 1), "map_id": 2, "market": "AAA", "venue": "bitvavo",
        "reference_price": 100, "trend_score": .60, "setup_score": .60, "compass_score": .60,
        "volume_score": .60, "distance_entry_to_target_pct": .60, "rotation_pressure_score": -100,
        "sector_rotation_score": -100, "pressure_state": "ROTATION_OUT", "sector_rotation_state": "ROTATION_OUT",
        "sector_code": "TESTSECTOR",
    }


def _shared_candles() -> dict[str, list[dict]]:
    start = datetime(2026, 8, 1)
    return {"AAA": [
        {"close_ts_utc": start + timedelta(hours=4), "close_price": 101, "high_price": 102, "low_price": 99},
        {"close_ts_utc": start + timedelta(hours=24), "close_price": 102, "high_price": 103, "low_price": 98},
        {"close_ts_utc": start + timedelta(hours=168), "close_price": 103, "high_price": 104, "low_price": 97},
    ]}


def test_retained_vs_neutralized_partition_no_double_counting() -> None:
    rows = [_retained_row(), _neutralized_row()]
    candles = _shared_candles()
    records = build_neutralization_records(rows, candles)
    assert len(records) == 2 * 3  # 2 rows x 3 horizons, each counted exactly once
    retained = [r for r in records if r["status"] == "RETAINED"]
    neutralized = [r for r in records if r["status"] == "NEUTRALIZED"]
    other = [r for r in records if r["status"] == "OTHER"]
    assert len(retained) == 3
    assert len(neutralized) == 3
    assert len(other) == 0
    assert all(r["map_id"] == 1 for r in retained)
    assert all(r["map_id"] == 2 for r in neutralized)


def test_neutralized_records_match_exact_forecast_identity_and_horizon() -> None:
    records = build_neutralization_records([_neutralized_row()], _shared_candles())
    horizons_seen = sorted(r["horizon_hours"] for r in records)
    assert horizons_seen == [4, 24, 168]
    for r in records:
        assert r["map_id"] == 2 and r["market"] == "AAA" and r["venue"] == "bitvavo"
        assert r["status"] == "NEUTRALIZED"
        assert "attribution" in r


def test_neutralization_rate_calculation() -> None:
    records = build_neutralization_records([_retained_row(), _neutralized_row()], _shared_candles())
    coverage = neutralization_coverage(records)
    assert coverage["baseline_non_neutral_outcome_count"] == 6
    assert coverage["retained_outcome_count"] == 3
    assert coverage["neutralized_outcome_count"] == 3
    assert coverage["neutralization_rate"] == 0.5
    assert coverage["baseline_non_neutral_unique_forecast_count"] == 2
    assert coverage["retained_unique_forecast_count"] == 1
    assert coverage["neutralized_unique_forecast_count"] == 1


def test_neutralization_bootstrap_ci_is_deterministic() -> None:
    a = [1.0, 2.0, -1.0, 0.5, -2.0]
    b = [-3.0, -1.5, -2.5, -4.0, -0.5]
    first = bootstrap_two_sample_mean_diff_ci(a, b, seed=1234, resamples=200)
    second = bootstrap_two_sample_mean_diff_ci(a, b, seed=1234, resamples=200)
    assert first == second
    assert first["ci_95"][1] < 0  # b (neutralized-like) confidently lower than a


def test_neutralization_bootstrap_ci_empty_side_is_zero() -> None:
    result = bootstrap_two_sample_mean_diff_ci([], [1.0, 2.0])
    assert result["ci_95"] == [0.0, 0.0]


def test_attribution_fails_closed_when_no_enrichment_present() -> None:
    row = {"rotation_pressure_score": None, "sector_rotation_score": None}
    assert classify_neutralization_attribution(row) == "cannot_attribute_no_enrichment_present"


def test_attribution_identifies_single_feature_when_only_one_present() -> None:
    assert classify_neutralization_attribution({"rotation_pressure_score": -100, "sector_rotation_score": None}) == "rotation_pressure_only"
    assert classify_neutralization_attribution({"rotation_pressure_score": None, "sector_rotation_score": -100}) == "sector_rotation_only"


def test_recommendation_rejects_when_neutralized_not_worse() -> None:
    coverage = {"neutralized_outcome_count": 100, "retained_outcome_count": 100}
    effect = {"neutralized_minus_retained": {"mean_forward_return_pct": 0.5}}  # neutralized BETTER
    bootstrap = {"ci_95": [0.1, 0.9]}
    recommendation, _rationale = build_neutralization_recommendation(coverage, effect, bootstrap, time_half_stable=True, horizon_stable=True)
    assert recommendation == "REJECT_FEATURE_ADDITION"


def test_recommendation_keeps_research_only_below_sample_floor() -> None:
    coverage = {"neutralized_outcome_count": 5, "retained_outcome_count": 100}
    effect = {"neutralized_minus_retained": {"mean_forward_return_pct": -2.0}}
    bootstrap = {"ci_95": [-3.0, -1.0]}
    recommendation, _rationale = build_neutralization_recommendation(coverage, effect, bootstrap, time_half_stable=True, horizon_stable=True)
    assert recommendation == "KEEP_RESEARCH_ONLY"


def test_recommendation_keeps_research_only_when_ci_crosses_zero() -> None:
    coverage = {"neutralized_outcome_count": 100, "retained_outcome_count": 100}
    effect = {"neutralized_minus_retained": {"mean_forward_return_pct": -0.5}}
    bootstrap = {"ci_95": [-1.5, 0.3]}
    recommendation, _rationale = build_neutralization_recommendation(coverage, effect, bootstrap, time_half_stable=True, horizon_stable=True)
    assert recommendation == "KEEP_RESEARCH_ONLY"


def test_recommendation_ready_for_rule_experiment_when_robustly_worse_and_stable() -> None:
    coverage = {"neutralized_outcome_count": 100, "retained_outcome_count": 100}
    effect = {"neutralized_minus_retained": {"mean_forward_return_pct": -2.0}}
    bootstrap = {"ci_95": [-3.0, -1.0]}
    recommendation, _rationale = build_neutralization_recommendation(coverage, effect, bootstrap, time_half_stable=True, horizon_stable=True)
    assert recommendation == "READY_FOR_RULE_EXPERIMENT"


def test_recommendation_keeps_research_only_when_effect_not_stable() -> None:
    coverage = {"neutralized_outcome_count": 100, "retained_outcome_count": 100}
    effect = {"neutralized_minus_retained": {"mean_forward_return_pct": -2.0}}
    bootstrap = {"ci_95": [-3.0, -1.0]}
    recommendation, _rationale = build_neutralization_recommendation(coverage, effect, bootstrap, time_half_stable=False, horizon_stable=True)
    assert recommendation == "KEEP_RESEARCH_ONLY"
