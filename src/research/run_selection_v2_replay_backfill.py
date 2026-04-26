from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.selection.selection_engine_v2 import (
    SelectionCandidate,
    SelectionRow,
    load_selection_config,
    rank_candidates,
)


DEFAULT_CONFIG_PATH = "configs/selection_engine_v2.yaml"
DEFAULT_VENUE = "bitvavo"
DEFAULT_ENGINE_NAME = "selection_engine_v2"
DEFAULT_ENGINE_VERSION = "2.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only replay backfill for selection_engine_v2 into synth_bt.bt_selection_v2_replay."
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--limit-snapshots", type=int, default=None)
    parser.add_argument("--min-snapshot-rows", type=int, default=20)
    parser.add_argument("--engine-name", default=DEFAULT_ENGINE_NAME)
    parser.add_argument("--engine-version", default=DEFAULT_ENGINE_VERSION)
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(UTC).replace(tzinfo=None)


def _to_decimal(value: Any, default: str = "0.0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return value


def fetch_replay_snapshots(
    conn,
    *,
    venue: str,
    from_ts: datetime,
    to_ts: datetime,
    min_snapshot_rows: int,
    limit_snapshots: int | None,
) -> list[datetime]:
    limit_sql = "" if limit_snapshots is None else "LIMIT %s"

    sql = f"""
    SELECT
        signal_ts_utc,
        COUNT(*) AS row_count
    FROM signal_engine_state
    WHERE venue = %s
      AND interval_code = '1h'
      AND signal_ts_utc >= %s
      AND signal_ts_utc < %s
    GROUP BY signal_ts_utc
    HAVING COUNT(*) >= %s
    ORDER BY signal_ts_utc ASC
    {limit_sql}
    """

    params: list[Any] = [
        venue,
        from_ts,
        to_ts,
        min_snapshot_rows,
    ]

    if limit_snapshots is not None:
        params.append(limit_snapshots)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    snapshots: list[datetime] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from snapshot query")
        snapshots.append(row["signal_ts_utc"])

    return snapshots


def fetch_replay_candidates(
    conn,
    *,
    venue: str,
    replay_asof_ts_utc: datetime,
    asset_id: int | None,
) -> list[SelectionCandidate]:
    asset_filter_sql = ""
    params: list[Any] = [
        venue,
        venue,
        replay_asof_ts_utc,
        venue,
    ]

    if asset_id is not None:
        asset_filter_sql = "AND a.asset_id = %s"
        params.append(asset_id)

    sql = f"""
    WITH scoped_asset AS (
        SELECT
            a.asset_id,
            a.symbol
        FROM asset a
        WHERE a.is_enabled = 1
          AND a.is_tradeable = 1
          {asset_filter_sql}
    ),
    signal_latest AS (
        SELECT s.*
        FROM signal_engine_state s
        JOIN (
            SELECT
                s2.asset_id,
                s2.interval_code,
                MAX(s2.signal_ts_utc) AS max_signal_ts_utc
            FROM signal_engine_state s2
            JOIN scoped_asset sa
              ON sa.asset_id = s2.asset_id
            WHERE s2.venue = %s
              AND s2.signal_ts_utc <= %s
              AND s2.interval_code IN ('1d', '4h', '1h')
            GROUP BY s2.asset_id, s2.interval_code
        ) x
          ON x.asset_id = s.asset_id
         AND x.interval_code = s.interval_code
         AND x.max_signal_ts_utc = s.signal_ts_utc
        WHERE s.venue = %s
    )
    SELECT
        sa.asset_id,
        sa.symbol,
        %s AS venue,

        'TRUSTED' AS quality_status_1d,
        'TRUSTED' AS quality_status_4h,
        'TRUSTED' AS quality_status_1h,

        COALESCE(sig1d.trend_score, 0) AS trend_score_1d,
        COALESCE(sig1d.setup_score, 0) AS setup_score_1d,
        COALESCE(sig1d.signal_confidence, 0) AS signal_confidence_1d,
        COALESCE(sig1d.risk_score, 0) AS risk_score_1d,

        COALESCE(sig4h.volume_score, 0) AS volume_score_4h,
        COALESCE(sig4h.compass_score, 0) AS compass_score_4h,
        COALESCE(sig4h.setup_score, 0) AS setup_score_4h,
        COALESCE(sig4h.relative_score, 0) AS relative_score_4h,
        COALESCE(sig4h.signal_confidence, 0) AS signal_confidence_4h,
        COALESCE(sig4h.expansion_position_score, 0) AS expansion_position_score_4h,
        COALESCE(sig4h.pullback_quality_score, 0) AS pullback_quality_score_4h,
        COALESCE(sig4h.risk_score, 0) AS risk_score_4h,

        COALESCE(sig1h.setup_score, 0) AS setup_score_1h,
        COALESCE(sig1h.signal_confidence, 0) AS signal_confidence_1h,
        COALESCE(sig1h.risk_score, 0) AS risk_score_1h,

        CAST(%s AS CHAR) AS latest_quality_asof_ts_utc,
        CAST(sig1h.signal_ts_utc AS CHAR) AS advice_ts_1h_utc,
        CAST(sig4h.signal_ts_utc AS CHAR) AS advice_ts_4h_utc

    FROM scoped_asset sa

    LEFT JOIN signal_latest sig1d
      ON sig1d.asset_id = sa.asset_id
     AND sig1d.interval_code = '1d'

    LEFT JOIN signal_latest sig4h
      ON sig4h.asset_id = sa.asset_id
     AND sig4h.interval_code = '4h'

    LEFT JOIN signal_latest sig1h
      ON sig1h.asset_id = sa.asset_id
     AND sig1h.interval_code = '1h'

    ORDER BY sa.asset_id
    """

    with conn.cursor() as cur:
        execute_params: list[Any] = []

        if asset_id is not None:
            execute_params.append(asset_id)

        execute_params.extend(
            [
                venue,
                replay_asof_ts_utc,
                venue,
                venue,
                replay_asof_ts_utc,
            ]
        )

        cur.execute(sql, execute_params)
        rows = cur.fetchall()

    out: list[SelectionCandidate] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from replay candidate query")

        out.append(
            SelectionCandidate(
                asset_id=int(row["asset_id"]),
                symbol=str(row["symbol"]),
                venue=str(row["venue"]),
                quality_status_1d=str(row.get("quality_status_1d") or "TRUSTED"),
                quality_status_4h=str(row.get("quality_status_4h") or "TRUSTED"),
                quality_status_1h=str(row.get("quality_status_1h") or "TRUSTED"),
                trend_score_1d=_to_decimal(row.get("trend_score_1d")),
                setup_score_1d=_to_decimal(row.get("setup_score_1d")),
                signal_confidence_1d=_to_decimal(row.get("signal_confidence_1d")),
                risk_score_1d=_to_decimal(row.get("risk_score_1d")),
                volume_score_4h=_to_decimal(row.get("volume_score_4h")),
                compass_score_4h=_to_decimal(row.get("compass_score_4h")),
                setup_score_4h=_to_decimal(row.get("setup_score_4h")),
                relative_score_4h=_to_decimal(row.get("relative_score_4h")),
                signal_confidence_4h=_to_decimal(row.get("signal_confidence_4h")),
                expansion_position_score_4h=_to_decimal(row.get("expansion_position_score_4h")),
                pullback_quality_score_4h=_to_decimal(row.get("pullback_quality_score_4h")),
                risk_score_4h=_to_decimal(row.get("risk_score_4h")),
                setup_score_1h=_to_decimal(row.get("setup_score_1h")),
                signal_confidence_1h=_to_decimal(row.get("signal_confidence_1h")),
                risk_score_1h=_to_decimal(row.get("risk_score_1h")),
                latest_quality_asof_ts_utc=(
                    None if row.get("latest_quality_asof_ts_utc") is None
                    else str(row["latest_quality_asof_ts_utc"])
                ),
                advice_ts_1h_utc=(
                    None if row.get("advice_ts_1h_utc") is None
                    else str(row["advice_ts_1h_utc"])
                ),
                advice_ts_4h_utc=(
                    None if row.get("advice_ts_4h_utc") is None
                    else str(row["advice_ts_4h_utc"])
                ),
            )
        )

    return out


def _allowed_sleeves_to_db(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item) for item in value)
    return str(value)


def write_replay_rows(
    conn,
    *,
    rows: list[SelectionRow],
    replay_asof_ts_utc: datetime,
    engine_name: str,
    engine_version: str,
) -> int:
    if not rows:
        return 0

    sql = """
    INSERT INTO bt_selection_v2_replay (
        asset_id,
        symbol,
        venue,
        replay_asof_ts_utc,
        advice_ts_1h_utc,
        advice_ts_4h_utc,
        selection_state,
        selection_bias,
        selection_score,
        priority_rank,
        allow_trade_flag,
        allowed_sleeves,
        blocked_reason,
        trade_quality_score,
        timing_refinement_score,
        quality_penalty,
        quality_status_1d,
        quality_status_4h,
        quality_status_1h,
        summary_text,
        engine_name,
        engine_version
    ) VALUES (
        %(asset_id)s,
        %(symbol)s,
        %(venue)s,
        %(replay_asof_ts_utc)s,
        %(advice_ts_1h_utc)s,
        %(advice_ts_4h_utc)s,
        %(selection_state)s,
        %(selection_bias)s,
        %(selection_score)s,
        %(priority_rank)s,
        %(allow_trade_flag)s,
        %(allowed_sleeves)s,
        %(blocked_reason)s,
        %(trade_quality_score)s,
        %(timing_refinement_score)s,
        %(quality_penalty)s,
        %(quality_status_1d)s,
        %(quality_status_4h)s,
        %(quality_status_1h)s,
        %(summary_text)s,
        %(engine_name)s,
        %(engine_version)s
    )
    ON DUPLICATE KEY UPDATE
        advice_ts_1h_utc = VALUES(advice_ts_1h_utc),
        advice_ts_4h_utc = VALUES(advice_ts_4h_utc),
        selection_state = VALUES(selection_state),
        selection_bias = VALUES(selection_bias),
        selection_score = VALUES(selection_score),
        priority_rank = VALUES(priority_rank),
        allow_trade_flag = VALUES(allow_trade_flag),
        allowed_sleeves = VALUES(allowed_sleeves),
        blocked_reason = VALUES(blocked_reason),
        trade_quality_score = VALUES(trade_quality_score),
        timing_refinement_score = VALUES(timing_refinement_score),
        quality_penalty = VALUES(quality_penalty),
        quality_status_1d = VALUES(quality_status_1d),
        quality_status_4h = VALUES(quality_status_4h),
        quality_status_1h = VALUES(quality_status_1h),
        summary_text = VALUES(summary_text),
        replay_created_ts_utc = CURRENT_TIMESTAMP(6)
    """

    params: list[dict[str, Any]] = []
    for row in rows:
        row_dict = asdict(row)

        params.append(
            {
                "asset_id": row.asset_id,
                "symbol": row.symbol,
                "venue": row.venue,
                "replay_asof_ts_utc": replay_asof_ts_utc,
                "advice_ts_1h_utc": row.advice_ts_1h_utc,
                "advice_ts_4h_utc": row.advice_ts_4h_utc,
                "selection_state": row.selection_state,
                "selection_bias": row.selection_bias,
                "selection_score": row.selection_score,
                "priority_rank": row.priority_rank,
                "allow_trade_flag": int(bool(row.allow_trade_flag)),
                "allowed_sleeves": _allowed_sleeves_to_db(row_dict.get("allowed_sleeves")),
                "blocked_reason": row.blocked_reason,
                "trade_quality_score": row.trade_quality_score,
                "timing_refinement_score": row.timing_refinement_score,
                "quality_penalty": row.quality_penalty,
                "quality_status_1d": row.quality_status_1d,
                "quality_status_4h": row.quality_status_4h,
                "quality_status_1h": row.quality_status_1h,
                "summary_text": row.summary,
                "engine_name": engine_name,
                "engine_version": engine_version,
            }
        )

    with conn.cursor() as cur:
        cur.executemany(sql, params)

    conn.commit()
    return len(rows)


def summarize_rows(rows: list[SelectionRow]) -> dict[str, Any]:
    states = Counter(row.selection_state for row in rows)
    return {
        "rows": len(rows),
        "states": dict(sorted(states.items())),
    }


def print_table(summaries: list[dict[str, Any]]) -> None:
    headers = [
        "snapshot",
        "candidates",
        "rows",
        "AVOID",
        "NEUTRAL",
        "WATCHLIST",
        "PREPARE",
        "BUY_READY",
        "written",
    ]

    printable: list[list[str]] = []
    for summary in summaries:
        states = summary["states"]
        printable.append(
            [
                str(summary["snapshot"]),
                str(summary["candidates"]),
                str(summary["rows"]),
                str(states.get("AVOID", 0)),
                str(states.get("NEUTRAL", 0)),
                str(states.get("WATCHLIST", 0)),
                str(states.get("PREPARE", 0)),
                str(states.get("BUY_READY", 0)),
                str(summary["written"]),
            ]
        )

    widths = [len(header) for header in headers]
    for row in printable:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def fmt(values: list[str]) -> str:
        return " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(values))

    print(fmt(headers))
    print("-+-".join("-" * width for width in widths))
    for row in printable:
        print(fmt(row))


def main() -> int:
    args = parse_args()

    from_ts = parse_ts(str(args.from_ts))
    to_ts = parse_ts(str(args.to_ts))
    config = load_selection_config(args.config)

    source_conn = get_connection()
    replay_conn = get_connection(database="synth_bt")

    try:
        snapshots = fetch_replay_snapshots(
            source_conn,
            venue=str(args.venue),
            from_ts=from_ts,
            to_ts=to_ts,
            min_snapshot_rows=int(args.min_snapshot_rows),
            limit_snapshots=args.limit_snapshots,
        )

        summaries: list[dict[str, Any]] = []

        for snapshot in snapshots:
            candidates = fetch_replay_candidates(
                source_conn,
                venue=str(args.venue),
                replay_asof_ts_utc=snapshot,
                asset_id=args.asset_id,
            )
            rows = rank_candidates(candidates, config)

            written = 0
            if args.write_db:
                written = write_replay_rows(
                    replay_conn,
                    rows=rows,
                    replay_asof_ts_utc=snapshot,
                    engine_name=str(args.engine_name),
                    engine_version=str(args.engine_version),
                )

            summary = summarize_rows(rows)
            summary["snapshot"] = snapshot
            summary["candidates"] = len(candidates)
            summary["written"] = written
            summaries.append(summary)

        if args.output == "json":
            print(json.dumps(summaries, indent=2, ensure_ascii=False, default=_serialize))
        else:
            print_table(summaries)

        print(
            f"[DONE] snapshots={len(snapshots)} write_db={args.write_db} "
            f"window=[{from_ts}, {to_ts})"
        )

        return 0

    finally:
        source_conn.close()
        replay_conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
