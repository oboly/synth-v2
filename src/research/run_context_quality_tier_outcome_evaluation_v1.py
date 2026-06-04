from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.research.run_symbol_reaction_profile_by_context_v1 import (
    as_float,
    boolish,
    parse_symbols_arg,
    read_csv_rows,
    sample_quality,
    write_csv,
    write_json,
    write_jsonl,
)


REPORT_NAME = "context_quality_tier_outcome_evaluation_v1"
REPORT_VERSION = "1.0"

DEFAULT_EVENT_LEVEL_ROWS = Path(
    "data/research/event_level_symbol_reaction_profile_by_context_v1_event_range"
    "/event_level_symbol_reaction_profile_by_context_rows_v1.csv"
)
DEFAULT_OUTPUT_DIR = Path("data/research/context_quality_tier_outcome_evaluation_v1")

TIER_ROWS_CSV = "context_quality_tier_outcome_rows_v1.csv"
SYMBOL_ROWS_CSV = "context_quality_tier_symbol_rows_v1.csv"
MANIFEST_JSON = "manifest_v1.json"

TIERS_ORDERED = (
    "BREATH_CONTEXT",
    "SYMBOL_REGIME_CONTEXT",
    "MARKET_ONLY_CONTEXT",
    "UNKNOWN_CONTEXT",
)
ALL_LABEL = "ALL"

RETURN_HORIZONS = ("15m", "30m", "1h", "4h", "24h")

SAFETY_MARKERS: dict[str, Any] = {
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
            "Evaluate whether context_quality_tier has measurable outcome value "
            "(research-only, no DB writes, no broker calls, no strategy promotion)."
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
        if not symbol:
            continue
        if symbols is not None and symbol not in symbols:
            continue
        item = dict(row)
        item["symbol"] = symbol
        out.append(item)
    return out


def _floats(rows: list[dict[str, Any]], field: str) -> list[float]:
    return [v for v in (as_float(row.get(field)) for row in rows) if v is not None]


def _avg(vals: list[float]) -> float | None:
    if not vals:
        return None
    return round(sum(vals) / len(vals), 6)


def _positive_rate(vals: list[float]) -> float | None:
    if not vals:
        return None
    return round(sum(1 for v in vals if v > 0.0) / len(vals) * 100.0, 6)


def _bool_rate(rows: list[dict[str, Any]], field: str) -> float | None:
    flags = [v for v in (boolish(row.get(field)) for row in rows) if v is not None]
    if not flags:
        return None
    return round(sum(1 for f in flags if f) / len(flags) * 100.0, 6)


def _mfe_mae_ratio(avg_mfe: float | None, avg_mae: float | None) -> float | None:
    if avg_mfe is None or avg_mae in (None, 0.0):
        return None
    return round(avg_mfe / abs(avg_mae), 6)


def _tier_row(
    tier: str,
    rows: list[dict[str, Any]],
    min_events: int,
) -> dict[str, Any]:
    n = len(rows)
    avg_mfe = _avg(_floats(rows, "max_favorable_excursion_pct"))
    avg_mae = _avg(_floats(rows, "max_adverse_excursion_pct"))

    row_out: dict[str, Any] = {
        "context_quality_tier": tier,
        "event_count": n,
        "symbol_count": len({str(r.get("symbol") or "") for r in rows}),
        "avg_mfe_pct": avg_mfe,
        "avg_mae_pct": avg_mae,
        "mfe_mae_ratio": _mfe_mae_ratio(avg_mfe, avg_mae),
        "avg_drawdown_pct": _avg(_floats(rows, "drawdown_after_event_pct")),
        "fakeout_rate": _bool_rate(rows, "fakeout_flag"),
        "reaction_zone_touch_rate": _bool_rate(rows, "reaction_zone_touch"),
        "sample_quality": sample_quality(n, min_events),
        "research_only": True,
    }

    for h in RETURN_HORIZONS:
        vals = _floats(rows, f"forward_return_{h}")
        row_out[f"avg_return_{h}_pct"] = _avg(vals)
        row_out[f"positive_rate_{h}"] = _positive_rate(vals)

    return row_out


def _symbol_tier_row(
    symbol: str,
    tier: str,
    rows: list[dict[str, Any]],
    min_events: int,
) -> dict[str, Any]:
    n = len(rows)
    avg_mfe = _avg(_floats(rows, "max_favorable_excursion_pct"))
    avg_mae = _avg(_floats(rows, "max_adverse_excursion_pct"))
    return {
        "symbol": symbol,
        "context_quality_tier": tier,
        "event_count": n,
        "avg_mfe_pct": avg_mfe,
        "avg_mae_pct": avg_mae,
        "mfe_mae_ratio": _mfe_mae_ratio(avg_mfe, avg_mae),
        "avg_return_4h_pct": _avg(_floats(rows, "forward_return_4h")),
        "avg_return_24h_pct": _avg(_floats(rows, "forward_return_24h")),
        "fakeout_rate": _bool_rate(rows, "fakeout_flag"),
        "sample_quality": sample_quality(n, min_events),
        "research_only": True,
    }


def build_tier_rows(
    event_rows: list[dict[str, Any]],
    min_events: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        tier = str(row.get("context_quality_tier") or "UNKNOWN_CONTEXT").strip().upper()
        grouped[tier].append(row)

    output: list[dict[str, Any]] = []
    # Known tiers in defined order first, then any remaining
    seen: set[str] = set()
    for tier in TIERS_ORDERED:
        if tier in grouped:
            output.append(_tier_row(tier, grouped[tier], min_events))
            seen.add(tier)
    for tier in sorted(grouped):
        if tier not in seen:
            output.append(_tier_row(tier, grouped[tier], min_events))

    # ALL baseline
    output.append(_tier_row(ALL_LABEL, event_rows, min_events))
    return output


def build_symbol_tier_rows(
    event_rows: list[dict[str, Any]],
    min_events: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        sym = str(row.get("symbol") or "").strip().upper()
        tier = str(row.get("context_quality_tier") or "UNKNOWN_CONTEXT").strip().upper()
        if sym:
            grouped[(sym, tier)].append(row)

    output: list[dict[str, Any]] = []
    for (sym, tier) in sorted(grouped):
        output.append(_symbol_tier_row(sym, tier, grouped[(sym, tier)], min_events))
    return output


def build_manifest(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    tier_rows: list[dict[str, Any]],
    symbol_rows: list[dict[str, Any]],
    event_row_count: int,
) -> dict[str, Any]:
    tier_event_counts = {
        str(r["context_quality_tier"]): r["event_count"]
        for r in tier_rows
        if r["context_quality_tier"] != ALL_LABEL
    }
    tier_sample_quality = {
        str(r["context_quality_tier"]): r["sample_quality"]
        for r in tier_rows
        if r["context_quality_tier"] != ALL_LABEL
    }
    usable_tiers = [t for t, sq in tier_sample_quality.items() if sq not in ("INSUFFICIENT",)]
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "event_row_count": event_row_count,
        "tier_row_count": len(tier_rows),
        "symbol_tier_row_count": len(symbol_rows),
        "tier_event_counts": tier_event_counts,
        "tier_sample_quality": tier_sample_quality,
        "usable_tiers": usable_tiers,
        "event_level_rows": str(args.event_level_rows),
        "output_dir": str(output_dir),
        "research_only": True,
        "safety_markers": dict(SAFETY_MARKERS),
    }


def print_summary(
    tier_rows: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(f"event_row_count={manifest['event_row_count']}")
    print(f"usable_tiers={manifest['usable_tiers']}")
    print()
    header = f"{'tier':<26} {'n':>5}  {'sq':<13}  {'mfe':>7}  {'mae':>7}  {'ratio':>6}  {'r4h':>7}  {'r24h':>7}  {'fake':>6}  {'touch':>6}"
    print(header)
    print("-" * len(header))
    for row in tier_rows:
        def _f(v: Any, w: int = 7) -> str:
            return f"{v:.2f}".rjust(w) if isinstance(v, (int, float)) else "".rjust(w)
        print(
            f"{str(row['context_quality_tier']):<26}"
            f" {row['event_count']:>5}"
            f"  {str(row['sample_quality']):<13}"
            f"  {_f(row.get('avg_mfe_pct'))}"
            f"  {_f(row.get('avg_mae_pct'))}"
            f"  {_f(row.get('mfe_mae_ratio'), 6)}"
            f"  {_f(row.get('avg_return_4h_pct'))}"
            f"  {_f(row.get('avg_return_24h_pct'))}"
            f"  {_f(row.get('fakeout_rate'), 6)}"
            f"  {_f(row.get('reaction_zone_touch_rate'), 6)}"
        )
    print()
    print("safety " + " ".join(f"{k}={v}" for k, v in SAFETY_MARKERS.items()))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = parse_symbols_arg(args.symbols)
    event_level_rows_path = Path(args.event_level_rows)
    output_dir = Path(args.output_dir)

    event_rows = load_event_rows(event_level_rows_path, symbols=symbols)

    tier_rows = build_tier_rows(event_rows, args.min_events)
    symbol_rows = build_symbol_tier_rows(event_rows, args.min_events)
    manifest = build_manifest(
        args=args,
        output_dir=output_dir,
        tier_rows=tier_rows,
        symbol_rows=symbol_rows,
        event_row_count=len(event_rows),
    )

    if args.write_files:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(output_dir / TIER_ROWS_CSV, tier_rows)
        write_csv(output_dir / SYMBOL_ROWS_CSV, symbol_rows)
        write_json(output_dir / MANIFEST_JSON, manifest)

    if args.output == "json":
        print(json.dumps(
            {"tier_rows": tier_rows, "symbol_rows": symbol_rows, "manifest": manifest},
            indent=2, sort_keys=True, ensure_ascii=True,
        ))
    else:
        print_summary(tier_rows, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
