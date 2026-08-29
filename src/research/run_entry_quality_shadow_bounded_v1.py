from __future__ import annotations

import argparse
import signal
import time
from decimal import Decimal
from typing import Any

from src.common.db import get_db_connection
from src.research.run_entry_quality_shadow_v1 import (
    DEFAULT_OUTPUT_CSV,
    _load_ppp_csv,
    build_shadow_rows,
    write_csv,
    write_shadow_rows,
)
from src.selection.run_selection_engine_v2 import DEFAULT_CONFIG_PATH
from src.selection.selection_engine_v2 import SelectionCandidate, load_selection_config, rank_candidates

RUNNER_NAME = "entry_quality_shadow_bounded_v1"


class _Interrupted(RuntimeError):
    def __init__(self, signum: int) -> None:
        super().__init__(f"signal={signum}")
        self.signum = signum


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded research-only CQ shadow population runner"
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--ppp-csv", default=None)
    parser.add_argument("--out-csv", default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--write-db", action="store_true")
    return parser.parse_args(argv)


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def fetch_bounded_selection_candidates(
    conn: Any,
    *,
    venue: str,
    asset_id: int | None,
    limit: int,
) -> list[SelectionCandidate]:
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be within 1..1000")

    asset_filter_sql = ""
    params: list[Any] = []
    if asset_id is not None:
        asset_filter_sql = "AND asset_id = %s"
        params.append(asset_id)
    params.append(limit)

    sql = f"""
    SELECT
        a.asset_id,
        a.symbol,
        COALESCE(q1d.quality_status, 'BLOCKED') AS quality_status_1d,
        COALESCE(q4h.quality_status, 'BLOCKED') AS quality_status_4h,
        COALESCE(q1h.quality_status, 'BLOCKED') AS quality_status_1h,
        COALESCE(s1d.trend_score, 0) AS trend_score_1d,
        COALESCE(s1d.setup_score, 0) AS setup_score_1d,
        COALESCE(s1d.signal_confidence, 0) AS signal_confidence_1d,
        COALESCE(s1d.risk_score, 0) AS risk_score_1d,
        COALESCE(s4h.volume_score, 0) AS volume_score_4h,
        COALESCE(s4h.compass_score, 0) AS compass_score_4h,
        COALESCE(s4h.setup_score, 0) AS setup_score_4h,
        COALESCE(s4h.relative_score, 0) AS relative_score_4h,
        COALESCE(s4h.signal_confidence, 0) AS signal_confidence_4h,
        COALESCE(s4h.expansion_position_score, 0) AS expansion_position_score_4h,
        COALESCE(s4h.pullback_quality_score, 0) AS pullback_quality_score_4h,
        COALESCE(s4h.risk_score, 0) AS risk_score_4h,
        COALESCE(s1h.setup_score, 0) AS setup_score_1h,
        COALESCE(s1h.signal_confidence, 0) AS signal_confidence_1h,
        COALESCE(s1h.risk_score, 0) AS risk_score_1h,
        CAST(
            GREATEST(
                COALESCE(q1d.asof_ts_utc, '1970-01-01 00:00:00'),
                COALESCE(q4h.asof_ts_utc, '1970-01-01 00:00:00'),
                COALESCE(q1h.asof_ts_utc, '1970-01-01 00:00:00')
            ) AS CHAR
        ) AS latest_quality_asof_ts_utc,
        CAST(s1h.signal_ts_utc AS CHAR) AS advice_ts_1h_utc,
        CAST(s4h.signal_ts_utc AS CHAR) AS advice_ts_4h_utc
    FROM (
        SELECT asset_id, symbol
        FROM asset
        WHERE is_enabled = 1
          AND is_tradeable = 1
          {asset_filter_sql}
        ORDER BY asset_id
        LIMIT %s
    ) a
    LEFT JOIN asset_interval_quality q1d
      ON q1d.asset_id = a.asset_id AND q1d.venue = %s AND q1d.interval_code = '1d'
     AND q1d.asof_ts_utc = (
         SELECT MAX(q.asof_ts_utc) FROM asset_interval_quality q
         WHERE q.asset_id = a.asset_id AND q.venue = %s AND q.interval_code = '1d'
     )
    LEFT JOIN asset_interval_quality q4h
      ON q4h.asset_id = a.asset_id AND q4h.venue = %s AND q4h.interval_code = '4h'
     AND q4h.asof_ts_utc = (
         SELECT MAX(q.asof_ts_utc) FROM asset_interval_quality q
         WHERE q.asset_id = a.asset_id AND q.venue = %s AND q.interval_code = '4h'
     )
    LEFT JOIN asset_interval_quality q1h
      ON q1h.asset_id = a.asset_id AND q1h.venue = %s AND q1h.interval_code = '1h'
     AND q1h.asof_ts_utc = (
         SELECT MAX(q.asof_ts_utc) FROM asset_interval_quality q
         WHERE q.asset_id = a.asset_id AND q.venue = %s AND q.interval_code = '1h'
     )
    LEFT JOIN signal_engine_state s1d
      ON s1d.asset_id = a.asset_id AND s1d.venue = %s AND s1d.interval_code = '1d'
     AND s1d.signal_ts_utc = (
         SELECT MAX(s.signal_ts_utc) FROM signal_engine_state s
         WHERE s.asset_id = a.asset_id AND s.venue = %s AND s.interval_code = '1d'
     )
    LEFT JOIN signal_engine_state s4h
      ON s4h.asset_id = a.asset_id AND s4h.venue = %s AND s4h.interval_code = '4h'
     AND s4h.signal_ts_utc = (
         SELECT MAX(s.signal_ts_utc) FROM signal_engine_state s
         WHERE s.asset_id = a.asset_id AND s.venue = %s AND s.interval_code = '4h'
     )
    LEFT JOIN signal_engine_state s1h
      ON s1h.asset_id = a.asset_id AND s1h.venue = %s AND s1h.interval_code = '1h'
     AND s1h.signal_ts_utc = (
         SELECT MAX(s.signal_ts_utc) FROM signal_engine_state s
         WHERE s.asset_id = a.asset_id AND s.venue = %s AND s.interval_code = '1h'
     )
    ORDER BY a.asset_id
    """
    params.extend([venue, venue] * 6)

    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()

    return [
        SelectionCandidate(
            asset_id=int(row["asset_id"]),
            symbol=str(row["symbol"]),
            venue=venue,
            quality_status_1d=str(row.get("quality_status_1d") or "BLOCKED"),
            quality_status_4h=str(row.get("quality_status_4h") or "BLOCKED"),
            quality_status_1h=str(row.get("quality_status_1h") or "BLOCKED"),
            trend_score_1d=_decimal(row.get("trend_score_1d")),
            setup_score_1d=_decimal(row.get("setup_score_1d")),
            signal_confidence_1d=_decimal(row.get("signal_confidence_1d")),
            risk_score_1d=_decimal(row.get("risk_score_1d")),
            volume_score_4h=_decimal(row.get("volume_score_4h")),
            compass_score_4h=_decimal(row.get("compass_score_4h")),
            setup_score_4h=_decimal(row.get("setup_score_4h")),
            relative_score_4h=_decimal(row.get("relative_score_4h")),
            signal_confidence_4h=_decimal(row.get("signal_confidence_4h")),
            expansion_position_score_4h=_decimal(row.get("expansion_position_score_4h")),
            pullback_quality_score_4h=_decimal(row.get("pullback_quality_score_4h")),
            risk_score_4h=_decimal(row.get("risk_score_4h")),
            setup_score_1h=_decimal(row.get("setup_score_1h")),
            signal_confidence_1h=_decimal(row.get("signal_confidence_1h")),
            risk_score_1h=_decimal(row.get("risk_score_1h")),
            latest_quality_asof_ts_utc=(
                None
                if row.get("latest_quality_asof_ts_utc") is None
                else str(row["latest_quality_asof_ts_utc"])
            ),
            advice_ts_1h_utc=(
                None if row.get("advice_ts_1h_utc") is None else str(row["advice_ts_1h_utc"])
            ),
            advice_ts_4h_utc=(
                None if row.get("advice_ts_4h_utc") is None else str(row["advice_ts_4h_utc"])
            ),
        )
        for row in rows
    ]


def fetch_bounded_evidence_timestamps(
    conn: Any,
    *,
    venue: str,
    asset_ids: list[int],
) -> dict[int, dict[str, str | None]]:
    if not asset_ids:
        return {}
    placeholders = ",".join(["%s"] * len(asset_ids))
    sql = f"""
    SELECT a.asset_id,
      (SELECT CAST(MAX(q.asof_ts_utc) AS CHAR) FROM asset_interval_quality q WHERE q.asset_id=a.asset_id AND q.venue=%s AND q.interval_code='1d') AS quality_ts_1d_utc,
      (SELECT CAST(MAX(q.asof_ts_utc) AS CHAR) FROM asset_interval_quality q WHERE q.asset_id=a.asset_id AND q.venue=%s AND q.interval_code='4h') AS quality_ts_4h_utc,
      (SELECT CAST(MAX(q.asof_ts_utc) AS CHAR) FROM asset_interval_quality q WHERE q.asset_id=a.asset_id AND q.venue=%s AND q.interval_code='1h') AS quality_ts_1h_utc,
      (SELECT CAST(MAX(s.signal_ts_utc) AS CHAR) FROM signal_engine_state s WHERE s.asset_id=a.asset_id AND s.venue=%s AND s.interval_code='1d') AS signal_ts_1d_utc,
      (SELECT CAST(MAX(s.signal_ts_utc) AS CHAR) FROM signal_engine_state s WHERE s.asset_id=a.asset_id AND s.venue=%s AND s.interval_code='4h') AS signal_ts_4h_utc,
      (SELECT CAST(MAX(s.signal_ts_utc) AS CHAR) FROM signal_engine_state s WHERE s.asset_id=a.asset_id AND s.venue=%s AND s.interval_code='1h') AS signal_ts_1h_utc
    FROM asset a
    WHERE a.asset_id IN ({placeholders})
    ORDER BY a.asset_id
    """
    params: list[Any] = [venue] * 6 + asset_ids
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    keys = (
        "quality_ts_1d_utc",
        "quality_ts_4h_utc",
        "quality_ts_1h_utc",
        "signal_ts_1d_utc",
        "signal_ts_4h_utc",
        "signal_ts_1h_utc",
    )
    return {
        int(row["asset_id"]): {
            key: (None if row.get(key) is None else str(row[key])) for key in keys
        }
        for row in rows
    }


def run(args: argparse.Namespace) -> int:
    mode = "shadow-db" if args.write_db else "shadow-csv"
    started = time.perf_counter()
    print(f"STARTED runner={RUNNER_NAME} mode={mode} bounded_assets=1 workers=1", flush=True)
    print(
        "SAFETY research_only=1 shadow_only=1 broker_private_calls=0 broker_writes=0 "
        "order_submission=0 live_orders=0 selection_ranking_changes=0 decision_gate=none "
        "execution_planner=none executor=none",
        flush=True,
    )

    conn = None
    previous_handlers: dict[int, Any] = {}

    def _handle_signal(signum: int, _frame: Any) -> None:
        raise _Interrupted(signum)

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _handle_signal)

        conn = get_db_connection()
        config = load_selection_config(args.config)

        phase = time.perf_counter()
        print(
            f"PHASE_START name=fetch_bounded_selection_candidates venue={args.venue} "
            f"asset_id={args.asset_id if args.asset_id is not None else 'ALL'} limit={args.limit}",
            flush=True,
        )
        candidates = fetch_bounded_selection_candidates(
            conn, venue=args.venue, asset_id=args.asset_id, limit=args.limit
        )
        print(
            f"PHASE_END name=fetch_bounded_selection_candidates rows={len(candidates)} "
            f"elapsed_s={time.perf_counter()-phase:.3f}",
            flush=True,
        )

        phase = time.perf_counter()
        print(f"PHASE_START name=rank_candidates input_rows={len(candidates)}", flush=True)
        selection_rows = rank_candidates(candidates, config)
        print(
            f"PHASE_END name=rank_candidates rows={len(selection_rows)} "
            f"elapsed_s={time.perf_counter()-phase:.3f}",
            flush=True,
        )

        phase = time.perf_counter()
        print(
            f"PHASE_START name=fetch_bounded_evidence_timestamps assets={len(selection_rows)}",
            flush=True,
        )
        evidence = fetch_bounded_evidence_timestamps(
            conn, venue=args.venue, asset_ids=[row.asset_id for row in selection_rows]
        )
        print(
            f"PHASE_END name=fetch_bounded_evidence_timestamps rows={len(evidence)} "
            f"elapsed_s={time.perf_counter()-phase:.3f}",
            flush=True,
        )

        phase = time.perf_counter()
        print(f"PHASE_START name=build_shadow rows={len(selection_rows)}", flush=True)
        rows = build_shadow_rows(
            selection_rows=selection_rows,
            ppp_by_symbol=_load_ppp_csv(args.ppp_csv),
            evidence_by_asset=evidence,
        )
        print(
            f"PHASE_END name=build_shadow rows={len(rows)} "
            f"elapsed_s={time.perf_counter()-phase:.3f}",
            flush=True,
        )

        phase = time.perf_counter()
        print(f"PHASE_START name=write_csv path={args.out_csv}", flush=True)
        write_csv(args.out_csv, rows)
        print(
            f"PHASE_END name=write_csv rows={len(rows)} elapsed_s={time.perf_counter()-phase:.3f}",
            flush=True,
        )

        written = 0
        if args.write_db:
            phase = time.perf_counter()
            print("PHASE_START name=write_db table=research_entry_quality_shadow", flush=True)
            written = write_shadow_rows(conn, rows)
            print(
                f"PHASE_END name=write_db rows={written} elapsed_s={time.perf_counter()-phase:.3f}",
                flush=True,
            )

        print(
            f"FINISHED runner={RUNNER_NAME} mode={mode} rows={len(rows)} db_rows_written={written} "
            f"production_ranking_changed=0 elapsed_s={time.perf_counter()-started:.3f}",
            flush=True,
        )
        return 0
    except _Interrupted as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        print(
            f"INTERRUPTED runner={RUNNER_NAME} mode={mode} signal={exc.signum} "
            f"resumable=1 elapsed_s={time.perf_counter()-started:.3f}",
            flush=True,
        )
        return 130
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        print(
            f"FAILED runner={RUNNER_NAME} mode={mode} reason={type(exc).__name__}:{exc} "
            f"elapsed_s={time.perf_counter()-started:.3f}",
            flush=True,
        )
        return 1
    finally:
        if conn is not None:
            conn.close()
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())