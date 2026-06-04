from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.research.run_historical_breath_regime_context_builder_v1 import (
    DEFAULT_INTERVAL,
    DEFAULT_VENUE,
    SAFETY_MARKERS,
    as_float,
    btc_context_from_scores,
    canonical_breath_alignment,
    canonical_breath_phase,
    confidence_bucket,
    fmt_ts,
    market_regime_from_scores,
    momentum_bucket,
    parse_symbols_arg,
    parse_ts,
    read_jsonl,
    relative_strength_bucket,
    symbol_regime_from_scores,
    write_csv,
    write_json,
    write_jsonl,
)


REPORT_NAME = "historical_market_breath_source_enrichment_v1"
REPORT_VERSION = "1.0"

DEFAULT_INPUT_ROWS = Path("data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl")
DEFAULT_CONTEXT_ROWS = Path("data/research/historical_breath_regime_context_builder_v1/historical_breath_regime_context_rows_v1.csv")
DEFAULT_PROFILE_ROWS = Path("data/research/symbol_reaction_profile_by_context_v1/symbol_reaction_profile_by_context_rows_v1.csv")
DEFAULT_OUTPUT_DIR = Path("data/research/historical_market_breath_source_enrichment_v1")

ROWS_CSV = "historical_market_breath_source_enriched_rows_v1.csv"
ROWS_JSONL = "historical_market_breath_source_enriched_rows_v1.jsonl"
MANIFEST_JSON = "manifest_v1.json"

UNKNOWN = "UNKNOWN"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich historical market-breath source rows with canonical context fields "
            "(research-only, market-only, file-output only)."
        )
    )
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--input-rows", default=str(DEFAULT_INPUT_ROWS))
    parser.add_argument("--context-rows", default=str(DEFAULT_CONTEXT_ROWS))
    parser.add_argument("--profile-rows", default=str(DEFAULT_PROFILE_ROWS))
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def raw_phase_known(value: Any) -> bool:
    phase = str(value or "").strip().upper()
    return phase not in ("", UNKNOWN, "NEUTRAL_TRANSITION", "INSUFFICIENT_DATA")


def raw_alignment_known(value: Any) -> bool:
    state = str(value or "").strip().upper()
    return state not in ("", UNKNOWN)


def quality_state_for_row(row: dict[str, Any]) -> str:
    breath_known = str(row.get("breath_phase") or UNKNOWN).upper() != UNKNOWN
    symbol_regime_known = str(row.get("symbol_regime") or UNKNOWN).upper() != UNKNOWN
    market_regime_known = str(row.get("market_regime") or UNKNOWN).upper() != UNKNOWN
    btc_context_known = str(row.get("btc_context") or UNKNOWN).upper() != UNKNOWN

    if breath_known and (symbol_regime_known or market_regime_known or btc_context_known):
        return "HIGH"
    if symbol_regime_known or market_regime_known or btc_context_known:
        return "MEDIUM"
    return "LOW"


def normalize_row(
    row: dict[str, Any],
    *,
    input_path: Path,
    default_venue: str,
    default_interval: str,
) -> dict[str, Any] | None:
    symbol = str(row.get("symbol") or "").strip().upper()
    asof_ts = parse_ts(row.get("asof_ts_utc"))
    if not symbol or asof_ts is None:
        return None

    market_breath_phase_raw = str(row.get("market_breath_phase") or "").strip().upper() or UNKNOWN
    market_breath_state_raw = str(row.get("market_breath_state") or "").strip().upper() or UNKNOWN
    relative_strength_score = as_float(row.get("relative_strength_score"))
    momentum_score = as_float(row.get("momentum_score"))

    normalized = {
        "symbol": symbol,
        "venue": str(row.get("venue") or default_venue).strip().lower(),
        "interval": str(row.get("interval_code") or row.get("interval") or default_interval).strip(),
        "asof_ts_utc": fmt_ts(asof_ts),
        "source_event_ts_utc": fmt_ts(asof_ts),
        "market_breath_phase_raw": market_breath_phase_raw,
        "market_breath_state_raw": market_breath_state_raw,
        "breath_phase": canonical_breath_phase(market_breath_phase_raw),
        "breath_alignment": canonical_breath_alignment(market_breath_state_raw),
        "market_regime": market_regime_from_scores(row),
        "btc_context": btc_context_from_scores(row),
        "symbol_regime": symbol_regime_from_scores(row),
        "relative_strength_score": relative_strength_score,
        "momentum_score": momentum_score,
        "relative_strength_bucket": relative_strength_bucket(relative_strength_score),
        "momentum_bucket": momentum_bucket(momentum_score),
        "confidence_bucket": confidence_bucket(as_float(row.get("market_breath_confidence"))),
        "source_refs": [
            {
                "source": "market_breath_outcome_validation_v1",
                "path": str(input_path),
                "asof_ts_utc": fmt_ts(asof_ts),
            }
        ],
        "research_only": True,
    }
    normalized["quality_state"] = quality_state_for_row(normalized)
    return normalized


def load_input_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Input rows file not found: {path}")
    return read_jsonl(path)


def enrich_rows(
    rows: list[dict[str, Any]],
    *,
    input_path: Path,
    symbols: list[str] | None,
    default_venue: str,
    default_interval: str,
    max_rows: int = 0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    allowed = set(symbols or [])
    enriched: list[dict[str, Any]] = []

    raw_phase_known_before = 0
    raw_alignment_known_before = 0
    symbol_regime_known_before = 0

    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if allowed and symbol not in allowed:
            continue
        if raw_phase_known(row.get("market_breath_phase")):
            raw_phase_known_before += 1
        if raw_alignment_known(row.get("market_breath_state")):
            raw_alignment_known_before += 1
        if str(row.get("symbol_regime") or "").strip().upper() not in ("", UNKNOWN):
            symbol_regime_known_before += 1

        normalized = normalize_row(
            row,
            input_path=input_path,
            default_venue=default_venue,
            default_interval=default_interval,
        )
        if normalized is None:
            continue
        enriched.append(normalized)
        if max_rows > 0 and len(enriched) >= max_rows:
            break

    enriched.sort(key=lambda item: (item["symbol"], item["asof_ts_utc"]))

    breath_phase_known_after = sum(1 for row in enriched if row["breath_phase"] != UNKNOWN)
    breath_alignment_known_after = sum(1 for row in enriched if row["breath_alignment"] != UNKNOWN)
    symbol_regime_known_after = sum(1 for row in enriched if row["symbol_regime"] != UNKNOWN)

    measures = {
        "input_rows": len(rows),
        "output_rows": len(enriched),
        "raw_phase_known_before": raw_phase_known_before,
        "breath_phase_known_after": breath_phase_known_after,
        "raw_alignment_known_before": raw_alignment_known_before,
        "breath_alignment_known_after": breath_alignment_known_after,
        "symbol_regime_known_before": symbol_regime_known_before,
        "symbol_regime_known_after": symbol_regime_known_after,
        "breath_phase_unknown_after": len(enriched) - breath_phase_known_after,
        "breath_alignment_unknown_after": len(enriched) - breath_alignment_known_after,
        "symbol_regime_unknown_after": len(enriched) - symbol_regime_known_after,
        "quality_state_distribution": dict(Counter(str(row["quality_state"]) for row in enriched)),
        "source_coverage": dict(Counter(ref["source"] for row in enriched for ref in row["source_refs"])),
    }
    return enriched, measures


def build_manifest(
    *,
    args: argparse.Namespace,
    input_path: Path,
    measures: dict[str, Any],
    output_paths: dict[str, str],
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "scope": "research-only market-only file-output",
        "symbols": parse_symbols_arg(args.symbols) or [],
        "venue": args.venue,
        "interval": args.interval,
        "input_rows_path": str(input_path),
        "context_rows_path": str(args.context_rows),
        "profile_rows_path": str(args.profile_rows),
        "measures": measures,
        "safety_markers": SAFETY_MARKERS,
        "output_paths": output_paths,
    }


def print_summary(*, measures: dict[str, Any]) -> None:
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(f"input_rows={measures['input_rows']} output_rows={measures['output_rows']}")
    print(
        "breath_phase_known_before/after="
        f"{measures['raw_phase_known_before']}/{measures['breath_phase_known_after']}"
    )
    print(
        "breath_alignment_known_before/after="
        f"{measures['raw_alignment_known_before']}/{measures['breath_alignment_known_after']}"
    )
    print(
        "symbol_regime_known_before/after="
        f"{measures['symbol_regime_known_before']}/{measures['symbol_regime_known_after']}"
    )
    quality_bits = " ; ".join(
        f"{key}:{value}"
        for key, value in sorted(measures["quality_state_distribution"].items())
    )
    if quality_bits:
        print(f"quality_state {quality_bits}")
    source_bits = " ; ".join(
        f"{key}:{value}"
        for key, value in sorted(measures["source_coverage"].items())
    )
    if source_bits:
        print(f"source_coverage {source_bits}")
    print(
        "safety "
        f"research_only={str(SAFETY_MARKERS['research_only']).lower()} "
        f"broker_calls={SAFETY_MARKERS['broker_calls']} "
        f"broker_writes={SAFETY_MARKERS['broker_writes']} "
        f"order_submission={SAFETY_MARKERS['order_submission']} "
        f"executor={SAFETY_MARKERS['executor']} "
        f"db_writes={SAFETY_MARKERS['db_writes']}"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = parse_symbols_arg(args.symbols)
    input_path = Path(args.input_rows)
    output_dir = Path(args.output_dir)

    rows = load_input_rows(input_path)
    enriched, measures = enrich_rows(
        rows,
        input_path=input_path,
        symbols=symbols,
        default_venue=args.venue,
        default_interval=args.interval,
        max_rows=args.max_rows,
    )

    output_paths: dict[str, str] = {}
    if args.write_files:
        csv_path = output_dir / ROWS_CSV
        jsonl_path = output_dir / ROWS_JSONL
        manifest_path = output_dir / MANIFEST_JSON
        write_csv(csv_path, enriched)
        write_jsonl(jsonl_path, enriched)
        output_paths = {
            "csv": str(csv_path),
            "jsonl": str(jsonl_path),
            "manifest": str(manifest_path),
        }
        manifest = build_manifest(
            args=args,
            input_path=input_path,
            measures=measures,
            output_paths=output_paths,
        )
        write_json(manifest_path, manifest)

    payload = {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "measures": measures,
        "safety_markers": SAFETY_MARKERS,
        "output_paths": output_paths,
    }
    if args.output == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_summary(measures=measures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
