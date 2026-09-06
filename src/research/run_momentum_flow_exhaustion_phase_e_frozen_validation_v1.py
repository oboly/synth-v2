"""Frozen temporal validation for Issue #306 exhaustion hypotheses.

Research-only, file-input only. Discovery evidence is immutable reference data
frozen before Phase E. Only pre-discovery robustness and forward holdout inputs
are evaluated here. No threshold or regime search is permitted.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, Final

RUNNER: Final[str] = "momentum_flow_exhaustion_phase_e_frozen_validation_v1"
DISCOVERY_START: Final[str] = "2025-09-04T04:00:00+00:00"
DISCOVERY_END: Final[str] = "2026-08-31T00:00:00+00:00"
FORWARD_HOLDOUT_START: Final[str] = "2026-09-01T00:00:00+00:00"
UNKNOWN: Final[str] = "UNKNOWN"


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    side: str
    score_threshold: float
    market_regime: str
    expected_direction: str
    minimum_sample: int = 8


HYPOTHESES: Final[tuple[Hypothesis, ...]] = (
    Hypothesis("BUYER_70_ALT_STRENGTH_REVERSAL", "BUYER", 70.0, "ALT_STRENGTH", "POSITIVE"),
    Hypothesis("SELLER_70_RISK_OFF_CONTINUATION", "SELLER", 70.0, "RISK_OFF", "NEGATIVE"),
)

# Frozen from the accepted #805 full-universe-breadth discovery run.
# These values are reference evidence only and are never recomputed in Phase E.
DISCOVERY_REFERENCE: Final[dict[str, dict[str, Any]]] = {
    "BUYER_70_ALT_STRENGTH_REVERSAL": {
        "sample_count": 36,
        "avg_reversal_return_1b_pct": 0.607585,
        "avg_reversal_return_3b_pct": 0.732855,
        "avg_reversal_return_6b_pct": 1.121614,
        "median_reversal_return_6b_pct": 2.455993,
    },
    "SELLER_70_RISK_OFF_CONTINUATION": {
        "sample_count": 13,
        "avg_reversal_return_1b_pct": -1.075012,
        "avg_reversal_return_3b_pct": -2.123664,
        "avg_reversal_return_6b_pct": -3.484848,
        "median_reversal_return_6b_pct": -3.493756,
    },
}

EVALUATED_PERIODS: Final[tuple[str, ...]] = ("PRE_DISCOVERY", "FORWARD_HOLDOUT")


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _f(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def enrich_exact_context(
    replay_rows: list[dict[str, Any]], context_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in context_rows:
        key = (
            str(row.get("symbol") or "").upper(),
            str(row.get("interval") or ""),
            str(row.get("asof_ts_utc") or ""),
        )
        if not all(key):
            continue
        if key in lookup:
            raise ValueError(f"duplicate context identity: {key}")
        lookup[key] = row
    output: list[dict[str, Any]] = []
    for raw in replay_rows:
        row = dict(raw)
        key = (
            str(row.get("market") or "").upper(),
            str(row.get("interval") or ""),
            str(row.get("asof_ts_utc") or ""),
        )
        context = lookup.get(key)
        row["market_regime"] = (
            UNKNOWN if context is None else str(context.get("market_regime") or UNKNOWN).upper()
        )
        row["context_exact_match"] = context is not None
        output.append(row)
    return output


def _direction_ok(value: float | None, expected: str) -> bool:
    if value is None:
        return False
    return value > 0 if expected == "POSITIVE" else value < 0


def evaluate_hypothesis(
    rows: list[dict[str, Any]], hypothesis: Hypothesis, period: str
) -> dict[str, Any]:
    side = hypothesis.side.lower()
    score_field = f"{side}_exhaustion_score"
    cohort = [
        row
        for row in rows
        if (_f(row.get(score_field)) or 0.0) >= hypothesis.score_threshold
        and str(row.get("market_regime") or UNKNOWN).upper() == hypothesis.market_regime
    ]
    metrics: dict[str, Any] = {
        "hypothesis_id": hypothesis.hypothesis_id,
        "period": period,
        "sample_count": len(cohort),
        "minimum_sample": hypothesis.minimum_sample,
        "side": hypothesis.side,
        "score_threshold": hypothesis.score_threshold,
        "market_regime": hypothesis.market_regime,
        "expected_direction": hypothesis.expected_direction,
    }
    for horizon in (1, 3, 6):
        values = [
            _f(row.get(f"{side}_reversal_return_{horizon}b_pct")) for row in cohort
        ]
        values = [value for value in values if value is not None]
        metrics[f"avg_reversal_return_{horizon}b_pct"] = (
            None if not values else round(mean(values), 6)
        )
        metrics[f"median_reversal_return_{horizon}b_pct"] = (
            None if not values else round(median(values), 6)
        )
    criteria = {
        "avg_3b_direction": _direction_ok(
            metrics["avg_reversal_return_3b_pct"], hypothesis.expected_direction
        ),
        "avg_6b_direction": _direction_ok(
            metrics["avg_reversal_return_6b_pct"], hypothesis.expected_direction
        ),
        "median_6b_direction": _direction_ok(
            metrics["median_reversal_return_6b_pct"], hypothesis.expected_direction
        ),
    }
    metrics["criteria"] = criteria
    if len(cohort) < hypothesis.minimum_sample:
        metrics["status"] = "INSUFFICIENT_SAMPLE"
    elif all(criteria.values()):
        metrics["status"] = (
            "ROBUSTNESS_SUPPORTED" if period == "PRE_DISCOVERY" else "HOLDOUT_SUPPORTED"
        )
    else:
        metrics["status"] = (
            "ROBUSTNESS_NOT_SUPPORTED"
            if period == "PRE_DISCOVERY"
            else "HOLDOUT_NOT_SUPPORTED"
        )
    return metrics


def evaluate_period(
    replay_rows: list[dict[str, Any]], context_rows: list[dict[str, Any]], period: str
) -> dict[str, Any]:
    if period not in EVALUATED_PERIODS:
        raise ValueError(f"unsupported evaluated period: {period}")
    enriched = enrich_exact_context(replay_rows, context_rows)
    exact = sum(1 for row in enriched if row["context_exact_match"])
    return {
        "period": period,
        "replay_rows": len(replay_rows),
        "exact_context_rows": exact,
        "exact_context_coverage_pct": (
            0.0 if not replay_rows else round(exact / len(replay_rows) * 100.0, 6)
        ),
        "min_asof_ts_utc": min(
            (str(row.get("asof_ts_utc") or "") for row in replay_rows), default=None
        ),
        "max_asof_ts_utc": max(
            (str(row.get("asof_ts_utc") or "") for row in replay_rows), default=None
        ),
        "hypotheses": [evaluate_hypothesis(enriched, hypothesis, period) for hypothesis in HYPOTHESES],
    }


def frozen_discovery_reference() -> dict[str, Any]:
    hypotheses = []
    for hypothesis in HYPOTHESES:
        item = {
            **asdict(hypothesis),
            **DISCOVERY_REFERENCE[hypothesis.hypothesis_id],
            "status": "FROZEN_REFERENCE_ONLY",
        }
        hypotheses.append(item)
    return {
        "period": "DISCOVERY",
        "start": DISCOVERY_START,
        "end": DISCOVERY_END,
        "contaminated_for_holdout": True,
        "source": "accepted #805 full-universe-breadth discovery evidence",
        "hypotheses": hypotheses,
    }


def build_report(
    pre_discovery: tuple[list[dict[str, Any]], list[dict[str, Any]]],
    forward_holdout: tuple[list[dict[str, Any]], list[dict[str, Any]]],
) -> dict[str, Any]:
    pre = evaluate_period(*pre_discovery, "PRE_DISCOVERY")
    forward = evaluate_period(*forward_holdout, "FORWARD_HOLDOUT")
    forward_min = forward["min_asof_ts_utc"]
    if forward_min and forward_min < FORWARD_HOLDOUT_START:
        raise ValueError("forward holdout contains pre-2026-09-01 observations")
    pre_max = pre["max_asof_ts_utc"]
    if pre_max and pre_max >= DISCOVERY_START:
        raise ValueError("pre-discovery input overlaps frozen discovery window")
    return {
        "runner": RUNNER,
        "research_only": True,
        "threshold_search": False,
        "regime_search": False,
        "discovery_reference": frozen_discovery_reference(),
        "forward_holdout_contract": {
            "start": FORWARD_HOLDOUT_START,
            "untouched_before_freeze": True,
        },
        "frozen_hypotheses": [asdict(hypothesis) for hypothesis in HYPOTHESES],
        "periods": {
            "PRE_DISCOVERY": pre,
            "FORWARD_HOLDOUT": forward,
        },
        "safety": {
            "account_awareness": 0,
            "selection_engine_change": 0,
            "decision_gate_change": 0,
            "execution_planner_change": 0,
            "executor_change": 0,
            "db_writes": 0,
            "broker_calls": 0,
            "order_submission": 0,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate frozen #306 exhaustion hypotheses without reopening discovery"
    )
    for prefix in ("pre-discovery", "forward-holdout"):
        parser.add_argument(f"--{prefix}-replay", required=True)
        parser.add_argument(f"--{prefix}-context", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(
        f"STARTED runner={RUNNER} discovery_recompute=0 threshold_search=0 regime_search=0",
        flush=True,
    )
    report = build_report(
        (
            read_csv(Path(args.pre_discovery_replay)),
            read_csv(Path(args.pre_discovery_context)),
        ),
        (
            read_csv(Path(args.forward_holdout_replay)),
            read_csv(Path(args.forward_holdout_context)),
        ),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"FINISHED runner={RUNNER} output={output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
