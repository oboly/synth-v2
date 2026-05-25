from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any


REPORT_NAME = "strategy_scoreboard_regime_join_v1"
VERSION = "1.0"
DEFAULT_OUTPUT_ROOT = "data/research/strategy_scoreboard_regime_join_v1"
DEFAULT_RUN_DIR_PREFIX = "run_"

ZONE_FIB_FILE = "zone_fib_replay_events_v1.csv"
REGIME_FILE = "discovered_regime_samples_v1.csv"
SCOREBOARD_FILE = "strategy_scoreboard_v1.csv"

EVENTS_CSV = "strategy_scoreboard_regime_join_events_v1.csv"
SUMMARY_BY_TP_ALIGNMENT_REGIME_CSV = "summary_by_tp_alignment_regime_v1.csv"
SUMMARY_BY_SYMBOL_TP_ALIGNMENT_REGIME_CSV = "summary_by_symbol_tp_alignment_regime_v1.csv"
SUMMARY_BY_REGIME_CSV = "summary_by_regime_v1.csv"
MANIFEST_JSON = "manifest_v1.json"

HORIZONS = [4, 8, 12, 24, 48]
FOCUS_BUCKETS = [
    "TP_NEAR_FIB_EXTENSION",
    "TP_FIB_EXTENSION_1272_1618",
    "TP_SR_ONLY",
]

EVENT_FIELDS = [
    "sample_ts_utc",
    "symbol",
    "leg_direction",
    "tp_alignment_label",
    "valid_future_tp_target",
    "discovered_regime_id",
    "discovered_regime_label_auto",
    "forward_return_4h_pct",
    "forward_return_8h_pct",
    "forward_return_12h_pct",
    "forward_return_24h_pct",
    "forward_return_48h_pct",
    "hit_tp_future_strict_4h",
    "hit_tp_future_strict_24h",
    "hit_tp_future_strict_48h",
]

SUMMARY_FIELDS = [
    "tp_alignment_label",
    "symbol",
    "discovered_regime_id",
    "discovered_regime_label_auto",
    "horizon_hours",
    "event_count",
    "avg_return_pct",
    "median_return_pct",
    "winrate_pct",
    "profit_factor",
    "avg_winner_pct",
    "avg_loser_pct",
    "hit_tp_future_strict_4h_rate_pct",
    "hit_tp_future_strict_24h_rate_pct",
    "hit_tp_future_strict_48h_rate_pct",
    "baseline_all_avg_return_pct",
    "excess_vs_regime_baseline_pct",
    "promotion_state_regime_v1",
    "promotion_reason_regime_v1",
]

SAFETY_MARKERS = {
    "db_writes": 0,
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "decision_gate_changes": 0,
    "execution_planner_changes": 0,
    "executor": "none",
    "account_tables_used": False,
}

MIN_SAMPLE_REJECT = 20
MIN_SAMPLE_WATCH = 60
MIN_SAMPLE_CANDIDATE = 150


@dataclass(frozen=True)
class OutputPaths:
    events_csv: Path
    summary_by_tp_alignment_regime_csv: Path
    summary_by_symbol_tp_alignment_regime_csv: Path
    summary_by_regime_csv: Path
    manifest_json: Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Join strategy scoreboard candidate evidence with discovered market regimes "
            "(research-only, file-input-only)."
        )
    )
    parser.add_argument("--zone-fib-run-dir", required=True)
    parser.add_argument("--regime-run-dir", required=True)
    parser.add_argument("--scoreboard-run-dir", required=True)
    parser.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output-root", default=None)
    return parser.parse_args(argv)


def fmt_ts(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def utc_run_id(now_utc: datetime) -> str:
    return now_utc.replace(tzinfo=UTC).strftime("%Y%m%dT%H%M%SZ")


def resolve_output_dir(*, output_root: str | None, run_id: str) -> Path:
    root = Path(output_root) if output_root else Path(DEFAULT_OUTPUT_ROOT)
    return root / f"{DEFAULT_RUN_DIR_PREFIX}{run_id}"


def output_paths(output_dir: Path) -> OutputPaths:
    return OutputPaths(
        events_csv=output_dir / EVENTS_CSV,
        summary_by_tp_alignment_regime_csv=output_dir / SUMMARY_BY_TP_ALIGNMENT_REGIME_CSV,
        summary_by_symbol_tp_alignment_regime_csv=output_dir / SUMMARY_BY_SYMBOL_TP_ALIGNMENT_REGIME_CSV,
        summary_by_regime_csv=output_dir / SUMMARY_BY_REGIME_CSV,
        manifest_json=output_dir / MANIFEST_JSON,
    )


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def to_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except Exception:
        return None


def to_int(value: Any) -> int:
    if value in ("", None):
        return 0
    try:
        return int(float(value))
    except Exception:
        return 0


def format_number(value: float | None, digits: int = 6) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return float(median(values))


def winrate_pct(values: list[float]) -> float | None:
    if not values:
        return None
    return (sum(1 for value in values if value > 0) / len(values)) * 100.0


def profit_factor(values: list[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = sum(-value for value in values if value < 0)
    if gains == 0 and losses == 0:
        return None
    if losses == 0:
        return 999.0
    return gains / losses


def avg_winner(values: list[float]) -> float | None:
    winners = [value for value in values if value > 0]
    return None if not winners else sum(winners) / len(winners)


def avg_loser(values: list[float]) -> float | None:
    losers = [value for value in values if value < 0]
    return None if not losers else sum(losers) / len(losers)


def hit_rate(rows: list[dict[str, str]], field: str) -> float | None:
    values = [to_int(row.get(field)) for row in rows if row.get(field) not in (None, "")]
    if not values:
        return None
    return (sum(values) / len(values)) * 100.0


def classify_regime_promotion(
    *,
    sample_count: int,
    avg_return_pct: float | None,
    median_return_pct: float | None,
    winrate: float | None,
    pf: float | None,
    excess_vs_baseline: float | None,
) -> tuple[str, str]:
    if sample_count < MIN_SAMPLE_REJECT:
        return "REJECT_INSUFFICIENT_SAMPLE", f"sample_count<{MIN_SAMPLE_REJECT}"
    if avg_return_pct is None or excess_vs_baseline is None:
        return "REJECT_NEGATIVE_EXPECTANCY", "Missing return metrics"
    if avg_return_pct <= 0 or excess_vs_baseline <= 0:
        return "REJECT_NEGATIVE_EXPECTANCY", "Non-positive expectancy or no excess vs regime baseline"
    effective_median = 0.0 if median_return_pct is None else median_return_pct
    effective_wr = 0.0 if winrate is None else winrate
    effective_pf = 0.0 if pf is None else pf
    if effective_median <= 0 and not (effective_wr >= 55.0 and effective_pf >= 1.20):
        return "REJECT_NEGATIVE_EXPECTANCY", "Median<=0 without compensating winrate/profit factor"
    if sample_count < MIN_SAMPLE_WATCH:
        return "WATCH_MORE_DATA", f"sample_count<{MIN_SAMPLE_WATCH}"
    if sample_count >= MIN_SAMPLE_CANDIDATE and excess_vs_baseline >= 0.25 and effective_pf >= 1.20 and (effective_median > 0 or effective_wr >= 57.0):
        return "RESEARCH_REGIME_CANDIDATE", "Positive excess return within regime on conservative sample"
    return "WATCH_MORE_DATA", "Positive regime signal but not yet above conservative bar"


def build_summary_rows(
    rows: list[dict[str, str]],
    *,
    group_fields: list[str],
    regime_baseline_by_key: dict[tuple[str, str], float | None],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = tuple(str(row.get(field) or "") for field in group_fields)
        grouped[key].append(row)

    out: list[dict[str, Any]] = []
    for key in sorted(grouped):
        group_rows = grouped[key]
        horizon = str(group_rows[0]["horizon_hours"])
        regime_id = str(group_rows[0]["discovered_regime_id"])
        returns = [to_float(row.get("return_pct")) for row in group_rows]
        returns = [value for value in returns if value is not None]
        avg_return = mean_or_none(returns)
        med_return = median_or_none(returns)
        wr = winrate_pct(returns)
        pf = profit_factor(returns)
        baseline = regime_baseline_by_key.get((regime_id, horizon))
        excess = None if avg_return is None or baseline is None else avg_return - baseline
        promotion_state, promotion_reason = classify_regime_promotion(
            sample_count=len(group_rows),
            avg_return_pct=avg_return,
            median_return_pct=med_return,
            winrate=wr,
            pf=pf,
            excess_vs_baseline=excess,
        )
        out_row = {
            "tp_alignment_label": "",
            "symbol": "",
            "discovered_regime_id": regime_id,
            "discovered_regime_label_auto": str(group_rows[0]["discovered_regime_label_auto"]),
            "horizon_hours": horizon,
            "event_count": len(group_rows),
            "avg_return_pct": avg_return,
            "median_return_pct": med_return,
            "winrate_pct": wr,
            "profit_factor": pf,
            "avg_winner_pct": avg_winner(returns),
            "avg_loser_pct": avg_loser(returns),
            "hit_tp_future_strict_4h_rate_pct": hit_rate(group_rows, "hit_tp_future_strict_4h"),
            "hit_tp_future_strict_24h_rate_pct": hit_rate(group_rows, "hit_tp_future_strict_24h"),
            "hit_tp_future_strict_48h_rate_pct": hit_rate(group_rows, "hit_tp_future_strict_48h"),
            "baseline_all_avg_return_pct": baseline,
            "excess_vs_regime_baseline_pct": excess,
            "promotion_state_regime_v1": promotion_state,
            "promotion_reason_regime_v1": promotion_reason,
        }
        for idx, field in enumerate(group_fields):
            out_row[field] = key[idx]
        out.append(out_row)
    return out


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            normalized = {}
            for field in fields:
                value = row.get(field)
                if isinstance(value, float):
                    normalized[field] = format_number(value)
                else:
                    normalized[field] = value
            writer.writerow(normalized)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_started_at = datetime.now(UTC)
    run_id = utc_run_id(run_started_at)

    zone_fib_run_dir = Path(args.zone_fib_run_dir)
    regime_run_dir = Path(args.regime_run_dir)
    scoreboard_run_dir = Path(args.scoreboard_run_dir)

    zone_fib_path = zone_fib_run_dir / ZONE_FIB_FILE
    regime_path = regime_run_dir / REGIME_FILE
    scoreboard_path = scoreboard_run_dir / SCOREBOARD_FILE
    for path in [zone_fib_path, regime_path, scoreboard_path]:
        if not path.exists():
            raise FileNotFoundError(f"Missing required input file: {path}")

    zone_rows = read_csv_rows(zone_fib_path)
    regime_rows = read_csv_rows(regime_path)
    scoreboard_rows = read_csv_rows(scoreboard_path)

    scoreboard_focus_keys = {
        row["strategy_key"]
        for row in scoreboard_rows
        if row.get("strategy_family") == "TP_ALIGNMENT_STRICT_FUTURE"
        and row.get("signal_bucket") in FOCUS_BUCKETS
    }

    regime_by_ts = {
        str(row["sample_ts_utc"]): row
        for row in regime_rows
    }

    joined_events: list[dict[str, Any]] = []
    unmatched_zone_rows = 0
    for row in zone_rows:
        if str(row.get("tp_alignment_label") or "") not in FOCUS_BUCKETS:
            continue
        if to_int(row.get("valid_future_tp_target")) != 1:
            continue
        regime = regime_by_ts.get(str(row.get("sample_ts_utc") or ""))
        if regime is None:
            unmatched_zone_rows += 1
            continue
        joined_events.append(
            {
                "sample_ts_utc": row["sample_ts_utc"],
                "symbol": str(row.get("symbol") or "").upper(),
                "leg_direction": str(row.get("leg_direction") or "").upper(),
                "tp_alignment_label": str(row.get("tp_alignment_label") or ""),
                "valid_future_tp_target": to_int(row.get("valid_future_tp_target")),
                "discovered_regime_id": str(regime.get("discovered_regime_id") or ""),
                "discovered_regime_label_auto": str(regime.get("discovered_regime_label_auto") or ""),
                "forward_return_4h_pct": row.get("forward_return_4h_pct", ""),
                "forward_return_8h_pct": row.get("forward_return_8h_pct", ""),
                "forward_return_12h_pct": row.get("forward_return_12h_pct", ""),
                "forward_return_24h_pct": row.get("forward_return_24h_pct", ""),
                "forward_return_48h_pct": row.get("forward_return_48h_pct", ""),
                "hit_tp_future_strict_4h": row.get("hit_tp_future_strict_4h", ""),
                "hit_tp_future_strict_24h": row.get("hit_tp_future_strict_24h", ""),
                "hit_tp_future_strict_48h": row.get("hit_tp_future_strict_48h", ""),
            }
        )

    expanded_rows: list[dict[str, Any]] = []
    for event in joined_events:
        for horizon in HORIZONS:
            return_value = to_float(event.get(f"forward_return_{horizon}h_pct"))
            if return_value is None:
                continue
            expanded_rows.append(
                {
                    **event,
                    "horizon_hours": str(horizon),
                    "return_pct": return_value,
                }
            )

    regime_baseline_by_key: dict[tuple[str, str], float | None] = {}
    regime_grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in expanded_rows:
        regime_grouped[(str(row["discovered_regime_id"]), str(row["horizon_hours"]))].append(row)
    for key, rows in regime_grouped.items():
        returns = [float(row["return_pct"]) for row in rows]
        regime_baseline_by_key[key] = mean_or_none(returns)

    summary_by_tp_alignment_regime = build_summary_rows(
        expanded_rows,
        group_fields=["tp_alignment_label", "discovered_regime_id", "discovered_regime_label_auto", "horizon_hours"],
        regime_baseline_by_key=regime_baseline_by_key,
    )
    summary_by_symbol_tp_alignment_regime = build_summary_rows(
        expanded_rows,
        group_fields=["symbol", "tp_alignment_label", "discovered_regime_id", "discovered_regime_label_auto", "horizon_hours"],
        regime_baseline_by_key=regime_baseline_by_key,
    )
    summary_by_regime = build_summary_rows(
        expanded_rows,
        group_fields=["discovered_regime_id", "discovered_regime_label_auto", "horizon_hours"],
        regime_baseline_by_key=regime_baseline_by_key,
    )

    output_dir = resolve_output_dir(output_root=args.output_root, run_id=run_id)
    paths = output_paths(output_dir)
    manifest = {
        "report": REPORT_NAME,
        "version": VERSION,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "zone_fib_run_dir": str(zone_fib_run_dir),
        "regime_run_dir": str(regime_run_dir),
        "scoreboard_run_dir": str(scoreboard_run_dir),
        "zone_input_rows": len(zone_rows),
        "regime_input_rows": len(regime_rows),
        "scoreboard_input_rows": len(scoreboard_rows),
        "joined_event_count": len(joined_events),
        "expanded_metric_rows": len(expanded_rows),
        "unmatched_zone_rows": unmatched_zone_rows,
        "focus_scoreboard_keys": sorted(scoreboard_focus_keys),
        "output_files": {
            "strategy_scoreboard_regime_join_events_v1_csv": str(paths.events_csv),
            "summary_by_tp_alignment_regime_v1_csv": str(paths.summary_by_tp_alignment_regime_csv),
            "summary_by_symbol_tp_alignment_regime_v1_csv": str(paths.summary_by_symbol_tp_alignment_regime_csv),
            "summary_by_regime_v1_csv": str(paths.summary_by_regime_csv),
            "manifest_v1_json": str(paths.manifest_json),
        },
        **SAFETY_MARKERS,
    }

    if args.write_files:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(paths.events_csv, joined_events, EVENT_FIELDS)
        write_csv(paths.summary_by_tp_alignment_regime_csv, summary_by_tp_alignment_regime, SUMMARY_FIELDS)
        write_csv(paths.summary_by_symbol_tp_alignment_regime_csv, summary_by_symbol_tp_alignment_regime, SUMMARY_FIELDS)
        write_csv(paths.summary_by_regime_csv, summary_by_regime, SUMMARY_FIELDS)
        paths.manifest_json.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"[RUN][ID] {run_id}")
    print(f"[RUN][OUT_DIR] {output_dir}")
    print(f"report={REPORT_NAME} version={VERSION}")
    print("scope=research/reporting only file-input-only")
    print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 decision_gate_changes=0 execution_planner_changes=0 executor=none account_tables_used=false")
    print(f"joined_event_count={len(joined_events)} expanded_metric_rows={len(expanded_rows)} unmatched_zone_rows={unmatched_zone_rows}")
    if args.write_files:
        for path in [
            paths.events_csv,
            paths.summary_by_tp_alignment_regime_csv,
            paths.summary_by_symbol_tp_alignment_regime_csv,
            paths.summary_by_regime_csv,
            paths.manifest_json,
        ]:
            print(f"wrote_files={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
