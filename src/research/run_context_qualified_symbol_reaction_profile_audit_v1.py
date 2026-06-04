from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPORT_NAME = "context_qualified_symbol_reaction_profile_audit_v1"
REPORT_VERSION = "1.0"

DEFAULT_CONTEXT_ROWS = Path(
    "data/research/historical_breath_regime_context_builder_v1/historical_breath_regime_context_rows_v1.csv"
)
DEFAULT_PROFILE_ROWS = Path(
    "data/research/symbol_reaction_profile_by_context_v1/symbol_reaction_profile_by_context_rows_v1.csv"
)
DEFAULT_OUTPUT_DIR = Path("data/research/context_qualified_symbol_reaction_profile_audit_v1")

ROWS_CSV = "context_qualified_profile_audit_rows_v1.csv"
ROWS_JSONL = "context_qualified_profile_audit_rows_v1.jsonl"
MANIFEST_JSON = "manifest_v1.json"

CONTEXT_FIELDS = (
    "breath_phase",
    "breath_alignment",
    "market_regime",
    "btc_context",
    "symbol_regime",
    "fibo_context",
)

BUCKETS = (
    "ALL",
    "CONTEXT_QUALITY_HIGH",
    "CONTEXT_QUALITY_MEDIUM_OR_HIGH",
    "BREATH_PHASE_KNOWN",
    "BREATH_ALIGNMENT_KNOWN",
    "SYMBOL_REGIME_KNOWN",
    "MARKET_REGIME_KNOWN",
    "BTC_CONTEXT_KNOWN",
    "UNKNOWN_HEAVY",
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
        description="Audit symbol reaction profiles across context-quality buckets from existing research CSV outputs."
    )
    parser.add_argument("--context-rows", default=str(DEFAULT_CONTEXT_ROWS))
    parser.add_argument("--profile-rows", default=str(DEFAULT_PROFILE_ROWS))
    parser.add_argument("--min-events", type=int, default=1)
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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def load_required_csv(path: Path, *, label: str) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing {label} file: {path}")
    rows = read_csv_rows(path)
    if not rows:
        raise ValueError(f"{label} file is empty: {path}")
    return rows


def is_unknown(value: Any) -> bool:
    return str(value or "").strip().upper() in {"", "UNKNOWN"}


def as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def build_context_lookup(context_rows: list[dict[str, str]]) -> dict[tuple[str, ...], list[dict[str, str]]]:
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in context_rows:
        grouped[context_key(row)].append(row)
    return dict(grouped)


def profile_row_with_context(
    profile_row: dict[str, str],
    context_lookup: dict[tuple[str, ...], list[dict[str, str]]],
) -> dict[str, Any]:
    key = context_key(profile_row)
    matching_context = context_lookup.get(key, [])
    quality_distribution = Counter(str(row.get("quality_state") or "UNKNOWN") for row in matching_context)
    enriched = dict(profile_row)
    enriched["context_row_count"] = len(matching_context)
    enriched["context_quality_distribution"] = dict(sorted(quality_distribution.items()))
    enriched["context_quality_has_high"] = quality_distribution.get("HIGH", 0) > 0
    enriched["context_quality_has_medium_or_high"] = (
        quality_distribution.get("HIGH", 0) + quality_distribution.get("MEDIUM", 0) > 0
    )
    return enriched


def unknown_heavy(row: dict[str, Any]) -> bool:
    return sum(1 for field in CONTEXT_FIELDS if is_unknown(row.get(field))) >= 4


def bucket_matches(bucket: str, row: dict[str, Any]) -> bool:
    if bucket == "ALL":
        return True
    if bucket == "CONTEXT_QUALITY_HIGH":
        return bool(row.get("context_quality_has_high"))
    if bucket == "CONTEXT_QUALITY_MEDIUM_OR_HIGH":
        return bool(row.get("context_quality_has_medium_or_high"))
    if bucket == "BREATH_PHASE_KNOWN":
        return not is_unknown(row.get("breath_phase"))
    if bucket == "BREATH_ALIGNMENT_KNOWN":
        return not is_unknown(row.get("breath_alignment"))
    if bucket == "SYMBOL_REGIME_KNOWN":
        return not is_unknown(row.get("symbol_regime"))
    if bucket == "MARKET_REGIME_KNOWN":
        return not is_unknown(row.get("market_regime"))
    if bucket == "BTC_CONTEXT_KNOWN":
        return not is_unknown(row.get("btc_context"))
    if bucket == "UNKNOWN_HEAVY":
        return unknown_heavy(row)
    raise ValueError(f"Unsupported bucket: {bucket}")


def weighted_average(rows: list[dict[str, Any]], field: str) -> float | None:
    numerator = 0.0
    denominator = 0
    for row in rows:
        value = as_float(row.get(field))
        weight = as_int(row.get("event_count"))
        if value is None or weight <= 0:
            continue
        numerator += value * weight
        denominator += weight
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def distribution(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter[str(row.get(field) or "UNKNOWN")] += 1
    return dict(sorted(counter.items()))


def bucket_row(bucket: str, rows: list[dict[str, Any]], min_events: int) -> dict[str, Any]:
    if not rows:
        return {
            "bucket": bucket,
            "profile_row_count": 0,
            "context_row_count": 0,
            "symbols_covered": 0,
            "event_count_sum": 0,
            "eligible_event_count_sum": 0,
            "profile_label_distribution": {},
            "sample_quality_distribution": {},
            "avg_mfe_pct_weighted": None,
            "avg_mae_pct_weighted": None,
            "avg_fakeout_rate_weighted": None,
            "avg_reaction_zone_touch_rate_weighted": None,
            "top_symbols_by_event_count": [],
            "skipped_reason": "NO_ROWS_QUALIFY",
            "research_only": True,
        }

    event_count_sum = sum(as_int(row.get("event_count")) for row in rows)
    eligible_event_count_sum = sum(as_int(row.get("eligible_event_count")) for row in rows)
    if event_count_sum < min_events:
        return {
            "bucket": bucket,
            "profile_row_count": len(rows),
            "context_row_count": sum(as_int(row.get("context_row_count")) for row in rows),
            "symbols_covered": len({str(row.get("symbol") or "").upper() for row in rows}),
            "event_count_sum": event_count_sum,
            "eligible_event_count_sum": eligible_event_count_sum,
            "profile_label_distribution": distribution(rows, "profile_label"),
            "sample_quality_distribution": distribution(rows, "sample_quality"),
            "avg_mfe_pct_weighted": None,
            "avg_mae_pct_weighted": None,
            "avg_fakeout_rate_weighted": None,
            "avg_reaction_zone_touch_rate_weighted": None,
            "top_symbols_by_event_count": top_symbols_by_event_count(rows),
            "skipped_reason": f"EVENT_COUNT_SUM_LT_MIN_EVENTS:{event_count_sum}<{min_events}",
            "research_only": True,
        }

    return {
        "bucket": bucket,
        "profile_row_count": len(rows),
        "context_row_count": sum(as_int(row.get("context_row_count")) for row in rows),
        "symbols_covered": len({str(row.get("symbol") or "").upper() for row in rows}),
        "event_count_sum": event_count_sum,
        "eligible_event_count_sum": eligible_event_count_sum,
        "profile_label_distribution": distribution(rows, "profile_label"),
        "sample_quality_distribution": distribution(rows, "sample_quality"),
        "avg_mfe_pct_weighted": weighted_average(rows, "avg_mfe_pct"),
        "avg_mae_pct_weighted": weighted_average(rows, "avg_mae_pct"),
        "avg_fakeout_rate_weighted": weighted_average(rows, "fakeout_rate"),
        "avg_reaction_zone_touch_rate_weighted": weighted_average(rows, "reaction_zone_touch_rate"),
        "top_symbols_by_event_count": top_symbols_by_event_count(rows),
        "skipped_reason": None,
        "research_only": True,
    }


def top_symbols_by_event_count(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: dict[str, int] = defaultdict(int)
    for row in rows:
        counter[str(row.get("symbol") or "").upper()] += as_int(row.get("event_count"))
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [{"symbol": symbol, "event_count": count} for symbol, count in ranked[:5]]


def build_audit_rows(
    *,
    context_rows: list[dict[str, str]],
    profile_rows: list[dict[str, str]],
    min_events: int,
) -> list[dict[str, Any]]:
    context_lookup = build_context_lookup(context_rows)
    enriched_profile_rows = [profile_row_with_context(row, context_lookup) for row in profile_rows]
    output: list[dict[str, Any]] = []
    for bucket in BUCKETS:
        selected = [row for row in enriched_profile_rows if bucket_matches(bucket, row)]
        output.append(bucket_row(bucket, selected, min_events))
    return output


def build_manifest(
    *,
    context_rows_path: Path,
    profile_rows_path: Path,
    output_dir: Path,
    audit_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "context_rows_path": str(context_rows_path),
        "profile_rows_path": str(profile_rows_path),
        "bucket_count": len(audit_rows),
        "output_dir": str(output_dir),
        "output_files": {
            "rows_csv": str(output_dir / ROWS_CSV),
            "rows_jsonl": str(output_dir / ROWS_JSONL),
            "manifest_json": str(output_dir / MANIFEST_JSON),
        },
        "safety_markers": SAFETY_MARKERS,
        "research_only": True,
    }


def print_summary(audit_rows: list[dict[str, Any]]) -> None:
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    for row in audit_rows:
        print(
            f"bucket={row['bucket']} profile_row_count={row['profile_row_count']} "
            f"context_row_count={row['context_row_count']} event_count_sum={row['event_count_sum']} "
            f"skipped_reason={row['skipped_reason'] or 'NONE'}"
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
    context_rows_path = Path(args.context_rows)
    profile_rows_path = Path(args.profile_rows)
    output_dir = Path(args.output_dir)

    context_rows = load_required_csv(context_rows_path, label="context rows")
    profile_rows = load_required_csv(profile_rows_path, label="profile rows")
    audit_rows = build_audit_rows(
        context_rows=context_rows,
        profile_rows=profile_rows,
        min_events=int(args.min_events),
    )
    manifest = build_manifest(
        context_rows_path=context_rows_path,
        profile_rows_path=profile_rows_path,
        output_dir=output_dir,
        audit_rows=audit_rows,
    )

    if args.write_files:
        write_csv(output_dir / ROWS_CSV, audit_rows)
        write_jsonl(output_dir / ROWS_JSONL, audit_rows)
        write_json(output_dir / MANIFEST_JSON, manifest)

    if args.output == "json":
        print(json.dumps({"rows": audit_rows, "manifest": manifest}, indent=2, sort_keys=True))
    else:
        print_summary(audit_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
