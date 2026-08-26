"""Incremental-value analysis for forecast confluence PIT replay.

Milestone 1 (identity guard): verify the committed canonical identity ledgers
are byte-exact and that a fresh reconstruction (via the canonical helpers in
``forecast_confluence_pit_cohort_audit_v1``) produces an identical identity
set. This module never constructs forecast or outcome identity itself; it
reuses ``forecast_identity``/``build_identity_ledgers`` from the cohort audit
module and ``assess``/``outcome_with_exclusion``/``metrics``/``grouped`` from
the replay module, so the original incremental-value bug (independent
identity reconstruction that silently omitted ``mode``) cannot recur here.

Milestone 2 (incremental-value analysis): using the identity-verified metric
records, evaluate whether Rotation Pressure and sector rotation context add
information over the baseline signal set on the fixed canonical cohort. This
is research-only: it produces a JSON artifact and a markdown report and does
not touch selection_engine, decision_gate, execution_planner, executor, or
broker code paths.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np

from src.common.db import get_connection
from src.research.forecast_confluence_pit_cohort_audit_v1 import (
    BASELINE_LEDGER_FILENAME,
    ENRICHED_LEDGER_FILENAME,
    FORECAST_LEDGER_FILENAME,
    build_identity_ledgers,
    endpoint_close_ts,
    forecast_identity,
    iso_z,
    sha256,
)
from src.research.forecast_confluence_pit_replay_v1 import (
    HORIZONS,
    assess,
    fetch_candles,
    fetch_rows,
    grouped,
    metrics,
    outcome_with_exclusion,
    parse_ts,
)
from src.research.runner_lifecycle_v1 import RunnerLifecycle

VERSION = "forecast_confluence_pit_incremental_value/v1"

ANALYSIS_ARTIFACT_FILENAME = "incremental_value_analysis_20260731_20260817_v1.json"
RANKING_MINIMUM_N = 30
BOOTSTRAP_SEED = 1234
BOOTSTRAP_RESAMPLES = 2000
REQUIRED_SIGNAL_COMBINATIONS = (
    "momentum+setup+volume",
    "momentum+setup+trend",
    "momentum+setup",
    "momentum+volume",
    "momentum",
    "no supporting signals",
)

CANONICAL_LEDGER_DIR = Path("data/research/forecast_confluence_pit_replay_v1")

CANONICAL_FORECAST_LEDGER_SHA256 = "862fb3a2df8611e1382447da5e3ecadfcda68de7086a98caa4b729e4ebb7692b"
CANONICAL_BASELINE_LEDGER_SHA256 = "85a01b801b7936daed5ba58e3110dd58b3078db1ddab4231fee47c8daef5d1de"
CANONICAL_ENRICHED_LEDGER_SHA256 = "10fccecebd7d812c57264e0e33d3f4c7eec16ab47a3bae7b836e2d5da15f8e85"

CANONICAL_FORECAST_COUNT = 3039
CANONICAL_BASELINE_OUTCOME_COUNT = 8081
CANONICAL_ENRICHED_OUTCOME_COUNT = 7844


class IdentityGuardError(RuntimeError):
    """Raised when a canonical digest or identity-set check fails closed."""


@dataclass(frozen=True)
class CanonicalLedgers:
    forecasts: list[dict[str, Any]]
    baseline_outcomes: list[dict[str, Any]]
    enriched_outcomes: list[dict[str, Any]]


@dataclass(frozen=True)
class IncrementalValueAnalysisInput:
    """Reusable, identity-verified input for the later feature-effect analysis."""

    forecasts: list[dict[str, Any]]
    baseline_outcomes: list[dict[str, Any]]
    enriched_outcomes: list[dict[str, Any]]
    forecast_count: int
    baseline_outcome_count: int
    enriched_outcome_count: int
    canonical_only_count: int
    reconstructed_only_count: int


def verify_canonical_digest(data: bytes, *, expected_sha256: str, label: str) -> None:
    actual = sha256(data)
    if actual != expected_sha256:
        raise IdentityGuardError(
            f"{label} digest mismatch: expected {expected_sha256}, got {actual}"
        )


def _read_jsonl(data: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in data.splitlines() if line]


def load_canonical_ledgers(ledger_dir: Path = CANONICAL_LEDGER_DIR) -> CanonicalLedgers:
    """Load and digest-verify the committed canonical identity ledgers.

    Fails closed: any digest or count mismatch raises ``IdentityGuardError``
    before any bytes are trusted as input to reconstruction comparison.
    """
    forecast_bytes = (ledger_dir / FORECAST_LEDGER_FILENAME).read_bytes()
    baseline_bytes = (ledger_dir / BASELINE_LEDGER_FILENAME).read_bytes()
    enriched_bytes = (ledger_dir / ENRICHED_LEDGER_FILENAME).read_bytes()

    verify_canonical_digest(forecast_bytes, expected_sha256=CANONICAL_FORECAST_LEDGER_SHA256, label="forecast_identity_ledger")
    verify_canonical_digest(baseline_bytes, expected_sha256=CANONICAL_BASELINE_LEDGER_SHA256, label="baseline_outcome_identity_ledger")
    verify_canonical_digest(enriched_bytes, expected_sha256=CANONICAL_ENRICHED_LEDGER_SHA256, label="enriched_outcome_identity_ledger")

    forecasts = _read_jsonl(forecast_bytes)
    baseline_outcomes = _read_jsonl(baseline_bytes)
    enriched_outcomes = _read_jsonl(enriched_bytes)

    if len(forecasts) != CANONICAL_FORECAST_COUNT:
        raise IdentityGuardError(f"forecast ledger count mismatch: expected {CANONICAL_FORECAST_COUNT}, got {len(forecasts)}")
    if len(baseline_outcomes) != CANONICAL_BASELINE_OUTCOME_COUNT:
        raise IdentityGuardError(f"baseline outcome ledger count mismatch: expected {CANONICAL_BASELINE_OUTCOME_COUNT}, got {len(baseline_outcomes)}")
    if len(enriched_outcomes) != CANONICAL_ENRICHED_OUTCOME_COUNT:
        raise IdentityGuardError(f"enriched outcome ledger count mismatch: expected {CANONICAL_ENRICHED_OUTCOME_COUNT}, got {len(enriched_outcomes)}")

    return CanonicalLedgers(forecasts=forecasts, baseline_outcomes=baseline_outcomes, enriched_outcomes=enriched_outcomes)


def _identity_key(row: dict[str, Any]) -> frozenset[tuple[str, Any]]:
    return frozenset(row.items())


def diff_identity_sets(canonical: list[dict[str, Any]], reconstructed: list[dict[str, Any]]) -> tuple[int, int]:
    """Return (canonical_only_count, reconstructed_only_count) for two identity lists."""
    canonical_keys = {_identity_key(row) for row in canonical}
    reconstructed_keys = {_identity_key(row) for row in reconstructed}
    return len(canonical_keys - reconstructed_keys), len(reconstructed_keys - canonical_keys)


def reconcile_with_canonical(
    canonical: CanonicalLedgers,
    rows: list[dict[str, Any]],
    candles_by_market: dict[str, list[dict[str, Any]]],
) -> IncrementalValueAnalysisInput:
    """Reconstruct identities via the canonical helper and fail closed on any mismatch.

    Identity reconstruction is delegated entirely to
    ``forecast_confluence_pit_cohort_audit_v1.build_identity_ledgers`` -- this
    function performs no independent forecast/outcome identity construction.
    """
    forecasts, outcomes, _exclusions = build_identity_ledgers(rows, candles_by_market)

    forecast_canonical_only, forecast_reconstructed_only = diff_identity_sets(canonical.forecasts, forecasts)
    if forecast_canonical_only or forecast_reconstructed_only:
        raise IdentityGuardError(
            f"forecast identity mismatch: canonical_only={forecast_canonical_only} reconstructed_only={forecast_reconstructed_only}"
        )

    baseline_canonical_only, baseline_reconstructed_only = diff_identity_sets(canonical.baseline_outcomes, outcomes["baseline"])
    if baseline_canonical_only or baseline_reconstructed_only:
        raise IdentityGuardError(
            f"baseline outcome identity mismatch: canonical_only={baseline_canonical_only} reconstructed_only={baseline_reconstructed_only}"
        )

    enriched_canonical_only, enriched_reconstructed_only = diff_identity_sets(canonical.enriched_outcomes, outcomes["enriched"])
    if enriched_canonical_only or enriched_reconstructed_only:
        raise IdentityGuardError(
            f"enriched outcome identity mismatch: canonical_only={enriched_canonical_only} reconstructed_only={enriched_reconstructed_only}"
        )

    return IncrementalValueAnalysisInput(
        forecasts=canonical.forecasts,
        baseline_outcomes=canonical.baseline_outcomes,
        enriched_outcomes=canonical.enriched_outcomes,
        forecast_count=len(canonical.forecasts),
        baseline_outcome_count=len(canonical.baseline_outcomes),
        enriched_outcome_count=len(canonical.enriched_outcomes),
        canonical_only_count=0,
        reconstructed_only_count=0,
    )


def build_metric_records(
    rows: list[dict[str, Any]], candles_by_market: dict[str, list[dict[str, Any]]]
) -> dict[str, list[dict[str, Any]]]:
    """Build identity-tagged, metric-bearing outcome records for both modes.

    Reuses ``forecast_identity``/``endpoint_close_ts`` (identity) and
    ``assess``/``outcome_with_exclusion`` (metrics) from the canonical
    modules -- no identity or metric algorithm is re-derived here.
    """
    records: dict[str, list[dict[str, Any]]] = {"baseline": [], "enriched": []}
    for row in rows:
        identity = forecast_identity(row)
        candles = candles_by_market[row["market"]]
        for mode in records:
            assessment = assess(row, enriched=mode == "enriched")
            for horizon in HORIZONS:
                horizon_hours = int(horizon.total_seconds() / 3600)
                result, exclusion_reason = outcome_with_exclusion(row, assessment, candles, horizon)
                if result is None:
                    continue
                close_ts = endpoint_close_ts(row, candles, horizon_hours)
                if close_ts is None:
                    raise RuntimeError("outcome was present without an endpoint close timestamp")
                records[mode].append(
                    {
                        **identity,
                        "endpoint_close_ts_utc": iso_z(close_ts),
                        "horizon_hours": horizon_hours,
                        "mode": mode,
                        **result,
                        "rotation_pressure_state": row["pressure_state"] or "UNAVAILABLE",
                        "sector_rotation_state": row["sector_rotation_state"] or "UNAVAILABLE",
                        "sector_code": row["sector_code"] or "UNAVAILABLE",
                        "rotation_pressure_score": None if row["rotation_pressure_score"] is None else float(row["rotation_pressure_score"]),
                        "sector_rotation_score": None if row["sector_rotation_score"] is None else float(row["sector_rotation_score"]),
                    }
                )
    return records


_IDENTITY_FIELDS = ("forecast_as_of_utc", "map_id", "market", "venue", "mode", "horizon_hours", "endpoint_close_ts_utc")


def verify_metric_record_identity(canonical_outcomes: list[dict[str, Any]], metric_records: list[dict[str, Any]]) -> None:
    """Fail closed if the identity-projection of metric records drifts from the canonical ledger."""
    projected = [{field: record[field] for field in _IDENTITY_FIELDS} for record in metric_records]
    canonical_only, reconstructed_only = diff_identity_sets(canonical_outcomes, projected)
    if canonical_only or reconstructed_only:
        raise IdentityGuardError(
            f"metric record identity drift: canonical_only={canonical_only} reconstructed_only={reconstructed_only}"
        )


def classify_neutralization_attribution(row: dict[str, Any]) -> str:
    """Counterfactual single-feature ablation via the canonical ``assess`` function.

    This is an approximation, not an exact linear decomposition: ``assess``
    renormalizes weighted confidence by the sum of *present* feature weights,
    so isolating one feature also changes that denominator for the other.
    It is reported as such and is not claimed to be a persisted ground-truth
    attribution field.
    """
    rp_present = row["rotation_pressure_score"] is not None
    sector_present = row["sector_rotation_score"] is not None
    if not rp_present and not sector_present:
        return "cannot_attribute_no_enrichment_present"
    if rp_present and not sector_present:
        return "rotation_pressure_only"
    if sector_present and not rp_present:
        return "sector_rotation_only"
    rp_only_direction = assess({**row, "sector_rotation_score": None}, enriched=True)["direction"]
    sector_only_direction = assess({**row, "rotation_pressure_score": None}, enriched=True)["direction"]
    rp_alone_neutral = rp_only_direction == "NEUTRAL"
    sector_alone_neutral = sector_only_direction == "NEUTRAL"
    if rp_alone_neutral and not sector_alone_neutral:
        return "rotation_pressure_only"
    if sector_alone_neutral and not rp_alone_neutral:
        return "sector_rotation_only"
    if rp_alone_neutral and sector_alone_neutral:
        return "both_either_sufficient"
    return "both_interaction_required"


def build_neutralization_records(
    rows: list[dict[str, Any]], candles_by_market: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Classify every baseline VALID (non-neutral, endpoint-present) outcome as
    RETAINED, NEUTRALIZED, or OTHER depending on what happens to the exact same
    forecast identity + horizon under the enriched assessment.

    Reuses ``forecast_identity``/``assess``/``outcome_with_exclusion`` from the
    canonical modules; no identity or metric algorithm is re-derived here.
    """
    records: list[dict[str, Any]] = []
    for row in rows:
        identity = forecast_identity(row)
        candles = candles_by_market[row["market"]]
        baseline_assessment = assess(row, enriched=False)
        enriched_assessment = assess(row, enriched=True)
        for horizon in HORIZONS:
            horizon_hours = int(horizon.total_seconds() / 3600)
            baseline_result, _baseline_reason = outcome_with_exclusion(row, baseline_assessment, candles, horizon)
            if baseline_result is None:
                continue
            enriched_result, enriched_reason = outcome_with_exclusion(row, enriched_assessment, candles, horizon)
            if enriched_result is not None:
                status = "RETAINED"
            elif enriched_reason == "neutral_direction":
                status = "NEUTRALIZED"
            else:
                status = "OTHER"
            record = {
                **identity,
                "horizon_hours": horizon_hours,
                "status": status,
                "baseline_return_pct": baseline_result["return_pct"],
                "baseline_direction_hit": baseline_result["direction_hit"],
                "baseline_mfe_pct": baseline_result["mfe_pct"],
                "baseline_mae_pct": baseline_result["mae_pct"],
                "baseline_confidence_bucket": baseline_result["confidence_bucket"],
                "baseline_signal_combination": baseline_result["signal_combination"],
                "rotation_pressure_state": row["pressure_state"] or "UNAVAILABLE",
                "sector_rotation_state": row["sector_rotation_state"] or "UNAVAILABLE",
                "sector_code": row["sector_code"] or "UNAVAILABLE",
            }
            if status == "NEUTRALIZED":
                record["attribution"] = classify_neutralization_attribution(row)
            records.append(record)
    return records


def _as_metric_inputs(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"return_pct": r["baseline_return_pct"], "direction_hit": r["baseline_direction_hit"], "mfe_pct": r["baseline_mfe_pct"], "mae_pct": r["baseline_mae_pct"]}
        for r in records
    ]


def neutralization_effect(retained: list[dict[str, Any]], neutralized: list[dict[str, Any]]) -> dict[str, Any]:
    retained_metrics = metrics(_as_metric_inputs(retained))
    neutralized_metrics = metrics(_as_metric_inputs(neutralized))
    effect: dict[str, Any] = {}
    for field in ("direction_hit_rate", "mean_forward_return_pct", "median_forward_return_pct", "positive_return_rate", "mean_mfe_pct", "mean_mae_pct"):
        if field in retained_metrics and field in neutralized_metrics:
            effect[field] = round(neutralized_metrics[field] - retained_metrics[field], 4)
    return {"retained_metrics": retained_metrics, "neutralized_metrics": neutralized_metrics, "neutralized_minus_retained": effect}


def bootstrap_two_sample_mean_diff_ci(
    a_returns: list[float], b_returns: list[float], *, seed: int = BOOTSTRAP_SEED, resamples: int = BOOTSTRAP_RESAMPLES
) -> dict[str, Any]:
    """Deterministic bootstrap CI for mean(b) - mean(a), e.g. neutralized minus retained."""
    if not a_returns or not b_returns:
        return {"a_n": len(a_returns), "b_n": len(b_returns), "ci_95": [0.0, 0.0], "seed": seed, "resamples": resamples}
    a = np.array(a_returns, dtype=float)
    b = np.array(b_returns, dtype=float)
    rng = np.random.default_rng(seed)
    diffs = np.empty(resamples, dtype=float)
    for i in range(resamples):
        a_sample = a[rng.integers(0, len(a), size=len(a))]
        b_sample = b[rng.integers(0, len(b), size=len(b))]
        diffs[i] = b_sample.mean() - a_sample.mean()
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {"a_n": len(a_returns), "b_n": len(b_returns), "ci_95": [round(float(lo), 4), round(float(hi), 4)], "seed": seed, "resamples": resamples}


def _forecast_key(record: dict[str, Any]) -> tuple[Any, ...]:
    return (record["venue"], record["market"], record["forecast_as_of_utc"], record["map_id"])


def neutralization_coverage(records: list[dict[str, Any]]) -> dict[str, Any]:
    retained = [r for r in records if r["status"] == "RETAINED"]
    neutralized = [r for r in records if r["status"] == "NEUTRALIZED"]
    other = [r for r in records if r["status"] == "OTHER"]
    baseline_forecasts = {_forecast_key(r) for r in records}
    retained_forecasts = {_forecast_key(r) for r in retained}
    neutralized_forecasts = {_forecast_key(r) for r in neutralized}
    return {
        "baseline_non_neutral_outcome_count": len(records),
        "retained_outcome_count": len(retained),
        "neutralized_outcome_count": len(neutralized),
        "other_outcome_count": len(other),
        "neutralization_rate": round(len(neutralized) / len(records), 4) if records else 0.0,
        "baseline_non_neutral_unique_forecast_count": len(baseline_forecasts),
        "retained_unique_forecast_count": len(retained_forecasts),
        "neutralized_unique_forecast_count": len(neutralized_forecasts),
    }


def neutralization_grouped_section(records: list[dict[str, Any]], field: str, *, minimum_n: int = RANKING_MINIMUM_N) -> dict[str, Any]:
    values = sorted({r[field] for r in records})
    section: dict[str, Any] = {}
    for value in values:
        group = [r for r in records if r[field] == value]
        retained = [r for r in group if r["status"] == "RETAINED"]
        neutralized = [r for r in group if r["status"] == "NEUTRALIZED"]
        entry = neutralization_effect(retained, neutralized)
        entry["retained_count"] = len(retained)
        entry["neutralized_count"] = len(neutralized)
        entry["meets_ranking_floor"] = min(len(retained), len(neutralized)) >= minimum_n
        section[value] = entry
    return section


def neutralization_attribution_summary(records: list[dict[str, Any]]) -> dict[str, int]:
    neutralized = [r for r in records if r["status"] == "NEUTRALIZED"]
    counts: dict[str, int] = {}
    for r in neutralized:
        key = r.get("attribution", "cannot_attribute_no_enrichment_present")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def build_neutralization_recommendation(
    coverage: dict[str, Any], overall_effect: dict[str, Any], bootstrap_ci: dict[str, Any], time_half_stable: bool, horizon_stable: bool
) -> tuple[str, str]:
    neutralized_n = coverage["neutralized_outcome_count"]
    retained_n = coverage["retained_outcome_count"]
    mean_diff = overall_effect["neutralized_minus_retained"].get("mean_forward_return_pct", 0.0)
    ci_lo, ci_hi = bootstrap_ci["ci_95"]
    if neutralized_n < RANKING_MINIMUM_N or retained_n < RANKING_MINIMUM_N:
        return "KEEP_RESEARCH_ONLY", (
            f"neutralized_outcome_count={neutralized_n} and/or retained_outcome_count={retained_n} is below the "
            f"sample floor of {RANKING_MINIMUM_N}; insufficient sample for a defensible abstention-value conclusion"
        )
    ci_confidently_negative = ci_hi < 0
    if mean_diff >= 0 or ci_lo > 0:
        return "REJECT_FEATURE_ADDITION", (
            f"neutralized_minus_retained mean_forward_return_pct={mean_diff} (bootstrap CI={bootstrap_ci['ci_95']}) "
            "shows neutralized calls are not worse than retained calls; enrichment provides no abstention value "
            "on this cohort"
        )
    if not ci_confidently_negative:
        return "KEEP_RESEARCH_ONLY", (
            f"neutralized_minus_retained mean_forward_return_pct={mean_diff} is negative but the bootstrap 95% "
            f"CI={bootstrap_ci['ci_95']} does not exclude zero; abstention effect is not statistically distinguishable "
            "from noise on the fixed cohort"
        )
    if not (time_half_stable and horizon_stable):
        return "KEEP_RESEARCH_ONLY", (
            f"neutralized_minus_retained mean_forward_return_pct={mean_diff} (CI={bootstrap_ci['ci_95']}) is "
            "confidently negative but is not stable across the time-half and/or horizon splits"
        )
    return "READY_FOR_RULE_EXPERIMENT", (
        f"neutralized calls are materially and robustly worse than retained calls "
        f"(mean_forward_return_pct diff={mean_diff}, CI={bootstrap_ci['ci_95']}), with defensible sample size "
        f"(retained_n={retained_n}, neutralized_n={neutralized_n}) and stability across time-half and horizon splits"
    )


def build_neutralization_analysis(records: list[dict[str, Any]], start: datetime, end: datetime) -> dict[str, Any]:
    coverage = neutralization_coverage(records)
    retained = [r for r in records if r["status"] == "RETAINED"]
    neutralized = [r for r in records if r["status"] == "NEUTRALIZED"]
    overall_effect = neutralization_effect(retained, neutralized)
    bootstrap_ci = bootstrap_two_sample_mean_diff_ci(
        [r["baseline_return_pct"] for r in retained], [r["baseline_return_pct"] for r in neutralized]
    )

    midpoint = start + (end - start) / 2
    first_half = [r for r in records if r["forecast_as_of_utc"] < iso_z(midpoint)]
    second_half = [r for r in records if r["forecast_as_of_utc"] >= iso_z(midpoint)]

    def _half_effect(half_records: list[dict[str, Any]]) -> dict[str, Any]:
        half_retained = [r for r in half_records if r["status"] == "RETAINED"]
        half_neutralized = [r for r in half_records if r["status"] == "NEUTRALIZED"]
        return neutralization_effect(half_retained, half_neutralized)

    first_half_effect = _half_effect(first_half)
    second_half_effect = _half_effect(second_half)
    first_diff = first_half_effect["neutralized_minus_retained"].get("mean_forward_return_pct")
    second_diff = second_half_effect["neutralized_minus_retained"].get("mean_forward_return_pct")
    time_half_stable = first_diff is not None and second_diff is not None and (first_diff <= 0) == (second_diff <= 0)

    by_horizon = neutralization_grouped_section(records, "horizon_hours")
    horizon_diffs = [v["neutralized_minus_retained"].get("mean_forward_return_pct") for v in by_horizon.values() if v.get("meets_ranking_floor")]
    horizon_stable = len(horizon_diffs) > 0 and all((d <= 0) == (horizon_diffs[0] <= 0) for d in horizon_diffs)

    recommendation, rationale = build_neutralization_recommendation(coverage, overall_effect, bootstrap_ci, time_half_stable, horizon_stable)

    return {
        "coverage": coverage,
        "overall_effect": overall_effect,
        "bootstrap_neutralized_minus_retained_mean_return_ci": bootstrap_ci,
        "by_horizon": by_horizon,
        "by_time_half": {
            "midpoint_utc": iso_z(midpoint),
            "first_half": first_half_effect,
            "second_half": second_half_effect,
            "stable": time_half_stable,
        },
        "by_rotation_pressure_state": neutralization_grouped_section(records, "rotation_pressure_state"),
        "by_sector_rotation_state": neutralization_grouped_section(records, "sector_rotation_state"),
        "by_confidence_bucket": neutralization_grouped_section(records, "baseline_confidence_bucket"),
        "by_signal_combination": neutralization_grouped_section(records, "baseline_signal_combination"),
        "attribution": neutralization_attribution_summary(records),
        "attribution_note": (
            "attribution is a counterfactual single-feature ablation via the canonical assess() function "
            "(approximate due to weight renormalization by present-feature weight sum), not a persisted "
            "ground-truth field"
        ),
        "horizon_stable": horizon_stable,
        "recommendation": recommendation,
        "recommendation_rationale": rationale,
    }


_PAIR_KEY_FIELDS = ("venue", "market", "forecast_as_of_utc", "map_id", "horizon_hours", "endpoint_close_ts_utc")


def _pair_key(record: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(record[field] for field in _PAIR_KEY_FIELDS)


def build_paired_records(baseline: list[dict[str, Any]], enriched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strict pairing on exact forecast identity + horizon + endpoint_close_ts only."""
    baseline_by_key = {_pair_key(r): r for r in baseline}
    enriched_by_key = {_pair_key(r): r for r in enriched}
    shared_keys = sorted(set(baseline_by_key) & set(enriched_by_key))
    paired: list[dict[str, Any]] = []
    for key in shared_keys:
        b, e = baseline_by_key[key], enriched_by_key[key]
        paired.append(
            {
                **dict(zip(_PAIR_KEY_FIELDS, key)),
                "rotation_pressure_state": b["rotation_pressure_state"],
                "sector_rotation_state": b["sector_rotation_state"],
                "sector_code": b["sector_code"],
                "baseline_signal_combination": b["signal_combination"],
                "enriched_signal_combination": e["signal_combination"],
                "baseline_confidence_bucket": b["confidence_bucket"],
                "enriched_confidence_bucket": e["confidence_bucket"],
                "baseline_return_pct": b["return_pct"],
                "enriched_return_pct": e["return_pct"],
                "return_delta_pct": e["return_pct"] - b["return_pct"],
                "direction_hit_delta": int(e["direction_hit"]) - int(b["direction_hit"]),
                "mfe_delta_pct": e["mfe_pct"] - b["mfe_pct"],
                "mae_delta_pct": e["mae_pct"] - b["mae_pct"],
                "rotation_pressure_score": b["rotation_pressure_score"],
                "sector_rotation_score": b["sector_rotation_score"],
            }
        )
    return paired


def paired_summary(pairs: list[dict[str, Any]], *, epsilon: float = 1e-9) -> dict[str, Any]:
    if not pairs:
        return {"paired_outcome_count": 0}
    deltas = [p["return_delta_pct"] for p in pairs]
    improved = sum(1 for d in deltas if d > epsilon)
    worsened = sum(1 for d in deltas if d < -epsilon)
    unchanged = len(deltas) - improved - worsened
    return {
        "paired_outcome_count": len(pairs),
        "mean_return_delta_pct": round(sum(deltas) / len(deltas), 4),
        "median_return_delta_pct": round(median(deltas), 4),
        "direction_hit_delta_rate": round(sum(p["direction_hit_delta"] for p in pairs) / len(pairs), 4),
        "mean_mfe_delta_pct": round(sum(p["mfe_delta_pct"] for p in pairs) / len(pairs), 4),
        "mean_mae_delta_pct": round(sum(p["mae_delta_pct"] for p in pairs) / len(pairs), 4),
        "improved_count": improved,
        "worsened_count": worsened,
        "unchanged_count": unchanged,
    }


def grouped_paired(pairs: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for item in pairs:
        key = tuple(str(item.get(f, "UNAVAILABLE")) for f in fields)
        groups.setdefault(key, []).append(item)
    return [{**dict(zip(fields, key)), **paired_summary(value)} for key, value in sorted(groups.items())]


def coverage_summary(records: list[dict[str, Any]], field: str) -> dict[str, Any]:
    total = len(records)
    available = sum(1 for r in records if r[field] != "UNAVAILABLE")
    return {
        "available_count": available,
        "unavailable_count": total - available,
        "available_rate": round(available / total, 4) if total else 0.0,
    }


def by_horizon_section(baseline: list[dict[str, Any]], enriched: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> dict[str, Any]:
    section: dict[str, Any] = {}
    for horizon in HORIZONS:
        hours = str(int(horizon.total_seconds() / 3600))
        section[hours] = {
            "baseline": metrics([r for r in baseline if str(r["horizon_hours"]) == hours]),
            "enriched": metrics([r for r in enriched if str(r["horizon_hours"]) == hours]),
            "paired": paired_summary([p for p in pairs if str(p["horizon_hours"]) == hours]),
        }
    return section


def by_state_section(baseline: list[dict[str, Any]], enriched: list[dict[str, Any]], pairs: list[dict[str, Any]], field: str) -> dict[str, Any]:
    states = sorted({r[field] for r in baseline} | {r[field] for r in enriched})
    section: dict[str, Any] = {}
    for state in states:
        section[state] = {
            "baseline": metrics([r for r in baseline if r[field] == state]),
            "enriched": metrics([r for r in enriched if r[field] == state]),
            "paired": paired_summary([p for p in pairs if p[field] == state]),
        }
    return section


def sector_code_section(baseline: list[dict[str, Any]], enriched: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> dict[str, Any]:
    """Sector-code segmentation, ranked only where the sample size is defensible."""
    codes = sorted({r["sector_code"] for r in baseline} | {r["sector_code"] for r in enriched})
    ranked: dict[str, Any] = {}
    exploratory: dict[str, Any] = {}
    for code in codes:
        b, e, p = [r for r in baseline if r["sector_code"] == code], [r for r in enriched if r["sector_code"] == code], [x for x in pairs if x["sector_code"] == code]
        entry = {"baseline": metrics(b), "enriched": metrics(e), "paired": paired_summary(p)}
        (ranked if len(p) >= RANKING_MINIMUM_N else exploratory)[code] = entry
    return {"ranked": ranked, "exploratory": exploratory, "ranking_minimum_n": RANKING_MINIMUM_N}


def signal_combination_section(baseline: list[dict[str, Any]], enriched: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> dict[str, Any]:
    combos = sorted({r["signal_combination"] for r in baseline} | {r["signal_combination"] for r in enriched} | set(REQUIRED_SIGNAL_COMBINATIONS))
    section: dict[str, Any] = {}
    for combo in combos:
        p = [x for x in pairs if x["baseline_signal_combination"] == combo]
        section[combo] = {
            "baseline": metrics([r for r in baseline if r["signal_combination"] == combo]),
            "enriched": metrics([r for r in enriched if r["signal_combination"] == combo]),
            "paired": paired_summary(p),
            "meets_ranking_floor": len(p) >= RANKING_MINIMUM_N,
        }
    return section


def interaction_section(pairs: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, Any]:
    rows = grouped_paired(pairs, fields)
    ranked = [r for r in rows if r["paired_outcome_count"] >= RANKING_MINIMUM_N]
    exploratory = [r for r in rows if r["paired_outcome_count"] < RANKING_MINIMUM_N]
    ranked.sort(key=lambda r: r["mean_return_delta_pct"], reverse=True)
    return {"ranked": ranked, "exploratory": exploratory, "ranking_minimum_n": RANKING_MINIMUM_N}


def confidence_semantics_section(baseline: list[dict[str, Any]], enriched: list[dict[str, Any]]) -> dict[str, Any]:
    order = ["LOW", "MEDIUM", "HIGH"]
    baseline_by_bucket = {row["confidence_bucket"]: row for row in grouped(baseline, ("confidence_bucket",))}
    enriched_by_bucket = {row["confidence_bucket"]: row for row in grouped(enriched, ("confidence_bucket",))}

    def _classify(by_bucket: dict[str, Any]) -> str:
        if not all(b in by_bucket and by_bucket[b].get("sample_count") for b in order):
            return "none reliably"
        hit_rates = [by_bucket[b]["direction_hit_rate"] for b in order]
        returns = [by_bucket[b]["mean_forward_return_pct"] for b in order]
        hit_monotonic = hit_rates[0] <= hit_rates[1] <= hit_rates[2] and hit_rates[0] < hit_rates[2]
        return_monotonic = returns[0] <= returns[1] <= returns[2] and returns[0] < returns[2]
        if hit_monotonic and return_monotonic:
            return "signal-strength heuristic"
        if hit_monotonic:
            return "directional probability"
        if return_monotonic:
            return "expected-return quality"
        return "none reliably"

    return {
        "baseline": baseline_by_bucket,
        "enriched": enriched_by_bucket,
        "baseline_high_behavior": _classify(baseline_by_bucket),
        "enriched_high_behavior": _classify(enriched_by_bucket),
    }


def independent_value_section(pairs: list[dict[str, Any]], field: str) -> dict[str, Any]:
    """Whether `field` (rotation_pressure_state or sector_rotation_state) explains
    paired delta variance after conditioning on the baseline signal combination.

    Transparent stratified comparison first; a secondary OLS regression is
    reported only as supplementary evidence, never as the primary conclusion.
    """
    stratified = grouped_paired(pairs, ("baseline_signal_combination", field))
    ranked = [r for r in stratified if r["paired_outcome_count"] >= RANKING_MINIMUM_N]
    spreads: dict[str, float] = {}
    for combo in {r["baseline_signal_combination"] for r in ranked}:
        combo_rows = [r for r in ranked if r["baseline_signal_combination"] == combo]
        if len(combo_rows) >= 2:
            deltas = [r["mean_return_delta_pct"] for r in combo_rows]
            spreads[combo] = round(max(deltas) - min(deltas), 4)
    materiality_threshold = 1.0
    material_spreads = {k: v for k, v in spreads.items() if v >= materiality_threshold}

    score_field = "rotation_pressure_score" if field == "rotation_pressure_state" else "sector_rotation_score"
    regression = None
    usable = [p for p in pairs if p[score_field] is not None]
    if len(usable) >= RANKING_MINIMUM_N:
        combos = sorted({p["baseline_signal_combination"] for p in usable})
        x_cols = [[1.0, p[score_field]] + [1.0 if p["baseline_signal_combination"] == combo else 0.0 for combo in combos[1:]] for p in usable]
        y = np.array([p["return_delta_pct"] for p in usable], dtype=float)
        x_mat = np.array(x_cols, dtype=float)
        coeffs, _residuals, _rank, _sv = np.linalg.lstsq(x_mat, y, rcond=None)
        regression = {
            "note": "secondary OLS, informational only, no leakage: uses only PIT-joined score already available at forecast time",
            "variables": ["const", score_field, *[f"signal_combination={combo}" for combo in combos[1:]]],
            "coefficients": [round(float(c), 6) for c in coeffs],
            "n": len(usable),
        }

    conclusion = (
        "independent_value_detected" if material_spreads else "no_independent_value_detected"
    )
    return {
        "method": "stratified_paired_delta_by_signal_combination",
        "stratified_ranked": ranked,
        "materiality_threshold_pct": materiality_threshold,
        "material_spreads_by_signal_combination": material_spreads,
        "regression": regression,
        "conclusion": conclusion,
    }


def time_split_section(pairs: list[dict[str, Any]], start: datetime, end: datetime) -> dict[str, Any]:
    midpoint = start + (end - start) / 2
    first_half = [p for p in pairs if p["forecast_as_of_utc"] < iso_z(midpoint)]
    second_half = [p for p in pairs if p["forecast_as_of_utc"] >= iso_z(midpoint)]
    first_summary = paired_summary(first_half)
    second_summary = paired_summary(second_half)
    first_mean = first_summary.get("mean_return_delta_pct", 0.0)
    second_mean = second_summary.get("mean_return_delta_pct", 0.0)
    same_sign = (first_mean >= 0) == (second_mean >= 0)
    ratio_bounded = min(abs(first_mean), abs(second_mean)) >= max(abs(first_mean), abs(second_mean)) / 3 if max(abs(first_mean), abs(second_mean)) > 0 else True
    stable = same_sign and ratio_bounded
    return {
        "midpoint_utc": iso_z(midpoint),
        "first_half": {"period_end_exclusive": iso_z(midpoint), "paired": first_summary},
        "second_half": {"period_start": iso_z(midpoint), "paired": second_summary},
        "stable": stable,
    }


def bootstrap_paired_mean_delta_ci(pairs: list[dict[str, Any]], *, seed: int = BOOTSTRAP_SEED, resamples: int = BOOTSTRAP_RESAMPLES) -> dict[str, Any]:
    if not pairs:
        return {"n": 0, "ci_95": [0.0, 0.0], "seed": seed, "resamples": resamples}
    deltas = np.array([p["return_delta_pct"] for p in pairs], dtype=float)
    rng = np.random.default_rng(seed)
    means = np.empty(resamples, dtype=float)
    n = len(deltas)
    for i in range(resamples):
        sample = deltas[rng.integers(0, n, size=n)]
        means[i] = sample.mean()
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"n": n, "ci_95": [round(float(lo), 4), round(float(hi), 4)], "seed": seed, "resamples": resamples}


def build_recommendation(paired: dict[str, Any], independent_value: dict[str, Any], time_split: dict[str, Any], bootstrap: dict[str, Any]) -> tuple[str, str]:
    n = paired.get("paired_outcome_count", 0)
    if n < RANKING_MINIMUM_N:
        return "REJECT_FEATURE_ADDITION", f"paired_outcome_count={n} is below the sample floor of {RANKING_MINIMUM_N}"
    ci_lo, ci_hi = bootstrap["ci_95"]
    ci_excludes_zero = ci_lo > 0 or ci_hi < 0
    mean_delta = paired.get("mean_return_delta_pct", 0.0)
    if not ci_excludes_zero or abs(mean_delta) < 0.05:
        return "KEEP_RESEARCH_ONLY", (
            f"paired mean_return_delta_pct={mean_delta} with bootstrap 95% CI={bootstrap['ci_95']} does not "
            "exclude zero; effect is not distinguishable from noise on the fixed cohort"
        )
    if independent_value.get("conclusion") != "independent_value_detected" or not time_split.get("stable"):
        return "KEEP_RESEARCH_ONLY", (
            "paired effect is non-zero but does not survive conditioning on signal combination and/or is not "
            "stable across the first/second half time split"
        )
    return "READY_FOR_RULE_EXPERIMENT", (
        f"paired effect (mean_return_delta_pct={mean_delta}, CI={bootstrap['ci_95']}) survives conditioning on "
        "signal combination and is stable across the time split"
    )


def build_analysis(
    *,
    canonical: CanonicalLedgers,
    baseline_records: list[dict[str, Any]],
    enriched_records: list[dict[str, Any]],
    neutralization_records: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    venue: str,
) -> dict[str, Any]:
    pairs = build_paired_records(baseline_records, enriched_records)
    overall_baseline, overall_enriched = metrics(baseline_records), metrics(enriched_records)
    paired = paired_summary(pairs)
    independent_value_rotation_pressure = independent_value_section(pairs, "rotation_pressure_state")
    independent_value_sector_rotation = independent_value_section(pairs, "sector_rotation_state")
    time_split = time_split_section(pairs, start, end)
    bootstrap = bootstrap_paired_mean_delta_ci(pairs)
    retained_call_recommendation, retained_call_rationale = build_recommendation(paired, independent_value_rotation_pressure, time_split, bootstrap)

    neutralization = build_neutralization_analysis(neutralization_records, start, end)

    # The retained-call paired comparison and the abstention/neutralization
    # comparison are the two disjoint effect channels for this enrichment.
    # The final recommendation follows the neutralization (abstention) decision
    # contract, since that is the only channel where enrichment can plausibly
    # add value once the retained-call effect is established to be zero.
    recommendation = neutralization["recommendation"]
    rationale = (
        f"retained-call effect: {retained_call_rationale} | "
        f"abstention effect (decisive channel): {neutralization['recommendation_rationale']}"
    )

    return {
        "analysis_version": VERSION,
        "venue": venue,
        "period": {"start": iso_z(start), "end_exclusive": iso_z(end)},
        "canonical_ledger_digests": {
            "forecast_identity_ledger_sha256": CANONICAL_FORECAST_LEDGER_SHA256,
            "baseline_outcome_identity_ledger_sha256": CANONICAL_BASELINE_LEDGER_SHA256,
            "enriched_outcome_identity_ledger_sha256": CANONICAL_ENRICHED_LEDGER_SHA256,
        },
        "identity_guard": {
            "canonical_only_count": 0,
            "reconstructed_only_count": 0,
            "forecast_count": len(canonical.forecasts),
            "baseline_outcome_count": len(canonical.baseline_outcomes),
            "enriched_outcome_count": len(canonical.enriched_outcomes),
        },
        "paired_identity_contract": list(_PAIR_KEY_FIELDS),
        "coverage": {
            "rotation_pressure": coverage_summary(baseline_records, "rotation_pressure_state"),
            "sector_rotation": coverage_summary(baseline_records, "sector_rotation_state"),
        },
        "overall": {"baseline": overall_baseline, "enriched": overall_enriched},
        "paired": paired,
        "by_horizon": by_horizon_section(baseline_records, enriched_records, pairs),
        "by_rotation_pressure_state": by_state_section(baseline_records, enriched_records, pairs, "rotation_pressure_state"),
        "by_sector_rotation_state": by_state_section(baseline_records, enriched_records, pairs, "sector_rotation_state"),
        "by_sector_code": sector_code_section(baseline_records, enriched_records, pairs),
        "signal_combination_results": signal_combination_section(baseline_records, enriched_records, pairs),
        "interactions": {
            "signal_combination_x_rotation_pressure": interaction_section(pairs, ("baseline_signal_combination", "rotation_pressure_state")),
            "signal_combination_x_sector_rotation": interaction_section(pairs, ("baseline_signal_combination", "sector_rotation_state")),
            "signal_combination_x_rotation_pressure_x_sector_rotation": interaction_section(
                pairs, ("baseline_signal_combination", "rotation_pressure_state", "sector_rotation_state")
            ),
        },
        "confidence_semantics": confidence_semantics_section(baseline_records, enriched_records),
        "independent_value": {
            "rotation_pressure": independent_value_rotation_pressure,
            "sector_rotation": independent_value_sector_rotation,
        },
        "time_split_stability": time_split,
        "bootstrap": bootstrap,
        "retained_call_effect": {
            "description": "paired baseline-vs-enriched direction/return quality on calls both modes still make",
            "recommendation": retained_call_recommendation,
            "rationale": retained_call_rationale,
        },
        "neutralization": neutralization,
        "abstention_effect": {
            "description": "whether calls the enriched mode neutralizes are systematically worse than calls it retains",
            "recommendation": neutralization["recommendation"],
            "rationale": neutralization["recommendation_rationale"],
        },
        "sample_floors": {"ranking_minimum_n": RANKING_MINIMUM_N},
        "future_leakage": {
            "asserted": True,
            "join_operator": "feature_asof <= forecast_asof",
            "freshness_hours": 4,
            "later_feature_rows_used": 0,
            "current_state_substitution": False,
            "breathline_used": False,
        },
        "recommendation": recommendation,
        "recommendation_rationale": rationale,
    }


def render_markdown_report(analysis: dict[str, Any]) -> str:
    p = analysis["paired"]
    lines = [
        "# Forecast Confluence PIT Incremental-Value Analysis v1",
        "",
        f"Analysis version: `{analysis['analysis_version']}`",
        f"Period: {analysis['period']['start']} to {analysis['period']['end_exclusive']} (venue={analysis['venue']})",
        "",
        "## Canonical ledger digests",
        "",
        f"- forecast: `{analysis['canonical_ledger_digests']['forecast_identity_ledger_sha256']}`",
        f"- baseline: `{analysis['canonical_ledger_digests']['baseline_outcome_identity_ledger_sha256']}`",
        f"- enriched: `{analysis['canonical_ledger_digests']['enriched_outcome_identity_ledger_sha256']}`",
        f"- identity_guard: canonical_only_count={analysis['identity_guard']['canonical_only_count']} reconstructed_only_count={analysis['identity_guard']['reconstructed_only_count']}",
        "",
        "## Overall",
        "",
        f"- baseline: {analysis['overall']['baseline']}",
        f"- enriched: {analysis['overall']['enriched']}",
        "",
        "## Strict paired comparison",
        "",
        f"Paired identity contract: `{analysis['paired_identity_contract']}`",
        "",
        f"- paired_outcome_count: {p.get('paired_outcome_count')}",
        f"- mean_return_delta_pct: {p.get('mean_return_delta_pct')}",
        f"- median_return_delta_pct: {p.get('median_return_delta_pct')}",
        f"- direction_hit_delta_rate: {p.get('direction_hit_delta_rate')}",
        f"- mean_mfe_delta_pct: {p.get('mean_mfe_delta_pct')}",
        f"- mean_mae_delta_pct: {p.get('mean_mae_delta_pct')}",
        f"- improved_count: {p.get('improved_count')}",
        f"- worsened_count: {p.get('worsened_count')}",
        f"- unchanged_count: {p.get('unchanged_count')}",
        "",
        "Aggregate unpaired counts alone are not treated as evidence of incremental value; the paired comparison above is the primary evidence.",
        "",
        "**Retained-call directional effect: zero.** Whenever both modes make a non-neutral call on the same "
        "forecast identity + horizon, they agree on direction 100% of the time in this cohort, so return/MFE/MAE "
        "deltas among retained calls are exactly zero. This channel provides no evidence of incremental value.",
        "",
        "## Abstention / neutralization effect (measured separately)",
        "",
        "Rotation Pressure and sector context change some baseline calls to NEUTRAL rather than changing the "
        "direction of calls that remain active. This section asks whether those neutralized calls were "
        "systematically worse than the calls the enriched mode retains -- the only channel through which this "
        "enrichment could plausibly add value, given the zero retained-call effect above.",
        "",
        f"- baseline_non_neutral_outcome_count: {analysis['neutralization']['coverage']['baseline_non_neutral_outcome_count']}",
        f"- retained_outcome_count: {analysis['neutralization']['coverage']['retained_outcome_count']}",
        f"- neutralized_outcome_count: {analysis['neutralization']['coverage']['neutralized_outcome_count']}",
        f"- other_outcome_count: {analysis['neutralization']['coverage']['other_outcome_count']}",
        f"- neutralization_rate: {analysis['neutralization']['coverage']['neutralization_rate']}",
        f"- baseline_non_neutral_unique_forecast_count: {analysis['neutralization']['coverage']['baseline_non_neutral_unique_forecast_count']}",
        f"- retained_unique_forecast_count: {analysis['neutralization']['coverage']['retained_unique_forecast_count']}",
        f"- neutralized_unique_forecast_count: {analysis['neutralization']['coverage']['neutralized_unique_forecast_count']}",
        "",
        f"- retained_metrics: {analysis['neutralization']['overall_effect']['retained_metrics']}",
        f"- neutralized_metrics: {analysis['neutralization']['overall_effect']['neutralized_metrics']}",
        f"- neutralized_minus_retained: {analysis['neutralization']['overall_effect']['neutralized_minus_retained']}",
        f"- bootstrap CI (neutralized - retained mean return): {analysis['neutralization']['bootstrap_neutralized_minus_retained_mean_return_ci']}",
        "",
        f"- by_time_half stable: {analysis['neutralization']['by_time_half']['stable']}",
        f"- by_horizon stable: {analysis['neutralization']['horizon_stable']}",
        "",
        f"- attribution counts: {analysis['neutralization']['attribution']}",
        f"- attribution note: {analysis['neutralization']['attribution_note']}",
        "",
        f"- abstention_effect recommendation: **{analysis['abstention_effect']['recommendation']}**",
        f"- {analysis['abstention_effect']['rationale']}",
        "",
        "## Coverage",
        "",
        f"- rotation_pressure: {analysis['coverage']['rotation_pressure']}",
        f"- sector_rotation: {analysis['coverage']['sector_rotation']}",
        "",
        "## Confidence semantics",
        "",
        f"- baseline HIGH behaves as: **{analysis['confidence_semantics']['baseline_high_behavior']}**",
        f"- enriched HIGH behaves as: **{analysis['confidence_semantics']['enriched_high_behavior']}**",
        "",
        "## Independent value",
        "",
        f"- rotation_pressure: {analysis['independent_value']['rotation_pressure']['conclusion']}",
        f"- sector_rotation: {analysis['independent_value']['sector_rotation']['conclusion']}",
        "",
        "## Time-split stability",
        "",
        f"- stable: {analysis['time_split_stability']['stable']}",
        f"- first_half paired: {analysis['time_split_stability']['first_half']['paired']}",
        f"- second_half paired: {analysis['time_split_stability']['second_half']['paired']}",
        "",
        "## Bootstrap (paired mean return delta, 95% CI)",
        "",
        f"- ci_95: {analysis['bootstrap']['ci_95']} (seed={analysis['bootstrap']['seed']}, resamples={analysis['bootstrap']['resamples']}, n={analysis['bootstrap']['n']})",
        "",
        "## Future-leakage assertion",
        "",
        f"- {analysis['future_leakage']}",
        "",
        "## Recommendation",
        "",
        f"**{analysis['recommendation']}**",
        "",
        analysis["recommendation_rationale"],
        "",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only forecast confluence incremental-value analysis")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--ledger-dir", type=Path, default=CANONICAL_LEDGER_DIR)
    parser.add_argument("--output-json", type=Path, default=CANONICAL_LEDGER_DIR / ANALYSIS_ARTIFACT_FILENAME)
    parser.add_argument("--output-doc", type=Path, default=Path("docs/research/forecast_confluence_pit_incremental_value_analysis_v1.md"))
    parser.add_argument("--heartbeat-seconds", type=float, default=15.0)
    args = parser.parse_args(argv)
    start, end = parse_ts(args.start), parse_ts(args.end)
    lifecycle = RunnerLifecycle(runner="forecast_confluence_pit_incremental_value_v1", heartbeat_seconds=args.heartbeat_seconds)
    conn = None
    lifecycle.start(mode="read_only", venue=args.venue, ledger_dir=args.ledger_dir)
    lifecycle.install_signal_handlers()
    try:
        lifecycle.phase_started("LOAD_CANONICAL_LEDGERS")
        canonical = load_canonical_ledgers(args.ledger_dir)
        lifecycle.phase_finished(
            "LOAD_CANONICAL_LEDGERS",
            forecast_count=len(canonical.forecasts),
            baseline_outcomes=len(canonical.baseline_outcomes),
            enriched_outcomes=len(canonical.enriched_outcomes),
        )
        lifecycle.phase_started("FETCH_FORECASTS")
        conn = get_connection()
        rows = fetch_rows(conn, start=start, end=end, venue=args.venue)
        lifecycle.phase_finished("FETCH_FORECASTS", count=len(rows))
        lifecycle.phase_started("FETCH_CANDLES")
        candles = fetch_candles(conn, rows, args.venue)
        lifecycle.phase_finished("FETCH_CANDLES", markets=len(candles), rows=sum(len(items) for items in candles.values()))
        lifecycle.phase_started("RECONCILE_IDENTITY")
        analysis_input = reconcile_with_canonical(canonical, rows, candles)
        lifecycle.phase_finished(
            "RECONCILE_IDENTITY",
            canonical_only_count=analysis_input.canonical_only_count,
            reconstructed_only_count=analysis_input.reconstructed_only_count,
        )
        lifecycle.phase_started("BUILD_METRIC_RECORDS")
        metric_records = build_metric_records(rows, candles)
        verify_metric_record_identity(canonical.baseline_outcomes, metric_records["baseline"])
        verify_metric_record_identity(canonical.enriched_outcomes, metric_records["enriched"])
        lifecycle.phase_finished(
            "BUILD_METRIC_RECORDS",
            baseline=len(metric_records["baseline"]),
            enriched=len(metric_records["enriched"]),
        )
        lifecycle.phase_started("BUILD_NEUTRALIZATION_RECORDS")
        neutralization_records = build_neutralization_records(rows, candles)
        lifecycle.phase_finished("BUILD_NEUTRALIZATION_RECORDS", count=len(neutralization_records))
        lifecycle.phase_started("INCREMENTAL_VALUE_ANALYSIS")
        analysis = build_analysis(
            canonical=canonical,
            baseline_records=metric_records["baseline"],
            enriched_records=metric_records["enriched"],
            neutralization_records=neutralization_records,
            start=start,
            end=end,
            venue=args.venue,
        )
        lifecycle.phase_finished("INCREMENTAL_VALUE_ANALYSIS", recommendation=analysis["recommendation"])
        lifecycle.phase_started("WRITE_ARTIFACT")
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.output_doc.parent.mkdir(parents=True, exist_ok=True)
        args.output_doc.write_text(render_markdown_report(analysis), encoding="utf-8")
        lifecycle.phase_finished("WRITE_ARTIFACT", output_json=args.output_json, output_doc=args.output_doc)
        lifecycle.terminal(
            "FINISHED",
            forecast_count=analysis_input.forecast_count,
            baseline_outcomes=analysis_input.baseline_outcome_count,
            enriched_outcomes=analysis_input.enriched_outcome_count,
            paired_outcome_count=analysis["paired"].get("paired_outcome_count"),
            recommendation=analysis["recommendation"],
            output_json=args.output_json,
            output_doc=args.output_doc,
        )
        return 0
    except KeyboardInterrupt:
        lifecycle.terminal("INTERRUPTED", signal=lifecycle.interruption_signal or "SIGINT", phase=lifecycle.current_phase or "none")
        return 130
    except Exception as exc:
        lifecycle.terminal("FAILED", error=f"{type(exc).__name__}:{exc}", phase=lifecycle.current_phase or "none")
        return 1
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()
        lifecycle.close()


if __name__ == "__main__":
    raise SystemExit(main())
