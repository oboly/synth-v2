from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any


REPORT_NAME = "aplus_transition_outcome_crosscheck_v1"
PARSER_VERSION = "0.1"
SAMPLE_LIMITATION = "LOW_SAMPLE_TRANSITION_OUTCOME_COVERAGE"

DEFAULT_TRANSITIONS_PATH = (
    "data/research/aplus_phase_exposure_stability_v1/"
    "phase_exposure_transition_rows_v1.jsonl"
)
DEFAULT_OUTCOMES_PATH = (
    "data/research/aplus_multi_snapshot_outcome_validation_v1/"
    "label_outcomes_multi_snapshot_v1.jsonl"
)
DEFAULT_OUTPUT_DIR = "data/research/aplus_transition_outcome_crosscheck_v1"

CHANGE_FLAG_GROUPS = [
    "table1_phase_changed",
    "table1_bias_changed",
    "table2_harmonic_phase_changed",
    "table2_offset_band_changed",
    "table2_quality_changed",
    "table2_extension_risk_changed",
    "combined_exposure_changed",
]

TRANSITION_VALUE_GROUPS: list[tuple[str, str, str]] = [
    ("table1_phase_transition", "from_table1_phase", "to_table1_phase"),
    ("table1_bias_transition", "from_table1_strategic_bias", "to_table1_strategic_bias"),
    ("table2_harmonic_phase_transition", "from_table2_harmonic_phase", "to_table2_harmonic_phase"),
    ("table2_offset_band_transition", "from_table2_offset_band", "to_table2_offset_band"),
    ("table2_quality_transition", "from_table2_quality", "to_table2_quality"),
    ("table2_extension_risk_transition", "from_table2_extension_risk", "to_table2_extension_risk"),
    ("combined_exposure_transition", "from_combined_exposure_key", "to_combined_exposure_key"),
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Cross-check A+ label transitions against forward market outcomes "
            "(research-only, market-only, account-agnostic; no DB, no broker)."
        )
    )
    p.add_argument("--transitions-path", default=DEFAULT_TRANSITIONS_PATH)
    p.add_argument("--outcomes-path", default=DEFAULT_OUTCOMES_PATH)
    p.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--min-n", type=int, default=2, help="Minimum valid outcomes to include in metric rows.")
    p.add_argument("--output", choices=["table", "json"], default="table")
    p.add_argument("--write-files", action="store_true")
    return p.parse_args(argv)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n")


def outcome_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return (
        str(row["snapshot_pair_id"]),
        str(row["token"]).upper(),
        int(row["horizon_hours"]),
    )


def transition_value(row: dict[str, Any], from_key: str, to_key: str) -> str:
    return f"{row.get(from_key, '')}->{row.get(to_key, '')}"


def build_joined_rows(
    transitions: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    outcomes_by_key = {outcome_key(row): row for row in outcomes}
    horizons = sorted({int(row["horizon_hours"]) for row in outcomes})
    joined: list[dict[str, Any]] = []

    for transition in transitions:
        to_snapshot = str(transition["to_snapshot_pair_id"])
        token = str(transition["token"]).upper()
        for horizon in horizons:
            outcome = outcomes_by_key.get((to_snapshot, token, horizon))
            if outcome is None:
                joined.append({
                    "token": token,
                    "from_snapshot_pair_id": transition["from_snapshot_pair_id"],
                    "to_snapshot_pair_id": transition["to_snapshot_pair_id"],
                    "horizon_hours": horizon,
                    "outcome_status": "MISSING_OUTCOME_ROW",
                    "forward_return_pct": None,
                    "mfe_pct": None,
                    "mae_pct": None,
                    "transition_signature": transition["transition_signature"],
                    **transition_group_values(transition),
                })
                continue

            joined.append({
                "token": token,
                "from_snapshot_pair_id": transition["from_snapshot_pair_id"],
                "to_snapshot_pair_id": transition["to_snapshot_pair_id"],
                "from_pair_reference_ts_utc": transition["from_pair_reference_ts_utc"],
                "to_pair_reference_ts_utc": transition["to_pair_reference_ts_utc"],
                "hours_between_snapshots": transition["hours_between_snapshots"],
                "horizon_hours": horizon,
                "outcome_status": outcome.get("outcome_status"),
                "base_ts_utc": outcome.get("base_ts_utc"),
                "future_ts_utc": outcome.get("future_ts_utc"),
                "forward_return_pct": outcome.get("forward_return_pct"),
                "mfe_pct": outcome.get("mfe_pct"),
                "mae_pct": outcome.get("mae_pct"),
                "transition_signature": transition["transition_signature"],
                **transition_group_values(transition),
            })

    return joined


def transition_group_values(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for flag in CHANGE_FLAG_GROUPS:
        out[flag] = bool(row.get(flag))
    for group_key, from_key, to_key in TRANSITION_VALUE_GROUPS:
        out[group_key] = transition_value(row, from_key, to_key)
    return out


def reliability_label(n_valid: int, snapshot_count: int, avg_return: float | None, win_rate: float | None) -> str:
    if n_valid < 2:
        return "TOO_SMALL"
    if snapshot_count < 2:
        return "LOW_SAMPLE"
    if n_valid >= 3 and avg_return is not None and avg_return > 0 and win_rate is not None and win_rate >= 55.0:
        return "POSITIVE_OBSERVATION"
    if n_valid >= 3 and avg_return is not None and avg_return < 0 and win_rate is not None and win_rate <= 45.0:
        return "NEGATIVE_OBSERVATION"
    return "MIXED"


def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid_rows = [r for r in rows if r.get("outcome_status") == "VALID"]
    rets = [float(r["forward_return_pct"]) for r in valid_rows if r.get("forward_return_pct") is not None]
    mfes = [float(r["mfe_pct"]) for r in valid_rows if r.get("mfe_pct") is not None]
    maes = [float(r["mae_pct"]) for r in valid_rows if r.get("mae_pct") is not None]
    snapshots = sorted({str(r["to_snapshot_pair_id"]) for r in valid_rows})
    tokens = sorted({str(r["token"]) for r in valid_rows})

    avg_return = sum(rets) / len(rets) if rets else None
    win_rate = 100.0 * sum(1 for r in rets if r > 0) / len(rets) if rets else None

    return {
        "n_total": len(rows),
        "n_valid": len(valid_rows),
        "n_no_future_candle": sum(1 for r in rows if r.get("outcome_status") == "NO_FUTURE_CANDLE"),
        "n_missing_outcome_row": sum(1 for r in rows if r.get("outcome_status") == "MISSING_OUTCOME_ROW"),
        "avg_return_pct": avg_return,
        "median_return_pct": median(rets) if rets else None,
        "win_rate_pct": win_rate,
        "avg_mfe_pct": sum(mfes) / len(mfes) if mfes else None,
        "avg_mae_pct": sum(maes) / len(maes) if maes else None,
        "token_count": len(tokens),
        "snapshot_count": len(snapshots),
        "snapshots_present": snapshots,
        "tokens_present": tokens,
        "reliability_label": reliability_label(len(valid_rows), len(snapshots), avg_return, win_rate),
    }


def evaluate_group(joined_rows: list[dict[str, Any]], group_key: str, min_n: int) -> list[dict[str, Any]]:
    buckets: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for row in joined_rows:
        horizon = int(row["horizon_hours"])
        value = str(row.get(group_key))
        buckets.setdefault((horizon, value), []).append(row)

    metrics: list[dict[str, Any]] = []
    for (horizon, value), bucket_rows in sorted(buckets.items()):
        m = compute_metrics(bucket_rows)
        if m["n_valid"] < min_n:
            continue
        metrics.append({
            "horizon_hours": horizon,
            "group_key": group_key,
            "group_value": value,
            **m,
        })
    return metrics


def build_metrics(joined_rows: list[dict[str, Any]], min_n: int) -> list[dict[str, Any]]:
    group_keys = CHANGE_FLAG_GROUPS + [g[0] for g in TRANSITION_VALUE_GROUPS]
    metrics: list[dict[str, Any]] = []
    for group_key in group_keys:
        metrics.extend(evaluate_group(joined_rows, group_key, min_n))
    return metrics


def _sort_positive(row: dict[str, Any]) -> float:
    return float(row["avg_return_pct"]) if row["avg_return_pct"] is not None else -999.0


def _sort_negative(row: dict[str, Any]) -> float:
    return float(row["avg_return_pct"]) if row["avg_return_pct"] is not None else 999.0


def brief(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "horizon_hours": row["horizon_hours"],
        "group_key": row["group_key"],
        "group_value": row["group_value"],
        "n_valid": row["n_valid"],
        "snapshot_count": row["snapshot_count"],
        "avg_return_pct": row["avg_return_pct"],
        "win_rate_pct": row["win_rate_pct"],
        "reliability_label": row["reliability_label"],
    }


def coverage_by_horizon(joined_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for horizon in sorted({int(r["horizon_hours"]) for r in joined_rows}):
        rows = [r for r in joined_rows if int(r["horizon_hours"]) == horizon]
        status_counts = dict(Counter(str(r["outcome_status"]) for r in rows))
        out[f"horizon_{horizon}h"] = {
            "total": len(rows),
            "status_counts": status_counts,
            "valid": status_counts.get("VALID", 0),
            "snapshots_with_valid_outcomes": sorted({
                str(r["to_snapshot_pair_id"]) for r in rows if r.get("outcome_status") == "VALID"
            }),
        }
    return out


def build_summary(
    transitions: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    joined_rows: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    args: argparse.Namespace,
    output_paths: dict[str, str],
) -> dict[str, Any]:
    label_counts = dict(Counter(r["reliability_label"] for r in metrics))
    positives = [r for r in metrics if r["avg_return_pct"] is not None]
    positives.sort(key=_sort_positive, reverse=True)
    negatives = [r for r in metrics if r["avg_return_pct"] is not None]
    negatives.sort(key=_sort_negative)

    return {
        "report": REPORT_NAME,
        "parser_version": PARSER_VERSION,
        "scope": "research-only market-only account-agnostic",
        "sample_limitation": SAMPLE_LIMITATION,
        "transition_outcome_alignment": "outcomes joined to transition to_snapshot_pair_id",
        "runtime_promotion_allowed": False,
        "feature_candidate_promotion_allowed": False,
        "transitions_path": args.transitions_path,
        "outcomes_path": args.outcomes_path,
        "input_transition_rows": len(transitions),
        "input_outcome_rows": len(outcomes),
        "joined_transition_outcome_rows": len(joined_rows),
        "metric_rows_written": len(metrics),
        "coverage_by_horizon": coverage_by_horizon(joined_rows),
        "reliability_label_counts": label_counts,
        "top_positive_observations": [brief(r) for r in positives[:10]],
        "top_negative_observations": [brief(r) for r in negatives[:10]],
        "output_paths": output_paths,
        "wrote_files": bool(args.write_files),
        "safety_markers": {
            "db_writes": 0,
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "selection_engine_changes": 0,
            "advice_engine_changes": 0,
            "decision_gate_changes": 0,
            "execution_planner_changes": 0,
            "executor_changes": 0,
            "paper_live_logic": "not_allowed",
            "account_state": "not_allowed",
            "research_only": True,
            "market_only": True,
            "account_agnostic": True,
        },
    }


def fmt(value: float | None) -> str:
    return "-" if value is None else f"{float(value):.3f}"


def render_table(summary: dict[str, Any]) -> str:
    lines = [
        f"report={REPORT_NAME} version={PARSER_VERSION}",
        "scope=research-only market-only account-agnostic",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        "selection_engine=none advice_engine=none decision_gate=none execution_planner=none executor=none",
        f"sample_limitation={SAMPLE_LIMITATION}",
        "runtime_promotion_allowed=False feature_candidate_promotion_allowed=False",
        (
            f"input_transition_rows={summary['input_transition_rows']} "
            f"input_outcome_rows={summary['input_outcome_rows']} "
            f"joined_rows={summary['joined_transition_outcome_rows']} "
            f"metric_rows={summary['metric_rows_written']}"
        ),
        "",
        "--- coverage by horizon ---",
    ]
    for horizon, coverage in summary["coverage_by_horizon"].items():
        lines.append(
            f"  {horizon}: total={coverage['total']} valid={coverage['valid']} "
            f"statuses={coverage['status_counts']}"
        )

    def block(title: str, rows: list[dict[str, Any]]) -> None:
        lines.append(f"\n--- {title} ---")
        if not rows:
            lines.append("  (none)")
            return
        for row in rows:
            lines.append(
                f"  [{row['reliability_label']}] h={row['horizon_hours']}h "
                f"{row['group_key']}={row['group_value']} "
                f"n={row['n_valid']} snaps={row['snapshot_count']} "
                f"avg={fmt(row['avg_return_pct'])} wr={fmt(row['win_rate_pct'])}"
            )

    block("highest average return observations", summary["top_positive_observations"])
    block("lowest average return observations", summary["top_negative_observations"])

    lines += ["", "--- reliability label counts ---"]
    for label, count in summary["reliability_label_counts"].items():
        lines.append(f"  {label}={count}")

    lines.append("")
    lines.append(f"wrote_files={summary['wrote_files']}")
    if summary["wrote_files"]:
        for key, value in summary["output_paths"].items():
            lines.append(f"  {key}={value}")
    lines.append("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    transitions_path = Path(args.transitions_path)
    outcomes_path = Path(args.outcomes_path)
    out_dir = Path(args.output_dir)

    if not transitions_path.exists():
        print(f"ERROR: missing transitions input: {transitions_path}")
        return 2
    if not outcomes_path.exists():
        print(f"ERROR: missing outcomes input: {outcomes_path}")
        return 2

    output_paths = {
        "rows_jsonl": str(out_dir / "transition_outcome_crosscheck_rows_v1.jsonl"),
        "summary_json": str(out_dir / "transition_outcome_crosscheck_summary_v1.json"),
    }

    transitions = load_jsonl(transitions_path)
    outcomes = load_jsonl(outcomes_path)
    joined_rows = build_joined_rows(transitions, outcomes)
    metrics = build_metrics(joined_rows, args.min_n)
    summary = build_summary(transitions, outcomes, joined_rows, metrics, args, output_paths)

    if args.write_files:
        write_jsonl(Path(output_paths["rows_jsonl"]), metrics)
        write_json(Path(output_paths["summary_json"]), summary)

    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print(render_table(summary))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
