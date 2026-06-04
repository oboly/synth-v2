from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


REPORT_NAME = "context_event_coverage_gap_audit_v1"
REPORT_VERSION = "1.0"

DEFAULT_EVENT_LEVEL_ROWS = Path(
    "data/research/event_level_symbol_reaction_profile_by_context_v1"
    "/event_level_symbol_reaction_profile_by_context_rows_v1.csv"
)
DEFAULT_CONTEXT_ROWS = Path(
    "data/research/historical_breath_regime_context_builder_v1"
    "/historical_breath_regime_context_rows_v1.csv"
)
DEFAULT_RECOMPUTE_ROWS = Path(
    "data/research/historical_market_breath_source_recompute_v1"
    "/historical_market_breath_source_recomputed_rows_v1.csv"
)
DEFAULT_OUTPUT_DIR = Path("data/research/context_event_coverage_gap_audit_v1")

ROWS_CSV = "context_event_coverage_gap_rows_v1.csv"
MANIFEST_JSON = "manifest_v1.json"

MAX_STALENESS = timedelta(days=7)

CONTEXT_VALUE_FIELDS = (
    "breath_phase",
    "breath_alignment",
    "market_regime",
    "btc_context",
    "symbol_regime",
)

SAFETY_MARKERS: dict[str, Any] = {
    "research_only": True,
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "executor": "none",
    "db_writes": 0,
}

# Issue classification values (ordered from most informative to least)
USABLE_CONTEXT = "USABLE_CONTEXT"
CONTEXT_ROW_UNKNOWN = "CONTEXT_ROW_UNKNOWN"
STALE_CONTEXT = "STALE_CONTEXT"
PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE = "PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE"
MISSING_CONTEXT_ROW = "MISSING_CONTEXT_ROW"
INTERVAL_MISMATCH = "INTERVAL_MISMATCH"
SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
UNKNOWN = "UNKNOWN"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit why event-level reaction rows have low historical context coverage "
            "(research-only, no DB writes, no broker calls)."
        )
    )
    parser.add_argument("--event-level-rows", default=str(DEFAULT_EVENT_LEVEL_ROWS))
    parser.add_argument("--context-rows", default=str(DEFAULT_CONTEXT_ROWS))
    parser.add_argument("--recompute-rows", default=None)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def is_unknown(value: Any) -> bool:
    return str(value or "").strip().upper() in {"", "UNKNOWN"}


def parse_ts(value: Any) -> datetime | None:
    if value in ("", None):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def fmt_ts(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def age_hours(event_ts: datetime, asof_ts: datetime) -> float:
    return (event_ts - asof_ts).total_seconds() / 3600.0


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    converted: list[dict[str, Any]] = []
    for row in rows:
        conv: dict[str, Any] = {}
        for key, value in row.items():
            conv[key] = json.dumps(value, sort_keys=True, ensure_ascii=True) if isinstance(value, (list, dict)) else value
        converted.append(conv)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(converted[0].keys()))
        writer.writeheader()
        writer.writerows(converted)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def load_event_level_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Event-level rows not found: {path}")
    raw = read_csv_rows(path)
    out: list[dict[str, Any]] = []
    for row in raw:
        symbol = str(row.get("symbol") or "").strip().upper()
        event_ts = parse_ts(row.get("event_ts_utc"))
        if not symbol or event_ts is None:
            continue
        item = dict(row)
        item["symbol"] = symbol
        item["_event_ts_dt"] = event_ts
        out.append(item)
    return out


def load_context_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = read_csv_rows(path)
    out: list[dict[str, Any]] = []
    for row in raw:
        symbol = str(row.get("symbol") or "").strip().upper()
        asof_ts = parse_ts(row.get("asof_ts_utc"))
        if not symbol or asof_ts is None:
            continue
        item = dict(row)
        item["symbol"] = symbol
        item["_asof_ts_dt"] = asof_ts
        out.append(item)
    return out


def build_lookup(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: (r["symbol"], r["_asof_ts_dt"])):
        grouped[row["symbol"]].append(row)
    return dict(grouped)


def nearest_at_or_before(
    lookup: dict[str, list[dict[str, Any]]],
    *,
    symbol: str,
    event_ts: datetime,
) -> dict[str, Any] | None:
    matched: dict[str, Any] | None = None
    for row in lookup.get(symbol, []):
        if row["_asof_ts_dt"] > event_ts:
            break
        matched = row
    return matched


def context_range_for_symbol(lookup: dict[str, list[dict[str, Any]]], symbol: str) -> tuple[datetime | None, datetime | None]:
    rows = lookup.get(symbol, [])
    if not rows:
        return None, None
    return rows[0]["_asof_ts_dt"], rows[-1]["_asof_ts_dt"]


def classify_event(
    *,
    symbol: str,
    event_ts: datetime,
    event_interval: str,
    context_lookup: dict[str, list[dict[str, Any]]],
    recompute_lookup: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    # Nearest context row
    ctx_row = nearest_at_or_before(context_lookup, symbol=symbol, event_ts=event_ts)
    recomp_row = nearest_at_or_before(recompute_lookup, symbol=symbol, event_ts=event_ts)

    ctx_asof = ctx_row["_asof_ts_dt"] if ctx_row else None
    recomp_asof = recomp_row["_asof_ts_dt"] if recomp_row else None

    ctx_age_h = age_hours(event_ts, ctx_asof) if ctx_asof else None
    recomp_age_h = age_hours(event_ts, recomp_asof) if recomp_asof else None

    ctx_range_start, ctx_range_end = context_range_for_symbol(context_lookup, symbol)
    recomp_range_start, recomp_range_end = context_range_for_symbol(recompute_lookup, symbol)

    result: dict[str, Any] = {
        "nearest_context_asof_ts_utc": fmt_ts(ctx_asof),
        "nearest_context_age_hours": round(ctx_age_h, 2) if ctx_age_h is not None else None,
        "nearest_recompute_asof_ts_utc": fmt_ts(recomp_asof),
        "nearest_recompute_age_hours": round(recomp_age_h, 2) if recomp_age_h is not None else None,
        "context_range_start": fmt_ts(ctx_range_start),
        "context_range_end": fmt_ts(ctx_range_end),
        "recompute_range_start": fmt_ts(recomp_range_start),
        "recompute_range_end": fmt_ts(recomp_range_end),
    }

    # Determine which context fields are known
    known_fields: list[str] = []
    unknown_fields: list[str] = []
    if ctx_row:
        for field in CONTEXT_VALUE_FIELDS:
            if is_unknown(ctx_row.get(field)):
                unknown_fields.append(field)
            else:
                known_fields.append(field)
    result["context_known_fields"] = known_fields
    result["context_unknown_fields"] = unknown_fields

    # Classify
    if symbol not in context_lookup:
        result["issue_classification"] = MISSING_CONTEXT_ROW
        result["issue_detail"] = "no context rows for this symbol"
        return result

    if ctx_row is None:
        # Symbol has rows but all are after the event
        result["issue_classification"] = PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE
        result["issue_detail"] = f"event is before context range start {fmt_ts(ctx_range_start)}"
        return result

    if ctx_age_h is not None and ctx_age_h > MAX_STALENESS.total_seconds() / 3600.0:
        # Context row found but too old
        if ctx_range_end is not None and event_ts > ctx_range_end + MAX_STALENESS:
            result["issue_classification"] = PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE
            result["issue_detail"] = (
                f"event {fmt_ts(event_ts)} is {ctx_age_h:.1f}h after nearest context "
                f"(context ends {fmt_ts(ctx_range_end)}, staleness limit {int(MAX_STALENESS.total_seconds() // 3600)}h)"
            )
        else:
            result["issue_classification"] = STALE_CONTEXT
            result["issue_detail"] = f"nearest context is {ctx_age_h:.1f}h old (limit {int(MAX_STALENESS.total_seconds() // 3600)}h)"
        return result

    # Context found and within staleness — check interval
    ctx_interval = str(ctx_row.get("interval") or "").strip()
    if ctx_interval and event_interval and ctx_interval != event_interval and event_interval not in {"UNKNOWN", ""}:
        result["issue_classification"] = INTERVAL_MISMATCH
        result["issue_detail"] = f"event interval {event_interval!r} != context interval {ctx_interval!r}"
        return result

    # Context found and within staleness — check if all fields are UNKNOWN
    if not known_fields and unknown_fields:
        result["issue_classification"] = CONTEXT_ROW_UNKNOWN
        result["issue_detail"] = "nearest context row has all UNKNOWN values for context fields"
        return result

    result["issue_classification"] = USABLE_CONTEXT
    result["issue_detail"] = f"context found {ctx_age_h:.1f}h before event, {len(known_fields)} known fields"
    return result


def recommend_next_action(issue_counts: Counter[str], total: int) -> str:
    if total == 0:
        return "no_action"
    outside_pct = (issue_counts.get(PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE, 0) + issue_counts.get(STALE_CONTEXT, 0)) / total
    if outside_pct >= 0.5:
        return "rerun_context_builder_with_wider_date_range"
    if issue_counts.get(MISSING_CONTEXT_ROW, 0) / total >= 0.5:
        return "fix_symbol_interval_join_or_extend_context_builder"
    if issue_counts.get(CONTEXT_ROW_UNKNOWN, 0) / total >= 0.5:
        return "rerun_recompute_with_wider_date_range_or_accept_unknown"
    usable_pct = issue_counts.get(USABLE_CONTEXT, 0) / total
    if usable_pct >= 0.9:
        return "no_action"
    return "rerun_context_builder_with_wider_date_range"


def build_audit_rows(
    *,
    event_rows: list[dict[str, Any]],
    context_lookup: dict[str, list[dict[str, Any]]],
    recompute_lookup: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in sorted(event_rows, key=lambda r: (r["symbol"], r["_event_ts_dt"])):
        symbol = row["symbol"]
        event_ts = row["_event_ts_dt"]
        event_interval = str(row.get("interval") or "").strip()

        classification = classify_event(
            symbol=symbol,
            event_ts=event_ts,
            event_interval=event_interval,
            context_lookup=context_lookup,
            recompute_lookup=recompute_lookup,
        )

        output.append({
            "symbol": symbol,
            "event_ts_utc": fmt_ts(event_ts),
            "event_interval": event_interval,
            **classification,
            "research_only": True,
        })
    return output


def build_manifest(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    rows: list[dict[str, Any]],
    context_lookup: dict[str, list[dict[str, Any]]],
    recompute_lookup: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    issue_counts: Counter[str] = Counter(str(row["issue_classification"]) for row in rows)
    usable = issue_counts.get(USABLE_CONTEXT, 0)
    total = len(rows)

    # Per-symbol issue distribution
    by_symbol: dict[str, dict[str, Any]] = {}
    sym_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        sym_rows[row["symbol"]].append(row)
    for sym, sym_list in sorted(sym_rows.items()):
        sym_issues: Counter[str] = Counter(str(r["issue_classification"]) for r in sym_list)
        event_ts_list = [r["event_ts_utc"] for r in sym_list if r.get("event_ts_utc")]
        ctx_rows = context_lookup.get(sym, [])
        recomp_rows = recompute_lookup.get(sym, [])
        by_symbol[sym] = {
            "event_count": len(sym_list),
            "issue_distribution": dict(sym_issues),
            "event_ts_range": [min(event_ts_list), max(event_ts_list)] if event_ts_list else [],
            "context_ts_range": (
                [fmt_ts(ctx_rows[0]["_asof_ts_dt"]), fmt_ts(ctx_rows[-1]["_asof_ts_dt"])]
                if ctx_rows else []
            ),
            "recompute_ts_range": (
                [fmt_ts(recomp_rows[0]["_asof_ts_dt"]), fmt_ts(recomp_rows[-1]["_asof_ts_dt"])]
                if recomp_rows else []
            ),
        }

    recommended = recommend_next_action(issue_counts, total)

    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "total_events": total,
        "usable_context_events": usable,
        "issue_distribution": dict(issue_counts),
        "recommended_next_action": recommended,
        "by_symbol": by_symbol,
        "event_level_rows": str(args.event_level_rows),
        "context_rows": str(args.context_rows),
        "recompute_rows": str(args.recompute_rows) if args.recompute_rows else None,
        "output_dir": str(output_dir),
        "research_only": True,
        "safety_markers": dict(SAFETY_MARKERS),
    }


def print_summary(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(f"total_events={manifest['total_events']}")
    print(f"usable_context_events={manifest['usable_context_events']}")
    issue_dist = manifest["issue_distribution"]
    print(
        "issue_distribution "
        + " ; ".join(f"{k}:{issue_dist[k]}" for k in sorted(issue_dist, key=lambda k: -issue_dist[k]))
    )
    print(f"recommended_next_action={manifest['recommended_next_action']}")
    print("per_symbol_issue_distribution:")
    for sym, data in sorted(manifest["by_symbol"].items()):
        issues = " ".join(f"{k}:{v}" for k, v in sorted(data["issue_distribution"].items(), key=lambda kv: -kv[1]))
        print(f"  {sym}: {issues}")
    print(
        "safety "
        + " ".join(f"{key}={value}" for key, value in SAFETY_MARKERS.items())
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    event_level_rows_path = Path(args.event_level_rows)
    context_rows_path = Path(args.context_rows)
    recompute_rows_path = Path(args.recompute_rows) if args.recompute_rows else DEFAULT_RECOMPUTE_ROWS
    output_dir = Path(args.output_dir)

    event_rows = load_event_level_rows(event_level_rows_path)
    context_rows = load_context_rows(context_rows_path)
    recompute_rows = load_context_rows(recompute_rows_path) if recompute_rows_path.exists() else []

    context_lookup = build_lookup(context_rows)
    recompute_lookup = build_lookup(recompute_rows)

    audit_rows = build_audit_rows(
        event_rows=event_rows,
        context_lookup=context_lookup,
        recompute_lookup=recompute_lookup,
    )
    manifest = build_manifest(
        args=args,
        output_dir=output_dir,
        rows=audit_rows,
        context_lookup=context_lookup,
        recompute_lookup=recompute_lookup,
    )

    if args.write_files:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(output_dir / ROWS_CSV, audit_rows)
        write_json(output_dir / MANIFEST_JSON, manifest)

    if args.output == "json":
        print(json.dumps({"rows": audit_rows, "manifest": manifest}, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print_summary(audit_rows, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
