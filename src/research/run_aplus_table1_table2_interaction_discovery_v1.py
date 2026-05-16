from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any


REPORT_NAME = "aplus_table1_table2_interaction_discovery_v1"
PARSER_VERSION = "0.1"
SAMPLE_LIMITATION = "LOW_SAMPLE_THREE_SNAPSHOTS_PARTIAL_OUTCOME_COVERAGE"

# ---------------------------------------------------------------------------
# Group definitions
# ---------------------------------------------------------------------------

SINGLE_FIELDS: list[str] = [
    "table1_phase",
    "table1_coherence",
    "table1_field",
    "table1_geometry",
    "table1_structural_role",
    "table1_expansion_quality",
    "table1_anchor_strength",
    "table1_strategic_bias",
    "table2_harmonic_phase",
    "table2_phase_state",
    "table2_offset_band",
    "table2_drift_direction",
    "table2_quality",
    "table2_extension_risk",
]

TWO_FIELD_GROUPS: list[tuple[str, str]] = [
    ("table1_phase", "table2_harmonic_phase"),
    ("table1_phase", "table2_offset_band"),
    ("table1_phase", "table2_quality"),
    ("table1_phase", "table2_extension_risk"),
    ("table1_coherence", "table2_quality"),
    ("table1_coherence", "table2_drift_direction"),
    ("table1_field", "table2_harmonic_phase"),
    ("table1_geometry", "table2_quality"),
    ("table1_structural_role", "table2_harmonic_phase"),
    ("table1_structural_role", "table2_offset_band"),
    ("table1_expansion_quality", "table2_quality"),
    ("table1_anchor_strength", "table2_quality"),
    ("table1_strategic_bias", "table2_harmonic_phase"),
    ("table1_strategic_bias", "table2_offset_band"),
    ("table1_strategic_bias", "table2_extension_risk"),
    ("table2_harmonic_phase", "table2_offset_band"),
    ("table2_harmonic_phase", "table2_drift_direction"),
    ("table2_offset_band", "table2_quality"),
    ("table2_quality", "table2_extension_risk"),
]

THREE_FIELD_GROUPS: list[tuple[str, str, str]] = [
    ("table1_phase", "table1_coherence", "table2_harmonic_phase"),
    ("table1_phase", "table1_strategic_bias", "table2_harmonic_phase"),
    ("table1_strategic_bias", "table2_harmonic_phase", "table2_offset_band"),
    ("table1_coherence", "table2_quality", "table2_extension_risk"),
    ("table1_structural_role", "table2_quality", "table2_extension_risk"),
    ("table1_field", "table2_harmonic_phase", "table2_drift_direction"),
]

GROUP_DEFINITIONS = (
    len(SINGLE_FIELDS) + len(TWO_FIELD_GROUPS) + len(THREE_FIELD_GROUPS)
)


def _group_key(fields: list[str] | tuple[str, ...]) -> str:
    return "__x__".join(fields)


def _group_type(n_fields: int) -> str:
    return {1: "single_field", 2: "two_field", 3: "three_field"}[n_fields]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Discover A+ Table1/Table2 label interaction groups that correlate "
            "with forward outcomes (research-only, no DB writes, no broker calls)."
        )
    )
    p.add_argument(
        "--outcomes-path",
        default=(
            "data/research/aplus_multi_snapshot_outcome_validation_v1/"
            "label_outcomes_multi_snapshot_v1.jsonl"
        ),
    )
    p.add_argument("--output-dir", default="data/research/aplus_table1_table2_interaction_discovery_v1")
    p.add_argument("--min-n", type=int, default=2, help="Minimum n_with_return to include in output.")
    p.add_argument("--output", choices=["table", "json"], default="table")
    p.add_argument("--write-files", action="store_true")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def load_outcomes(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def reliability_label(
    n_with_return: int,
    snapshot_count: int,
    avg_return: float | None,
    win_rate: float | None,
) -> str:
    if n_with_return < 2:
        return "TOO_SMALL"
    if snapshot_count < 2:
        return "LOW_SAMPLE"
    if n_with_return >= 3 and avg_return is not None and avg_return > 0 and win_rate is not None and win_rate >= 55.0:
        return "WATCH_CANDIDATE"
    if n_with_return >= 3 and avg_return is not None and avg_return < 0 and win_rate is not None and win_rate <= 45.0:
        return "NEGATIVE_CANDIDATE"
    return "MIXED"


def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rets = [r["forward_return_pct"] for r in rows if r.get("forward_return_pct") is not None]
    mfes = [r["mfe_pct"] for r in rows if r.get("mfe_pct") is not None]
    maes = [r["mae_pct"] for r in rows if r.get("mae_pct") is not None]
    n = len(rows)
    n_ret = len(rets)
    tokens = sorted({r["token"] for r in rows})
    snapshots = sorted({r["snapshot_pair_id"] for r in rows})
    avg_ret = sum(rets) / n_ret if n_ret else None
    med_ret = median(rets) if n_ret else None
    wins = sum(1 for r in rets if r > 0)
    wr = 100.0 * wins / n_ret if n_ret else None
    avg_mfe = sum(mfes) / len(mfes) if mfes else None
    avg_mae = sum(maes) / len(maes) if maes else None
    return {
        "n_total": n,
        "n_with_return": n_ret,
        "avg_return_pct": avg_ret,
        "median_return_pct": med_ret,
        "win_rate_pct": wr,
        "avg_mfe_pct": avg_mfe,
        "avg_mae_pct": avg_mae,
        "token_count": len(tokens),
        "snapshot_count": len(snapshots),
        "snapshots_present": snapshots,
        "tokens_present": tokens,
        "reliability_label": reliability_label(n_ret, len(snapshots), avg_ret, wr),
    }


def evaluate_group(
    valid_rows_for_horizon: list[dict[str, Any]],
    fields: list[str] | tuple[str, ...],
    horizon: int,
    min_n: int,
) -> list[dict[str, Any]]:
    gkey = _group_key(fields)
    gtype = _group_type(len(fields))

    # Partition by field-value combination.
    buckets: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in valid_rows_for_horizon:
        combo = tuple(str(row.get(f) or "") for f in fields)
        buckets.setdefault(combo, []).append(row)

    result: list[dict[str, Any]] = []
    for combo, bucket_rows in sorted(buckets.items()):
        m = compute_metrics(bucket_rows)
        if m["n_with_return"] < min_n:
            continue
        gval_dict = dict(zip(fields, combo))
        gval_str = "|".join(combo)
        result.append({
            "horizon_hours": horizon,
            "group_type": gtype,
            "group_key": gkey,
            "group_fields": list(fields),
            "group_values": gval_dict,
            "group_values_str": gval_str,
            **m,
        })

    return result


# ---------------------------------------------------------------------------
# Top lists for summary
# ---------------------------------------------------------------------------

def _sortkey_pos(r: dict[str, Any]) -> float:
    return r["avg_return_pct"] if r["avg_return_pct"] is not None else -999.0


def _sortkey_neg(r: dict[str, Any]) -> float:
    return r["avg_return_pct"] if r["avg_return_pct"] is not None else 999.0


def _brief(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "horizon_hours": r["horizon_hours"],
        "group_type": r["group_type"],
        "group_key": r["group_key"],
        "group_values_str": r["group_values_str"],
        "n_with_return": r["n_with_return"],
        "snapshot_count": r["snapshot_count"],
        "avg_return_pct": r["avg_return_pct"],
        "win_rate_pct": r["win_rate_pct"],
        "reliability_label": r["reliability_label"],
    }


def top_by_label(metrics: list[dict[str, Any]], label: str, top_n: int = 8) -> list[dict[str, Any]]:
    rows = [r for r in metrics if r["reliability_label"] == label]
    rows.sort(key=_sortkey_pos, reverse=True)
    return [_brief(r) for r in rows[:top_n]]


def top_positive(metrics: list[dict[str, Any]], gtype: str | None, top_n: int = 5) -> list[dict[str, Any]]:
    rows = [
        r for r in metrics
        if (gtype is None or r["group_type"] == gtype) and r["avg_return_pct"] is not None
    ]
    rows.sort(key=_sortkey_pos, reverse=True)
    return [_brief(r) for r in rows[:top_n]]


def top_negative(metrics: list[dict[str, Any]], gtype: str | None, top_n: int = 5) -> list[dict[str, Any]]:
    rows = [
        r for r in metrics
        if (gtype is None or r["group_type"] == gtype) and r["avg_return_pct"] is not None
    ]
    rows.sort(key=_sortkey_neg)
    return [_brief(r) for r in rows[:top_n]]


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def _fmt(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{float(v):.3f}"


def render_table(summary: dict[str, Any]) -> str:
    lines: list[str] = [
        f"report={REPORT_NAME} version={PARSER_VERSION}",
        "scope=research-only market-only account-agnostic",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        "selection_engine=none advice_engine=none decision_gate=none execution_planner=none executor=none",
        f"sample_limitation={SAMPLE_LIMITATION}",
        f"runtime_promotion_allowed=False  feature_candidate_promotion_allowed=False",
        f"input_outcome_rows={summary['input_outcome_rows']}  "
        f"valid_outcome_rows={summary['valid_outcome_rows']}  "
        f"horizons={summary['horizons_covered']}",
        f"group_definitions={summary['group_definitions']}  "
        f"metric_rows_written={summary['metric_rows_written']}",
        "",
        "--- coverage by horizon ---",
    ]
    for h, cov in summary["coverage_by_horizon"].items():
        lines.append(
            f"  {h}: valid={cov['valid']} no_future={cov['no_future_candle']} snapshots={cov['snapshots']}"
        )

    def _block(label: str, rows: list[dict[str, Any]]) -> None:
        lines.append(f"\n--- {label} ---")
        if not rows:
            lines.append("  (none)")
            return
        for r in rows:
            lines.append(
                f"  [{r['reliability_label']}] h={r['horizon_hours']}h "
                f"{r['group_key']}={r['group_values_str']}  "
                f"n={r['n_with_return']} snaps={r['snapshot_count']} "
                f"avg={_fmt(r['avg_return_pct'])} wr={_fmt(r['win_rate_pct'])}"
            )

    _block("top WATCH_CANDIDATE groups", summary["top_positive_watch_candidates"])
    _block("top NEGATIVE_CANDIDATE groups", summary["top_negative_candidates"])
    _block("strongest single-field groups", summary["strongest_single_fields"])
    _block("strongest two-field interactions", summary["strongest_two_field_interactions"])
    _block("strongest three-field interactions", summary["strongest_three_field_interactions"])
    _block("weakest interactions (most negative)", summary["weakest_interactions"])

    lines += [
        "",
        "--- reliability label counts ---",
    ]
    for lbl, cnt in summary["reliability_label_counts"].items():
        lines.append(f"  {lbl}={cnt}")

    lines += [
        "",
        f"wrote_files={summary['wrote_files']}",
    ]
    if summary["wrote_files"]:
        for k, v in summary["output_paths"].items():
            lines.append(f"  {k}={v}")
    lines.append("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    outcomes_path = Path(args.outcomes_path)
    out_dir = Path(args.output_dir)

    output_paths = {
        "metrics_jsonl": str(out_dir / "interaction_group_metrics_v1.jsonl"),
        "summary_json": str(out_dir / "interaction_discovery_summary_v1.json"),
    }

    if not outcomes_path.exists():
        print(f"ERROR: not found: {outcomes_path}")
        return 2

    all_rows = load_outcomes(outcomes_path)

    valid_rows = [r for r in all_rows if r.get("outcome_status") == "VALID"]
    horizons = sorted({r["horizon_hours"] for r in all_rows})

    # Coverage counts by horizon.
    coverage_by_horizon: dict[str, dict[str, Any]] = {}
    for h in horizons:
        h_rows = [r for r in all_rows if r["horizon_hours"] == h]
        valid_h = [r for r in h_rows if r["outcome_status"] == "VALID"]
        nf_h = sum(1 for r in h_rows if r["outcome_status"] == "NO_FUTURE_CANDLE")
        snaps = sorted({r["snapshot_pair_id"] for r in valid_h})
        coverage_by_horizon[f"horizon_{h}h"] = {
            "total": len(h_rows),
            "valid": len(valid_h),
            "no_future_candle": nf_h,
            "snapshots": snaps,
        }

    # Build all metric rows.
    all_metrics: list[dict[str, Any]] = []
    for h in horizons:
        valid_h = [r for r in valid_rows if r["horizon_hours"] == h]
        if not valid_h:
            continue

        for field in SINGLE_FIELDS:
            all_metrics.extend(evaluate_group(valid_h, [field], h, args.min_n))

        for fields in TWO_FIELD_GROUPS:
            all_metrics.extend(evaluate_group(valid_h, list(fields), h, args.min_n))

        for fields in THREE_FIELD_GROUPS:
            all_metrics.extend(evaluate_group(valid_h, list(fields), h, args.min_n))

    from collections import Counter
    label_counts = dict(Counter(r["reliability_label"] for r in all_metrics))

    summary: dict[str, Any] = {
        "report": REPORT_NAME,
        "parser_version": PARSER_VERSION,
        "scope": "research-only market-only account-agnostic",
        "sample_limitation": SAMPLE_LIMITATION,
        "runtime_promotion_allowed": False,
        "feature_candidate_promotion_allowed": False,
        "outcomes_path": str(outcomes_path),
        "input_outcome_rows": len(all_rows),
        "valid_outcome_rows": len(valid_rows),
        "horizons_covered": horizons,
        "coverage_by_horizon": coverage_by_horizon,
        "group_definitions": GROUP_DEFINITIONS,
        "metric_rows_written": len(all_metrics),
        "reliability_label_counts": label_counts,
        "top_positive_watch_candidates": top_by_label(all_metrics, "WATCH_CANDIDATE", top_n=10),
        "top_negative_candidates": top_by_label(all_metrics, "NEGATIVE_CANDIDATE", top_n=8),
        "strongest_single_fields": top_positive(all_metrics, "single_field", top_n=8),
        "strongest_two_field_interactions": top_positive(all_metrics, "two_field", top_n=8),
        "strongest_three_field_interactions": top_positive(all_metrics, "three_field", top_n=5),
        "weakest_interactions": top_negative(all_metrics, None, top_n=5),
        "output_paths": output_paths,
        "wrote_files": bool(args.write_files),
        "safety_markers": {
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "db_writes": 0,
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

    if args.write_files:
        write_jsonl(Path(output_paths["metrics_jsonl"]), all_metrics)
        write_json(Path(output_paths["summary_json"]), summary)

    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(render_table(summary))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
