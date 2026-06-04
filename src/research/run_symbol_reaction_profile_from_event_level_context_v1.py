from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.research.run_symbol_reaction_profile_by_context_v1 import (
    average_or_none,
    boolish,
    as_float,
    median_or_none,
    parse_symbols_arg,
    rate_or_none,
    read_csv_rows,
    sample_quality,
    write_csv,
    write_json,
    write_jsonl,
)


REPORT_NAME = "symbol_reaction_profile_from_event_level_context_v1"
REPORT_VERSION = "1.0"

DEFAULT_EVENT_LEVEL_ROWS = Path(
    "data/research/event_level_symbol_reaction_profile_by_context_v1"
    "/event_level_symbol_reaction_profile_by_context_rows_v1.csv"
)
DEFAULT_OUTPUT_DIR = Path("data/research/symbol_reaction_profile_from_event_level_context_v1")

ROWS_CSV = "symbol_reaction_profile_from_event_level_context_rows_v1.csv"
ROWS_JSONL = "symbol_reaction_profile_from_event_level_context_rows_v1.jsonl"
MANIFEST_JSON = "manifest_v1.json"

CONTEXT_KEY_FIELDS = (
    "breath_phase",
    "breath_alignment",
    "market_regime",
    "btc_context",
    "symbol_regime",
    "fibo_context",
    "context_quality_state",
)

RETURN_HORIZONS = ("15m", "30m", "1h", "4h", "24h")

SAFETY_MARKERS = {
    "research_only": True,
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "executor": "none",
    "db_writes": 0,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build aggregate symbol reaction profiles from event-level context rows "
            "(research-only, no DB writes, no broker calls). "
            "Groups by symbol + context fields without collapsing known context into UNKNOWN."
        )
    )
    parser.add_argument("--event-level-rows", default=str(DEFAULT_EVENT_LEVEL_ROWS))
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--min-events", type=int, default=1)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def is_unknown(value: Any) -> bool:
    return str(value or "").strip().upper() in {"", "UNKNOWN"}


TIER_BREATH = "BREATH_CONTEXT"
TIER_SYMBOL_REGIME = "SYMBOL_REGIME_CONTEXT"
TIER_MARKET_ONLY = "MARKET_ONLY_CONTEXT"
TIER_UNKNOWN = "UNKNOWN_CONTEXT"


def context_quality_tier(row: dict[str, Any]) -> str:
    if not is_unknown(row.get("breath_phase")) or not is_unknown(row.get("breath_alignment")):
        return TIER_BREATH
    if not is_unknown(row.get("symbol_regime")):
        return TIER_SYMBOL_REGIME
    if not is_unknown(row.get("market_regime")) or not is_unknown(row.get("btc_context")):
        return TIER_MARKET_ONLY
    return TIER_UNKNOWN


def context_bucket_key(row: dict[str, Any]) -> tuple[str, ...]:
    symbol = str(row.get("symbol") or "UNKNOWN").strip().upper()
    return (symbol,) + tuple(
        str(row.get(field) or "UNKNOWN").strip().upper() for field in CONTEXT_KEY_FIELDS
    )


def load_event_level_rows(path: Path, symbols: set[str] | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Event-level rows file not found: {path}")
    rows = read_csv_rows(path)
    out: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        if symbols is not None and symbol not in symbols:
            continue
        item = dict(row)
        item["symbol"] = symbol
        out.append(item)
    return out


def _float_col(rows: list[dict[str, Any]], field: str) -> list[float]:
    return [v for v in (as_float(row.get(field)) for row in rows) if v is not None]


def _bool_col(rows: list[dict[str, Any]], field: str) -> list[bool]:
    return [v for v in (boolish(row.get(field)) for row in rows) if v is not None]


def _forward_return_col(rows: list[dict[str, Any]], horizon: str) -> list[float]:
    return [v for v in (as_float(row.get(f"forward_return_{horizon}")) for row in rows) if v is not None]


def horizon_positive_rate(rows: list[dict[str, Any]], horizon: str) -> float | None:
    values = _forward_return_col(rows, horizon)
    if not values:
        return None
    return round(sum(1 for v in values if v > 0.0) / len(values) * 100.0, 6)


def mfe_mae_ratio(avg_mfe: float | None, avg_mae: float | None) -> float | None:
    if avg_mfe is None or avg_mae in (None, 0.0):
        return None
    return round(avg_mfe / abs(avg_mae), 6)


def build_aggregate_rows(
    *,
    event_rows: list[dict[str, Any]],
    min_events: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        grouped[context_bucket_key(row)].append(row)

    output: list[dict[str, Any]] = []
    for key in sorted(grouped):
        rows = grouped[key]
        symbol = key[0]
        context_values = dict(zip(CONTEXT_KEY_FIELDS, key[1:]))

        known_context = any(not is_unknown(context_values.get(f)) for f in ("breath_phase", "breath_alignment", "symbol_regime"))
        tier = context_quality_tier(context_values)

        avg_mfe = average_or_none(_float_col(rows, "max_favorable_excursion_pct"))
        avg_mae = average_or_none(_float_col(rows, "max_adverse_excursion_pct"))
        fakeout_flags = _bool_col(rows, "fakeout_flag")
        reaction_touch_flags = _bool_col(rows, "reaction_zone_touch")

        row_out: dict[str, Any] = {
            "symbol": symbol,
            **context_values,
            "event_count": len(rows),
            "context_quality_tier": tier,
            "known_context": known_context,
            "avg_mfe_pct": avg_mfe,
            "median_mfe_pct": median_or_none(_float_col(rows, "max_favorable_excursion_pct")),
            "avg_mae_pct": avg_mae,
            "median_mae_pct": median_or_none(_float_col(rows, "max_adverse_excursion_pct")),
            "mfe_mae_ratio": mfe_mae_ratio(avg_mfe, avg_mae),
            "avg_drawdown_pct": average_or_none(_float_col(rows, "drawdown_after_event_pct")),
            "fakeout_rate": rate_or_none(fakeout_flags) if fakeout_flags else None,
            "reaction_zone_touch_rate": rate_or_none(reaction_touch_flags) if reaction_touch_flags else None,
            "avg_retrace_to_entry_low_pct": average_or_none(_float_col(rows, "retrace_to_entry_low_pct")),
            "avg_retrace_to_entry_mid_pct": average_or_none(_float_col(rows, "retrace_to_entry_mid_pct")),
            "avg_retrace_to_entry_high_pct": average_or_none(_float_col(rows, "retrace_to_entry_high_pct")),
            "sample_quality": sample_quality(len(rows), min_events),
            "research_only": True,
        }

        for horizon in RETURN_HORIZONS:
            row_out[f"avg_forward_return_{horizon}"] = average_or_none(_forward_return_col(rows, horizon))
            row_out[f"positive_rate_{horizon}"] = horizon_positive_rate(rows, horizon)

        output.append(row_out)
    return output


def build_manifest(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    rows: list[dict[str, Any]],
    event_row_count: int,
) -> dict[str, Any]:
    known_context_rows = sum(1 for row in rows if row.get("known_context"))
    unknown_rows = sum(1 for row in rows if not row.get("known_context"))
    tier_dist = Counter(str(row.get("context_quality_tier") or TIER_UNKNOWN) for row in rows)
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "symbols": sorted({str(row.get("symbol") or "") for row in rows}),
        "aggregate_row_count": len(rows),
        "known_context_aggregate_rows": known_context_rows,
        "unknown_aggregate_rows": unknown_rows,
        "tier_distribution": dict(tier_dist),
        "source_event_row_count": event_row_count,
        "event_level_rows": str(args.event_level_rows),
        "output_dir": str(output_dir),
        "research_only": True,
        "safety_markers": dict(SAFETY_MARKERS),
    }


def print_summary(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(f"aggregate_row_count={len(rows)}")
    print(f"known_context_aggregate_rows={manifest['known_context_aggregate_rows']}")
    print(f"unknown_aggregate_rows={manifest['unknown_aggregate_rows']}")
    print(f"source_event_row_count={manifest['source_event_row_count']}")
    symbols = sorted({str(row.get("symbol") or "") for row in rows})
    print(f"symbols={','.join(symbols)}")
    tier_dist = manifest.get("tier_distribution", {})
    print(
        "tier_distribution "
        + " ; ".join(
            f"{k}:{tier_dist[k]}"
            for k in sorted(tier_dist, key=lambda k: -tier_dist[k])
        )
    )
    phase_counts: Counter[str] = Counter()
    for row in rows:
        phase_counts[str(row.get("breath_phase") or "UNKNOWN").upper()] += 1
    print(
        "breath_phase_distribution "
        + " ; ".join(f"{k}:{phase_counts[k]}" for k in sorted(phase_counts))
    )
    print(
        "safety "
        + " ".join(f"{key}={value}" for key, value in SAFETY_MARKERS.items())
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = parse_symbols_arg(args.symbols)
    event_level_rows_path = Path(args.event_level_rows)
    output_dir = Path(args.output_dir)

    event_rows = load_event_level_rows(event_level_rows_path, symbols=symbols)
    rows = build_aggregate_rows(event_rows=event_rows, min_events=args.min_events)
    manifest = build_manifest(
        args=args,
        output_dir=output_dir,
        rows=rows,
        event_row_count=len(event_rows),
    )

    if args.write_files:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(output_dir / ROWS_CSV, rows)
        write_jsonl(output_dir / ROWS_JSONL, rows)
        write_json(output_dir / MANIFEST_JSON, manifest)

    if args.output == "json":
        print(json.dumps({"rows": rows, "manifest": manifest}, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print_summary(rows, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
