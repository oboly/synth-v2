"""Research-only coverage audit for Issue #805 historical context backbone."""
from __future__ import annotations

import argparse
import bisect
import csv
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Final

REPORT_NAME: Final[str] = "historical_breath_regime_backbone_coverage_v1"
REPORT_VERSION: Final[str] = "1.0"
UNKNOWN: Final[str] = "UNKNOWN"
CONTEXT_FIELDS: Final[tuple[str, ...]] = (
    "breath_phase",
    "breath_alignment",
    "market_regime",
    "btc_context",
    "symbol_regime",
)


def _utc(value: str | datetime) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_lookup(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[tuple[datetime, dict[str, Any]]]]:
    grouped: dict[tuple[str, str], list[tuple[datetime, dict[str, Any]]]] = defaultdict(list)
    for row in rows:
        key = (str(row.get("symbol") or "").upper(), str(row.get("interval") or row.get("interval_code") or ""))
        grouped[key].append((_utc(row["asof_ts_utc"]), row))
    for values in grouped.values():
        values.sort(key=lambda item: item[0])
    return dict(grouped)


def latest_at_or_before(
    candidates: list[tuple[datetime, dict[str, Any]]],
    *,
    asof: datetime,
    max_age: timedelta,
) -> tuple[dict[str, Any] | None, int | None]:
    if not candidates:
        return None, None
    times = [item[0] for item in candidates]
    idx = bisect.bisect_right(times, asof) - 1
    if idx < 0:
        return None, None
    ts, row = candidates[idx]
    age = asof - ts
    if age < timedelta(0) or age > max_age:
        return None, None
    return row, int(age.total_seconds())


def audit_coverage(
    exhaustion_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    *,
    max_context_age: timedelta,
) -> dict[str, Any]:
    if max_context_age.total_seconds() < 0:
        raise ValueError("max_context_age must be nonnegative")
    lookup = build_lookup(context_rows)
    matched = 0
    ages: list[int] = []
    field_known = Counter()
    by_symbol: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "matched": 0})
    high_score = {
        "buyer_70_plus_total": 0,
        "buyer_70_plus_matched": 0,
        "seller_70_plus_total": 0,
        "seller_70_plus_matched": 0,
    }

    for row in exhaustion_rows:
        symbol = str(row.get("market") or row.get("symbol") or "").upper()
        interval = str(row.get("interval") or row.get("interval_code") or "")
        asof = _utc(row["asof_ts_utc"])
        by_symbol[symbol]["total"] += 1
        buyer_high = (_float(row.get("buyer_exhaustion_score")) or 0.0) >= 70.0
        seller_high = (_float(row.get("seller_exhaustion_score")) or 0.0) >= 70.0
        if buyer_high:
            high_score["buyer_70_plus_total"] += 1
        if seller_high:
            high_score["seller_70_plus_total"] += 1

        context, age_seconds = latest_at_or_before(
            lookup.get((symbol, interval), []), asof=asof, max_age=max_context_age
        )
        if context is None:
            continue
        matched += 1
        by_symbol[symbol]["matched"] += 1
        ages.append(age_seconds or 0)
        if buyer_high:
            high_score["buyer_70_plus_matched"] += 1
        if seller_high:
            high_score["seller_70_plus_matched"] += 1
        for field in CONTEXT_FIELDS:
            if str(context.get(field) or UNKNOWN).upper() != UNKNOWN:
                field_known[field] += 1

    total = len(exhaustion_rows)
    symbol_rows = []
    for symbol in sorted(by_symbol):
        counts = by_symbol[symbol]
        symbol_rows.append({
            "symbol": symbol,
            "total": counts["total"],
            "matched": counts["matched"],
            "coverage_pct": round(100.0 * counts["matched"] / counts["total"], 3) if counts["total"] else 0.0,
        })

    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "exhaustion_row_count": total,
        "context_row_count": len(context_rows),
        "matched_context_count": matched,
        "coverage_pct": round(100.0 * matched / total, 3) if total else 0.0,
        "max_context_age_seconds": int(max_context_age.total_seconds()),
        "avg_context_age_seconds": round(mean(ages), 3) if ages else None,
        "max_observed_context_age_seconds": max(ages) if ages else None,
        "field_known_count": {field: field_known[field] for field in CONTEXT_FIELDS},
        "high_score_coverage": high_score,
        "by_symbol": symbol_rows,
        "research_only": True,
        "safety": {
            "account_awareness": 0,
            "selection_engine_change": 0,
            "decision_gate_change": 0,
            "execution_planner_change": 0,
            "executor_change": 0,
            "db_writes": 0,
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
        },
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit #805 historical context overlap with #306 replay")
    p.add_argument("--exhaustion-csv", required=True)
    p.add_argument("--context-csv", required=True)
    p.add_argument("--max-context-age-hours", type=int, default=4)
    p.add_argument("--output-json", required=True)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    print(f"STARTED runner={REPORT_NAME} version={REPORT_VERSION}", flush=True)
    print("PHASE_STARTED phase=read_inputs", flush=True)
    exhaustion_rows = read_csv(Path(args.exhaustion_csv))
    context_rows = read_csv(Path(args.context_csv))
    print(
        f"PHASE_FINISHED phase=read_inputs exhaustion_rows={len(exhaustion_rows)} context_rows={len(context_rows)}",
        flush=True,
    )
    print("PHASE_STARTED phase=audit", flush=True)
    summary = audit_coverage(
        exhaustion_rows,
        context_rows,
        max_context_age=timedelta(hours=args.max_context_age_hours),
    )
    print(
        f"PHASE_FINISHED phase=audit matched={summary['matched_context_count']} coverage_pct={summary['coverage_pct']}",
        flush=True,
    )
    output = Path(args.output_json)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"FINISHED output={output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
