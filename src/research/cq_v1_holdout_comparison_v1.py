from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import mean
from typing import Any, Iterable, Mapping

REQUIRED_HORIZONS = ("1h", "4h", "24h")
REQUIRED_CANDIDATES = (
    "cq_v1_mrp_balanced_v1",
    "cq_v1_mrp_anchor_v1",
)


@dataclass(frozen=True)
class CorrelationSummary:
    sample_count: int
    pearson: float | None
    spearman: float | None


def _finite(value: Any, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}:NON_NUMERIC") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field}:NON_FINITE")
    return number


def _rankdata(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        value = values[order[cursor]]
        while end < len(order) and values[order[end]] == value:
            end += 1
        average_rank = ((cursor + 1) + end) / 2.0
        for position in range(cursor, end):
            ranks[order[position]] = average_rank
        cursor = end
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys):
        raise ValueError("correlation vectors differ in length")
    if len(xs) < 2:
        return None
    x_mean = mean(xs)
    y_mean = mean(ys)
    x_delta = [value - x_mean for value in xs]
    y_delta = [value - y_mean for value in ys]
    numerator = sum(x * y for x, y in zip(x_delta, y_delta, strict=True))
    x_ss = sum(value * value for value in x_delta)
    y_ss = sum(value * value for value in y_delta)
    if x_ss == 0.0 or y_ss == 0.0:
        return None
    return numerator / math.sqrt(x_ss * y_ss)


def correlation(xs: list[float], ys: list[float]) -> CorrelationSummary:
    return CorrelationSummary(
        sample_count=len(xs),
        pearson=_pearson(xs, ys),
        spearman=_pearson(_rankdata(xs), _rankdata(ys)),
    )


def _bucket_rows(rows: list[dict[str, Any]], score_field: str, bucket_count: int) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: (_finite(row[score_field], field=score_field), int(row["shadow_id"])),
    )
    out: list[dict[str, Any]] = []
    n = len(ordered)
    for bucket_index in range(bucket_count):
        start = (bucket_index * n) // bucket_count
        end = ((bucket_index + 1) * n) // bucket_count
        bucket = ordered[start:end]
        if not bucket:
            continue
        out.append(
            {
                "bucket": bucket_index + 1,
                "sample_count": len(bucket),
                "score_min": min(_finite(row[score_field], field=score_field) for row in bucket),
                "score_max": max(_finite(row[score_field], field=score_field) for row in bucket),
                "mean_forward_return_pct": mean(
                    _finite(row["forward_return_pct"], field="forward_return_pct") for row in bucket
                ),
                "mean_mfe_pct": mean(_finite(row["mfe_pct"], field="mfe_pct") for row in bucket),
                "mean_mae_pct": mean(_finite(row["mae_pct"], field="mae_pct") for row in bucket),
            }
        )
    return out


def _identity_from_outcome(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(row["shadow_id"]),
        int(row["asset_id"]),
        str(row["venue"]),
        str(row["evidence_key"]),
        str(row["cq_model_version"]),
    )


def _identity_from_score(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(row["shadow_id"]),
        int(row["asset_id"]),
        str(row["venue"]),
        str(row["evidence_key"]),
        str(row["cq_model_version"]),
    )


def _validate_candidates(score_row: Mapping[str, Any]) -> None:
    candidates = score_row.get("candidates")
    if not isinstance(candidates, Mapping):
        raise ValueError(f"shadow_id={score_row.get('shadow_id')}:CANDIDATES_MISSING")
    missing = [candidate for candidate in REQUIRED_CANDIDATES if candidate not in candidates]
    if missing:
        raise ValueError(
            f"shadow_id={score_row.get('shadow_id')}:CANDIDATES_MISSING:{','.join(missing)}"
        )


def join_artifacts(
    outcome_rows: Iterable[Mapping[str, Any]],
    score_rows: Iterable[Mapping[str, Any]],
    *,
    required_asof: str,
) -> list[dict[str, Any]]:
    scores_by_shadow: dict[int, Mapping[str, Any]] = {}
    for score in score_rows:
        shadow_id = int(score["shadow_id"])
        if shadow_id in scores_by_shadow:
            raise ValueError(f"shadow_id={shadow_id}:DUPLICATE_SCORE_IDENTITY")
        _validate_candidates(score)
        scores_by_shadow[shadow_id] = score

    seen_outcomes: set[tuple[int, str]] = set()
    joined: list[dict[str, Any]] = []
    for outcome in outcome_rows:
        shadow_id = int(outcome["shadow_id"])
        horizon = str(outcome["horizon"])
        key = (shadow_id, horizon)
        if key in seen_outcomes:
            raise ValueError(f"shadow_id={shadow_id}:horizon={horizon}:DUPLICATE_OUTCOME")
        seen_outcomes.add(key)
        if horizon not in REQUIRED_HORIZONS:
            raise ValueError(f"shadow_id={shadow_id}:UNEXPECTED_HORIZON:{horizon}")
        if str(outcome.get("status")) != "COMPLETE":
            continue
        if str(outcome.get("observation_asof_ts_utc")) != required_asof:
            raise ValueError(f"shadow_id={shadow_id}:ASOF_MISMATCH")
        score = scores_by_shadow.get(shadow_id)
        if score is None:
            raise ValueError(f"shadow_id={shadow_id}:SCORE_ROW_MISSING")
        if _identity_from_outcome(outcome) != _identity_from_score(score):
            raise ValueError(f"shadow_id={shadow_id}:IDENTITY_MISMATCH")
        score_asof = str(score.get("asof_ts_utc"))
        if score_asof != required_asof:
            raise ValueError(f"shadow_id={shadow_id}:SCORE_ASOF_MISMATCH")

        row = dict(outcome)
        row["cq_v0"] = _finite(score.get("cq_v0"), field="cq_v0")
        ppp = outcome.get("ppp_pct")
        row["ppp_pct"] = None if ppp is None else _finite(ppp, field="ppp_pct")
        for field in ("trade_quality_score", "selection_score", "entry_strength_v0"):
            value = outcome.get(field)
            row[field] = None if value is None else _finite(value, field=field)
        for candidate_id in REQUIRED_CANDIDATES:
            payload = score["candidates"][candidate_id]
            state = str(payload.get("state"))
            candidate_score = payload.get("score")
            row[candidate_id] = (
                _finite(candidate_score, field=candidate_id)
                if state == "AVAILABLE" and candidate_score is not None
                else None
            )
            row[f"{candidate_id}_state"] = state
            row[f"entry_strength_{candidate_id}"] = (
                row["ppp_pct"] * row[candidate_id]
                if row["ppp_pct"] is not None and row[candidate_id] is not None
                else None
            )
        for field in ("forward_return_pct", "mfe_pct", "mae_pct"):
            row[field] = _finite(row.get(field), field=field)
        joined.append(row)

    return joined


def _common_rows(rows: list[dict[str, Any]], score_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    return [row for row in rows if all(row.get(field) is not None for field in score_fields)]


def _metric_summary(rows: list[dict[str, Any]], score_field: str, bucket_count: int) -> dict[str, Any]:
    xs = [_finite(row[score_field], field=score_field) for row in rows]
    ys = [_finite(row["forward_return_pct"], field="forward_return_pct") for row in rows]
    corr = correlation(xs, ys)
    return {
        "sample_count": corr.sample_count,
        "pearson_forward_return": corr.pearson,
        "spearman_forward_return": corr.spearman,
        "buckets": _bucket_rows(rows, score_field, bucket_count),
    }


def evaluate(joined_rows: list[dict[str, Any]], *, bucket_count: int = 5) -> dict[str, Any]:
    by_horizon: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in joined_rows:
        by_horizon[str(row["horizon"])].append(row)

    candidate_comparisons: dict[str, Any] = {}
    baseline_fields = ("trade_quality_score", "selection_score", "cq_v0")
    for candidate_id in REQUIRED_CANDIDATES:
        candidate_comparisons[candidate_id] = {}
        comparison_fields = baseline_fields + (candidate_id,)
        for horizon in REQUIRED_HORIZONS:
            rows = _common_rows(by_horizon.get(horizon, []), comparison_fields)
            candidate_comparisons[candidate_id][horizon] = {
                "eligible_sample_count": len(rows),
                "metrics": {
                    field: _metric_summary(rows, field, bucket_count)
                    for field in comparison_fields
                },
            }

    ppp_cohorts: dict[str, Any] = {}
    ppp_kinds = sorted(
        {
            str(row["ppp_kind"])
            for row in joined_rows
            if row.get("ppp_pct") is not None and row.get("ppp_kind") is not None
        }
    )
    for ppp_kind in ppp_kinds:
        ppp_cohorts[ppp_kind] = {}
        for candidate_id in REQUIRED_CANDIDATES:
            ppp_cohorts[ppp_kind][candidate_id] = {}
            fields = (
                "ppp_pct",
                "entry_strength_v0",
                candidate_id,
                f"entry_strength_{candidate_id}",
            )
            for horizon in REQUIRED_HORIZONS:
                rows = [
                    row
                    for row in by_horizon.get(horizon, [])
                    if str(row.get("ppp_kind")) == ppp_kind
                ]
                rows = _common_rows(rows, fields)
                ppp_cohorts[ppp_kind][candidate_id][horizon] = {
                    "eligible_sample_count": len(rows),
                    "metrics": {field: _metric_summary(rows, field, bucket_count) for field in fields},
                }

    return {
        "joined_complete_rows": len(joined_rows),
        "complete_observation_count": len({int(row["shadow_id"]) for row in joined_rows}),
        "horizon_counts": {horizon: len(by_horizon.get(horizon, [])) for horizon in REQUIRED_HORIZONS},
        "candidate_comparisons": candidate_comparisons,
        "ppp_cohorts": ppp_cohorts,
    }


def promotion_verdict(
    evaluation: Mapping[str, Any],
    *,
    minimum_candidate_sample: int,
    material_delta: float,
) -> tuple[str, dict[str, Any]]:
    candidate_results: dict[str, Any] = {}
    for candidate_id in REQUIRED_CANDIDATES:
        improved_vs_both = 0
        improved_vs_cq0 = 0
        materially_worse_vs_cq0 = 0
        all_horizons_eligible = True
        top_bucket_nonnegative = True
        horizon_details: dict[str, Any] = {}
        for horizon in REQUIRED_HORIZONS:
            block = evaluation["candidate_comparisons"][candidate_id][horizon]
            sample_count = int(block["eligible_sample_count"])
            if sample_count < minimum_candidate_sample:
                all_horizons_eligible = False
            metrics = block["metrics"]
            candidate_s = metrics[candidate_id]["spearman_forward_return"]
            cq0_s = metrics["cq_v0"]["spearman_forward_return"]
            selection_s = metrics["selection_score"]["spearman_forward_return"]
            if candidate_s is None or cq0_s is None or selection_s is None:
                all_horizons_eligible = False
                delta_cq0 = None
                delta_selection = None
            else:
                delta_cq0 = candidate_s - cq0_s
                delta_selection = candidate_s - selection_s
                if delta_cq0 > 0:
                    improved_vs_cq0 += 1
                if delta_cq0 >= material_delta and delta_selection >= material_delta:
                    improved_vs_both += 1
                if delta_cq0 <= -material_delta:
                    materially_worse_vs_cq0 += 1
            buckets = metrics[candidate_id]["buckets"]
            top_bucket_return = buckets[-1]["mean_forward_return_pct"] if buckets else None
            if top_bucket_return is None or top_bucket_return < 0:
                top_bucket_nonnegative = False
            horizon_details[horizon] = {
                "sample_count": sample_count,
                "spearman_delta_vs_cq_v0": delta_cq0,
                "spearman_delta_vs_selection": delta_selection,
                "top_bucket_mean_forward_return_pct": top_bucket_return,
            }
        candidate_results[candidate_id] = {
            "all_horizons_eligible": all_horizons_eligible,
            "improved_vs_both_horizons": improved_vs_both,
            "improved_vs_cq_v0_horizons": improved_vs_cq0,
            "materially_worse_vs_cq_v0_horizons": materially_worse_vs_cq0,
            "top_bucket_nonnegative_all_horizons": top_bucket_nonnegative,
            "horizons": horizon_details,
        }

    if any(
        result["all_horizons_eligible"]
        and result["improved_vs_both_horizons"] == len(REQUIRED_HORIZONS)
        and result["top_bucket_nonnegative_all_horizons"]
        for result in candidate_results.values()
    ):
        verdict = "RANKING_PROMOTION_CANDIDATE"
    elif any(
        result["all_horizons_eligible"] and result["improved_vs_cq_v0_horizons"] >= 2
        for result in candidate_results.values()
    ):
        verdict = "CQ_V1_SHADOW_ACCEPTED"
    elif all(
        result["all_horizons_eligible"] and result["materially_worse_vs_cq_v0_horizons"] >= 2
        for result in candidate_results.values()
    ):
        verdict = "REJECT"
    else:
        verdict = "RESEARCH_FURTHER"
    return verdict, candidate_results
