"""Frozen CQ v1 discovery+validation evaluator for Issue #684.

Evaluates already-preregistered CQ v0 / CQ v1 candidate definitions against
the frozen temporal forward-outcome artifact for the discovery and
validation splits only. Holdout analytical outcome values (forward_return_pct,
mfe_pct, mae_pct on split=="holdout" rows) are never read by any metric,
bucket, or pairwise function in this module -- see `filter_safe_rows`.

This module does not retune candidate weights, does not touch the database,
and does not write operational runtime state.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from math import sqrt
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Mapping

from src.research.cq_v1_model_candidate_v1 import normalize_cq_v0, normalize_mrp_market_score

EVALUATOR_VERSION = "1.0.0"
ISSUE = 684

PINNED_POPULATION_SHA256 = "61bab264b2921b93a25a22ec0d12cbc031ad0ef234fa989b2ea43c894bc263b4"
PINNED_POPULATION_ROW_COUNT = 19520
PINNED_POPULATION_UNIQUE_ASOFS = 45
PINNED_POPULATION_UNIQUE_ASSETS = 445

PINNED_OUTCOMES_SHA256 = "2c1b3b9e17e6e06eec3831ac47b48bfd91944730cf9c6e75929979a795727500"
PINNED_OUTCOMES_ROW_COUNT = 58560

HORIZONS = ("1h", "4h", "24h")
OUTCOME_METRICS = ("forward_return_pct", "mfe_pct", "mae_pct")
OUTCOME_STATUSES = (
    "COMPLETE",
    "INSUFFICIENT_BASE_PRICE",
    "INSUFFICIENT_HORIZON_COVERAGE",
    "INSUFFICIENT_FUTURE_CANDLES",
)

ALL_SPLITS = ("discovery", "validation", "holdout")
PINNED_SPLIT_OUTCOME_ROW_COUNTS = {
    "discovery": 34911,
    "validation": 11637,
    "holdout": 12012,
}

# CLI-facing evaluation scopes. "holdout" and "all" are intentionally absent:
# this evaluator implementation does not enable holdout analytics.
ALLOWED_EVAL_SPLITS = ("discovery", "validation", "discovery_validation")

CQ_V0 = "cq_v0"
CQ_V1_BALANCED = "cq_v1_balanced"
CQ_V1_ANCHOR = "cq_v1_anchor"
TRADE_QUALITY_SCORE = "trade_quality_score"
SELECTION_SCORE = "selection_score"

BASELINE_SCORES = (
    TRADE_QUALITY_SCORE,
    SELECTION_SCORE,
    CQ_V0,
    CQ_V1_BALANCED,
    CQ_V1_ANCHOR,
)

# Frozen candidate formulas (issue #684 task contract):
#   cq_v1_balanced = 0.50 * cq_v0 + 0.50 * normalized_mrp_aggregate
#   cq_v1_anchor   = 0.75 * cq_v0 + 0.25 * normalized_mrp_aggregate
#   normalized_mrp_aggregate = (mrp_aggregate.market_score + 100) / 200
CQ_V1_BALANCED_CQ_V0_WEIGHT = Decimal("0.50")
CQ_V1_BALANCED_MRP_WEIGHT = Decimal("0.50")
CQ_V1_ANCHOR_CQ_V0_WEIGHT = Decimal("0.75")
CQ_V1_ANCHOR_MRP_WEIGHT = Decimal("0.25")
SCORE_QUANTUM = Decimal("0.000001")

PAIRWISE = (
    (CQ_V1_BALANCED, CQ_V0),
    (CQ_V1_ANCHOR, CQ_V0),
    (CQ_V1_BALANCED, TRADE_QUALITY_SCORE),
    (CQ_V1_ANCHOR, TRADE_QUALITY_SCORE),
    (CQ_V1_BALANCED, SELECTION_SCORE),
    (CQ_V1_ANCHOR, SELECTION_SCORE),
)

BUCKET_COUNT = 10  # deciles; see docstring on `_bucket_count_for`


def resolve_eval_splits(split_arg: str) -> tuple[str, ...]:
    if split_arg not in ALLOWED_EVAL_SPLITS:
        raise ValueError(
            f"unsupported --split {split_arg!r}; holdout evaluation is not implemented in this evaluator"
        )
    if split_arg == "discovery_validation":
        return ("discovery", "validation")
    return (split_arg,)


def _round6(value: Decimal) -> Decimal:
    return value.quantize(SCORE_QUANTUM)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("JSONL row must be an object")
        rows.append(row)
    return rows


def load_population(path: Path) -> list[dict[str, Any]]:
    actual_sha = _sha256_path(path)
    if actual_sha != PINNED_POPULATION_SHA256:
        raise ValueError(
            f"population SHA256 mismatch expected={PINNED_POPULATION_SHA256} actual={actual_sha}"
        )
    rows = load_jsonl(path)
    if len(rows) != PINNED_POPULATION_ROW_COUNT:
        raise ValueError(
            f"population row count mismatch expected={PINNED_POPULATION_ROW_COUNT} actual={len(rows)}"
        )
    ids = [str(row["observation_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate population observation_id")
    asofs = {str(row["asof_ts_utc"]) for row in rows}
    if len(asofs) != PINNED_POPULATION_UNIQUE_ASOFS:
        raise ValueError(
            f"population unique asof count mismatch expected={PINNED_POPULATION_UNIQUE_ASOFS} actual={len(asofs)}"
        )
    assets = {int(row["asset_id"]) for row in rows}
    if len(assets) != PINNED_POPULATION_UNIQUE_ASSETS:
        raise ValueError(
            f"population unique asset count mismatch expected={PINNED_POPULATION_UNIQUE_ASSETS} actual={len(assets)}"
        )
    unexpected_splits = {str(row["split"]) for row in rows} - set(ALL_SPLITS)
    if unexpected_splits:
        raise ValueError(f"unexpected population split names: {sorted(unexpected_splits)}")
    return rows


def load_outcomes(path: Path) -> list[dict[str, Any]]:
    actual_sha = _sha256_path(path)
    if actual_sha != PINNED_OUTCOMES_SHA256:
        raise ValueError(
            f"outcomes SHA256 mismatch expected={PINNED_OUTCOMES_SHA256} actual={actual_sha}"
        )
    rows = load_jsonl(path)
    if len(rows) != PINNED_OUTCOMES_ROW_COUNT:
        raise ValueError(
            f"outcomes row count mismatch expected={PINNED_OUTCOMES_ROW_COUNT} actual={len(rows)}"
        )
    ids = [str(row["outcome_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate outcome_id")
    horizons = {str(row["horizon"]) for row in rows}
    if horizons != set(HORIZONS):
        raise ValueError(f"outcomes must contain exactly horizons {HORIZONS}, found {sorted(horizons)}")
    unexpected_splits = {str(row["split"]) for row in rows} - set(ALL_SPLITS)
    if unexpected_splits:
        raise ValueError(f"unexpected outcome split names: {sorted(unexpected_splits)}")
    unexpected_statuses = {str(row["status"]) for row in rows} - set(OUTCOME_STATUSES)
    if unexpected_statuses:
        raise ValueError(f"unexpected outcome statuses: {sorted(unexpected_statuses)}")
    pair_keys = [(str(row["observation_id"]), str(row["horizon"])) for row in rows]
    if len(pair_keys) != len(set(pair_keys)):
        raise ValueError("duplicate (observation_id, horizon) outcome pair")
    split_counts: dict[str, int] = {}
    for row in rows:
        split_counts[str(row["split"])] = split_counts.get(str(row["split"]), 0) + 1
    for split_name, expected in PINNED_SPLIT_OUTCOME_ROW_COUNTS.items():
        actual = split_counts.get(split_name, 0)
        if actual != expected:
            raise ValueError(
                f"outcome split row count mismatch split={split_name} expected={expected} actual={actual}"
            )
    return rows


def validate_identity(population: list[dict[str, Any]], outcomes: list[dict[str, Any]]) -> None:
    """Cross-check population/outcome identity using only counts and IDs.

    This step reads outcome `split`, `horizon`, `status`, `observation_id`
    identity fields only. It never reads `forward_return_pct`, `mfe_pct`, or
    `mae_pct`, so it is safe to run before the holdout evaluation gate.
    """
    population_ids = {str(row["observation_id"]) for row in population}
    outcome_observation_ids = {str(row["observation_id"]) for row in outcomes}
    missing = outcome_observation_ids - population_ids
    if missing:
        raise ValueError(f"outcome rows reference unknown observation_id (sample): {sorted(missing)[:5]}")
    extra = population_ids - outcome_observation_ids
    if extra:
        raise ValueError(f"population observations missing all outcomes (sample): {sorted(extra)[:5]}")
    per_observation: dict[str, set[str]] = {}
    for row in outcomes:
        per_observation.setdefault(str(row["observation_id"]), set()).add(str(row["horizon"]))
    bad = [obs_id for obs_id, horizons in per_observation.items() if horizons != set(HORIZONS)]
    if bad:
        raise ValueError(f"observation missing exactly one outcome per horizon (sample): {sorted(bad)[:5]}")
    population_split_by_id = {str(row["observation_id"]): str(row["split"]) for row in population}
    mismatched = [
        row["observation_id"]
        for row in outcomes
        if population_split_by_id.get(str(row["observation_id"])) != str(row["split"])
    ]
    if mismatched:
        raise ValueError(f"population/outcome split mismatch (sample): {sorted(set(mismatched))[:5]}")


def filter_safe_rows(
    population: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    eval_splits: tuple[str, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return population/outcome rows restricted to `eval_splits`.

    Holdout rows are excluded entirely -- not merely masked -- so no
    downstream metric, bucket, or pairwise function ever receives a holdout
    analytical outcome value.
    """
    allowed = set(eval_splits)
    if not allowed.issubset({"discovery", "validation"}):
        raise ValueError("filter_safe_rows only supports discovery/validation splits")
    safe_population = [row for row in population if str(row["split"]) in allowed]
    safe_outcomes = [row for row in outcomes if str(row["split"]) in allowed]
    return safe_population, safe_outcomes


def _cq_v0_value(row: Mapping[str, Any]) -> Decimal | None:
    value = row.get("cq_v0")
    if value is None:
        return None
    try:
        return normalize_cq_v0(value)
    except ValueError:
        return None


def _normalized_mrp_aggregate(row: Mapping[str, Any]) -> Decimal | None:
    aggregate = row.get("mrp_aggregate")
    if not isinstance(aggregate, Mapping):
        return None
    market_score = aggregate.get("market_score")
    if market_score is None:
        return None
    try:
        return normalize_mrp_market_score(market_score)
    except ValueError:
        return None


def compute_candidate_scores(row: Mapping[str, Any]) -> dict[str, float | None]:
    """Compute frozen CQ v1 candidate scores for one population row.

    No imputation, no weight renormalization: if either input is
    unavailable/non-numeric, the candidate score is unavailable (None).
    """
    cq_v0 = _cq_v0_value(row)
    mrp = _normalized_mrp_aggregate(row)
    balanced: Decimal | None = None
    anchor: Decimal | None = None
    if cq_v0 is not None and mrp is not None:
        balanced = _round6(CQ_V1_BALANCED_CQ_V0_WEIGHT * cq_v0 + CQ_V1_BALANCED_MRP_WEIGHT * mrp)
        anchor = _round6(CQ_V1_ANCHOR_CQ_V0_WEIGHT * cq_v0 + CQ_V1_ANCHOR_MRP_WEIGHT * mrp)
    return {
        CQ_V1_BALANCED: None if balanced is None else float(balanced),
        CQ_V1_ANCHOR: None if anchor is None else float(anchor),
    }


def score_values(population_row: Mapping[str, Any]) -> dict[str, float | None]:
    values: dict[str, float | None] = {
        TRADE_QUALITY_SCORE: _number(population_row.get(TRADE_QUALITY_SCORE)),
        SELECTION_SCORE: _number(population_row.get(SELECTION_SCORE)),
        CQ_V0: _number(population_row.get(CQ_V0)),
    }
    values.update(compute_candidate_scores(population_row))
    return values


def pair_rows(
    safe_population: list[dict[str, Any]], safe_outcomes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    population_by_id = {str(row["observation_id"]): row for row in safe_population}
    paired: list[dict[str, Any]] = []
    for outcome in safe_outcomes:
        observation_id = str(outcome["observation_id"])
        population_row = population_by_id.get(observation_id)
        if population_row is None:
            raise ValueError(f"observation_id={observation_id}:SAFE_POPULATION_ROW_MISSING")
        scores = score_values(population_row)
        paired.append(
            {
                "observation_id": observation_id,
                "asset_id": int(outcome["asset_id"]),
                "split": str(outcome["split"]),
                "horizon": str(outcome["horizon"]),
                "status": str(outcome["status"]),
                "forward_return_pct": outcome.get("forward_return_pct"),
                "mfe_pct": outcome.get("mfe_pct"),
                "mae_pct": outcome.get("mae_pct"),
                "scores": scores,
            }
        )
    return paired


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mx, my = mean(xs), mean(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denom = sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
    if denom == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / denom


def _ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [0.0] * len(values)
    i = 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and ordered[j][1] == ordered[i][1]:
            j += 1
        avg_rank = ((i + 1) + j) / 2.0
        for k in range(i, j):
            ranks[ordered[k][0]] = avg_rank
        i = j
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    return _pearson(_ranks(xs), _ranks(ys))


def eligible_rows(rows: list[dict[str, Any]], score: str, outcome_metric: str) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row["status"] == "COMPLETE"
        and _number(row["scores"].get(score)) is not None
        and _number(row.get(outcome_metric)) is not None
    ]


def _bucket_count_for(n: int) -> int:
    """Deterministic decile scheme; shrinks to N buckets only when N < 10.

    No canonical bucket-count convention exists elsewhere in the repo for
    this evaluator's row volumes, so this evaluator freezes deciles as its
    own scheme (`BUCKET_COUNT = 10`). The shrink rule is a pure function of
    N applied identically to every score, so it never "silently" changes
    the comparison basis between models on the same eligible sample.
    """
    if n <= 0:
        return 0
    return min(BUCKET_COUNT, n)


def _stats(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "mean": None if not values else mean(values),
        "median": None if not values else median(values),
    }


def build_buckets(rows: list[dict[str, Any]], score: str) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (float(row["scores"][score]), str(row["observation_id"])))
    n = len(ordered)
    bucket_count = _bucket_count_for(n)
    buckets: list[dict[str, Any]] = []
    for bucket_index in range(bucket_count):
        bucket_rows = [
            row
            for rank, row in enumerate(ordered)
            if min(bucket_count - 1, (rank * bucket_count) // n) == bucket_index
        ]
        score_vals = [float(row["scores"][score]) for row in bucket_rows]
        buckets.append(
            {
                "bucket": bucket_index + 1,
                "n": len(bucket_rows),
                "score_min": min(score_vals) if score_vals else None,
                "score_max": max(score_vals) if score_vals else None,
                "score_mean": mean(score_vals) if score_vals else None,
                "forward_return_pct": _stats([float(row["forward_return_pct"]) for row in bucket_rows]),
                "mfe_pct": _stats([float(row["mfe_pct"]) for row in bucket_rows]),
                "mae_pct": _stats([float(row["mae_pct"]) for row in bucket_rows]),
            }
        )
    return buckets


def _top_bottom_spread(buckets: list[dict[str, Any]], outcome_metric: str) -> float | None:
    if not buckets:
        return None
    top = buckets[-1][outcome_metric]["mean"]
    bottom = buckets[0][outcome_metric]["mean"]
    if top is None or bottom is None:
        return None
    return top - bottom


def score_horizon_split_metrics(
    total_frozen: int,
    rows_in_scope: list[dict[str, Any]],
    score: str,
) -> dict[str, Any]:
    complete_rows = [row for row in rows_in_scope if row["status"] == "COMPLETE"]
    score_available = [row for row in rows_in_scope if _number(row["scores"].get(score)) is not None]
    result: dict[str, Any] = {
        "total_frozen_observations": total_frozen,
        "complete_outcome_count": len(complete_rows),
        "score_available_count": len(score_available),
        "coverage": {},
        "buckets": {},
    }
    for outcome_metric in OUTCOME_METRICS:
        eligible = eligible_rows(rows_in_scope, score, outcome_metric)
        xs = [float(row["scores"][score]) for row in eligible]
        ys = [float(row[outcome_metric]) for row in eligible]
        result["coverage"][outcome_metric] = {
            "jointly_eligible_count": len(eligible),
            "coverage_pct": 0.0 if total_frozen == 0 else round(100.0 * len(eligible) / total_frozen, 6),
            "pearson": _pearson(xs, ys),
            "spearman": _spearman(xs, ys),
        }
        buckets = build_buckets(eligible, score)
        result["buckets"][outcome_metric] = {
            "bucket_count": len(buckets),
            "buckets": buckets,
            "top_bottom_spread": _top_bottom_spread(buckets, outcome_metric),
        }
    return result


def pairwise_comparison(
    rows_in_scope: list[dict[str, Any]], left: str, right: str
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for outcome_metric in OUTCOME_METRICS:
        eligible = [
            row
            for row in rows_in_scope
            if row["status"] == "COMPLETE"
            and _number(row["scores"].get(left)) is not None
            and _number(row["scores"].get(right)) is not None
            and _number(row.get(outcome_metric)) is not None
        ]
        left_metrics = score_horizon_split_metrics(len(eligible), eligible, left)
        right_metrics = score_horizon_split_metrics(len(eligible), eligible, right)
        left_cov = left_metrics["coverage"][outcome_metric]
        right_cov = right_metrics["coverage"][outcome_metric]
        left_spread = left_metrics["buckets"][outcome_metric]["top_bottom_spread"]
        right_spread = right_metrics["buckets"][outcome_metric]["top_bottom_spread"]
        result[outcome_metric] = {
            "n": len(eligible),
            "pearson": {
                "left": left_cov["pearson"],
                "right": right_cov["pearson"],
                "delta": None
                if left_cov["pearson"] is None or right_cov["pearson"] is None
                else left_cov["pearson"] - right_cov["pearson"],
            },
            "spearman": {
                "left": left_cov["spearman"],
                "right": right_cov["spearman"],
                "delta": None
                if left_cov["spearman"] is None or right_cov["spearman"] is None
                else left_cov["spearman"] - right_cov["spearman"],
            },
            "top_bottom_spread": {
                "left": left_spread,
                "right": right_spread,
                "delta": None if left_spread is None or right_spread is None else left_spread - right_spread,
            },
        }
    return result


def evaluate(
    safe_population: list[dict[str, Any]],
    safe_outcomes: list[dict[str, Any]],
    eval_splits: tuple[str, ...],
) -> dict[str, Any]:
    paired = pair_rows(safe_population, safe_outcomes)
    population_split_counts: dict[str, int] = {}
    for row in safe_population:
        population_split_counts[str(row["split"])] = population_split_counts.get(str(row["split"]), 0) + 1

    metrics: dict[str, Any] = {}
    pairwise: dict[str, Any] = {}
    for split in eval_splits:
        split_total = population_split_counts.get(split, 0)
        metrics[split] = {}
        pairwise[split] = {}
        for horizon in HORIZONS:
            scope = [row for row in paired if row["split"] == split and row["horizon"] == horizon]
            metrics[split][horizon] = {
                score: score_horizon_split_metrics(split_total, scope, score) for score in BASELINE_SCORES
            }
            pairwise[split][horizon] = {
                f"{left}__vs__{right}": pairwise_comparison(scope, left, right) for left, right in PAIRWISE
            }
    return {"metrics": metrics, "pairwise": pairwise}
