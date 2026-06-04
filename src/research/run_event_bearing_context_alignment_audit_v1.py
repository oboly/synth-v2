from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPORT_NAME = "event_bearing_context_alignment_audit_v1"
REPORT_VERSION = "1.0"

DEFAULT_RECOMPUTE_ROWS = Path(
    "data/research/historical_market_breath_source_recompute_v1/historical_market_breath_source_recomputed_rows_v1.csv"
)
DEFAULT_CONTEXT_ROWS = Path(
    "data/research/historical_breath_regime_context_builder_v1/historical_breath_regime_context_rows_v1.csv"
)
DEFAULT_PROFILE_ROWS = Path(
    "data/research/symbol_reaction_profile_by_context_v1/symbol_reaction_profile_by_context_rows_v1.csv"
)
DEFAULT_CONTEXT_QUALIFIED_AUDIT_ROWS = Path(
    "data/research/context_qualified_symbol_reaction_profile_audit_v1/context_qualified_profile_audit_rows_v1.csv"
)
DEFAULT_OUTPUT_DIR = Path("data/research/event_bearing_context_alignment_audit_v1")

ROWS_CSV = "event_bearing_context_alignment_rows_v1.csv"
MANIFEST_JSON = "manifest_v1.json"

CONTEXT_FIELDS = (
    "breath_phase",
    "breath_alignment",
    "market_regime",
    "btc_context",
    "symbol_regime",
    "fibo_context",
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
        description="Audit whether known recomputed context rows align with event-bearing profile buckets."
    )
    parser.add_argument("--recompute-rows", default=str(DEFAULT_RECOMPUTE_ROWS))
    parser.add_argument("--context-rows", default=str(DEFAULT_CONTEXT_ROWS))
    parser.add_argument("--profile-rows", default=str(DEFAULT_PROFILE_ROWS))
    parser.add_argument("--context-qualified-audit-rows", default=str(DEFAULT_CONTEXT_QUALIFIED_AUDIT_ROWS))
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_required_csv(path: Path, *, label: str) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing {label} file: {path}")
    rows = read_csv_rows(path)
    if not rows:
        raise ValueError(f"{label} file is empty: {path}")
    return rows


def load_optional_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return read_csv_rows(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    converted_rows: list[dict[str, Any]] = []
    for row in rows:
        converted: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                converted[key] = json.dumps(value, sort_keys=True, ensure_ascii=True)
            else:
                converted[key] = value
        converted_rows.append(converted)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(converted_rows[0].keys()))
        writer.writeheader()
        writer.writerows(converted_rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def is_unknown(value: Any) -> bool:
    return str(value or "").strip().upper() in {"", "UNKNOWN"}


def as_int(value: Any) -> int:
    if value in ("", None):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def context_key(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(row.get("symbol") or "").strip().upper(),
        *(str(row.get(field) or "UNKNOWN").strip().upper() for field in CONTEXT_FIELDS),
    )


def known_recompute(row: dict[str, Any]) -> bool:
    return not is_unknown(row.get("breath_phase")) or not is_unknown(row.get("breath_alignment"))


def unknown_heavy_bucket(row: dict[str, Any]) -> bool:
    return sum(1 for field in CONTEXT_FIELDS if is_unknown(row.get(field))) >= 4


def issue_classification(
    *,
    recompute_row_count: int,
    recompute_known_count: int,
    profile_row_count: int,
    overlap_profile_row_count: int,
    overlap_event_count: int,
    context_overlap_count: int,
    profile_unknown_heavy_event_count: int,
) -> str:
    if overlap_profile_row_count > 0 and overlap_event_count > 0:
        return "USABLE_CONTEXT_OVERLAP"
    if recompute_row_count <= 0:
        return "NO_RECOMPUTE_KNOWN_ROWS"
    if recompute_known_count <= 0:
        return "LIVE_SEMANTICS_UNKNOWN"
    if profile_row_count <= 0:
        return "KNOWN_ROWS_NOT_EVENT_BEARING"
    if context_overlap_count > 0 and overlap_event_count <= 0:
        return "PROFILE_BUCKET_AGGREGATION_LOSSES"
    if recompute_known_count > 0 and profile_unknown_heavy_event_count > 0:
        return "KNOWN_ROWS_NOT_EVENT_BEARING"
    return "UNKNOWN"


def top_counter(counter: dict[str, int], limit: int = 5) -> list[dict[str, Any]]:
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [{"symbol": symbol, "value": value} for symbol, value in ranked[:limit]]


def build_alignment_rows(
    *,
    recompute_rows: list[dict[str, str]],
    context_rows: list[dict[str, str]],
    profile_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    recompute_by_symbol: dict[str, list[dict[str, str]]] = defaultdict(list)
    context_by_symbol: dict[str, list[dict[str, str]]] = defaultdict(list)
    profile_by_symbol: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in recompute_rows:
        recompute_by_symbol[str(row.get("symbol") or "").upper()].append(row)
    for row in context_rows:
        context_by_symbol[str(row.get("symbol") or "").upper()].append(row)
    for row in profile_rows:
        profile_by_symbol[str(row.get("symbol") or "").upper()].append(row)

    symbols = sorted(set(recompute_by_symbol) | set(context_by_symbol) | set(profile_by_symbol))
    output: list[dict[str, Any]] = []
    for symbol in symbols:
        symbol_recompute = recompute_by_symbol.get(symbol, [])
        symbol_context = context_by_symbol.get(symbol, [])
        symbol_profile = profile_by_symbol.get(symbol, [])

        recompute_key_counts: dict[tuple[str, ...], int] = defaultdict(int)
        recompute_known_key_counts: dict[tuple[str, ...], int] = defaultdict(int)
        for row in symbol_recompute:
            key = context_key(row)
            recompute_key_counts[key] += 1
            if known_recompute(row):
                recompute_known_key_counts[key] += 1

        context_key_counts: dict[tuple[str, ...], int] = defaultdict(int)
        for row in symbol_context:
            context_key_counts[context_key(row)] += 1

        profile_key_counts: dict[tuple[str, ...], int] = defaultdict(int)
        overlap_profile_row_count = 0
        overlap_event_count = 0
        profile_unknown_heavy_event_count = 0
        event_count_sum = 0
        for row in symbol_profile:
            key = context_key(row)
            profile_key_counts[key] += 1
            event_count = as_int(row.get("event_count"))
            event_count_sum += event_count
            if key in recompute_known_key_counts:
                overlap_profile_row_count += 1
                overlap_event_count += event_count
            if unknown_heavy_bucket(row):
                profile_unknown_heavy_event_count += event_count

        context_overlap_count = sum(
            count for key, count in context_key_counts.items() if key in recompute_known_key_counts
        )
        known_rows_with_zero_profile_events = sum(
            count for key, count in recompute_known_key_counts.items() if key not in profile_key_counts
        )
        issue = issue_classification(
            recompute_row_count=len(symbol_recompute),
            recompute_known_count=sum(recompute_known_key_counts.values()),
            profile_row_count=len(symbol_profile),
            overlap_profile_row_count=overlap_profile_row_count,
            overlap_event_count=overlap_event_count,
            context_overlap_count=context_overlap_count,
            profile_unknown_heavy_event_count=profile_unknown_heavy_event_count,
        )
        output.append(
            {
                "symbol": symbol,
                "profile_row_count": len(symbol_profile),
                "event_count_sum": event_count_sum,
                "recompute_row_count": len(symbol_recompute),
                "recompute_known_breath_phase_rows": sum(
                    1 for row in symbol_recompute if not is_unknown(row.get("breath_phase"))
                ),
                "recompute_known_breath_alignment_rows": sum(
                    1 for row in symbol_recompute if not is_unknown(row.get("breath_alignment"))
                ),
                "recompute_known_context_rows": sum(recompute_known_key_counts.values()),
                "context_row_count": len(symbol_context),
                "context_overlap_count": context_overlap_count,
                "overlap_profile_row_count": overlap_profile_row_count,
                "overlap_event_count": overlap_event_count,
                "known_rows_with_zero_profile_events": known_rows_with_zero_profile_events,
                "profile_unknown_heavy_event_count": profile_unknown_heavy_event_count,
                "issue_classification": issue,
                "research_only": True,
            }
        )
    output.sort(key=lambda row: row["symbol"])
    return output


def build_summary(alignment_rows: list[dict[str, Any]], context_qualified_rows: list[dict[str, str]]) -> dict[str, Any]:
    issue_distribution = dict(
        sorted(Counter(str(row.get("issue_classification") or "UNKNOWN") for row in alignment_rows).items())
    )
    useful_counter = {
        row["symbol"]: row["overlap_event_count"]
        for row in alignment_rows
        if row["overlap_event_count"] > 0
    }
    unknown_counter = {
        row["symbol"]: row["profile_unknown_heavy_event_count"]
        for row in alignment_rows
        if row["profile_unknown_heavy_event_count"] > 0
    }
    qualified_snapshot = {
        str(row.get("bucket")): {
            "profile_row_count": as_int(row.get("profile_row_count")),
            "event_count_sum": as_int(row.get("event_count_sum")),
            "skipped_reason": row.get("skipped_reason") or None,
        }
        for row in context_qualified_rows
    }
    return {
        "row_count": len(alignment_rows),
        "issue_distribution": issue_distribution,
        "top_symbols_where_context_is_useful": top_counter(useful_counter),
        "top_symbols_where_context_is_mostly_unknown": top_counter(unknown_counter),
        "qualified_bucket_snapshot": qualified_snapshot,
    }


def build_manifest(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "recompute_rows_path": str(args.recompute_rows),
        "context_rows_path": str(args.context_rows),
        "profile_rows_path": str(args.profile_rows),
        "context_qualified_audit_rows_path": str(args.context_qualified_audit_rows),
        "summary": summary,
        "output_dir": str(output_dir),
        "output_files": {
            "rows_csv": str(output_dir / ROWS_CSV),
            "manifest_json": str(output_dir / MANIFEST_JSON),
        },
        "safety_markers": SAFETY_MARKERS,
        "research_only": True,
    }


def print_summary(alignment_rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(
        "issue_distribution "
        + " ; ".join(f"{key}:{value}" for key, value in sorted(summary["issue_distribution"].items()))
    )
    for row in alignment_rows[:10]:
        print(
            f"symbol={row['symbol']} issue={row['issue_classification']} "
            f"overlap_event_count={row['overlap_event_count']} "
            f"known_zero_profile={row['known_rows_with_zero_profile_events']} "
            f"unknown_heavy_events={row['profile_unknown_heavy_event_count']}"
        )
    print(
        "safety "
        + " ".join(
            f"{key}={str(value).lower() if isinstance(value, bool) else value}"
            for key, value in SAFETY_MARKERS.items()
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir)

    recompute_rows = load_required_csv(Path(args.recompute_rows), label="recompute rows")
    context_rows = load_required_csv(Path(args.context_rows), label="context rows")
    profile_rows = load_required_csv(Path(args.profile_rows), label="profile rows")
    context_qualified_rows = load_optional_csv(Path(args.context_qualified_audit_rows))

    alignment_rows = build_alignment_rows(
        recompute_rows=recompute_rows,
        context_rows=context_rows,
        profile_rows=profile_rows,
    )
    summary = build_summary(alignment_rows, context_qualified_rows)
    manifest = build_manifest(args=args, output_dir=output_dir, summary=summary)

    if args.write_files:
        write_csv(output_dir / ROWS_CSV, alignment_rows)
        write_json(output_dir / MANIFEST_JSON, manifest)

    if args.output == "json":
        print(json.dumps({"rows": alignment_rows, "manifest": manifest}, indent=2, sort_keys=True))
    else:
        print_summary(alignment_rows, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
