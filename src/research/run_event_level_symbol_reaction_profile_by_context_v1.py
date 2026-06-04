from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

from src.research.run_historical_breath_regime_context_builder_v1 import (
    confidence_bucket,
    fmt_ts,
    parse_ts,
    quality_state_from_row,
)
from src.research.run_symbol_reaction_profile_by_context_v1 import (
    DEFAULT_CONTEXT_ROWS_CSV,
    DEFAULT_CONTEXT_ROWS_JSONL,
    DEFAULT_FIBO_ROWS,
    DEFAULT_INPUT_ROWS,
    DEFAULT_OUTPUT_DIR as DEFAULT_AGGREGATE_OUTPUT_DIR,
    MAX_STALENESS,
    as_float,
    boolish,
    fibo_context_for_event,
    midpoint,
    parse_symbols_arg,
    read_csv_rows,
    read_jsonl,
    retrace_to_level_pct,
    write_csv,
    write_json,
    write_jsonl,
)
from src.research.run_xlm_event_level_context_overlap_audit_v1 import nearest_at_or_before


REPORT_NAME = "event_level_symbol_reaction_profile_by_context_v1"
REPORT_VERSION = "1.0"

DEFAULT_RECOMPUTE_ROWS = Path(
    "data/research/historical_market_breath_source_recompute_v1/historical_market_breath_source_recomputed_rows_v1.csv"
)
DEFAULT_OUTPUT_DIR = Path("data/research/event_level_symbol_reaction_profile_by_context_v1")

ROWS_CSV = "event_level_symbol_reaction_profile_by_context_rows_v1.csv"
ROWS_JSONL = "event_level_symbol_reaction_profile_by_context_rows_v1.jsonl"
MANIFEST_JSON = "manifest_v1.json"

CONTEXT_FIELDS = (
    "breath_phase",
    "breath_alignment",
    "market_regime",
    "btc_context",
    "symbol_regime",
    "relative_strength_bucket",
    "momentum_bucket",
    "quality_state",
    "confidence_bucket",
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
            "Export event-level symbol reaction rows joined with historical context "
            "(research-only, no DB writes, no broker calls)."
        )
    )
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--context-rows", default=None)
    parser.add_argument("--recompute-rows", default=None)
    parser.add_argument("--input-rows", default=str(DEFAULT_INPUT_ROWS))
    parser.add_argument("--fibo-rows", default=str(DEFAULT_FIBO_ROWS))
    parser.add_argument("--min-events", type=int, default=1)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def choose_context_rows_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    if DEFAULT_CONTEXT_ROWS_JSONL.exists():
        return DEFAULT_CONTEXT_ROWS_JSONL
    return DEFAULT_CONTEXT_ROWS_CSV


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


def load_context_like_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Context rows file not found: {path}")
    if path.suffix.lower() == ".jsonl":
        rows = read_jsonl(path)
    else:
        rows = [dict(row) for row in read_csv_rows(path)]
    out: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        asof_ts_utc = parse_ts(row.get("asof_ts_utc"))
        if not symbol or asof_ts_utc is None:
            continue
        item = dict(row)
        item["symbol"] = symbol
        item["asof_ts_utc_dt"] = asof_ts_utc
        out.append(item)
    return out


def load_event_rows(path: Path, symbols: set[str] | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Input event rows file not found: {path}")
    rows = read_jsonl(path)
    out: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        event_ts_utc = parse_ts(row.get("event_ts_utc"))
        if not symbol or event_ts_utc is None:
            continue
        if symbols is not None and symbol not in symbols:
            continue
        item = dict(row)
        item["symbol"] = symbol
        item["event_ts_utc_dt"] = event_ts_utc
        out.append(item)
    return out


def load_fibo_rows(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in read_csv_rows(path):
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol:
            out[symbol] = dict(row)
    return out


def build_lookup(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(rows, key=lambda item: (item["symbol"], item["asof_ts_utc_dt"])):
        grouped[row["symbol"]].append(row)
    return dict(grouped)


def merge_source_refs(*source_values: Any) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for value in source_values:
        refs = value
        if isinstance(refs, str):
            try:
                refs = json.loads(refs)
            except json.JSONDecodeError:
                refs = None
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            encoded = json.dumps(ref, sort_keys=True, ensure_ascii=True)
            unique[encoded] = ref
    return [unique[key] for key in sorted(unique)]


def best_context_value(field: str, context_row: dict[str, Any] | None, recompute_row: dict[str, Any] | None) -> Any:
    context_value = context_row.get(field) if context_row else None
    if not is_unknown(context_value):
        return context_value
    recompute_value = recompute_row.get(field) if recompute_row else None
    if not is_unknown(recompute_value):
        return recompute_value
    return "UNKNOWN"


def reaction_zone_touch(row: dict[str, Any]) -> bool | None:
    current_price = as_float(row.get("current_price"))
    entry_low = as_float(row.get("entry_zone_low"))
    retrace = retrace_to_level_pct(current_price, entry_low)
    if retrace is None:
        return None
    return retrace <= 3.0


def fakeout_flag(row: dict[str, Any]) -> bool | None:
    return boolish(row.get("broke_invalidation_like_move"))


def nearest_context_row(
    lookup: dict[str, list[dict[str, Any]]],
    *,
    symbol: str,
    event_ts_utc,
    max_staleness: timedelta = MAX_STALENESS,
) -> dict[str, Any] | None:
    return nearest_at_or_before(
        lookup,
        symbol=symbol,
        event_ts_utc=event_ts_utc,
        max_staleness=max_staleness,
    )


def build_event_level_rows(
    *,
    event_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    recompute_rows: list[dict[str, Any]],
    fibo_by_symbol: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    context_lookup = build_lookup(context_rows)
    recompute_lookup = build_lookup(recompute_rows)
    output: list[dict[str, Any]] = []

    for row in sorted(event_rows, key=lambda item: (item["symbol"], item["event_ts_utc_dt"])):
        symbol = row["symbol"]
        event_ts_utc = row["event_ts_utc_dt"]
        context_row = nearest_context_row(context_lookup, symbol=symbol, event_ts_utc=event_ts_utc)
        recompute_row = nearest_context_row(recompute_lookup, symbol=symbol, event_ts_utc=event_ts_utc)

        current_price = as_float(row.get("current_price"))
        entry_low = as_float(row.get("entry_zone_low"))
        entry_high = as_float(row.get("entry_zone_high"))
        entry_mid = midpoint(entry_low, entry_high)

        fibo_context = "UNKNOWN"
        if context_row and not is_unknown(context_row.get("fibo_context")):
            fibo_context = str(context_row.get("fibo_context") or "UNKNOWN").upper()
        else:
            fibo_context = fibo_context_for_event(fibo_by_symbol.get(symbol), current_price)

        merged_row = {
            "breath_phase": best_context_value("breath_phase", context_row, recompute_row),
            "breath_alignment": best_context_value("breath_alignment", context_row, recompute_row),
            "market_regime": best_context_value("market_regime", context_row, recompute_row),
            "btc_context": best_context_value("btc_context", context_row, recompute_row),
            "symbol_regime": best_context_value("symbol_regime", context_row, recompute_row),
            "relative_strength_bucket": best_context_value("relative_strength_bucket", context_row, recompute_row),
            "momentum_bucket": best_context_value("momentum_bucket", context_row, recompute_row),
            "confidence_bucket": best_context_value("confidence_bucket", context_row, recompute_row),
        }
        quality_state = best_context_value("quality_state", context_row, recompute_row)
        if is_unknown(quality_state):
            quality_state = quality_state_from_row(
                {
                    "breath_phase": merged_row["breath_phase"],
                    "breath_alignment": merged_row["breath_alignment"],
                    "market_regime": merged_row["market_regime"],
                    "btc_context": merged_row["btc_context"],
                    "symbol_regime": merged_row["symbol_regime"],
                    "aplus_context_state": "UNKNOWN",
                }
            )
        confidence_value = merged_row["confidence_bucket"]
        if is_unknown(confidence_value):
            confidence_value = confidence_bucket(as_float(recompute_row.get("market_breath_confidence")) if recompute_row else None)

        source_refs = merge_source_refs(
            context_row.get("source_refs") if context_row else None,
            recompute_row.get("source_refs") if recompute_row else None,
        )

        row_out: dict[str, Any] = {
            "symbol": symbol,
            "event_ts_utc": fmt_ts(event_ts_utc),
            "venue": str(
                (context_row or {}).get("venue")
                or (recompute_row or {}).get("venue")
                or row.get("venue")
                or "UNKNOWN"
            ).lower(),
            "interval": str(
                (context_row or {}).get("interval")
                or (recompute_row or {}).get("interval")
                or row.get("interval_code")
                or "UNKNOWN"
            ),
            "context_asof_ts_utc": fmt_ts((context_row or {}).get("asof_ts_utc_dt")) if context_row else None,
            "recompute_asof_ts_utc": fmt_ts((recompute_row or {}).get("asof_ts_utc_dt")) if recompute_row else None,
            "breath_phase": str(merged_row["breath_phase"]).upper(),
            "breath_alignment": str(merged_row["breath_alignment"]).upper(),
            "market_regime": str(merged_row["market_regime"]).upper(),
            "btc_context": str(merged_row["btc_context"]).upper(),
            "symbol_regime": str(merged_row["symbol_regime"]).upper(),
            "fibo_context": fibo_context,
            "context_quality_state": str(quality_state).upper(),
            "context_confidence_bucket": str(confidence_value).upper(),
            "current_price": current_price,
            "entry_zone_low": entry_low,
            "entry_zone_high": entry_high,
            "entry_zone_mid": entry_mid,
            "retrace_to_entry_low_pct": retrace_to_level_pct(current_price, entry_low),
            "retrace_to_entry_mid_pct": retrace_to_level_pct(current_price, entry_mid),
            "retrace_to_entry_high_pct": retrace_to_level_pct(current_price, entry_high),
            "max_favorable_excursion_pct": as_float(row.get("max_favorable_excursion_pct")),
            "max_adverse_excursion_pct": as_float(row.get("max_adverse_excursion_pct")),
            "drawdown_after_event_pct": as_float(row.get("drawdown_after_event_pct")),
            "reaction_zone_touch": reaction_zone_touch(row),
            "fakeout_flag": fakeout_flag(row),
            "source_refs": source_refs,
            "research_only": True,
        }
        row_out["context_quality_tier"] = context_quality_tier(row_out)

        forward_returns = row.get("forward_returns") or {}
        if not isinstance(forward_returns, dict):
            forward_returns = {}
        for horizon in RETURN_HORIZONS:
            row_out[f"forward_return_{horizon}"] = as_float(forward_returns.get(horizon))

        output.append(row_out)
    return output


def build_manifest(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    known_context_event_count = sum(
        1
        for row in rows
        if any(not is_unknown(row.get(field)) for field in ("breath_phase", "breath_alignment", "symbol_regime"))
    )
    tier_dist = Counter(str(row.get("context_quality_tier") or TIER_UNKNOWN) for row in rows)
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "symbols": sorted({str(row.get("symbol") or "") for row in rows}),
        "row_count": len(rows),
        "known_context_event_count": known_context_event_count,
        "tier_distribution": dict(tier_dist),
        "input_rows": str(args.input_rows),
        "context_rows": str(args.context_rows),
        "recompute_rows": str(args.recompute_rows) if args.recompute_rows else None,
        "fibo_rows": str(args.fibo_rows),
        "output_dir": str(output_dir),
        "research_only": True,
        "safety_markers": dict(SAFETY_MARKERS),
    }


def print_summary(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    phase_counts = Counter(str(row.get("breath_phase") or "UNKNOWN").upper() for row in rows)
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(f"row_count={len(rows)}")
    print(f"known_context_event_count={manifest['known_context_event_count']}")
    print(
        "breath_phase_distribution "
        + " ; ".join(f"{key}:{phase_counts[key]}" for key in sorted(phase_counts))
    )
    tier_dist = manifest.get("tier_distribution", {})
    print(
        "tier_distribution "
        + " ; ".join(
            f"{k}:{tier_dist[k]}"
            for k in sorted(tier_dist, key=lambda k: -tier_dist[k])
        )
    )
    print(
        "safety "
        + " ".join(f"{key}={value}" for key, value in SAFETY_MARKERS.items())
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = parse_symbols_arg(args.symbols)
    context_rows_path = choose_context_rows_path(args.context_rows)
    recompute_rows_path = Path(args.recompute_rows) if args.recompute_rows else None
    input_rows_path = Path(args.input_rows)
    fibo_rows_path = Path(args.fibo_rows)
    output_dir = Path(args.output_dir)

    context_rows = load_context_like_rows(context_rows_path)
    recompute_rows = load_context_like_rows(recompute_rows_path) if recompute_rows_path else []
    event_rows = load_event_rows(input_rows_path, symbols=symbols)
    fibo_by_symbol = load_fibo_rows(fibo_rows_path)

    rows = build_event_level_rows(
        event_rows=event_rows,
        context_rows=context_rows,
        recompute_rows=recompute_rows,
        fibo_by_symbol=fibo_by_symbol,
    )
    manifest = build_manifest(args=args, output_dir=output_dir, rows=rows)

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
