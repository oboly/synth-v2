from __future__ import annotations

from collections import Counter
from math import sqrt
from statistics import mean, median
from typing import Any, Iterable, Mapping

HORIZONS = ("1h", "4h", "24h")
OUTCOMES = ("forward_return_pct", "mfe_pct", "mae_pct")
BUCKET_COUNT = 5
CANDIDATES = ("cq_v1_mrp_balanced_v1", "cq_v1_mrp_anchor_v1")
METRICS = (
    "ppp_only",
    "trade_quality_score",
    "selection_score",
    "cq_v0",
    "cq_v1_mrp_balanced_v1",
    "cq_v1_mrp_anchor_v1",
    "ppp_x_cq_v0",
    "ppp_x_cq_v1_mrp_balanced_v1",
    "ppp_x_cq_v1_mrp_anchor_v1",
)
PAIRWISE = (
    ("cq_v1_mrp_balanced_v1", "ppp_only"),
    ("cq_v1_mrp_anchor_v1", "ppp_only"),
    ("cq_v1_mrp_balanced_v1", "trade_quality_score"),
    ("cq_v1_mrp_anchor_v1", "trade_quality_score"),
    ("cq_v1_mrp_balanced_v1", "selection_score"),
    ("cq_v1_mrp_anchor_v1", "selection_score"),
    ("cq_v1_mrp_balanced_v1", "cq_v0"),
    ("cq_v1_mrp_anchor_v1", "cq_v0"),
    ("ppp_x_cq_v1_mrp_balanced_v1", "ppp_x_cq_v0"),
    ("ppp_x_cq_v1_mrp_anchor_v1", "ppp_x_cq_v0"),
)


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


def exact_identity(score: Mapping[str, Any], outcome: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(score["shadow_id"]),
        int(score["asset_id"]),
        str(score["venue"]),
        str(score["asof_ts_utc"]).replace("+00:00", "Z"),
        str(score["evidence_key"]),
        str(score["cq_model_version"]),
    )


def outcome_identity(outcome: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(outcome["shadow_id"]),
        int(outcome["asset_id"]),
        str(outcome["venue"]),
        str(outcome["observation_asof_ts_utc"]).replace("+00:00", "Z"),
        str(outcome["evidence_key"]),
        str(outcome["cq_model_version"]),
    )


def metric_values(score: Mapping[str, Any], outcome: Mapping[str, Any]) -> tuple[dict[str, float | None], dict[str, str | None]]:
    ppp = _number(outcome.get("ppp_pct"))
    cq_v0 = _number(score.get("cq_v0"))
    values: dict[str, float | None] = {
        "ppp_only": ppp,
        "trade_quality_score": _number(outcome.get("trade_quality_score")),
        "selection_score": _number(outcome.get("selection_score")),
        "cq_v0": cq_v0,
    }
    reasons: dict[str, str | None] = {
        key: None if value is not None else "UNAVAILABLE_INPUT" for key, value in values.items()
    }
    for candidate_id in CANDIDATES:
        payload = score.get("candidates", {}).get(candidate_id) or {}
        value = _number(payload.get("score")) if payload.get("state") == "AVAILABLE" else None
        values[candidate_id] = value
        reasons[candidate_id] = None if value is not None else str(payload.get("reason") or payload.get("state") or "UNAVAILABLE")

    values["ppp_x_cq_v0"] = None if ppp is None or cq_v0 is None else ppp * cq_v0
    reasons["ppp_x_cq_v0"] = None if values["ppp_x_cq_v0"] is not None else "PPP_OR_CQ_V0_UNAVAILABLE"
    for candidate_id in CANDIDATES:
        key = f"ppp_x_{candidate_id}"
        candidate = values[candidate_id]
        values[key] = None if ppp is None or candidate is None else ppp * candidate
        reasons[key] = None if values[key] is not None else "PPP_OR_CQ_V1_UNAVAILABLE"
    return values, reasons


def pair_rows(scores: Iterable[Mapping[str, Any]], outcomes: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    score_by_shadow: dict[int, Mapping[str, Any]] = {}
    for row in scores:
        shadow_id = int(row["shadow_id"])
        if shadow_id in score_by_shadow:
            raise ValueError(f"duplicate score shadow_id: {shadow_id}")
        score_by_shadow[shadow_id] = row
    paired: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for outcome in outcomes:
        horizon = str(outcome.get("horizon"))
        if horizon not in HORIZONS:
            raise ValueError(f"unexpected horizon: {horizon}")
        key = (int(outcome["shadow_id"]), horizon)
        if key in seen:
            raise ValueError(f"duplicate outcome identity: {key}")
        seen.add(key)
        score = score_by_shadow.get(key[0])
        if score is None:
            raise ValueError(f"shadow_id={key[0]}:SCORE_ROW_MISSING")
        if exact_identity(score, outcome) != outcome_identity(outcome):
            raise ValueError(f"shadow_id={key[0]}:IDENTITY_MISMATCH")
        if str(score.get("cq_v0")) != str(outcome.get("cq_v0")):
            raise ValueError(f"shadow_id={key[0]}:CQ_V0_MISMATCH")
        values, reasons = metric_values(score, outcome)
        paired.append(
            {
                "shadow_id": key[0],
                "asset_id": int(score["asset_id"]),
                "venue": str(score["venue"]),
                "asof_ts_utc": str(score["asof_ts_utc"]),
                "evidence_key": str(score["evidence_key"]),
                "cq_model_version": str(score["cq_model_version"]),
                "horizon": horizon,
                "label_status": str(outcome.get("status")),
                "forward_return_pct": outcome.get("forward_return_pct"),
                "mfe_pct": outcome.get("mfe_pct"),
                "mae_pct": outcome.get("mae_pct"),
                "metric_values": values,
                "metric_unavailable_reasons": reasons,
            }
        )
    return sorted(paired, key=lambda row: (int(row["shadow_id"]), HORIZONS.index(str(row["horizon"]))))


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


def _stats(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "mean": None if not values else mean(values),
        "median": None if not values else median(values),
    }


def _metric_on_rows(rows: list[Mapping[str, Any]], metric: str, outcome_name: str) -> dict[str, Any]:
    eligible = [
        row for row in rows
        if row["label_status"] == "COMPLETE"
        and _number(row["metric_values"].get(metric)) is not None
        and _number(row.get(outcome_name)) is not None
    ]
    xs = [_number(row["metric_values"][metric]) for row in eligible]
    ys = [_number(row[outcome_name]) for row in eligible]
    x = [float(v) for v in xs if v is not None]
    y = [float(v) for v in ys if v is not None]
    ordered = sorted(eligible, key=lambda row: (float(row["metric_values"][metric]), int(row["shadow_id"])))
    buckets: list[dict[str, Any]] = []
    for bucket_index in range(BUCKET_COUNT):
        bucket_rows = [
            row for rank, row in enumerate(ordered)
            if min(BUCKET_COUNT - 1, (rank * BUCKET_COUNT) // len(ordered)) == bucket_index
        ] if ordered else []
        buckets.append(
            {
                "bucket": bucket_index + 1,
                "n": len(bucket_rows),
                "metric": _stats([float(row["metric_values"][metric]) for row in bucket_rows]),
                "outcome": _stats([float(row[outcome_name]) for row in bucket_rows]),
            }
        )
    return {
        "n": len(eligible),
        "pearson": _pearson(x, y),
        "spearman": _spearman(x, y),
        "buckets": buckets,
    }


def _pair_on_rows(rows: list[Mapping[str, Any]], left: str, right: str, outcome_name: str) -> dict[str, Any]:
    eligible = [
        row for row in rows
        if row["label_status"] == "COMPLETE"
        and _number(row["metric_values"].get(left)) is not None
        and _number(row["metric_values"].get(right)) is not None
        and _number(row.get(outcome_name)) is not None
    ]
    return {
        "n": len(eligible),
        "left": _metric_on_rows(eligible, left, outcome_name),
        "right": _metric_on_rows(eligible, right, outcome_name),
    }


def summarize(paired: list[Mapping[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"horizons": {}}
    for horizon in HORIZONS:
        rows = [row for row in paired if row["horizon"] == horizon]
        complete = [row for row in rows if row["label_status"] == "COMPLETE"]
        coverage: dict[str, Any] = {}
        for metric in METRICS:
            reasons = Counter(
                row["metric_unavailable_reasons"].get(metric) or "AVAILABLE"
                for row in complete
            )
            available = sum(1 for row in complete if _number(row["metric_values"].get(metric)) is not None)
            coverage[metric] = {
                "complete_label_count": len(complete),
                "available_count": available,
                "available_rate": 0.0 if not complete else round(available / len(complete), 6),
                "reason_counts": dict(sorted(reasons.items())),
            }
        metric_results = {
            metric: {outcome: _metric_on_rows(rows, metric, outcome) for outcome in OUTCOMES}
            for metric in METRICS
        }
        pairwise = {
            f"{left}__vs__{right}": {
                outcome: _pair_on_rows(rows, left, right, outcome) for outcome in OUTCOMES
            }
            for left, right in PAIRWISE
        }
        summary["horizons"][horizon] = {
            "row_count": len(rows),
            "label_status_counts": dict(sorted(Counter(str(row["label_status"]) for row in rows).items())),
            "coverage": coverage,
            "metrics": metric_results,
            "pairwise": pairwise,
        }
    return summary
