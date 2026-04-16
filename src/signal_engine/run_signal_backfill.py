from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_db_connection
from src.engine.write_signal_engine_state import (
    SignalEngineStateRow,
    upsert_signal_engine_state,
)
from src.signal_engine.run_signal_state_etl import (
    DEFAULT_VENUE,
    _ensure_utc,
    build_signal_engine_input,
    compute_expansion_position_score,
    compute_pullback_quality_score,
    fetch_snapshot_feat_rows,
    compute_late_trend_flag,
)
from src.signal_engine.signal_engine import evaluate_signal_engine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill signal_engine_state from historical feat_candle snapshots"
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", required=True, help="1h / 4h / 1d")
    parser.add_argument("--asset-id", type=int, default=None, help="Optional single asset_id filter")
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--limit-snapshots", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _to_decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def fetch_snapshot_timestamps(
    conn,
    *,
    venue: str,
    interval_code: str,
    asset_id: int | None,
    from_ts: datetime,
    to_ts: datetime,
    limit_snapshots: int | None,
) -> list[datetime]:
    where = [
        "fc.venue = %s",
        "fc.interval_code = %s",
        "fc.close_ts_utc >= %s",
        "fc.close_ts_utc <= %s",
        "a.is_enabled = 1",
    ]
    params: list[Any] = [
        venue,
        interval_code,
        from_ts.replace(tzinfo=None),
        to_ts.replace(tzinfo=None),
    ]

    if asset_id is not None:
        where.append("fc.asset_id = %s")
        params.append(asset_id)

    sql = f"""
    SELECT DISTINCT fc.close_ts_utc
    FROM feat_candle fc
    JOIN asset a
      ON a.asset_id = fc.asset_id
    WHERE {' AND '.join(where)}
    ORDER BY fc.close_ts_utc
    """

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
        ts = row["close_ts_utc"]
        if ts is None:
            continue
        out.append(_ensure_utc(ts))
    return out


def build_state_row(row: dict[str, Any]) -> SignalEngineStateRow:
    signal_input = build_signal_engine_input(row)
    signal_output = evaluate_signal_engine(signal_input)

    signal_ts_utc = _ensure_utc(row["close_ts_utc"])
    expansion_position_score = compute_expansion_position_score(row)
    pullback_quality_score = compute_pullback_quality_score(row)
    late_trend_flag = compute_late_trend_flag(row)

    return SignalEngineStateRow(
        asset_id=int(row["asset_id"]),
        venue=str(row["venue"]),
        interval_code=str(row["interval_code"]),
        signal_ts_utc=signal_ts_utc.replace(tzinfo=None),
        trend_signal=str(signal_output.trend_signal),
        volume_signal=str(signal_output.volume_signal),
        phase_signal=str(signal_output.phase_signal),
        compass_signal=str(signal_output.compass_signal),
        rotation_signal=str(signal_output.rotation_signal),
        relative_signal=str(signal_output.relative_signal),
        setup_signal=str(signal_output.setup_signal),
        risk_signal=str(signal_output.risk_signal),
        signal_confidence=_to_decimal_or_none(signal_output.signal_confidence),
        trend_score=_to_decimal_or_none(signal_output.trend_score),
        volume_score=_to_decimal_or_none(signal_output.volume_score),
        phase_score=_to_decimal_or_none(signal_output.phase_score),
        compass_score=_to_decimal_or_none(signal_output.compass_score),
        rotation_score=_to_decimal_or_none(signal_output.rotation_score),
        relative_score=_to_decimal_or_none(signal_output.relative_score),
        setup_score=_to_decimal_or_none(signal_output.setup_score),
        risk_score=_to_decimal_or_none(signal_output.risk_score),
        rotation_trigger_score=_to_decimal_or_none(signal_output.rotation_trigger_score),
        expansion_delay_score=_to_decimal_or_none(signal_output.expansion_delay_score),
        expansion_position_score=_to_decimal_or_none(expansion_position_score),
        pullback_quality_score=_to_decimal_or_none(pullback_quality_score),
        late_trend_flag=int(late_trend_flag),
    )


def run(
    *,
    venue: str,
    interval_code: str,
    asset_id: int | None,
    from_ts: datetime,
    to_ts: datetime,
    limit_snapshots: int | None,
    dry_run: bool,
) -> int:
    conn = get_db_connection()

    try:
        snapshots = fetch_snapshot_timestamps(
            conn,
            venue=venue,
            interval_code=interval_code,
            asset_id=asset_id,
            from_ts=from_ts,
            to_ts=to_ts,
            limit_snapshots=limit_snapshots,
        )

        if not snapshots:
            print("[WARN] no feat_candle snapshots found in requested range")
            return 0

        total_written = 0

        for idx, snapshot_ts in enumerate(snapshots, start=1):
            feat_rows = fetch_snapshot_feat_rows(
                conn,
                venue=venue,
                interval_code=interval_code,
                snapshot_ts_utc=snapshot_ts,
                asset_id=asset_id,
            )

            if not feat_rows:
                print(f"[SKIP] {idx}/{len(snapshots)} snapshot={snapshot_ts.isoformat()} no feat rows")
                continue

            out_rows = [build_state_row(row) for row in feat_rows]

            if dry_run:
                first_preview = asdict(out_rows[0]) if out_rows else None
                print(
                    f"[DRY-RUN] {idx}/{len(snapshots)} "
                    f"interval={interval_code} "
                    f"signal_ts_utc={snapshot_ts.isoformat()} "
                    f"rows={len(out_rows)} "
                    f"first_row={first_preview}"
                )
                continue

            written = upsert_signal_engine_state(conn, out_rows)
            total_written += written

            print(
                f"[SNAPSHOT] {idx}/{len(snapshots)} "
                f"interval={interval_code} "
                f"signal_ts_utc={snapshot_ts.isoformat()} "
                f"rows={written}"
            )

        print(
            f"[DONE] signal backfill rows={total_written} "
            f"interval={interval_code} venue={venue}"
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
            asset_id=args.asset_id,
            from_ts=_parse_ts(args.from_ts),
            to_ts=_parse_ts(args.to_ts),
            limit_snapshots=args.limit_snapshots,
            dry_run=args.dry_run,
        )
    )
