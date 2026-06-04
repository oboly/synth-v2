from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.research.run_context_quality_tier_outcome_evaluation_v1 import (
    SAFETY_MARKERS,
    _avg,
    _bool_rate,
    _floats,
    _mfe_mae_ratio,
    read_csv_rows,
)
from src.research.run_event_level_symbol_reaction_profile_by_context_v1 import (
    TIER_BREATH,
    TIER_MARKET_ONLY,
    TIER_SYMBOL_REGIME,
    TIER_UNKNOWN,
)
from src.research.run_symbol_reaction_profile_by_context_v1 import (
    as_float,
    boolish,
    parse_symbols_arg,
    parse_ts,
    sample_quality,
    write_csv,
    write_json,
    write_jsonl,
)


REPORT_NAME = "context_quality_tier_bias_audit_v1"
REPORT_VERSION = "1.0"

DEFAULT_EVENT_LEVEL_ROWS = Path(
    "data/research/event_level_symbol_reaction_profile_by_context_v1_event_range/"
    "event_level_symbol_reaction_profile_by_context_rows_v1.csv"
)
DEFAULT_TIER_ROWS = Path(
    "data/research/context_quality_tier_outcome_evaluation_v1/context_quality_tier_outcome_rows_v1.csv"
)
DEFAULT_OUTPUT_DIR = Path("data/research/context_quality_tier_bias_audit_v1")

SYMBOL_ROWS_CSV = "context_quality_tier_symbol_bias_rows_v1.csv"
TIME_ROWS_CSV = "context_quality_tier_time_bias_rows_v1.csv"
BREATH_ROWS_CSV = "context_quality_tier_breath_subtype_rows_v1.csv"
FAKEOUT_TOUCH_ROWS_CSV = "context_quality_tier_fakeout_touch_rows_v1.csv"
MANIFEST_JSON = "manifest_v1.json"

RETURN_4H = "forward_return_4h"
RETURN_24H = "forward_return_24h"
THREE_DAY_BUCKET = timedelta(days=3)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit whether context quality tier outcome ordering is robust or biased "
            "(research-only, no DB writes, no strategy promotion)."
        )
    )
    parser.add_argument("--event-level-rows", default=str(DEFAULT_EVENT_LEVEL_ROWS))
    parser.add_argument("--tier-outcome-rows", default=str(DEFAULT_TIER_ROWS))
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
        item["context_quality_tier"] = str(row.get("context_quality_tier") or TIER_UNKNOWN).strip().upper()
        item["breath_phase"] = str(row.get("breath_phase") or "UNKNOWN").strip().upper()
        item["breath_alignment"] = str(row.get("breath_alignment") or "UNKNOWN").strip().upper()
        out.append(item)
    return out


def load_optional_tier_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [dict(row) for row in read_csv_rows(path)]


def mean_metric(rows: list[dict[str, Any]], field: str) -> float | None:
    return _avg(_floats(rows, field))


def event_count_sum(rows: list[dict[str, Any]]) -> int:
    return len(rows)


def classify_sample(n: int, min_events: int) -> str:
    return sample_quality(n, min_events)


def iso_date(value: datetime) -> str:
    return value.replace(tzinfo=UTC).date().isoformat()


def bucket_start(ts: datetime) -> datetime:
    base = datetime(1970, 1, 1)
    delta_days = (ts.date() - base.date()).days
    bucket_days = delta_days - (delta_days % 3)
    return datetime.combine(base.date() + timedelta(days=bucket_days), datetime.min.time())


def format_bool_bucket(value: bool | None) -> str:
    if value is None:
        return "UNKNOWN"
    return "TRUE" if value else "FALSE"


def top_symbols(rows: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("symbol") or "").upper()].append(row)
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


def build_symbol_rows(event_rows: list[dict[str, Any]], min_events: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        grouped[(row["symbol"], row["context_quality_tier"])].append(row)
    output: list[dict[str, Any]] = []
    for (symbol, tier) in sorted(grouped):
        rows = grouped[(symbol, tier)]
        avg_mfe = mean_metric(rows, "max_favorable_excursion_pct")
        avg_mae = mean_metric(rows, "max_adverse_excursion_pct")
        output.append(
            {
                "symbol": symbol,
                "context_quality_tier": tier,
                "event_count": len(rows),
                "avg_mfe_pct": avg_mfe,
                "avg_mae_pct": avg_mae,
                "mfe_mae_ratio": _mfe_mae_ratio(avg_mfe, avg_mae),
                "avg_return_4h_pct": mean_metric(rows, RETURN_4H),
                "avg_return_24h_pct": mean_metric(rows, RETURN_24H),
                "fakeout_rate": _bool_rate(rows, "fakeout_flag"),
                "reaction_zone_touch_rate": _bool_rate(rows, "reaction_zone_touch"),
                "sample_quality": classify_sample(len(rows), min_events),
                "research_only": True,
            }
        )
    return output


def build_time_rows(event_rows: list[dict[str, Any]], min_events: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        start = bucket_start(row["event_ts_utc_dt"])
        grouped[(start.isoformat(), row["context_quality_tier"])].append(row)
    output: list[dict[str, Any]] = []
    for (bucket_iso, tier) in sorted(grouped):
        rows = grouped[(bucket_iso, tier)]
        avg_mfe = mean_metric(rows, "max_favorable_excursion_pct")
        avg_mae = mean_metric(rows, "max_adverse_excursion_pct")
        bucket_dt = datetime.fromisoformat(bucket_iso)
        output.append(
            {
                "event_date": iso_date(rows[0]["event_ts_utc_dt"]),
                "time_bucket_start_utc": bucket_dt.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
                "context_quality_tier": tier,
                "event_count": len(rows),
                "tier_distribution_in_bucket": json.dumps(
                    Counter(r["context_quality_tier"] for r in rows),
                    sort_keys=True,
                    ensure_ascii=True,
                ),
                "avg_mfe_pct": avg_mfe,
                "avg_mae_pct": avg_mae,
                "mfe_mae_ratio": _mfe_mae_ratio(avg_mfe, avg_mae),
                "avg_return_4h_pct": mean_metric(rows, RETURN_4H),
                "avg_return_24h_pct": mean_metric(rows, RETURN_24H),
                "sample_quality": classify_sample(len(rows), min_events),
                "research_only": True,
            }
        )
    return output


def build_breath_rows(event_rows: list[dict[str, Any]], min_events: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        if row["context_quality_tier"] != TIER_BREATH:
            continue
        grouped[(row["breath_phase"], row["breath_alignment"])].append(row)
    output: list[dict[str, Any]] = []
    for (phase, alignment) in sorted(grouped):
        rows = grouped[(phase, alignment)]
        output.append(
            {
                "breath_phase": phase,
                "breath_alignment": alignment,
                "event_count": len(rows),
                "avg_return_4h_pct": mean_metric(rows, RETURN_4H),
                "avg_return_24h_pct": mean_metric(rows, RETURN_24H),
                "fakeout_rate": _bool_rate(rows, "fakeout_flag"),
                "touch_rate": _bool_rate(rows, "reaction_zone_touch"),
                "sample_quality": classify_sample(len(rows), min_events),
                "research_only": True,
            }
        )
    return output


def build_fakeout_touch_rows(event_rows: list[dict[str, Any]], min_events: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        touch_bucket = format_bool_bucket(boolish(row.get("reaction_zone_touch")))
        fakeout_bucket = format_bool_bucket(boolish(row.get("fakeout_flag")))
        grouped[(row["context_quality_tier"], touch_bucket, fakeout_bucket)].append(row)
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
                "avg_mfe_pct": avg_mfe,
                "avg_mae_pct": avg_mae,
                "mfe_mae_ratio": _mfe_mae_ratio(avg_mfe, avg_mae),
                "avg_return_4h_pct": mean_metric(rows, RETURN_4H),
                "avg_return_24h_pct": mean_metric(rows, RETURN_24H),
                "sample_quality": classify_sample(len(rows), min_events),
                "research_only": True,
            }
        )
    return output


def assess_bias(
    event_rows: list[dict[str, Any]],
    symbol_rows: list[dict[str, Any]],
    breath_rows: list[dict[str, Any]],
) -> str:
    breath_rows_all = [r for r in event_rows if r["context_quality_tier"] == TIER_BREATH]
    market_only_rows = [r for r in event_rows if r["context_quality_tier"] == TIER_MARKET_ONLY]
    symbol_regime_rows = [r for r in event_rows if r["context_quality_tier"] == TIER_SYMBOL_REGIME]
    if len(breath_rows_all) < 10:
        return "BREATH_SAMPLE_TOO_THIN"
    if len(breath_rows) <= 1:
        return "BREATH_SUBTYPE_CONCENTRATED"
    top_breath = top_symbols(breath_rows_all, limit=1)
    if top_breath and top_breath[0]["event_count"] / max(len(breath_rows_all), 1) > 0.4:
        return "SYMBOL_OUTLIER_BIAS"
    breath_r24 = mean_metric(breath_rows_all, RETURN_24H)
    market_r24 = mean_metric(market_only_rows, RETURN_24H)
    symbol_r24 = mean_metric(symbol_regime_rows, RETURN_24H)
    if breath_r24 is None or market_r24 is None:
        return "INSUFFICIENT_COMPARISON"
    if market_r24 > breath_r24 and (symbol_r24 is None or symbol_r24 > breath_r24):
        return "LIKELY_BIASED_OR_CONTEXT_THIN"
    return "PLAUSIBLY_ROBUST"


def build_manifest(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    event_rows: list[dict[str, Any]],
    symbol_rows: list[dict[str, Any]],
    time_rows: list[dict[str, Any]],
    breath_rows: list[dict[str, Any]],
    fakeout_touch_rows: list[dict[str, Any]],
    tier_outcome_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    breath_rows_all = [r for r in event_rows if r["context_quality_tier"] == TIER_BREATH]
    market_only_rows = [r for r in event_rows if r["context_quality_tier"] == TIER_MARKET_ONLY]
    tier_counts = Counter(row["context_quality_tier"] for row in event_rows)
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "event_row_count": len(event_rows),
        "symbol_row_count": len(symbol_rows),
        "time_row_count": len(time_rows),
        "breath_subtype_row_count": len(breath_rows),
        "fakeout_touch_row_count": len(fakeout_touch_rows),
        "tier_distribution": dict(sorted(tier_counts.items())),
        "top_negative_breath_symbols": top_symbols(sorted(breath_rows_all, key=lambda r: as_float(r.get(RETURN_24H)) or 0.0), 5),
        "top_positive_market_only_symbols": top_symbols(
            sorted(market_only_rows, key=lambda r: -(as_float(r.get(RETURN_24H)) or 0.0)),
            5,
        ),
        "bias_assessment": assess_bias(event_rows, symbol_rows, breath_rows),
        "tier_outcome_rows_path": str(args.tier_outcome_rows) if tier_outcome_rows else None,
        "event_level_rows_path": str(args.event_level_rows),
        "output_dir": str(output_dir),
        "research_only": True,
        "safety_markers": dict(SAFETY_MARKERS),
    }


def print_summary(
    *,
    symbol_rows: list[dict[str, Any]],
    breath_rows: list[dict[str, Any]],
    fakeout_touch_rows: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    top_symbol_lines = [
        f"{row['symbol']}:{row['context_quality_tier']} n={row['event_count']} r24h={row['avg_return_24h_pct']}"
        for row in sorted(symbol_rows, key=lambda r: (-(r["event_count"]), r["symbol"], r["context_quality_tier"]))[:5]
    ]
    breath_lines = [
        f"{row['breath_phase']}/{row['breath_alignment']} n={row['event_count']} r24h={row['avg_return_24h_pct']}"
        for row in sorted(breath_rows, key=lambda r: (-r["event_count"], r["breath_phase"], r["breath_alignment"]))[:5]
    ]
    fakeout_lines = [
        f"{row['context_quality_tier']} touch={row['reaction_zone_touch']} fakeout={row['fakeout_flag']} n={row['event_count']} r24h={row['avg_return_24h_pct']}"
        for row in sorted(fakeout_touch_rows, key=lambda r: (-r["event_count"], r["context_quality_tier"]))[:5]
    ]
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(f"event_row_count={manifest['event_row_count']}")
    print(f"tier_distribution={manifest['tier_distribution']}")
    print(f"bias_assessment={manifest['bias_assessment']}")
    print("top_symbol_tiers " + " ; ".join(top_symbol_lines))
    print("breath_subtypes " + " ; ".join(breath_lines))
    print("fakeout_touch " + " ; ".join(fakeout_lines))
    print(
        "safety "
        + " ".join(f"{key}={value}" for key, value in SAFETY_MARKERS.items())
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = parse_symbols_arg(args.symbols)
    event_rows = load_event_rows(Path(args.event_level_rows), symbols=symbols)
    tier_outcome_rows = load_optional_tier_rows(Path(args.tier_outcome_rows))
    output_dir = Path(args.output_dir)

    symbol_rows = build_symbol_rows(event_rows, args.min_events)
    time_rows = build_time_rows(event_rows, args.min_events)
    breath_rows = build_breath_rows(event_rows, args.min_events)
    fakeout_touch_rows = build_fakeout_touch_rows(event_rows, args.min_events)
    manifest = build_manifest(
        args=args,
        output_dir=output_dir,
        event_rows=event_rows,
        symbol_rows=symbol_rows,
        time_rows=time_rows,
        breath_rows=breath_rows,
        fakeout_touch_rows=fakeout_touch_rows,
        tier_outcome_rows=tier_outcome_rows,
    )

    if args.write_files:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(output_dir / SYMBOL_ROWS_CSV, symbol_rows)
        write_csv(output_dir / TIME_ROWS_CSV, time_rows)
        write_csv(output_dir / BREATH_ROWS_CSV, breath_rows)
        write_csv(output_dir / FAKEOUT_TOUCH_ROWS_CSV, fakeout_touch_rows)
        write_json(output_dir / MANIFEST_JSON, manifest)

    if args.output == "json":
        print(
            json.dumps(
                {
                    "symbol_rows": symbol_rows,
                    "time_rows": time_rows,
                    "breath_rows": breath_rows,
                    "fakeout_touch_rows": fakeout_touch_rows,
                    "manifest": manifest,
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
        )
    else:
        print_summary(
            symbol_rows=symbol_rows,
            breath_rows=breath_rows,
            fakeout_touch_rows=fakeout_touch_rows,
            manifest=manifest,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
