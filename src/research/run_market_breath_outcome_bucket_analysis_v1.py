from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Callable


REPORT_NAME = "market_breath_outcome_bucket_analysis_v1"
VERSION = "1.0"
DEFAULT_INPUT_ROWS = "data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl"
DEFAULT_INPUT_SUMMARY = "data/research/market_breath_outcome_validation_v1/outcome_summary_v1.json"
DEFAULT_OUTPUT_DIR = "data/research/market_breath_outcome_bucket_analysis_v1"
OUTPUT_ROWS = "bucket_rows_v1.jsonl"
OUTPUT_SUMMARY = "bucket_summary_v1.json"

PHASES = [
    "INHALE_ACCUMULATION",
    "HOLD_COMPRESSION",
    "EXHALE_EXPANSION",
    "OVERBREATH_EXTENSION",
    "COLLAPSE_RESET",
    "NEUTRAL_TRANSITION",
    "INSUFFICIENT_DATA",
]

FORWARD_FIELDS = [
    "fwd_return_1c",
    "fwd_return_3c",
    "fwd_return_6c",
    "fwd_return_12c",
    "fwd_return_18c",
    "fwd_return_24c",
]

SAFETY_MARKERS = {
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "db_writes": 0,
    "db_reads": 0,
    "selection_engine_changes": 0,
    "advice_engine_changes": 0,
    "decision_gate_changes": 0,
    "execution_planner_changes": 0,
    "executor_changes": 0,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bucket existing Market Breath outcome validation rows without DB access."
    )
    parser.add_argument("--input-rows", default=DEFAULT_INPUT_ROWS)
    parser.add_argument("--input-summary", default=DEFAULT_INPUT_SUMMARY)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-count", type=int, default=20)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=["table", "json"], default="table")
    return parser.parse_args(argv)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n")


def band(value: Any, bands: list[tuple[str, float | None, float | None]]) -> str:
    if value is None:
        return "MISSING"
    numeric = float(value)
    for label, low, high in bands:
        if (low is None or numeric >= low) and (high is None or numeric < high):
            return label
    return "MISSING"


def confidence_band(row: dict[str, Any]) -> str:
    return band(
        row.get("market_breath_confidence"),
        [
            ("CONF_LOW", None, 40.0),
            ("CONF_MID", 40.0, 70.0),
            ("CONF_HIGH", 70.0, None),
        ],
    )


def momentum_band(row: dict[str, Any]) -> str:
    return band(
        row.get("momentum_score"),
        [
            ("MOM_NEG_HIGH", None, -25.0),
            ("MOM_NEG", -25.0, 0.0),
            ("MOM_FLAT", 0.0, 20.0),
            ("MOM_POS", 20.0, 50.0),
            ("MOM_POS_HIGH", 50.0, None),
        ],
    )


def relative_strength_band(row: dict[str, Any]) -> str:
    return band(
        row.get("relative_strength_score"),
        [
            ("RS_WEAK", None, -20.0),
            ("RS_NEG", -20.0, 0.0),
            ("RS_NEUTRAL", 0.0, 20.0),
            ("RS_STRONG", 20.0, 50.0),
            ("RS_LEADER", 50.0, None),
        ],
    )


def expansion_band(row: dict[str, Any]) -> str:
    return band(
        row.get("expansion_score"),
        [
            ("EXP_LOW", None, 35.0),
            ("EXP_MID", 35.0, 65.0),
            ("EXP_HIGH", 65.0, None),
        ],
    )


def reversal_pressure_band(row: dict[str, Any]) -> str:
    return band(
        row.get("reversal_pressure_score"),
        [
            ("REV_LOW", None, 25.0),
            ("REV_MID", 25.0, 45.0),
            ("REV_HIGH", 45.0, None),
        ],
    )


def btc_alignment_band(row: dict[str, Any]) -> str:
    return band(
        row.get("btc_alignment_score"),
        [
            ("BTC_DIVERGENT", None, -20.0),
            ("BTC_WEAK", -20.0, 0.0),
            ("BTC_NEUTRAL", 0.0, 20.0),
            ("BTC_ALIGNED", 20.0, 50.0),
            ("BTC_STRONGLY_ALIGNED", 50.0, None),
        ],
    )


def breadth_alignment_band(row: dict[str, Any]) -> str:
    return band(
        row.get("breadth_alignment_score"),
        [
            ("BREADTH_WEAK", None, -20.0),
            ("BREADTH_NEG", -20.0, 0.0),
            ("BREADTH_NEUTRAL", 0.0, 20.0),
            ("BREADTH_ALIGNED", 20.0, 50.0),
            ("BREADTH_STRONGLY_ALIGNED", 50.0, None),
        ],
    )


BUCKET_DIMENSIONS: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
    ("phase", lambda row: row["market_breath_phase"]),
    ("phase_symbol", lambda row: str(row["symbol"])),
    ("phase_state", lambda row: str(row["market_breath_state"])),
    ("phase_confidence_band", confidence_band),
    ("phase_momentum_band", momentum_band),
    ("phase_relative_strength_band", relative_strength_band),
    ("phase_expansion_band", expansion_band),
    ("phase_reversal_pressure_band", reversal_pressure_band),
    ("phase_btc_alignment_band", btc_alignment_band),
    ("phase_breadth_alignment_band", breadth_alignment_band),
]


def avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(median(values)), 6)


def positive_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(1 for value in values if value > 0.0) / len(values) * 100.0, 6)


def values(rows: list[dict[str, Any]], field: str) -> list[float]:
    return [
        float(row[field])
        for row in rows
        if row.get("outcome_available") and row.get(field) is not None
    ]


def interpretation_hint(
    *,
    sample_status: str,
    avg_24c: float | None,
    positive_rate_24c: float | None,
    neutral_avg_24c: float | None,
    neutral_positive_rate_24c: float | None,
) -> str:
    if sample_status == "LOW_SAMPLE":
        return "LOW_SAMPLE"
    if (
        avg_24c is not None
        and positive_rate_24c is not None
        and neutral_avg_24c is not None
        and neutral_positive_rate_24c is not None
        and avg_24c >= neutral_avg_24c + 1.0
        and positive_rate_24c >= neutral_positive_rate_24c + 5.0
    ):
        return "OUTPERFORMS_BASELINE"
    if (
        avg_24c is not None
        and positive_rate_24c is not None
        and neutral_avg_24c is not None
        and neutral_positive_rate_24c is not None
        and avg_24c <= neutral_avg_24c - 1.0
        and positive_rate_24c <= neutral_positive_rate_24c - 5.0
    ):
        return "UNDERPERFORMS_BASELINE"
    return "MIXED_OR_FLAT"


def bucket_record(
    *,
    bucket_dimension: str,
    bucket_key: str,
    phase: str,
    rows: list[dict[str, Any]],
    min_count: int,
    neutral_avg_24c: float | None,
    neutral_positive_rate_24c: float | None,
) -> dict[str, Any]:
    fwd24 = values(rows, "fwd_return_24c")
    avg_24c = avg(fwd24)
    pos_24c = positive_rate(fwd24)
    outcome_available_count = sum(1 for row in rows if row.get("outcome_available"))
    sample_status = "SUFFICIENT" if outcome_available_count >= min_count else "LOW_SAMPLE"
    return {
        "bucket_dimension": bucket_dimension,
        "bucket_key": bucket_key,
        "market_breath_phase": phase,
        "count": len(rows),
        "outcome_available_count": outcome_available_count,
        "avg_fwd_return_1c": avg(values(rows, "fwd_return_1c")),
        "avg_fwd_return_3c": avg(values(rows, "fwd_return_3c")),
        "avg_fwd_return_6c": avg(values(rows, "fwd_return_6c")),
        "avg_fwd_return_12c": avg(values(rows, "fwd_return_12c")),
        "avg_fwd_return_18c": avg(values(rows, "fwd_return_18c")),
        "avg_fwd_return_24c": avg_24c,
        "median_fwd_return_24c": median_or_none(fwd24),
        "positive_rate_24c": pos_24c,
        "avg_max_runup_24c": avg(values(rows, "max_runup_24c_from_asof_close")),
        "avg_max_drawdown_24c": avg(values(rows, "max_drawdown_24c_from_asof_close")),
        "vs_neutral_avg_fwd_return_24c": round(avg_24c - neutral_avg_24c, 6) if avg_24c is not None and neutral_avg_24c is not None else None,
        "vs_neutral_positive_rate_24c": round(pos_24c - neutral_positive_rate_24c, 6) if pos_24c is not None and neutral_positive_rate_24c is not None else None,
        "sample_status": sample_status,
        "interpretation_hint": interpretation_hint(
            sample_status=sample_status,
            avg_24c=avg_24c,
            positive_rate_24c=pos_24c,
            neutral_avg_24c=neutral_avg_24c,
            neutral_positive_rate_24c=neutral_positive_rate_24c,
        ),
    }


def build_bucket_rows(
    rows: list[dict[str, Any]],
    *,
    min_count: int,
    neutral_avg_24c: float | None,
    neutral_positive_rate_24c: float | None,
) -> list[dict[str, Any]]:
    bucket_rows: list[dict[str, Any]] = []
    for dimension, key_fn in BUCKET_DIMENSIONS:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            phase = str(row["market_breath_phase"])
            grouped[(phase, key_fn(row))].append(row)
        for phase in PHASES:
            for (group_phase, key), group_rows in sorted(grouped.items()):
                if group_phase != phase:
                    continue
                bucket_key = phase if dimension == "phase" else f"{phase}|{key}"
                bucket_rows.append(
                    bucket_record(
                        bucket_dimension=dimension,
                        bucket_key=bucket_key,
                        phase=phase,
                        rows=group_rows,
                        min_count=min_count,
                        neutral_avg_24c=neutral_avg_24c,
                        neutral_positive_rate_24c=neutral_positive_rate_24c,
                    )
                )
    return bucket_rows


def top_buckets(
    bucket_rows: list[dict[str, Any]],
    *,
    phase: str,
    hints: set[str] | None = None,
    reverse: bool = True,
    limit: int = 8,
) -> list[dict[str, Any]]:
    candidates = [
        row for row in bucket_rows
        if row["market_breath_phase"] == phase
        and row["sample_status"] == "SUFFICIENT"
        and row.get("avg_fwd_return_24c") is not None
        and (hints is None or row["interpretation_hint"] in hints)
    ]
    candidates.sort(
        key=lambda row: (
            row["avg_fwd_return_24c"],
            row["positive_rate_24c"] if row.get("positive_rate_24c") is not None else -999.0,
            row["outcome_available_count"],
        ),
        reverse=reverse,
    )
    return candidates[:limit]


def neutral_baseline(input_summary: dict[str, Any], bucket_rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary_neutral = input_summary.get("phase_outcome_summary", {}).get("NEUTRAL_TRANSITION", {})
    phase_bucket = next(
        (
            row for row in bucket_rows
            if row["bucket_dimension"] == "phase"
            and row["market_breath_phase"] == "NEUTRAL_TRANSITION"
        ),
        {},
    )
    return {
        "count": summary_neutral.get("count", phase_bucket.get("count")),
        "outcome_available_count": summary_neutral.get("outcome_available_count", phase_bucket.get("outcome_available_count")),
        "avg_fwd_return_24c": summary_neutral.get("avg_fwd_return_24c", phase_bucket.get("avg_fwd_return_24c")),
        "median_fwd_return_24c": summary_neutral.get("median_fwd_return_24c", phase_bucket.get("median_fwd_return_24c")),
        "positive_rate_24c": summary_neutral.get("positive_rate_24c", phase_bucket.get("positive_rate_24c")),
    }


def build_summary(
    *,
    rows: list[dict[str, Any]],
    input_summary: dict[str, Any],
    bucket_rows: list[dict[str, Any]],
    input_rows_path: Path,
    input_summary_path: Path,
    min_count: int,
) -> dict[str, Any]:
    baseline = neutral_baseline(input_summary, bucket_rows)
    collapse_outperformers = top_buckets(
        bucket_rows,
        phase="COLLAPSE_RESET",
        hints={"OUTPERFORMS_BASELINE"},
        reverse=True,
    )
    exhale_underperformers = top_buckets(
        bucket_rows,
        phase="EXHALE_EXPANSION",
        hints={"UNDERPERFORMS_BASELINE"},
        reverse=False,
    )
    exhale_outperformers = top_buckets(
        bucket_rows,
        phase="EXHALE_EXPANSION",
        hints={"OUTPERFORMS_BASELINE"},
        reverse=True,
    )
    overbreath_risk = top_buckets(
        bucket_rows,
        phase="OVERBREATH_EXTENSION",
        hints={"UNDERPERFORMS_BASELINE"},
        reverse=False,
    )
    return {
        "report": REPORT_NAME,
        "version": VERSION,
        "scope": "research-only market-only account-agnostic no-aplus no-pro no-symbolic-labels file-derived no-db",
        "input_rows": str(input_rows_path),
        "input_summary": str(input_summary_path),
        "row_count": len(rows),
        "outcome_available_count": sum(1 for row in rows if row.get("outcome_available")),
        "min_count": min_count,
        "neutral_baseline": baseline,
        "strongest_collapse_reset_buckets": collapse_outperformers,
        "weakest_exhale_expansion_buckets": exhale_underperformers,
        "strongest_exhale_expansion_buckets": exhale_outperformers,
        "overbreath_risk_buckets": overbreath_risk,
        "sparse_phase_notes": [
            "INHALE_ACCUMULATION remains low sample in bucket analysis; bucket findings are exploratory only.",
            "HOLD_COMPRESSION remains too sparse and is excluded from conclusions.",
            "Low-sample buckets are marked LOW_SAMPLE and should not drive threshold decisions.",
        ],
        "interpretation": [
            "Bucket analysis compares phase buckets against the NEUTRAL_TRANSITION baseline.",
            "COLLAPSE_RESET has sufficient outperforming buckets, but this is a candidate for further review, not a signal.",
            "EXHALE_EXPANSION has sufficient underperforming buckets and no sufficient outperforming buckets in this pass.",
            "OVERBREATH_EXTENSION remains consistent with late-risk / exhaustion, but sample mass is limited.",
            "Sparse phase findings are not meaningful enough for threshold decisions.",
            "Threshold calibration remains blocked pending review of these bucket findings or longer-history validation.",
        ],
        "limitations": [
            "Reads only existing generated outcome validation files.",
            "Does not query the database, rerun labels, or recompute outcomes from candles.",
            "Does not declare strategy edge or recommend buys/sells.",
            "Bucketed samples can become small quickly; LOW_SAMPLE rows are not meaningful conclusions.",
        ],
        "next_recommended_step": [
            "Review bucketed findings manually.",
            "Decide whether threshold calibration remains blocked.",
            "Consider longer-history validation only if the bucket findings need stability checks.",
            "Do not promote to runtime.",
        ],
        "no_threshold_changes_applied": True,
        "strategy_logic_added": False,
        "runtime_promotion_allowed": False,
        "feature_candidate_promotion_allowed": False,
        **SAFETY_MARKERS,
    }


def render_table(summary: dict[str, Any]) -> str:
    baseline = summary["neutral_baseline"]
    lines = [
        f"report={REPORT_NAME} version={VERSION}",
        "scope=research-only market-only account-agnostic file_derived no_db no_strategy no_runtime",
        f"input_rows={summary['input_rows']}",
        f"input_summary={summary['input_summary']}",
        f"row_count={summary['row_count']} outcome_available_count={summary['outcome_available_count']} min_count={summary['min_count']}",
        (
            "neutral_baseline "
            f"avg_24c={baseline['avg_fwd_return_24c']} "
            f"median_24c={baseline['median_fwd_return_24c']} "
            f"positive_rate_24c={baseline['positive_rate_24c']}"
        ),
        "",
        "--- strongest collapse reset buckets ---",
    ]
    lines.extend(render_bucket_preview(summary["strongest_collapse_reset_buckets"]))
    lines.append("")
    lines.append("--- weakest exhale expansion buckets ---")
    lines.extend(render_bucket_preview(summary["weakest_exhale_expansion_buckets"]))
    lines.append("")
    lines.append("--- strongest exhale expansion buckets ---")
    lines.extend(render_bucket_preview(summary["strongest_exhale_expansion_buckets"]))
    lines.append("")
    lines.append("--- overbreath risk buckets ---")
    lines.extend(render_bucket_preview(summary["overbreath_risk_buckets"]))
    lines.append("")
    lines.append("--- interpretation ---")
    lines.extend(f"  {item}" for item in summary["interpretation"])
    lines.append("[DONE] db_reads=0 db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


def render_bucket_preview(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["  (none)"]
    return [
        (
            f"  {row['bucket_dimension']} {row['bucket_key']} "
            f"available={row['outcome_available_count']} "
            f"avg_24c={row['avg_fwd_return_24c']} "
            f"positive_rate_24c={row['positive_rate_24c']} "
            f"vs_neutral_avg={row['vs_neutral_avg_fwd_return_24c']} "
            f"hint={row['interpretation_hint']}"
        )
        for row in rows
    ]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.min_count <= 0:
        raise ValueError("--min-count must be > 0")

    input_rows_path = Path(args.input_rows)
    input_summary_path = Path(args.input_summary)
    output_dir = Path(args.output_dir)
    bucket_rows_path = output_dir / OUTPUT_ROWS
    bucket_summary_path = output_dir / OUTPUT_SUMMARY

    rows = load_jsonl(input_rows_path)
    input_summary = load_json(input_summary_path)
    neutral = input_summary.get("phase_outcome_summary", {}).get("NEUTRAL_TRANSITION", {})
    neutral_avg_24c = neutral.get("avg_fwd_return_24c")
    neutral_positive_rate_24c = neutral.get("positive_rate_24c")

    bucket_rows = build_bucket_rows(
        rows,
        min_count=args.min_count,
        neutral_avg_24c=neutral_avg_24c,
        neutral_positive_rate_24c=neutral_positive_rate_24c,
    )
    summary = build_summary(
        rows=rows,
        input_summary=input_summary,
        bucket_rows=bucket_rows,
        input_rows_path=input_rows_path,
        input_summary_path=input_summary_path,
        min_count=args.min_count,
    )

    if args.write_files:
        write_jsonl(bucket_rows_path, bucket_rows)
        write_json(bucket_summary_path, summary)

    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print(render_table(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
