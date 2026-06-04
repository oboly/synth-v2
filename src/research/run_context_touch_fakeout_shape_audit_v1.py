from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.research.run_context_quality_tier_outcome_evaluation_v1 import (
    SAFETY_MARKERS,
    _bool_rate,
    _floats,
    _mfe_mae_ratio,
    read_csv_rows,
)
from src.research.run_symbol_reaction_profile_by_context_v1 import (
    as_float,
    boolish,
    parse_symbols_arg,
    parse_ts,
    sample_quality,
    write_csv,
    write_json,
)


REPORT_NAME = "context_touch_fakeout_shape_audit_v1"
REPORT_VERSION = "1.0"

DEFAULT_EVENT_LEVEL_ROWS = Path(
    "data/research/event_level_symbol_reaction_profile_by_context_v1_event_range/"
    "event_level_symbol_reaction_profile_by_context_rows_v1.csv"
)
DEFAULT_OUTPUT_DIR = Path("data/research/context_touch_fakeout_shape_audit_v1")

SHAPE_ROWS_CSV = "context_touch_fakeout_shape_rows_v1.csv"
SYMBOL_ROWS_CSV = "context_touch_fakeout_symbol_rows_v1.csv"
TIME_ROWS_CSV = "context_touch_fakeout_time_rows_v1.csv"
MANIFEST_JSON = "manifest_v1.json"

RETURN_4H = "forward_return_4h"
RETURN_24H = "forward_return_24h"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit touch/fakeout outcome shapes across context tiers, symbols, and time buckets "
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


def load_event_rows(path: Path, symbols: set[str] | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Event-level rows not found: {path}")
    raw = read_csv_rows(path)
    out: list[dict[str, Any]] = []
    for row in raw:
        symbol = str(row.get("symbol") or "").strip().upper()
        event_ts = parse_ts(row.get("event_ts_utc"))
        if not symbol or event_ts is None:
            continue
        if symbols is not None and symbol not in symbols:
            continue
        item = dict(row)
        item["symbol"] = symbol
        item["event_ts_utc_dt"] = event_ts
        item["context_quality_tier"] = str(row.get("context_quality_tier") or "UNKNOWN_CONTEXT").strip().upper()
        out.append(item)
    return out


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def bool_bucket(value: Any) -> str:
    parsed = boolish(value)
    if parsed is None:
        return "UNKNOWN"
    return "TRUE" if parsed else "FALSE"


def mean_metric(rows: list[dict[str, Any]], field: str) -> float | None:
    return _avg(_floats(rows, field))


def bucket_start(ts: datetime) -> datetime:
    base = datetime(1970, 1, 1)
    delta_days = (ts.date() - base.date()).days
    bucket_days = delta_days - (delta_days % 3)
    return datetime.combine(base.date() + timedelta(days=bucket_days), datetime.min.time())


def shape_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("context_quality_tier") or "UNKNOWN_CONTEXT").strip().upper(),
        bool_bucket(row.get("reaction_zone_touch")),
        bool_bucket(row.get("fakeout_flag")),
    )


def top_symbols(rows: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["symbol"]].append(row)
    ranked = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    out: list[dict[str, Any]] = []
    for symbol, symbol_rows in ranked[:limit]:
        out.append(
            {
                "symbol": symbol,
                "event_count": len(symbol_rows),
                "avg_return_24h_pct": mean_metric(symbol_rows, RETURN_24H),
                "avg_mfe_pct": mean_metric(symbol_rows, "max_favorable_excursion_pct"),
                "avg_mae_pct": mean_metric(symbol_rows, "max_adverse_excursion_pct"),
            }
        )
    return out


def build_shape_rows(event_rows: list[dict[str, Any]], min_events: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        grouped[shape_key(row)].append(row)
    output: list[dict[str, Any]] = []
    for (tier, touch_bucket, fakeout_bucket) in sorted(grouped):
        rows = grouped[(tier, touch_bucket, fakeout_bucket)]
        avg_mfe = mean_metric(rows, "max_favorable_excursion_pct")
        avg_mae = mean_metric(rows, "max_adverse_excursion_pct")
        output.append(
            {
                "context_quality_tier": tier,
                "reaction_zone_touch": touch_bucket,
                "fakeout_flag": fakeout_bucket,
                "event_count": len(rows),
                "avg_return_4h_pct": mean_metric(rows, RETURN_4H),
                "avg_return_24h_pct": mean_metric(rows, RETURN_24H),
                "avg_mfe_pct": avg_mfe,
                "avg_mae_pct": avg_mae,
                "mfe_mae_ratio": _mfe_mae_ratio(avg_mfe, avg_mae),
                "sample_quality": sample_quality(len(rows), min_events),
                "research_only": True,
            }
        )
    return output


def build_symbol_rows(event_rows: list[dict[str, Any]], min_events: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        tier, touch_bucket, fakeout_bucket = shape_key(row)
        grouped[(row["symbol"], tier, touch_bucket, fakeout_bucket)].append(row)
    output: list[dict[str, Any]] = []
    for (symbol, tier, touch_bucket, fakeout_bucket) in sorted(grouped):
        rows = grouped[(symbol, tier, touch_bucket, fakeout_bucket)]
        output.append(
            {
                "symbol": symbol,
                "context_quality_tier": tier,
                "reaction_zone_touch": touch_bucket,
                "fakeout_flag": fakeout_bucket,
                "event_count": len(rows),
                "avg_return_24h_pct": mean_metric(rows, RETURN_24H),
                "fakeout_rate": _bool_rate(rows, "fakeout_flag"),
                "touch_rate": _bool_rate(rows, "reaction_zone_touch"),
                "sample_quality": sample_quality(len(rows), min_events),
                "research_only": True,
            }
        )
    return output


def build_time_rows(event_rows: list[dict[str, Any]], min_events: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        bucket = bucket_start(row["event_ts_utc_dt"]).replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
        tier, touch_bucket, fakeout_bucket = shape_key(row)
        grouped[(bucket, tier, touch_bucket, fakeout_bucket)].append(row)
    output: list[dict[str, Any]] = []
    for (bucket, tier, touch_bucket, fakeout_bucket) in sorted(grouped):
        rows = grouped[(bucket, tier, touch_bucket, fakeout_bucket)]
        output.append(
            {
                "time_bucket_start_utc": bucket,
                "context_quality_tier": tier,
                "reaction_zone_touch": touch_bucket,
                "fakeout_flag": fakeout_bucket,
                "event_count": len(rows),
                "avg_return_24h_pct": mean_metric(rows, RETURN_24H),
                "sample_quality": sample_quality(len(rows), min_events),
                "research_only": True,
            }
        )
    return output


def stability_assessment(shape_rows: list[dict[str, Any]], symbol_rows: list[dict[str, Any]], time_rows: list[dict[str, Any]]) -> str:
    target = next(
        (
            row
            for row in shape_rows
            if row["context_quality_tier"] == "MARKET_ONLY_CONTEXT"
            and row["reaction_zone_touch"] == "TRUE"
            and row["fakeout_flag"] == "FALSE"
        ),
        None,
    )
    if target is None or target["event_count"] < 20:
        return "TARGET_SAMPLE_THIN"
    target_symbol_rows = [
        row
        for row in symbol_rows
        if row["context_quality_tier"] == "MARKET_ONLY_CONTEXT"
        and row["reaction_zone_touch"] == "TRUE"
        and row["fakeout_flag"] == "FALSE"
    ]
    if len(target_symbol_rows) < 3:
        return "SYMBOL_CONCENTRATED"
    if target_symbol_rows and max(row["event_count"] for row in target_symbol_rows) / target["event_count"] > 0.5:
        return "SYMBOL_OUTLIER_BIAS"
    target_time_rows = [
        row
        for row in time_rows
        if row["context_quality_tier"] == "MARKET_ONLY_CONTEXT"
        and row["reaction_zone_touch"] == "TRUE"
        and row["fakeout_flag"] == "FALSE"
    ]
    if len(target_time_rows) < 3:
        return "TIME_CONCENTRATED"
    positive_buckets = sum(1 for row in target_time_rows if (row["avg_return_24h_pct"] or 0.0) > 0.0)
    if positive_buckets / len(target_time_rows) < 0.6:
        return "MIXED_TIME_SHAPE"
    return "PLAUSIBLY_STABLE"


def build_manifest(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    event_rows: list[dict[str, Any]],
    shape_rows: list[dict[str, Any]],
    symbol_rows: list[dict[str, Any]],
    time_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    target_positive = [
        row
        for row in event_rows
        if shape_key(row) == ("MARKET_ONLY_CONTEXT", "TRUE", "FALSE")
    ]
    fakeout_negative = [
        row
        for row in event_rows
        if bool_bucket(row.get("fakeout_flag")) == "TRUE"
    ]
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "event_row_count": len(event_rows),
        "shape_row_count": len(shape_rows),
        "symbol_row_count": len(symbol_rows),
        "time_row_count": len(time_rows),
        "shape_distribution": {
            f"{row['context_quality_tier']}|touch={row['reaction_zone_touch']}|fakeout={row['fakeout_flag']}": row["event_count"]
            for row in shape_rows
        },
        "positive_market_only_touch_no_fakeout_drivers": top_symbols(target_positive, 5),
        "negative_fakeout_bucket_drivers": top_symbols(
            sorted(fakeout_negative, key=lambda row: as_float(row.get(RETURN_24H)) or 0.0),
            5,
        ),
        "stability_assessment": stability_assessment(shape_rows, symbol_rows, time_rows),
        "event_level_rows_path": str(args.event_level_rows),
        "output_dir": str(output_dir),
        "research_only": True,
        "safety_markers": dict(SAFETY_MARKERS),
    }


def print_summary(shape_rows: list[dict[str, Any]], symbol_rows: list[dict[str, Any]], time_rows: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    shape_lines = [
        f"{row['context_quality_tier']} touch={row['reaction_zone_touch']} fakeout={row['fakeout_flag']} n={row['event_count']} r24h={row['avg_return_24h_pct']}"
        for row in sorted(shape_rows, key=lambda r: (-r["event_count"], r["context_quality_tier"], r["reaction_zone_touch"], r["fakeout_flag"]))[:6]
    ]
    symbol_lines = [
        f"{row['symbol']}:{row['context_quality_tier']} touch={row['reaction_zone_touch']} fakeout={row['fakeout_flag']} n={row['event_count']} r24h={row['avg_return_24h_pct']}"
        for row in sorted(symbol_rows, key=lambda r: (-r["event_count"], r["symbol"]))[:6]
    ]
    time_lines = [
        f"{row['time_bucket_start_utc']}:{row['context_quality_tier']} touch={row['reaction_zone_touch']} fakeout={row['fakeout_flag']} n={row['event_count']} r24h={row['avg_return_24h_pct']}"
        for row in sorted(time_rows, key=lambda r: (-r["event_count"], r["time_bucket_start_utc"]))[:6]
    ]
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(f"event_row_count={manifest['event_row_count']}")
    print(f"stability_assessment={manifest['stability_assessment']}")
    print("shape_buckets " + " ; ".join(shape_lines))
    print("per_symbol " + " ; ".join(symbol_lines))
    print("time_buckets " + " ; ".join(time_lines))
    print("safety " + " ".join(f"{k}={v}" for k, v in SAFETY_MARKERS.items()))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = parse_symbols_arg(args.symbols)
    event_rows = load_event_rows(Path(args.event_level_rows), symbols=symbols)
    output_dir = Path(args.output_dir)

    shape_rows = build_shape_rows(event_rows, args.min_events)
    symbol_rows = build_symbol_rows(event_rows, args.min_events)
    time_rows = build_time_rows(event_rows, args.min_events)
    manifest = build_manifest(
        args=args,
        output_dir=output_dir,
        event_rows=event_rows,
        shape_rows=shape_rows,
        symbol_rows=symbol_rows,
        time_rows=time_rows,
    )

    if args.write_files:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(output_dir / SHAPE_ROWS_CSV, shape_rows)
        write_csv(output_dir / SYMBOL_ROWS_CSV, symbol_rows)
        write_csv(output_dir / TIME_ROWS_CSV, time_rows)
        write_json(output_dir / MANIFEST_JSON, manifest)

    if args.output == "json":
        print(
            json.dumps(
                {
                    "shape_rows": shape_rows,
                    "symbol_rows": symbol_rows,
                    "time_rows": time_rows,
                    "manifest": manifest,
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
        )
    else:
        print_summary(shape_rows, symbol_rows, time_rows, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
