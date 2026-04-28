from __future__ import annotations

"""
Synth v2 - Ranking Backfill.

LAYER:
ranking

BOUNDARY:
Allowed:
- read historical signal_engine_state snapshots
- rebuild ranking_state rows deterministically
- write ranking_state via normal ranking upsert path

Forbidden:
- account state
- balances
- positions
- orders
- execution plans
- broker actions

Important:
Backfill must produce the same semantic fields as the live ranking engine.
Do not copy nullable sleeve_fit_code from inputs. Recompute it from
rotation_bucket + classification_code.
"""

import argparse
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_db_connection
from src.ranking.run_ranking_engine import (
    RANKING_VERSION,
    _to_decimal,
    classify_code,
    classify_rotation_bucket,
    classify_sleeve_fit,
    compute_relative_strength_score,
    compute_trade_quality_score,
    fetch_ranking_inputs,
    upsert_ranking_rows,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill ranking_state from historical signal_engine_state snapshots"
    )
    parser.add_argument("--interval", required=True, help="1h / 4h / 1d")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--limit-snapshots", type=int, default=None)
    return parser.parse_args()


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fetch_snapshot_timestamps(
    conn,
    *,
    venue: str,
    interval_code: str,
    from_ts: datetime,
    to_ts: datetime,
    limit_snapshots: int | None,
) -> list[datetime]:
    sql = """
    SELECT DISTINCT s.signal_ts_utc
    FROM signal_engine_state s
    WHERE s.venue = %s
      AND s.interval_code = %s
      AND s.signal_ts_utc >= %s
      AND s.signal_ts_utc <= %s
    ORDER BY s.signal_ts_utc
    """

    params: list[Any] = [
        venue,
        interval_code,
        from_ts.replace(tzinfo=None),
        to_ts.replace(tzinfo=None),
    ]

    if limit_snapshots is not None:
        sql += " LIMIT %s"
        params.append(limit_snapshots)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    out: list[datetime] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows")
        ts = row["signal_ts_utc"]
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        else:
            ts = ts.astimezone(UTC)
        out.append(ts)

    return out


def build_rows_for_snapshot(
    *,
    rows: list[dict[str, Any]],
    interval_code: str,
) -> list[dict[str, Any]]:
    out_rows: list[dict[str, Any]] = []

    for row in rows:
        trade_quality_score = compute_trade_quality_score(row)
        relative_strength_score = compute_relative_strength_score(row)

        classification_code = classify_code(row, trade_quality_score)
        rotation_bucket = classify_rotation_bucket(
            row,
            trade_quality_score,
            classification_code,
        )
        sleeve_fit_code = classify_sleeve_fit(rotation_bucket, classification_code)

        context_score = _to_decimal(row.get("opportunity_score"), "0")
        signal_confidence_score = _to_decimal(row.get("signal_confidence"), "0")
        regime_fit_score = _to_decimal(row.get("regime_fit_score"), "0")
        advice_risk_score = _to_decimal(row.get("advice_risk_score"), "0")
        rotation_trigger_score = _to_decimal(row.get("rotation_trigger_score"), "0")
        expansion_delay_score = _to_decimal(row.get("expansion_delay_score"), "0")
        expansion_position_score = _to_decimal(row.get("expansion_position_score"), "0")
        pullback_quality_score = _to_decimal(row.get("pullback_quality_score"), "0")

        out_rows.append(
            {
                "asset_id": row["asset_id"],
                "venue": row["venue"],
                "interval_code": interval_code,
                "asof_ts_utc": row["signal_ts_utc"],
                "ranking_version": RANKING_VERSION,
                "symbol": row["symbol"],
                "asset_class": row["asset_class"],
                "sector": row["sector"],
                "trade_quality_score": str(trade_quality_score),
                "relative_strength_score": str(relative_strength_score),
                "context_score": str(context_score),
                "signal_confidence_score": str(signal_confidence_score),
                "regime_fit_score": str(regime_fit_score),
                "advice_risk_score": str(advice_risk_score),
                "rotation_trigger_score": str(rotation_trigger_score),
                "expansion_delay_score": str(expansion_delay_score),
                "expansion_position_score": str(expansion_position_score),
                "pullback_quality_score": str(pullback_quality_score),
                "rotation_bucket": rotation_bucket,
                "classification_code": classification_code,
                "sleeve_fit_code": sleeve_fit_code,
                "regime_label": row.get("regime_label"),
                "time_horizon_hint": row.get("time_horizon_hint"),
                "advice_state": row.get("advice_state"),
                "priority_rank": row.get("priority_rank"),
                "final_rank": None,
                "notes": row.get("summary_text"),
            }
        )

    out_rows.sort(
        key=lambda r: (
            Decimal(str(r["trade_quality_score"])),
            str(r["symbol"]),
        ),
        reverse=True,
    )

    for idx, row in enumerate(out_rows, start=1):
        row["final_rank"] = idx

    return out_rows


def run(
    *,
    venue: str,
    interval_code: str,
    from_ts: datetime,
    to_ts: datetime,
    limit_snapshots: int | None,
) -> int:
    conn = get_db_connection()

    try:
        snapshots = fetch_snapshot_timestamps(
            conn,
            venue=venue,
            interval_code=interval_code,
            from_ts=from_ts,
            to_ts=to_ts,
            limit_snapshots=limit_snapshots,
        )

        if not snapshots:
            print("[WARN] no signal snapshots found in requested range")
            return 0

        total_written = 0

        for idx, snapshot_ts in enumerate(snapshots, start=1):
            rows = fetch_ranking_inputs(
                conn,
                venue=venue,
                interval_code=interval_code,
                snapshot_ts_utc=snapshot_ts,
            )

            if not rows:
                print(f"[SKIP] {idx}/{len(snapshots)} snapshot={snapshot_ts.isoformat()} no inputs")
                continue

            out_rows = build_rows_for_snapshot(
                rows=rows,
                interval_code=interval_code,
            )

            written = upsert_ranking_rows(conn, out_rows)
            total_written += written

            print(
                f"[SNAPSHOT] {idx}/{len(snapshots)} "
                f"interval={interval_code} "
                f"asof_ts_utc={snapshot_ts.isoformat()} "
                f"rows={written}"
            )

        print(
            f"[DONE] ranking backfill rows={total_written} "
            f"interval={interval_code} venue={venue} ranking_version={RANKING_VERSION}"
        )
        return total_written

    finally:
        conn.close()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(
        run(
            venue=args.venue,
            interval_code=args.interval,
            from_ts=_parse_ts(args.from_ts),
            to_ts=_parse_ts(args.to_ts),
            limit_snapshots=args.limit_snapshots,
        )
    )
