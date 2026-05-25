from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any


REPORT_NAME = "strategy_scoreboard_v1"
VERSION = "1.0"
DEFAULT_OUTPUT_ROOT = "data/research/strategy_scoreboard_v1"
DEFAULT_RUN_DIR_PREFIX = "run_"

ZONE_FIB_ROOT = Path("data/research/historical_zone_fib_replay_audit_v1")
ROTATION_ROOT = Path("data/research/rotation_destination_historical_replay_audit_v2")
ZONE_FIB_EVENTS_FILE = "zone_fib_replay_events_v1.csv"
ROTATION_EVENTS_FILE = "event_table_dedup_destination_historical_replay_v2.csv"

SCOREBOARD_CSV = "strategy_scoreboard_v1.csv"
SCOREBOARD_JSONL = "strategy_scoreboard_v1.jsonl"
SCOREBOARD_HTML = "strategy_scoreboard_v1.html"
INPUTS_MANIFEST_JSON = "scoreboard_inputs_manifest_v1.json"
MANIFEST_JSON = "manifest_v1.json"

FEE_SLIPPAGE_PLACEHOLDER_BPS = 25
MIN_SAMPLE_REJECT = 30
MIN_SAMPLE_WATCH = 100
MIN_SAMPLE_PROMOTION = 250
MIN_SAMPLE_READY = 500

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

HORIZONS = [4, 8, 12, 24, 48]

SCOREBOARD_FIELDS = [
    "strategy_key",
    "strategy_family",
    "signal_bucket",
    "horizon_hours",
    "sample_count",
    "avg_return_pct",
    "median_return_pct",
    "winrate_pct",
    "profit_factor",
    "max_drawdown_pct",
    "avg_winner_pct",
    "avg_loser_pct",
    "baseline_buy_hold_avg_pct",
    "excess_return_vs_baseline_pct",
    "hit_tp_future_strict_4h_rate_pct",
    "hit_tp_future_strict_24h_rate_pct",
    "hit_tp_future_strict_48h_rate_pct",
    "fee_slippage_placeholder_bps",
    "promotion_state",
    "promotion_reason",
]


@dataclass(frozen=True)
class OutputPaths:
    scoreboard_csv: Path
    scoreboard_jsonl: Path
    scoreboard_html: Path
    inputs_manifest_json: Path
    manifest_json: Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a research strategy scoreboard from replay/backtest outputs "
            "(research-only, no runtime writes)."
        )
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--start-ts", default=None)
    parser.add_argument("--end-ts", default=None)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--zone-fib-run-dir", default=None)
    parser.add_argument("--rotation-run-dir", default=None)
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output-root", default=None)
    return parser.parse_args(argv)


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC).replace(tzinfo=None)
    return parsed.astimezone(UTC).replace(tzinfo=None)


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
        scoreboard_csv=output_dir / SCOREBOARD_CSV,
        scoreboard_jsonl=output_dir / SCOREBOARD_JSONL,
        scoreboard_html=output_dir / SCOREBOARD_HTML,
        inputs_manifest_json=output_dir / INPUTS_MANIFEST_JSON,
        manifest_json=output_dir / MANIFEST_JSON,
    )


def esc(text: Any) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def format_number(value: Any, places: int = 4) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.{places}f}"
    except Exception:
        return str(value)


def latest_run_dir(root: Path) -> Path | None:
    if not root.exists():
        return None
    candidates = sorted([path for path in root.iterdir() if path.is_dir() and path.name.startswith("run_")])
    return None if not candidates else candidates[-1]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def parse_symbols(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {piece.strip().upper() for piece in str(value).split(",") if piece.strip()}


def coerce_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except Exception:
        return None


def coerce_int(value: Any) -> int:
    if value in ("", None):
        return 0
    try:
        return int(float(value))
    except Exception:
        return 0


def filter_zone_fib_rows(
    rows: list[dict[str, str]],
    *,
    start_ts: datetime | None,
    end_ts: datetime | None,
    symbols: set[str] | None,
    max_samples: int,
) -> list[dict[str, str]]:
    prefiltered: list[dict[str, str]] = []
    for row in rows:
        sample_raw = row.get("sample_ts_utc")
        sample_dt = parse_ts(sample_raw)
        if sample_dt is None:
            continue
        if start_ts and sample_dt < start_ts:
            continue
        if end_ts and sample_dt > end_ts:
            continue
        symbol = str(row.get("symbol") or "").upper()
        if symbols and symbol not in symbols:
            continue
        prefiltered.append(row)
    allowed_samples: set[str] | None = None
    if max_samples > 0:
        sample_values = sorted({row["sample_ts_utc"] for row in prefiltered if row.get("sample_ts_utc")})
        allowed_samples = set(sample_values[:max_samples])
    if allowed_samples is None:
        return prefiltered
    return [row for row in prefiltered if row.get("sample_ts_utc") in allowed_samples]


def raw_buy_hold_return(row: dict[str, str], horizon_hours: int) -> float | None:
    value = coerce_float(row.get(f"forward_return_{horizon_hours}h_pct"))
    if value is None:
        return None
    leg = str(row.get("leg_direction") or "").upper()
    return value if leg == "UP" else -value if leg == "DOWN" else value


def profit_factor(values: list[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = sum(-value for value in values if value < 0)
    if gains == 0 and losses == 0:
        return None
    if losses == 0:
        return 999.0
    return gains / losses


def max_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in values:
        equity *= max(0.0001, 1.0 + (value / 100.0))
        peak = max(peak, equity)
        drawdown = ((equity / peak) - 1.0) * 100.0
        worst = min(worst, drawdown)
    return worst


def summarize_return_metrics(values: list[float]) -> dict[str, float | None]:
    positives = [value for value in values if value > 0]
    negatives = [value for value in values if value < 0]
    return {
        "sample_count": len(values),
        "avg_return_pct": None if not values else sum(values) / len(values),
        "median_return_pct": None if not values else float(median(values)),
        "winrate_pct": None if not values else (len(positives) / len(values)) * 100.0,
        "profit_factor": profit_factor(values),
        "max_drawdown_pct": max_drawdown(values),
        "avg_winner_pct": None if not positives else sum(positives) / len(positives),
        "avg_loser_pct": None if not negatives else sum(negatives) / len(negatives),
    }


def average_int_rate(rows: list[dict[str, str]], field: str) -> float | None:
    values = [coerce_int(row.get(field)) for row in rows if row.get(field) not in (None, "")]
    if not values:
        return None
    return (sum(values) / len(values)) * 100.0


def promotion_state_rank(value: str) -> int:
    order = {
        "READY_FOR_PAPER_ONLY": 0,
        "RESEARCH_PROMOTION_CANDIDATE": 1,
        "WATCH_MORE_DATA": 2,
        "BLOCKED_NEEDS_REPLAY_SAFE_VALIDATION": 3,
        "REJECT_NEGATIVE_EXPECTANCY": 4,
        "REJECT_INSUFFICIENT_SAMPLE": 5,
    }
    return order.get(value, 99)


def classify_promotion(
    *,
    family: str,
    signal_bucket: str,
    sample_count: int,
    avg_return_pct: float | None,
    median_return_pct: float | None,
    winrate_pct: float | None,
    profit_factor_value: float | None,
    excess_return_vs_baseline_pct: float | None,
) -> tuple[str, str]:
    if family == "BUY_AND_HOLD_BASELINE":
        return "BLOCKED_NEEDS_REPLAY_SAFE_VALIDATION", "Baseline comparator only"
    if sample_count < MIN_SAMPLE_REJECT:
        return "REJECT_INSUFFICIENT_SAMPLE", f"sample_count<{MIN_SAMPLE_REJECT}"
    if family in {"TP_ALIGNMENT", "TP_SIDE"}:
        return "BLOCKED_NEEDS_REPLAY_SAFE_VALIDATION", "Use strict-future-valid rows before promotion"
    if family == "VALID_FUTURE_TP_TARGET" and signal_bucket != "VALID":
        return "BLOCKED_NEEDS_REPLAY_SAFE_VALIDATION", "Invalid future TP targets are diagnostic only"
    if avg_return_pct is None or excess_return_vs_baseline_pct is None:
        return "REJECT_NEGATIVE_EXPECTANCY", "Missing expectancy metrics"
    if avg_return_pct <= 0 or excess_return_vs_baseline_pct <= 0:
        return "REJECT_NEGATIVE_EXPECTANCY", "Non-positive expectancy or no excess vs buy-and-hold"
    pf = 0.0 if profit_factor_value is None else profit_factor_value
    wr = 0.0 if winrate_pct is None else winrate_pct
    med = 0.0 if median_return_pct is None else median_return_pct
    if med <= 0 and not (wr >= 55.0 and pf >= 1.20):
        return "REJECT_NEGATIVE_EXPECTANCY", "Median<=0 without compensating winrate/profit factor"
    if sample_count < MIN_SAMPLE_WATCH:
        return "WATCH_MORE_DATA", f"sample_count<{MIN_SAMPLE_WATCH}"
    if sample_count >= MIN_SAMPLE_READY and excess_return_vs_baseline_pct >= 0.75 and pf >= 1.40 and wr >= 60.0 and med > 0:
        return "READY_FOR_PAPER_ONLY", "Conservative paper-only threshold met"
    if sample_count >= MIN_SAMPLE_PROMOTION and excess_return_vs_baseline_pct >= 0.35 and pf >= 1.20 and (med > 0 or wr >= 57.0):
        return "RESEARCH_PROMOTION_CANDIDATE", "Positive excess return with conservative sample and quality"
    return "WATCH_MORE_DATA", "Positive signal but not yet above conservative promotion bar"


def build_row(
    *,
    family: str,
    signal_bucket: str,
    horizon_hours: int,
    rows: list[dict[str, str]],
    return_values: list[float],
    baseline_values: list[float],
) -> dict[str, Any]:
    metrics = summarize_return_metrics(return_values)
    baseline_avg = None if not baseline_values else sum(baseline_values) / len(baseline_values)
    avg_return = metrics["avg_return_pct"]
    excess = None if avg_return is None or baseline_avg is None else avg_return - baseline_avg
    promotion_state, promotion_reason = classify_promotion(
        family=family,
        signal_bucket=signal_bucket,
        sample_count=int(metrics["sample_count"]),
        avg_return_pct=avg_return,
        median_return_pct=metrics["median_return_pct"],
        winrate_pct=metrics["winrate_pct"],
        profit_factor_value=metrics["profit_factor"],
        excess_return_vs_baseline_pct=excess,
    )
    return {
        "strategy_key": f"{family}|{signal_bucket}|{horizon_hours}h",
        "strategy_family": family,
        "signal_bucket": signal_bucket,
        "horizon_hours": horizon_hours,
        "sample_count": metrics["sample_count"],
        "avg_return_pct": metrics["avg_return_pct"],
        "median_return_pct": metrics["median_return_pct"],
        "winrate_pct": metrics["winrate_pct"],
        "profit_factor": metrics["profit_factor"],
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "avg_winner_pct": metrics["avg_winner_pct"],
        "avg_loser_pct": metrics["avg_loser_pct"],
        "baseline_buy_hold_avg_pct": baseline_avg,
        "excess_return_vs_baseline_pct": excess,
        "hit_tp_future_strict_4h_rate_pct": average_int_rate(rows, "hit_tp_future_strict_4h"),
        "hit_tp_future_strict_24h_rate_pct": average_int_rate(rows, "hit_tp_future_strict_24h"),
        "hit_tp_future_strict_48h_rate_pct": average_int_rate(rows, "hit_tp_future_strict_48h"),
        "fee_slippage_placeholder_bps": FEE_SLIPPAGE_PLACEHOLDER_BPS,
        "promotion_state": promotion_state,
        "promotion_reason": promotion_reason,
    }


def build_zone_fib_scoreboard_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    scoreboard_rows: list[dict[str, Any]] = []

    def returns_for(group_rows: list[dict[str, str]], horizon_hours: int) -> list[float]:
        values = [coerce_float(row.get(f"forward_return_{horizon_hours}h_pct")) for row in group_rows]
        return [value for value in values if value is not None]

    def baselines_for(group_rows: list[dict[str, str]], horizon_hours: int) -> list[float]:
        values = [raw_buy_hold_return(row, horizon_hours) for row in group_rows]
        return [value for value in values if value is not None]

    for horizon in HORIZONS:
        horizon_rows = [row for row in rows if coerce_float(row.get(f"forward_return_{horizon}h_pct")) is not None]
        if not horizon_rows:
            continue
        baseline_values = baselines_for(horizon_rows, horizon)
        scoreboard_rows.append(
            build_row(
                family="BUY_AND_HOLD_BASELINE",
                signal_bucket="ALL",
                horizon_hours=horizon,
                rows=horizon_rows,
                return_values=baseline_values,
                baseline_values=baseline_values,
            )
        )

        for bucket in sorted({str(row.get("tp_alignment_label") or "") for row in horizon_rows if row.get("tp_alignment_label")}):
            group_rows = [row for row in horizon_rows if str(row.get("tp_alignment_label") or "") == bucket]
            scoreboard_rows.append(
                build_row(
                    family="TP_ALIGNMENT",
                    signal_bucket=bucket,
                    horizon_hours=horizon,
                    rows=group_rows,
                    return_values=returns_for(group_rows, horizon),
                    baseline_values=baselines_for(group_rows, horizon),
                )
            )

        strict_rows = [
            row
            for row in horizon_rows
            if coerce_int(row.get("valid_future_tp_target")) == 1
            and str(row.get("tp_alignment_label") or "") in {
                "TP_NEAR_FIB_EXTENSION",
                "TP_FIB_EXTENSION_1272_1618",
                "TP_SR_ONLY",
            }
        ]
        for bucket in sorted({str(row.get("tp_alignment_label") or "") for row in strict_rows if row.get("tp_alignment_label")}):
            group_rows = [row for row in strict_rows if str(row.get("tp_alignment_label") or "") == bucket]
            scoreboard_rows.append(
                build_row(
                    family="TP_ALIGNMENT_STRICT_FUTURE",
                    signal_bucket=bucket,
                    horizon_hours=horizon,
                    rows=group_rows,
                    return_values=returns_for(group_rows, horizon),
                    baseline_values=baselines_for(group_rows, horizon),
                )
            )

        for bucket in ["TP_ABOVE_PRICE", "TP_BELOW_PRICE", "TP_WRONG_SIDE_FOR_LEG", "TP_AT_OR_NEAR_PRICE"]:
            group_rows = [row for row in horizon_rows if str(row.get("tp_side_label") or "") == bucket]
            if not group_rows:
                continue
            scoreboard_rows.append(
                build_row(
                    family="TP_SIDE",
                    signal_bucket=bucket,
                    horizon_hours=horizon,
                    rows=group_rows,
                    return_values=returns_for(group_rows, horizon),
                    baseline_values=baselines_for(group_rows, horizon),
                )
            )

        for bucket_value, bucket_label in [(1, "VALID"), (0, "INVALID")]:
            group_rows = [row for row in horizon_rows if coerce_int(row.get("valid_future_tp_target")) == bucket_value]
            if not group_rows:
                continue
            scoreboard_rows.append(
                build_row(
                    family="VALID_FUTURE_TP_TARGET",
                    signal_bucket=bucket_label,
                    horizon_hours=horizon,
                    rows=group_rows,
                    return_values=returns_for(group_rows, horizon),
                    baseline_values=baselines_for(group_rows, horizon),
                )
            )

    return [row for row in scoreboard_rows if int(row["sample_count"]) > 0]


def render_html(rows: list[dict[str, Any]], *, inputs_manifest: dict[str, Any]) -> str:
    headers = [
        "Promotion",
        "Family",
        "Bucket",
        "H",
        "Samples",
        "Avg %",
        "Median %",
        "Winrate %",
        "PF",
        "Max DD %",
        "Baseline %",
        "Excess %",
        "Strict Hit 4h %",
        "Strict Hit 24h %",
        "Strict Hit 48h %",
        "Reason",
    ]
    table_rows: list[str] = []
    for row in rows:
        table_rows.append(
            "<tr>"
            f"<td>{esc(row['promotion_state'])}</td>"
            f"<td>{esc(row['strategy_family'])}</td>"
            f"<td>{esc(row['signal_bucket'])}</td>"
            f"<td>{esc(row['horizon_hours'])}</td>"
            f"<td>{esc(row['sample_count'])}</td>"
            f"<td>{esc(format_number(row['avg_return_pct'], 3))}</td>"
            f"<td>{esc(format_number(row['median_return_pct'], 3))}</td>"
            f"<td>{esc(format_number(row['winrate_pct'], 2))}</td>"
            f"<td>{esc(format_number(row['profit_factor'], 3))}</td>"
            f"<td>{esc(format_number(row['max_drawdown_pct'], 2))}</td>"
            f"<td>{esc(format_number(row['baseline_buy_hold_avg_pct'], 3))}</td>"
            f"<td>{esc(format_number(row['excess_return_vs_baseline_pct'], 3))}</td>"
            f"<td>{esc(format_number(row['hit_tp_future_strict_4h_rate_pct'], 2))}</td>"
            f"<td>{esc(format_number(row['hit_tp_future_strict_24h_rate_pct'], 2))}</td>"
            f"<td>{esc(format_number(row['hit_tp_future_strict_48h_rate_pct'], 2))}</td>"
            f"<td>{esc(row['promotion_reason'])}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Strategy Scoreboard V1</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; background: #0f172a; color: #e5e7eb; }}
    .note {{ margin-bottom: 18px; padding: 12px 14px; background: #111827; border: 1px solid #334155; }}
    .meta {{ color: #94a3b8; font-size: 13px; margin-bottom: 18px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border: 1px solid #334155; padding: 8px; text-align: left; }}
    th {{ background: #1e293b; position: sticky; top: 0; }}
    tr:nth-child(even) {{ background: rgba(30, 41, 59, 0.35); }}
  </style>
</head>
<body>
  <h1>Strategy Scoreboard V1</h1>
  <div class="note"><strong>Research scoreboard only. No row is a trade instruction.</strong></div>
  <div class="meta">
    zone_fib_run_dir={esc(inputs_manifest.get('zone_fib_run_dir') or '')}<br>
    rotation_run_dir={esc(inputs_manifest.get('rotation_run_dir') or '')}<br>
    filtered_event_count={esc(inputs_manifest.get('zone_fib_filtered_event_count') or 0)}
  </div>
  <table>
    <thead><tr>{''.join(f'<th>{esc(header)}</th>' for header in headers)}</tr></thead>
    <tbody>
      {''.join(table_rows)}
    </tbody>
  </table>
</body>
</html>"""


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_started_at = datetime.now(UTC)
    run_id = utc_run_id(run_started_at)

    start_ts = parse_ts(args.start_ts)
    end_ts = parse_ts(args.end_ts)
    symbols = parse_symbols(args.symbols)

    zone_fib_run_dir = Path(args.zone_fib_run_dir) if args.zone_fib_run_dir else latest_run_dir(ZONE_FIB_ROOT)
    if zone_fib_run_dir is None:
        raise FileNotFoundError("No historical_zone_fib_replay_audit_v1 run directory found")
    zone_fib_events_path = zone_fib_run_dir / ZONE_FIB_EVENTS_FILE
    if not zone_fib_events_path.exists():
        raise FileNotFoundError(f"Missing zone-fib events file: {zone_fib_events_path}")

    rotation_run_dir = None if not args.rotation_run_dir else Path(args.rotation_run_dir)
    rotation_events_path = None
    rotation_rows_loaded = 0
    if rotation_run_dir is not None:
        rotation_events_path = rotation_run_dir / ROTATION_EVENTS_FILE
        if rotation_events_path.exists():
            rotation_rows_loaded = len(read_csv_rows(rotation_events_path))

    zone_fib_rows = read_csv_rows(zone_fib_events_path)
    filtered_zone_fib_rows = filter_zone_fib_rows(
        zone_fib_rows,
        start_ts=start_ts,
        end_ts=end_ts,
        symbols=symbols,
        max_samples=args.max_samples,
    )

    scoreboard_rows = build_zone_fib_scoreboard_rows(filtered_zone_fib_rows)
    scoreboard_rows.sort(
        key=lambda row: (
            promotion_state_rank(str(row["promotion_state"])),
            -(float(row["excess_return_vs_baseline_pct"]) if row["excess_return_vs_baseline_pct"] is not None else -999999.0),
            -int(row["sample_count"]),
            str(row["strategy_family"]),
            str(row["signal_bucket"]),
            int(row["horizon_hours"]),
        )
    )

    output_dir = resolve_output_dir(output_root=args.output_root, run_id=run_id)
    outputs = output_paths(output_dir)

    inputs_manifest = {
        "report": "scoreboard_inputs_manifest_v1",
        "zone_fib_run_dir": str(zone_fib_run_dir),
        "zone_fib_events_path": str(zone_fib_events_path),
        "zone_fib_input_event_count": len(zone_fib_rows),
        "zone_fib_filtered_event_count": len(filtered_zone_fib_rows),
        "rotation_run_dir": None if rotation_run_dir is None else str(rotation_run_dir),
        "rotation_events_path": None if rotation_events_path is None else str(rotation_events_path),
        "rotation_rows_loaded": rotation_rows_loaded,
        "rotation_rows_used_in_v1": 0,
        "start_ts": fmt_ts(start_ts),
        "end_ts": fmt_ts(end_ts),
        "symbols": [] if symbols is None else sorted(symbols),
        "max_samples": args.max_samples,
    }
    manifest = {
        "report": REPORT_NAME,
        "version": VERSION,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "run_started_at_utc": fmt_ts(run_started_at),
        "run_finished_at_utc": fmt_ts(datetime.now(UTC)),
        "zone_fib_run_dir": str(zone_fib_run_dir),
        "rotation_run_dir": None if rotation_run_dir is None else str(rotation_run_dir),
        "scoreboard_rows": len(scoreboard_rows),
        "zone_fib_input_event_count": len(zone_fib_rows),
        "zone_fib_filtered_event_count": len(filtered_zone_fib_rows),
        "rotation_rows_loaded": rotation_rows_loaded,
        "rotation_rows_used_in_v1": 0,
        "source_file_based": True,
        "output_files": {
            "strategy_scoreboard_v1_csv": str(outputs.scoreboard_csv),
            "strategy_scoreboard_v1_jsonl": str(outputs.scoreboard_jsonl),
            "strategy_scoreboard_v1_html": str(outputs.scoreboard_html),
            "scoreboard_inputs_manifest_v1_json": str(outputs.inputs_manifest_json),
            "manifest_v1_json": str(outputs.manifest_json),
        },
        **SAFETY_MARKERS,
    }

    if args.write_files:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(outputs.scoreboard_csv, scoreboard_rows, SCOREBOARD_FIELDS)
        write_jsonl(outputs.scoreboard_jsonl, scoreboard_rows)
        outputs.scoreboard_html.write_text(render_html(scoreboard_rows, inputs_manifest=inputs_manifest), encoding="utf-8")
        outputs.inputs_manifest_json.write_text(json.dumps(inputs_manifest, indent=2, sort_keys=True), encoding="utf-8")
        outputs.manifest_json.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    print(f"[RUN][ID] {run_id}")
    print(f"[RUN][OUT_DIR] {output_dir}")
    print(f"report={REPORT_NAME} version={VERSION}")
    print("scope=research/reporting only")
    print("source=file-based replay outputs")
    print(
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 "
        "decision_gate_changes=0 execution_planner_changes=0 executor=none account_tables_used=false"
    )
    print(f"scoreboard_rows={len(scoreboard_rows)} zone_fib_filtered_event_count={len(filtered_zone_fib_rows)}")
    if args.write_files:
        for path in [
            outputs.scoreboard_csv,
            outputs.scoreboard_jsonl,
            outputs.scoreboard_html,
            outputs.inputs_manifest_json,
            outputs.manifest_json,
        ]:
            print(f"wrote_files={path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
