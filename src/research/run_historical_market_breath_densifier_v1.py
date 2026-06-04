from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.research.run_historical_breath_regime_context_builder_v1 import (
    SAFETY_MARKERS,
    canonical_breath_alignment,
    canonical_breath_phase,
    confidence_bucket,
    fmt_ts,
    load_market_breath_rows,
    market_regime_from_scores,
    parse_symbols_arg,
    parse_ts,
    quality_state_from_row,
    read_jsonl,
    relative_strength_bucket,
    momentum_bucket,
    symbol_regime_from_scores,
    btc_context_from_scores,
    write_csv,
    write_json,
    write_jsonl,
)


REPORT_NAME = "historical_market_breath_densifier_v1"
REPORT_VERSION = "1.0"

DEFAULT_CONTEXT_ROWS = Path(
    "data/research/historical_breath_regime_context_builder_v1/historical_breath_regime_context_rows_v1.csv"
)
DEFAULT_PROFILE_ROWS = Path(
    "data/research/symbol_reaction_profile_by_context_v1/symbol_reaction_profile_by_context_rows_v1.csv"
)
DEFAULT_MARKET_BREATH_ROWS = Path("data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl")
DEFAULT_EVENT_ROWS = Path("data/research/position_lifecycle_outcome_validation_v1/outcome_rows_v1.jsonl")
DEFAULT_OUTPUT_DIR = Path("data/research/historical_market_breath_densifier_v1")

ROWS_CSV = "historical_market_breath_densified_rows_v1.csv"
ROWS_JSONL = "historical_market_breath_densified_rows_v1.jsonl"
MANIFEST_JSON = "manifest_v1.json"

MAX_NEARBY_STALENESS = timedelta(days=7)
UNKNOWN_KEYS = (
    "breath_phase",
    "breath_alignment",
    "market_regime",
    "btc_context",
    "symbol_regime",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Densify historical context rows around lifecycle/profile event dates using "
            "available market-breath research rows (research-only, file-output only)."
        )
    )
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--context-rows", default=str(DEFAULT_CONTEXT_ROWS))
    parser.add_argument("--profile-rows", default=str(DEFAULT_PROFILE_ROWS))
    parser.add_argument("--market-breath-rows", default=str(DEFAULT_MARKET_BREATH_ROWS))
    parser.add_argument("--event-rows", default=str(DEFAULT_EVENT_ROWS))
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_unknown(value: Any) -> bool:
    return str(value or "").strip().upper() in {"", "UNKNOWN"}


def load_context_rows(path: Path) -> list[dict[str, Any]]:
    rows = read_csv_rows(path)
    out: list[dict[str, Any]] = []
    for row in rows:
        asof_ts = parse_ts(row.get("asof_ts_utc"))
        symbol = str(row.get("symbol") or "").strip().upper()
        if asof_ts is None or not symbol:
            continue
        item = dict(row)
        item["symbol"] = symbol
        item["asof_ts_utc_dt"] = asof_ts
        source_refs = row.get("source_refs")
        if isinstance(source_refs, str) and source_refs.strip():
            try:
                item["source_refs"] = json.loads(source_refs)
            except Exception:
                item["source_refs"] = []
        else:
            item["source_refs"] = []
        out.append(item)
    return out


def load_profile_rows(path: Path) -> list[dict[str, Any]]:
    return [dict(row) for row in read_csv_rows(path)]


def load_event_rows(path: Path, symbols: set[str] | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = read_jsonl(path)
    out: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        event_ts = parse_ts(row.get("event_ts_utc"))
        if not symbol or event_ts is None:
            continue
        if symbols is not None and symbol not in symbols:
            continue
        out.append({"symbol": symbol, "event_ts_utc": event_ts, "source_row": row})
    out.sort(key=lambda item: (item["symbol"], item["event_ts_utc"]))
    return out


def build_lookup(rows: list[dict[str, Any]], ts_key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(rows, key=lambda item: (item["symbol"], item[ts_key])):
        grouped[row["symbol"]].append(row)
    return dict(grouped)


def nearest_row(rows: list[dict[str, Any]], *, target_ts: datetime, ts_key: str) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_delta: timedelta | None = None
    for row in rows:
        delta = abs(row[ts_key] - target_ts)
        if best_delta is None or delta < best_delta or (delta == best_delta and row[ts_key] < best[ts_key]):
            best = row
            best_delta = delta
    if best is None or best_delta is None or best_delta > MAX_NEARBY_STALENESS:
        return None
    return best


def unknown_heavy(row: dict[str, Any]) -> bool:
    return sum(1 for key in UNKNOWN_KEYS if is_unknown(row.get(key))) >= 3


def unknown_core_count(row: dict[str, Any]) -> int:
    return sum(1 for key in UNKNOWN_KEYS if is_unknown(row.get(key)))


def densified_row_from_source(
    *,
    symbol: str,
    event_ts_utc: datetime,
    existing_row: dict[str, Any] | None,
    source_row: dict[str, Any] | None,
) -> tuple[dict[str, Any], bool]:
    base = dict(existing_row) if existing_row is not None else {
        "symbol": symbol,
        "venue": str(source_row.get("venue") if source_row else "bitvavo"),
        "interval": str(source_row.get("interval") if source_row else "4h"),
        "asof_ts_utc": fmt_ts(event_ts_utc),
        "source_event_ts_utc": fmt_ts(event_ts_utc),
        "breath_phase": "UNKNOWN",
        "breath_alignment": "UNKNOWN",
        "market_regime": "UNKNOWN",
        "btc_context": "UNKNOWN",
        "symbol_regime": "UNKNOWN",
        "fibo_context": "UNKNOWN",
        "aplus_context_state": "UNKNOWN",
        "martee_context_state": "UNKNOWN",
        "relative_strength_bucket": "UNKNOWN",
        "momentum_bucket": "UNKNOWN",
        "quality_state": "UNKNOWN",
        "confidence_bucket": "UNKNOWN",
        "source_refs": [],
        "research_only": True,
    }
    base["symbol"] = symbol
    base["asof_ts_utc"] = fmt_ts(event_ts_utc)
    base["asof_ts_utc_dt"] = event_ts_utc
    if not isinstance(base.get("source_refs"), list):
        base["source_refs"] = []
    before_unknown = unknown_core_count(base)
    enriched = False
    if source_row is not None:
        mapped = {
            "breath_phase": str(source_row.get("breath_phase") or canonical_breath_phase(source_row.get("market_breath_phase"))).upper(),
            "breath_alignment": str(source_row.get("breath_alignment") or canonical_breath_alignment(source_row.get("market_breath_state"))).upper(),
            "market_regime": str(source_row.get("market_regime") or market_regime_from_scores(source_row)).upper(),
            "btc_context": str(source_row.get("btc_context") or btc_context_from_scores(source_row)).upper(),
            "symbol_regime": str(source_row.get("symbol_regime") or symbol_regime_from_scores(source_row)).upper(),
            "relative_strength_bucket": str(source_row.get("relative_strength_bucket") or relative_strength_bucket(as_float(source_row.get("relative_strength_score")))).upper(),
            "momentum_bucket": str(source_row.get("momentum_bucket") or momentum_bucket(as_float(source_row.get("momentum_score")))).upper(),
            "confidence_bucket": str(source_row.get("confidence_bucket") or confidence_bucket(as_float(source_row.get("market_breath_confidence")))).upper(),
        }
        for key, value in mapped.items():
            if is_unknown(base.get(key)) and not is_unknown(value):
                base[key] = value
                enriched = True
        if enriched or existing_row is None:
            base["source_event_ts_utc"] = fmt_ts(source_row.get("source_event_ts_utc") or source_row.get("asof_ts_utc"))
        ref = {
            "source": "historical_market_breath_densifier_v1",
            "upstream_source": source_row.get("source_name", "market_breath_outcome_validation_v1"),
            "upstream_asof_ts_utc": fmt_ts(source_row.get("asof_ts_utc")),
        }
        if ref not in base["source_refs"]:
            base["source_refs"].append(ref)
    base["quality_state"] = quality_state_from_row(base)
    base["research_only"] = True
    after_unknown = unknown_core_count(base)
    improved = after_unknown < before_unknown
    return base, enriched and improved


def densify_rows(
    *,
    context_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    market_breath_rows: list[dict[str, Any]],
    symbols: set[str] | None = None,
    max_rows: int = 0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if symbols is not None:
        context_rows = [row for row in context_rows if row["symbol"] in symbols]
        event_rows = [row for row in event_rows if row["symbol"] in symbols]
        market_breath_rows = [row for row in market_breath_rows if row["symbol"] in symbols]

    context_lookup = build_lookup(context_rows, "asof_ts_utc_dt")
    source_lookup = build_lookup(market_breath_rows, "asof_ts_utc")

    output_rows: dict[tuple[str, datetime], dict[str, Any]] = {
        (row["symbol"], row["asof_ts_utc_dt"]): dict(row)
        for row in context_rows
    }
    unknown_before = sum(1 for row in context_rows if unknown_heavy(row))
    enriched_rows = 0

    targets = event_rows[: int(max_rows)] if max_rows > 0 else list(event_rows)
    for target in targets:
        symbol = target["symbol"]
        event_ts = target["event_ts_utc"]
        existing = nearest_row(context_lookup.get(symbol, []), target_ts=event_ts, ts_key="asof_ts_utc_dt")
        if existing is not None and not unknown_heavy(existing):
            continue
        source = nearest_row(source_lookup.get(symbol, []), target_ts=event_ts, ts_key="asof_ts_utc")
        if source is None:
            continue
        densified, enriched = densified_row_from_source(
            symbol=symbol,
            event_ts_utc=event_ts,
            existing_row=existing,
            source_row=source,
        )
        if existing is not None and not enriched:
            continue
        if existing is None and unknown_heavy(densified):
            continue
        output_rows[(symbol, event_ts)] = densified
        if enriched:
            enriched_rows += 1

    rows = sorted(output_rows.values(), key=lambda row: (row["symbol"], row["asof_ts_utc"]))
    unknown_after = sum(1 for row in rows if unknown_heavy(row))
    measures = {
        "input_context_rows": len(context_rows),
        "input_profile_rows": None,
        "output_rows": len(rows),
        "enriched_rows": enriched_rows,
        "unknown_heavy_before": unknown_before,
        "unknown_heavy_after": unknown_after,
        "breath_phase_unknown_before": sum(1 for row in context_rows if is_unknown(row.get("breath_phase"))),
        "breath_phase_unknown_after": sum(1 for row in rows if is_unknown(row.get("breath_phase"))),
        "breath_alignment_unknown_before": sum(1 for row in context_rows if is_unknown(row.get("breath_alignment"))),
        "breath_alignment_unknown_after": sum(1 for row in rows if is_unknown(row.get("breath_alignment"))),
        "market_regime_unknown_before": sum(1 for row in context_rows if is_unknown(row.get("market_regime"))),
        "market_regime_unknown_after": sum(1 for row in rows if is_unknown(row.get("market_regime"))),
        "symbol_regime_unknown_before": sum(1 for row in context_rows if is_unknown(row.get("symbol_regime"))),
        "symbol_regime_unknown_after": sum(1 for row in rows if is_unknown(row.get("symbol_regime"))),
        "quality_state_distribution": dict(sorted(Counter(str(row.get("quality_state") or "UNKNOWN") for row in rows).items())),
        "source_coverage": dict(sorted(Counter(
            ref.get("source", "UNKNOWN")
            for row in rows
            for ref in (row.get("source_refs") or [])
            if isinstance(ref, dict)
        ).items())),
    }
    return rows, measures


def build_manifest(*, output_dir: Path, measures: dict[str, Any], source_paths: dict[str, str]) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "output_dir": str(output_dir),
        "output_files": {
            "rows_csv": str(output_dir / ROWS_CSV),
            "rows_jsonl": str(output_dir / ROWS_JSONL),
            "manifest_json": str(output_dir / MANIFEST_JSON),
        },
        "source_paths": source_paths,
        "measures": measures,
        "safety_markers": SAFETY_MARKERS,
        "research_only": True,
    }


def print_summary(*, measures: dict[str, Any], output_mode: str, manifest: dict[str, Any]) -> None:
    payload = {"measures": measures, "manifest": manifest}
    if output_mode == "json":
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))
        return
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(
        f"input_context_rows={measures['input_context_rows']} output_rows={measures['output_rows']} "
        f"enriched_rows={measures['enriched_rows']}"
    )
    print(
        f"unknown_heavy_before={measures['unknown_heavy_before']} "
        f"unknown_heavy_after={measures['unknown_heavy_after']}"
    )
    print(
        f"breath_phase_unknown_before={measures['breath_phase_unknown_before']} "
        f"after={measures['breath_phase_unknown_after']}"
    )
    print(
        f"breath_alignment_unknown_before={measures['breath_alignment_unknown_before']} "
        f"after={measures['breath_alignment_unknown_after']}"
    )
    print(
        f"market_regime_unknown_before={measures['market_regime_unknown_before']} "
        f"after={measures['market_regime_unknown_after']}"
    )
    print(
        f"symbol_regime_unknown_before={measures['symbol_regime_unknown_before']} "
        f"after={measures['symbol_regime_unknown_after']}"
    )
    print("quality_state " + " ; ".join(f"{k}:{v}" for k, v in measures["quality_state_distribution"].items()))
    print("source_coverage " + " ; ".join(f"{k}:{v}" for k, v in measures["source_coverage"].items()))
    print(
        "safety "
        + " ".join(
            f"{key}={str(value).lower() if isinstance(value, bool) else value}"
            for key, value in SAFETY_MARKERS.items()
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = parse_symbols_arg(args.symbols)
    symbol_set = None if symbols is None else set(symbols)
    context_rows_path = Path(args.context_rows)
    profile_rows_path = Path(args.profile_rows)
    market_breath_rows_path = Path(args.market_breath_rows)
    event_rows_path = Path(args.event_rows)
    output_dir = Path(args.output_dir)

    context_rows = load_context_rows(context_rows_path)
    profile_rows = load_profile_rows(profile_rows_path) if profile_rows_path.exists() else []
    event_rows = load_event_rows(event_rows_path, symbols=symbol_set)
    market_breath_rows = load_market_breath_rows(market_breath_rows_path) if market_breath_rows_path.exists() else []

    rows, measures = densify_rows(
        context_rows=context_rows,
        event_rows=event_rows,
        market_breath_rows=market_breath_rows,
        symbols=symbol_set,
        max_rows=int(args.max_rows or 0),
    )
    measures["input_profile_rows"] = len(profile_rows)

    manifest = build_manifest(
        output_dir=output_dir,
        measures=measures,
        source_paths={
            "context_rows": str(context_rows_path),
            "profile_rows": str(profile_rows_path),
            "market_breath_rows": str(market_breath_rows_path),
            "event_rows": str(event_rows_path),
        },
    )

    if args.write_files:
        persist_rows: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item.pop("asof_ts_utc_dt", None)
            persist_rows.append(item)
        write_csv(output_dir / ROWS_CSV, persist_rows)
        write_jsonl(output_dir / ROWS_JSONL, persist_rows)
        write_json(output_dir / MANIFEST_JSON, manifest)

    print_summary(measures=measures, output_mode=args.output, manifest=manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
