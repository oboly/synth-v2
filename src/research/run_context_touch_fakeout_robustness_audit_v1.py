from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.research.run_context_quality_tier_outcome_evaluation_v1 import (
    SAFETY_MARKERS,
    _floats,
    _mfe_mae_ratio,
    read_csv_rows,
)
from src.research.run_context_touch_fakeout_shape_audit_v1 import (
    RETURN_4H,
    RETURN_24H,
    bool_bucket,
)
from src.research.run_symbol_reaction_profile_by_context_v1 import (
    as_float,
    parse_symbols_arg,
    parse_ts,
    sample_quality,
    write_csv,
    write_json,
)


REPORT_NAME = "context_touch_fakeout_robustness_audit_v1"
REPORT_VERSION = "1.0"

DEFAULT_EVENT_LEVEL_ROWS = Path(
    "data/research/event_level_symbol_reaction_profile_by_context_v1_event_range/"
    "event_level_symbol_reaction_profile_by_context_rows_v1.csv"
)
DEFAULT_OUTPUT_DIR = Path("data/research/context_touch_fakeout_robustness_audit_v1")

ROBUSTNESS_ROWS_CSV = "context_touch_fakeout_robustness_rows_v1.csv"
LEAVE_ONE_SYMBOL_ROWS_CSV = "context_touch_fakeout_leave_one_symbol_rows_v1.csv"
LEAVE_ONE_TIME_ROWS_CSV = "context_touch_fakeout_leave_one_time_rows_v1.csv"
MANIFEST_JSON = "manifest_v1.json"

TARGET_TIER = "MARKET_ONLY_CONTEXT"
TARGET_TOUCH = "TRUE"
TARGET_FAKEOUT = "FALSE"
TIME_BUCKET_DAYS = 3


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit robustness of MARKET_ONLY_CONTEXT + touch=TRUE + fakeout=FALSE "
            "(research-only, no DB writes, no strategy promotion)."
        )
    )
    parser.add_argument("--event-level-rows", default=str(DEFAULT_EVENT_LEVEL_ROWS))
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--min-events", type=int, default=5)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def load_event_rows(path: Path, symbols: set[str] | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Event-level rows not found: {path}")
    out: list[dict[str, Any]] = []
    for row in read_csv_rows(path):
        symbol = str(row.get("symbol") or "").strip().upper()
        event_ts = parse_ts(row.get("event_ts_utc"))
        if not symbol or event_ts is None:
            continue
        if symbols is not None and symbol not in symbols:
            continue
        item = dict(row)
        item["symbol"] = symbol
        item["event_ts_utc_dt"] = event_ts
        out.append(item)
    return out


def target_shape_filter(row: dict[str, Any]) -> bool:
    return (
        str(row.get("context_quality_tier") or "").strip().upper() == TARGET_TIER
        and bool_bucket(row.get("reaction_zone_touch")) == TARGET_TOUCH
        and bool_bucket(row.get("fakeout_flag")) == TARGET_FAKEOUT
    )


def bucket_start(ts: datetime) -> str:
    base = datetime(1970, 1, 1)
    delta_days = (ts.date() - base.date()).days
    bucket_days = delta_days - (delta_days % TIME_BUCKET_DAYS)
    bucket = datetime.combine(base.date() + timedelta(days=bucket_days), datetime.min.time())
    return bucket.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def target_rows(event_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in event_rows if target_shape_filter(row)]


def mean_metric(rows: list[dict[str, Any]], field: str) -> float | None:
    return _avg(_floats(rows, field))


def baseline_summary(rows: list[dict[str, Any]], min_events: int) -> dict[str, Any]:
    avg_mfe = mean_metric(rows, "max_favorable_excursion_pct")
    avg_mae = mean_metric(rows, "max_adverse_excursion_pct")
    avg_r4h = mean_metric(rows, RETURN_4H)
    avg_r24h = mean_metric(rows, RETURN_24H)
    top_symbol_counts: dict[str, int] = defaultdict(int)
    top_symbol_return_sum: dict[str, float] = defaultdict(float)
    top_bucket_counts: dict[str, int] = defaultdict(int)
    top_bucket_return_sum: dict[str, float] = defaultdict(float)
    total_return_sum = 0.0
    for row in rows:
        symbol = row["symbol"]
        bucket = bucket_start(row["event_ts_utc_dt"])
        top_symbol_counts[symbol] += 1
        top_bucket_counts[bucket] += 1
        r24 = as_float(row.get(RETURN_24H)) or 0.0
        top_symbol_return_sum[symbol] += r24
        top_bucket_return_sum[bucket] += r24
        total_return_sum += r24
    top_symbol = max(top_symbol_counts, key=top_symbol_counts.get) if top_symbol_counts else None
    top_bucket = max(top_bucket_counts, key=top_bucket_counts.get) if top_bucket_counts else None
    return {
        "context_quality_tier": TARGET_TIER,
        "reaction_zone_touch": TARGET_TOUCH,
        "fakeout_flag": TARGET_FAKEOUT,
        "event_count": len(rows),
        "avg_return_4h_pct": avg_r4h,
        "avg_return_24h_pct": avg_r24h,
        "avg_mfe_pct": avg_mfe,
        "avg_mae_pct": avg_mae,
        "mfe_mae_ratio": _mfe_mae_ratio(avg_mfe, avg_mae),
        "sample_quality": sample_quality(len(rows), min_events),
        "top_symbol_event_share": None if not rows or not top_symbol else round(top_symbol_counts[top_symbol] / len(rows), 6),
        "top_symbol_return_contribution_share": None if total_return_sum == 0.0 or not top_symbol else round(top_symbol_return_sum[top_symbol] / total_return_sum, 6),
        "top_time_bucket_event_share": None if not rows or not top_bucket else round(top_bucket_counts[top_bucket] / len(rows), 6),
        "top_time_bucket_return_contribution_share": None if total_return_sum == 0.0 or not top_bucket else round(top_bucket_return_sum[top_bucket] / total_return_sum, 6),
        "top_symbol": top_symbol,
        "top_time_bucket": top_bucket,
        "research_only": True,
    }


def leave_one_symbol_rows(rows: list[dict[str, Any]], min_events: int) -> list[dict[str, Any]]:
    symbols = sorted({row["symbol"] for row in rows})
    output: list[dict[str, Any]] = []
    for symbol in symbols:
        filtered = [row for row in rows if row["symbol"] != symbol]
        summary = baseline_summary(filtered, min_events)
        summary.update({"excluded_symbol": symbol})
        output.append(summary)
    return output


def leave_one_time_rows(rows: list[dict[str, Any]], min_events: int) -> list[dict[str, Any]]:
    buckets = sorted({bucket_start(row["event_ts_utc_dt"]) for row in rows})
    output: list[dict[str, Any]] = []
    for bucket in buckets:
        filtered = [row for row in rows if bucket_start(row["event_ts_utc_dt"]) != bucket]
        summary = baseline_summary(filtered, min_events)
        summary.update({"excluded_time_bucket_start_utc": bucket})
        output.append(summary)
    return output


def classify_robustness(
    base: dict[str, Any],
    symbol_rows: list[dict[str, Any]],
    time_rows: list[dict[str, Any]],
) -> str:
    event_count = int(base.get("event_count") or 0)
    symbol_share = base.get("top_symbol_event_share")
    time_share = base.get("top_time_bucket_event_share")
    if isinstance(symbol_share, float) and symbol_share > 0.5:
        return "SYMBOL_CONCENTRATED"
    if isinstance(time_share, float) and time_share > 0.55:
        return "TIME_CONCENTRATED"
    if event_count < 20:
        return "SAMPLE_TOO_SMALL"
    base_r24 = as_float(base.get("avg_return_24h_pct"))
    if base_r24 is None:
        return "UNKNOWN"
    symbol_r24s = [as_float(row.get("avg_return_24h_pct")) for row in symbol_rows]
    time_r24s = [as_float(row.get("avg_return_24h_pct")) for row in time_rows]
    if any(value is not None and value <= 0.0 for value in symbol_r24s):
        return "NOT_ROBUST"
    if any(value is not None and value <= 0.0 for value in time_r24s):
        return "NOT_ROBUST"
    if any(value is not None and value < (base_r24 * 0.5) for value in symbol_r24s):
        return "NOT_ROBUST"
    if any(value is not None and value < (base_r24 * 0.5) for value in time_r24s):
        return "NOT_ROBUST"
    if base_r24 > 0.0:
        return "ROBUST_ENOUGH_FOR_MORE_RESEARCH"
    return "NOT_ROBUST"


def build_manifest(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    base: dict[str, Any],
    symbol_rows: list[dict[str, Any]],
    time_rows: list[dict[str, Any]],
    robustness_classification: str,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "target_shape": {
            "context_quality_tier": TARGET_TIER,
            "reaction_zone_touch": TARGET_TOUCH,
            "fakeout_flag": TARGET_FAKEOUT,
        },
        "baseline": base,
        "robustness_classification": robustness_classification,
        "leave_one_symbol_row_count": len(symbol_rows),
        "leave_one_time_row_count": len(time_rows),
        "event_level_rows_path": str(args.event_level_rows),
        "output_dir": str(output_dir),
        "research_only": True,
        "safety_markers": dict(SAFETY_MARKERS),
    }


def print_summary(base: dict[str, Any], robustness_classification: str, symbol_rows: list[dict[str, Any]], time_rows: list[dict[str, Any]]) -> None:
    symbol_lines = [
        f"-{row['excluded_symbol']} n={row['event_count']} r24h={row['avg_return_24h_pct']}"
        for row in sorted(symbol_rows, key=lambda r: (as_float(r.get("avg_return_24h_pct")) or -999999.0))
    ]
    time_lines = [
        f"-{row['excluded_time_bucket_start_utc']} n={row['event_count']} r24h={row['avg_return_24h_pct']}"
        for row in sorted(time_rows, key=lambda r: (as_float(r.get("avg_return_24h_pct")) or -999999.0))
    ]
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(
        f"target_shape {TARGET_TIER} touch={TARGET_TOUCH} fakeout={TARGET_FAKEOUT} "
        f"n={base['event_count']} r4h={base['avg_return_4h_pct']} r24h={base['avg_return_24h_pct']} "
        f"mfe_mae={base['mfe_mae_ratio']}"
    )
    print(f"robustness_classification={robustness_classification}")
    print(
        "concentration "
        f"top_symbol={base['top_symbol']} share={base['top_symbol_event_share']} return_share={base['top_symbol_return_contribution_share']} "
        f"top_time_bucket={base['top_time_bucket']} share={base['top_time_bucket_event_share']} return_share={base['top_time_bucket_return_contribution_share']}"
    )
    print("leave_one_symbol " + " ; ".join(symbol_lines[:6]))
    print("leave_one_time " + " ; ".join(time_lines[:6]))
    print("safety " + " ".join(f"{k}={v}" for k, v in SAFETY_MARKERS.items()))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = parse_symbols_arg(args.symbols)
    event_rows = load_event_rows(Path(args.event_level_rows), symbols=symbols)
    rows = target_rows(event_rows)
    output_dir = Path(args.output_dir)

    base = baseline_summary(rows, args.min_events)
    symbol_rows = leave_one_symbol_rows(rows, args.min_events)
    time_rows = leave_one_time_rows(rows, args.min_events)
    robustness_classification = classify_robustness(base, symbol_rows, time_rows)
    manifest = build_manifest(
        args=args,
        output_dir=output_dir,
        base=base,
        symbol_rows=symbol_rows,
        time_rows=time_rows,
        robustness_classification=robustness_classification,
    )

    if args.write_files:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(output_dir / ROBUSTNESS_ROWS_CSV, [base | {"robustness_classification": robustness_classification}])
        write_csv(output_dir / LEAVE_ONE_SYMBOL_ROWS_CSV, symbol_rows)
        write_csv(output_dir / LEAVE_ONE_TIME_ROWS_CSV, time_rows)
        write_json(output_dir / MANIFEST_JSON, manifest)

    if args.output == "json":
        print(
            json.dumps(
                {
                    "baseline": base,
                    "robustness_classification": robustness_classification,
                    "leave_one_symbol_rows": symbol_rows,
                    "leave_one_time_rows": time_rows,
                    "manifest": manifest,
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
        )
    else:
        print_summary(base, robustness_classification, symbol_rows, time_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
