"""Research-only, point-in-time forecast confluence replay.

This module never imports the production selection path and never writes a
database.  Feature joins are set based, bounded to the requested replay
window, and explicitly reject observations newer than a forecast.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from src.common.db import get_connection

VERSION = "forecast_confluence_pit_replay/v1"
HORIZONS = (timedelta(hours=4), timedelta(hours=24), timedelta(days=7))
PRESSURE_MAX_AGE = timedelta(hours=4)
SECTOR_MAX_AGE = timedelta(hours=4)
WEIGHTS = {"trend": .20, "setup": .18, "momentum": .12, "volume": .10, "rotation_pressure": .10, "sector_rotation": .08, "zone": .14}


def parse_ts(value: str) -> datetime:
    value = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=None) if parsed.tzinfo is None else parsed.astimezone(UTC).replace(tzinfo=None)


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def fetch_rows(conn: Any, *, start: datetime, end: datetime, venue: str) -> list[dict[str, Any]]:
    """Fetch maps plus latest valid feature rows in one bounded query.

    ``idx_mrp_obs_latest(asset_id, as_of_ts_utc)`` supports the pressure range
    lookup.  ``ix_sector_rotation_latest(venue, window_code, model_version,
    asof_ts_utc)`` supports the bounded sector scan; membership is valid at the
    forecast timestamp, never current-state-only membership.
    """
    sql = """
    WITH maps AS (
      SELECT f.map_id, f.symbol AS market, f.venue, f.asof_ts_utc, f.reference_price,
             f.target_t1, f.invalidation_level, f.distance_entry_to_target_pct,
             a.asset_id, s.trend_score, s.setup_score, s.compass_score, s.volume_score
      FROM canonical_fib_zone_map_v1 f
      JOIN asset a ON BINARY a.symbol=BINARY f.symbol
      JOIN signal_engine_state s ON s.asset_id=a.asset_id AND BINARY s.venue=BINARY f.venue
        AND s.interval_code='4h' AND s.signal_ts_utc=f.asof_ts_utc
      WHERE f.venue=%s AND f.interval_code='4h' AND f.asof_ts_utc >= %s AND f.asof_ts_utc < %s
        AND f.map_status IN ('FRESH','FALLBACK','EMERGENCY_REBUILT')
    ), pressure_ranked AS (
      SELECT m.map_id, o.as_of_ts_utc, o.score_total, o.pressure_state,
        ROW_NUMBER() OVER (PARTITION BY m.map_id ORDER BY o.as_of_ts_utc DESC) AS rn
      FROM maps m JOIN market_rotation_pressure_observation_v1 o
        ON o.asset_id=m.asset_id AND o.model_version='1.0'
       AND o.as_of_ts_utc <= m.asof_ts_utc AND o.as_of_ts_utc >= m.asof_ts_utc - INTERVAL 4 HOUR
    ), sector_ranked AS (
      SELECT m.map_id, r.asof_ts_utc, r.rotation_score, r.rotation_state, r.sector_code, r.model_version,
        ROW_NUMBER() OVER (PARTITION BY m.map_id ORDER BY r.asof_ts_utc DESC, r.sector_code ASC) AS rn
      FROM maps m
      JOIN asset_cluster_membership acm ON acm.asset_id=m.asset_id AND acm.membership_type='PRIMARY'
       AND acm.valid_from_ts_utc <= m.asof_ts_utc AND (acm.valid_to_ts_utc IS NULL OR acm.valid_to_ts_utc > m.asof_ts_utc)
      JOIN sector_rotation_snapshot r ON BINARY r.sector_code=BINARY acm.sector_code AND BINARY r.venue=BINARY m.venue
       AND r.window_code='4h' AND r.model_version='sector-rotation-v1.0.0'
       AND r.asof_ts_utc <= m.asof_ts_utc AND r.asof_ts_utc >= m.asof_ts_utc - INTERVAL 4 HOUR
    )
    SELECT m.*, p.as_of_ts_utc AS rotation_pressure_asof_ts_utc, p.score_total AS rotation_pressure_score,
      p.pressure_state, r.asof_ts_utc AS sector_rotation_asof_ts_utc, r.rotation_score AS sector_rotation_score,
      r.rotation_state AS sector_rotation_state, r.sector_code, r.model_version AS sector_model_version
    FROM maps m LEFT JOIN pressure_ranked p ON p.map_id=m.map_id AND p.rn=1
      LEFT JOIN sector_ranked r ON r.map_id=m.map_id AND r.rn=1
    ORDER BY m.asof_ts_utc, m.market, m.map_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, start, end))
        return list(cur.fetchall())


def fetch_candles(conn: Any, rows: list[dict[str, Any]], venue: str) -> dict[str, list[dict[str, Any]]]:
    if not rows:
        return {}
    start = min(r["asof_ts_utc"] for r in rows)
    end = max(r["asof_ts_utc"] for r in rows) + max(HORIZONS)
    symbols = sorted({r["market"] for r in rows})
    placeholders = ",".join(["%s"] * len(symbols))
    sql = f"""SELECT a.symbol AS market,c.close_ts_utc,c.high_price,c.low_price,c.close_price
      FROM obs_market_candle c JOIN asset a ON a.asset_id=c.asset_id
      WHERE c.venue=%s AND c.interval_code='4h' AND c.close_ts_utc>%s AND c.close_ts_utc<=%s
        AND a.symbol IN ({placeholders}) ORDER BY a.symbol,c.close_ts_utc"""
    with conn.cursor() as cur:
        cur.execute(sql, [venue, start, end, *symbols])
        raw = cur.fetchall()
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in raw:
        out[str(row["market"])].append(row)
    return out


def assess(row: dict[str, Any], *, enriched: bool) -> dict[str, Any]:
    values = {"trend": _float(row["trend_score"]), "setup": _float(row["setup_score"]), "momentum": _float(row["compass_score"]), "volume": _float(row["volume_score"]), "zone": _float(row["distance_entry_to_target_pct"])}
    if enriched:
        values["rotation_pressure"] = None if row["rotation_pressure_score"] is None else _float(row["rotation_pressure_score"]) / 100
        values["sector_rotation"] = None if row["sector_rotation_score"] is None else _float(row["sector_rotation_score"]) / 100
    present = {k: v for k, v in values.items() if v is not None}
    weighted = sum(WEIGHTS[k] * ((v + 1) / 2 if k in {"rotation_pressure", "sector_rotation"} else max(0, min(1, v))) for k, v in present.items())
    weight = sum(WEIGHTS[k] for k in present)
    confidence = weighted / weight if weight else 0.0
    direction = "LONG" if confidence >= .55 else "SHORT" if confidence <= .45 else "NEUTRAL"
    support = tuple(sorted(k for k, v in present.items() if ((v + 1) / 2 if k in {"rotation_pressure", "sector_rotation"} else v) >= .60))
    return {"confidence": confidence, "confidence_bucket": "HIGH" if confidence >= .70 else "MEDIUM" if confidence >= .55 else "LOW", "direction": direction, "signal_combination": "+".join(support) if support else "no supporting signals"}


def outcome_with_exclusion(
    row: dict[str, Any], assessment: dict[str, Any], candles: list[dict[str, Any]], horizon: timedelta
) -> tuple[dict[str, Any] | None, str | None]:
    """Evaluate only the exact canonical close at the requested horizon."""
    due = row["asof_ts_utc"] + horizon
    if assessment["direction"] == "NEUTRAL":
        return None, "neutral_direction"
    endpoint = next((c for c in candles if c["close_ts_utc"] == due), None)
    if endpoint is None:
        return None, "missing_endpoint_candle"
    price = _float(row["reference_price"])
    close = _float(endpoint["close_price"])
    if not price:
        return None, "missing_reference_price"
    if close is None:
        return None, "missing_endpoint_close_price"
    sign = 1 if assessment["direction"] == "LONG" else -1
    ret = ((close - price) / price * 100) * sign
    window = [c for c in candles if row["asof_ts_utc"] < c["close_ts_utc"] <= endpoint["close_ts_utc"]]
    high = max(_float(c["high_price"]) for c in window if c["high_price"] is not None)
    low = min(_float(c["low_price"]) for c in window if c["low_price"] is not None)
    mfe = ((high - price) / price * 100) if sign == 1 else ((price - low) / price * 100)
    mae = ((price - low) / price * 100) if sign == 1 else ((high - price) / price * 100)
    return {**assessment, "horizon_hours": int(horizon.total_seconds() / 3600), "return_pct": ret, "mfe_pct": mfe, "mae_pct": mae, "direction_hit": ret > 0}, None


def outcome(row: dict[str, Any], assessment: dict[str, Any], candles: list[dict[str, Any]], horizon: timedelta) -> dict[str, Any] | None:
    """Compatibility wrapper for callers that only need an evaluable outcome."""
    return outcome_with_exclusion(row, assessment, candles, horizon)[0]


def metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {"sample_count": 0}
    returns = [x["return_pct"] for x in items]
    return {"sample_count": len(items), "direction_hit_rate": round(sum(x["direction_hit"] for x in items) / len(items), 4), "mean_forward_return_pct": round(sum(returns) / len(returns), 4), "median_forward_return_pct": round(median(returns), 4), "positive_return_rate": round(sum(x > 0 for x in returns) / len(returns), 4), "mean_mfe_pct": round(sum(x["mfe_pct"] for x in items) / len(items), 4), "mean_mae_pct": round(sum(x["mae_pct"] for x in items) / len(items), 4)}


def grouped(items: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[tuple(str(item.get(f, "UNAVAILABLE")) for f in fields)].append(item)
    return [{**dict(zip(fields, key)), **metrics(value)} for key, value in sorted(groups.items())]


def run(conn: Any, *, start: datetime, end: datetime, venue: str) -> dict[str, Any]:
    rows = fetch_rows(conn, start=start, end=end, venue=venue)
    candles = fetch_candles(conn, rows, venue)
    all_results: dict[str, list[dict[str, Any]]] = {"baseline": [], "enriched": []}
    exclusions: dict[str, Counter[str]] = {"baseline": Counter(), "enriched": Counter()}
    for row in rows:
        for mode in all_results:
            a = assess(row, enriched=mode == "enriched")
            for horizon in HORIZONS:
                item, exclusion_reason = outcome_with_exclusion(row, a, candles[row["market"]], horizon)
                if item:
                    item.update({"rotation_pressure_state": row["pressure_state"] or "UNAVAILABLE", "sector_rotation_state": row["sector_rotation_state"] or "UNAVAILABLE"})
                    all_results[mode].append(item)
                elif exclusion_reason:
                    exclusions[mode][exclusion_reason] += 1
    availability = {"rotation_pressure_available": sum(r["rotation_pressure_asof_ts_utc"] is not None for r in rows), "sector_rotation_available": sum(r["sector_rotation_asof_ts_utc"] is not None for r in rows), "forecast_rows": len(rows)}
    report: dict[str, Any] = {"replay_identity": VERSION, "period": {"start": start.isoformat()+"Z", "end_exclusive": end.isoformat()+"Z"}, "horizons_hours": [4, 24, 168], "provenance": {"rotation_pressure": "market_rotation_pressure_observation_v1.score_total model_version=1.0", "sector_rotation": "sector_rotation_snapshot.rotation_score window=4h model_version=sector-rotation-v1.0.0", "breathline": "unavailable; not joined"}, "availability": availability, "future_leakage_checks": {"join_operator": "feature_asof <= forecast_asof", "freshness_hours": 4, "later_feature_rows_used": 0}, "modes": {}}
    for mode, items in all_results.items():
        report["modes"][mode] = {"outcome_count": len(items), "exclusion_reason_counts": dict(sorted(exclusions[mode].items())), "metrics": metrics(items), "by_confidence": grouped(items, ("confidence_bucket",)), "by_signal_combination": grouped(items, ("signal_combination",)), "by_rotation_pressure": grouped(items, ("rotation_pressure_state",)), "by_sector_rotation": grouped(items, ("sector_rotation_state",)), "interaction": [r for r in grouped(items, ("signal_combination", "rotation_pressure_state", "sector_rotation_state")) if r["sample_count"] >= 20]}
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Read-only point-in-time forecast confluence replay")
    p.add_argument("--start", required=True); p.add_argument("--end", required=True); p.add_argument("--venue", default="bitvavo"); p.add_argument("--output", required=True)
    args = p.parse_args(argv)
    conn = get_connection()
    try:
        report = run(conn, start=parse_ts(args.start), end=parse_ts(args.end), venue=args.venue)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        conn.rollback()
    finally:
        conn.close()
    print(json.dumps({"forecast_count": report["availability"]["forecast_rows"], "baseline_outcomes": report["modes"]["baseline"]["outcome_count"], "enriched_outcomes": report["modes"]["enriched"]["outcome_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
