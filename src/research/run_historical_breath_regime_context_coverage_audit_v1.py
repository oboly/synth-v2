from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPORT_NAME = "historical_breath_regime_context_coverage_audit_v1"
REPORT_VERSION = "1.0"

DEFAULT_CONTEXT_ROWS = Path(
    "data/research/historical_breath_regime_context_builder_v1/historical_breath_regime_context_rows_v1.csv"
)
DEFAULT_PROFILE_ROWS = Path(
    "data/research/symbol_reaction_profile_by_context_v1/symbol_reaction_profile_by_context_rows_v1.csv"
)
DEFAULT_OUTPUT_DIR = Path("data/research/historical_breath_regime_context_coverage_audit_v1")

SUMMARY_CSV = "context_coverage_summary_v1.csv"
SYMBOL_ROWS_CSV = "symbol_context_coverage_rows_v1.csv"
MANIFEST_JSON = "manifest_v1.json"

CONTEXT_FIELDS = (
    "breath_phase",
    "breath_alignment",
    "market_regime",
    "btc_context",
    "symbol_regime",
    "fibo_context",
    "aplus_context_state",
    "martee_context_state",
)

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
        description="Audit historical context and profile coverage from existing research CSV outputs."
    )
    parser.add_argument("--context-rows", default=str(DEFAULT_CONTEXT_ROWS))
    parser.add_argument("--profile-rows", default=str(DEFAULT_PROFILE_ROWS))
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_unknown(value: Any) -> bool:
    return str(value or "").strip().upper() in {"", "UNKNOWN"}


def load_required_csv(path: Path, *, label: str) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing {label} file: {path}")
    rows = read_csv_rows(path)
    if not rows:
        raise ValueError(f"{label} file is empty: {path}")
    return rows


def distribution(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter[str(row.get(field) or "UNKNOWN")] += 1
    return dict(sorted(counter.items()))


def unknown_rate(rows: list[dict[str, Any]], field: str) -> float:
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if is_unknown(row.get(field))) / len(rows) * 100.0, 6)


def per_symbol_context_coverage(context_rows: list[dict[str, str]], profile_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    context_by_symbol: dict[str, list[dict[str, str]]] = defaultdict(list)
    profile_by_symbol: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in context_rows:
        context_by_symbol[str(row.get("symbol") or "").upper()].append(row)
    for row in profile_rows:
        profile_by_symbol[str(row.get("symbol") or "").upper()].append(row)

    symbols = sorted(set(context_by_symbol) | set(profile_by_symbol))
    output: list[dict[str, Any]] = []
    for symbol in symbols:
        symbol_context_rows = context_by_symbol.get(symbol, [])
        symbol_profile_rows = profile_by_symbol.get(symbol, [])
        unknown_counts = {
            field: round(
                sum(1 for row in symbol_context_rows if is_unknown(row.get(field))) / len(symbol_context_rows) * 100.0,
                6,
            )
            if symbol_context_rows
            else 0.0
            for field in CONTEXT_FIELDS
        }
        output.append(
            {
                "symbol": symbol,
                "context_row_count": len(symbol_context_rows),
                "profile_row_count": len(symbol_profile_rows),
                "profile_unknown_breath_count": sum(1 for row in symbol_profile_rows if is_unknown(row.get("breath_phase"))),
                "profile_unknown_regime_count": sum(1 for row in symbol_profile_rows if is_unknown(row.get("market_regime"))),
                "context_enriched_profile_rows": sum(
                    1
                    for row in symbol_profile_rows
                    if not is_unknown(row.get("breath_phase")) or not is_unknown(row.get("market_regime"))
                ),
                "unknown_heavy_profile_rows": sum(
                    1
                    for row in symbol_profile_rows
                    if is_unknown(row.get("breath_phase")) and is_unknown(row.get("market_regime"))
                ),
                "unknown_breath_phase_rate_pct": unknown_counts["breath_phase"],
                "unknown_market_regime_rate_pct": unknown_counts["market_regime"],
                "quality_state_distribution": json.dumps(distribution(symbol_context_rows, "quality_state"), sort_keys=True),
                "profile_label_distribution": json.dumps(distribution(symbol_profile_rows, "profile_label"), sort_keys=True),
            }
        )
    return output


def top_missing_context_fields(context_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in CONTEXT_FIELDS:
        rows.append(
            {
                "metric": f"unknown_rate_{field}_pct",
                "value": unknown_rate(context_rows, field),
            }
        )
    rows.sort(key=lambda row: (-float(row["value"]), row["metric"]))
    return rows


def coverage_status(profile_rows: list[dict[str, str]]) -> str:
    if not profile_rows:
        return "UNUSABLE_NO_PROFILE_ROWS"
    enriched = sum(
        1
        for row in profile_rows
        if not is_unknown(row.get("breath_phase")) or not is_unknown(row.get("market_regime"))
    )
    ratio = enriched / len(profile_rows)
    if ratio >= 0.7:
        return "USABLE"
    if ratio >= 0.3:
        return "PARTIAL"
    return "UNKNOWN_HEAVY"


def recommended_next_enrichment_target(context_rows: list[dict[str, str]], profile_rows: list[dict[str, str]]) -> str:
    missing = top_missing_context_fields(context_rows)
    top_metric = missing[0]["metric"] if missing else ""
    profile_unknown_breath = unknown_rate(profile_rows, "breath_phase")
    profile_unknown_regime = unknown_rate(profile_rows, "market_regime")
    if profile_unknown_breath >= profile_unknown_regime:
        return "Densify historical market-breath rows across lifecycle event dates."
    if "fibo_context" in top_metric:
        return "Add replay-safe fibo context enrichment to the historical context builder."
    if "aplus_context_state" in top_metric:
        return "Increase historical A+ snapshot coverage and timestamp alignment."
    return "Densify historical regime coverage and timestamp alignment."


def build_summary(context_rows: list[dict[str, str]], profile_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    per_symbol_rows = per_symbol_context_coverage(context_rows, profile_rows)
    context_unknown_heavy = sum(
        1
        for row in context_rows
        if sum(1 for field in CONTEXT_FIELDS if is_unknown(row.get(field))) >= 4
    )
    profile_unknown_heavy = sum(
        1
        for row in profile_rows
        if is_unknown(row.get("breath_phase")) and is_unknown(row.get("market_regime"))
    )
    summary_rows = [
        {"metric": "total_context_rows", "value": len(context_rows)},
        {"metric": "total_profile_rows", "value": len(profile_rows)},
        {"metric": "context_unknown_heavy_rows", "value": context_unknown_heavy},
        {"metric": "profile_unknown_heavy_rows", "value": profile_unknown_heavy},
        {"metric": "context_enriched_profile_rows", "value": sum(1 for row in profile_rows if not is_unknown(row.get("breath_phase")) or not is_unknown(row.get("market_regime")))},
    ]
    for field in CONTEXT_FIELDS:
        summary_rows.append({"metric": f"unknown_rate_{field}_pct", "value": unknown_rate(context_rows, field)})
    summary_rows.extend(
        {"metric": f"quality_state_{key}", "value": value}
        for key, value in distribution(context_rows, "quality_state").items()
    )
    summary_rows.extend(
        {"metric": f"confidence_bucket_{key}", "value": value}
        for key, value in distribution(context_rows, "confidence_bucket").items()
    )
    summary_rows.extend(
        {"metric": f"profile_label_{key}", "value": value}
        for key, value in distribution(profile_rows, "profile_label").items()
    )
    summary_rows.extend(
        {"metric": f"sample_quality_{key}", "value": value}
        for key, value in distribution(profile_rows, "sample_quality").items()
    )

    summary = {
        "coverage_status": coverage_status(profile_rows),
        "top_missing_context_fields": top_missing_context_fields(context_rows),
        "recommended_next_enrichment_target": recommended_next_enrichment_target(context_rows, profile_rows),
        "per_symbol_rows": per_symbol_rows,
        "summary_rows": summary_rows,
    }
    return summary_rows, summary


def build_manifest(*, context_rows_path: Path, profile_rows_path: Path, output_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "context_rows_path": str(context_rows_path),
        "profile_rows_path": str(profile_rows_path),
        "coverage_status": summary["coverage_status"],
        "recommended_next_enrichment_target": summary["recommended_next_enrichment_target"],
        "output_dir": str(output_dir),
        "output_files": {
            "summary_csv": str(output_dir / SUMMARY_CSV),
            "symbol_rows_csv": str(output_dir / SYMBOL_ROWS_CSV),
            "manifest_json": str(output_dir / MANIFEST_JSON),
        },
        "safety_markers": SAFETY_MARKERS,
        "research_only": True,
    }


def print_summary(summary: dict[str, Any], *, output_mode: str) -> None:
    if output_mode == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True))
        return
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(f"coverage_status={summary['coverage_status']}")
    print(f"recommended_next_enrichment_target={summary['recommended_next_enrichment_target']}")
    top_missing = summary["top_missing_context_fields"][:4]
    if top_missing:
        print("top_missing " + " ; ".join(f"{row['metric']}:{row['value']}" for row in top_missing))
    print(
        "safety "
        + " ".join(
            f"{key}={str(value).lower() if isinstance(value, bool) else value}"
            for key, value in SAFETY_MARKERS.items()
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    context_rows_path = Path(args.context_rows)
    profile_rows_path = Path(args.profile_rows)
    output_dir = Path(args.output_dir)

    context_rows = load_required_csv(context_rows_path, label="context rows")
    profile_rows = load_required_csv(profile_rows_path, label="profile rows")
    summary_rows, summary = build_summary(context_rows, profile_rows)
    manifest = build_manifest(
        context_rows_path=context_rows_path,
        profile_rows_path=profile_rows_path,
        output_dir=output_dir,
        summary=summary,
    )

    if args.write_files:
        write_csv(output_dir / SUMMARY_CSV, summary_rows)
        write_csv(output_dir / SYMBOL_ROWS_CSV, summary["per_symbol_rows"])
        write_json(output_dir / MANIFEST_JSON, manifest)

    payload = {
        "summary_rows": summary_rows,
        "per_symbol_rows": summary["per_symbol_rows"],
        "coverage_status": summary["coverage_status"],
        "recommended_next_enrichment_target": summary["recommended_next_enrichment_target"],
        "top_missing_context_fields": summary["top_missing_context_fields"],
        "manifest": manifest,
    }
    print_summary(payload, output_mode=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
