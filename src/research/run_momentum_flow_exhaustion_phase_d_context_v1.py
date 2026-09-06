"""Research-only regime-context interaction diagnostic for Issue #306 Phase D."""
from __future__ import annotations

import argparse
import bisect
import csv
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any, Final

from src.common.db_core_v1 import get_connection

MODEL_VERSION: Final[str] = "momentum_flow_exhaustion_phase_d_context_v1"
UNKNOWN: Final[str] = "UNKNOWN"
DEFAULT_MAX_CONTEXT_AGE_HOURS: Final[int] = 4


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float]) -> float | None:
    return None if not values else round(mean(values), 6)


def _median(values: list[float]) -> float | None:
    return None if not values else round(median(values), 6)


def enrich_with_regime_context(
    exhaustion_rows: list[dict[str, Any]],
    regime_rows: list[dict[str, Any]],
    *,
    max_context_age: timedelta = timedelta(hours=DEFAULT_MAX_CONTEXT_AGE_HOURS),
) -> list[dict[str, Any]]:
    if max_context_age.total_seconds() < 0:
        raise ValueError("max_context_age must be nonnegative")

    by_key: dict[tuple[str, str], list[tuple[datetime, dict[str, Any]]]] = defaultdict(list)
    for raw in regime_rows:
        key = (str(raw.get("symbol") or "").upper(), str(raw.get("interval_code") or ""))
        ts = _utc(raw["asof_ts_utc"])
        by_key[key].append((ts, raw))
    for values in by_key.values():
        values.sort(key=lambda item: item[0])

    output: list[dict[str, Any]] = []
    for raw in exhaustion_rows:
        row = dict(raw)
        market = str(row.get("market") or "").upper()
        interval = str(row.get("interval") or "")
        asof = _utc(row["asof_ts_utc"])
        candidates = by_key.get((market, interval), [])
        times = [item[0] for item in candidates]
        idx = bisect.bisect_right(times, asof) - 1
        matched: dict[str, Any] | None = None
        matched_ts: datetime | None = None
        if idx >= 0:
            candidate_ts, candidate = candidates[idx]
            age = asof - candidate_ts
            if timedelta(0) <= age <= max_context_age:
                matched, matched_ts = candidate, candidate_ts

        row["context_state"] = "KNOWN" if matched is not None else UNKNOWN
        row["context_asof_ts_utc"] = None if matched_ts is None else matched_ts.isoformat().replace("+00:00", "Z")
        row["context_age_seconds"] = None if matched_ts is None else int((asof - matched_ts).total_seconds())
        for field in ("global_regime", "asset_class_regime", "global_class_regime", "asset_class"):
            row[field] = UNKNOWN if matched is None else str(matched.get(field) or UNKNOWN).upper()
        output.append(row)
    return output


def build_interaction_summary(rows: list[dict[str, Any]], horizons: tuple[int, ...] = (1, 3, 6)) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "schema_version": MODEL_VERSION,
        "row_count": len(rows),
        "known_context_count": sum(1 for row in rows if row.get("context_state") == "KNOWN"),
        "by_side_and_global_regime_70_plus": {},
        "interpretation": "Research interaction diagnostic only; positive reversal return means reversal after same-side exhaustion score.",
    }
    for side in ("buyer", "seller"):
        score_field = f"{side}_exhaustion_score"
        high = [row for row in rows if (_number(row.get(score_field)) or 0.0) >= 70.0 and row.get("context_state") == "KNOWN"]
        groups: dict[str, Any] = {}
        for regime in sorted({str(row.get("global_regime") or UNKNOWN) for row in high}):
            cohort = [row for row in high if str(row.get("global_regime") or UNKNOWN) == regime]
            item: dict[str, Any] = {"count": len(cohort)}
            for horizon in horizons:
                field = f"{side}_reversal_return_{horizon}b_pct"
                values = [value for row in cohort if (value := _number(row.get(field))) is not None]
                item[f"avg_reversal_return_{horizon}b_pct"] = _mean(values)
                item[f"median_reversal_return_{horizon}b_pct"] = _median(values)
            groups[regime] = item
        summary["by_side_and_global_regime_70_plus"][side.upper()] = groups
    return summary


def fetch_regime_rows(conn: Any, *, symbols: list[str], interval: str, start_ts: datetime, end_ts: datetime) -> list[dict[str, Any]]:
    symbol_sql = ""
    params: list[Any] = [interval, start_ts, end_ts]
    if symbols:
        symbol_sql = " AND symbol IN (" + ",".join(["%s"] * len(symbols)) + ")"
        params.extend(symbols)
    sql = f"""
    SELECT symbol, interval_code, asof_ts_utc, global_regime, asset_class_regime,
           global_class_regime, asset_class
    FROM regime_selector_backtest_observation_v1
    WHERE interval_code=%s AND asof_ts_utc >= %s AND asof_ts_utc <= %s
    {symbol_sql}
    ORDER BY symbol, asof_ts_utc
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_outputs(rows: list[dict[str, Any]], summary: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary_v1.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if rows:
        with (output_dir / "enriched_rows_v1.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader(); writer.writerows(rows)


def main() -> None:
    p = argparse.ArgumentParser(description="Run #306 Phase D regime interaction diagnostic")
    p.add_argument("--input-csv", required=True); p.add_argument("--database", default="synth")
    p.add_argument("--interval", default="4h"); p.add_argument("--max-context-age-hours", type=int, default=4)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    rows = read_csv(Path(args.input_csv))
    if not rows:
        write_outputs([], build_interaction_summary([]), Path(args.output_dir)); return
    symbols = sorted({str(row["market"]).upper() for row in rows})
    asofs = [_utc(row["asof_ts_utc"]) for row in rows]
    padding = timedelta(hours=args.max_context_age_hours)
    conn = get_connection(database=args.database)
    try:
        regimes = fetch_regime_rows(conn, symbols=symbols, interval=args.interval, start_ts=min(asofs)-padding, end_ts=max(asofs))
    finally:
        conn.close()
    enriched = enrich_with_regime_context(rows, regimes, max_context_age=padding)
    summary = build_interaction_summary(enriched)
    write_outputs(enriched, summary, Path(args.output_dir))
    print(f"rows={len(enriched)} known_context={summary['known_context_count']} output={args.output_dir}")


if __name__ == "__main__":
    main()
