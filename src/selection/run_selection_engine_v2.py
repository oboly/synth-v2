from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
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
        description="Run Selection Engine v2 (stdout / CSV / optional DB write)"
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--out-csv", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--engine-name", default=DEFAULT_ENGINE_NAME)
    parser.add_argument("--engine-version", default=DEFAULT_ENGINE_VERSION)
    return parser.parse_args()


def _to_decimal(value: Any, default: str = "0.0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def fetch_selection_candidates(
    conn,
    *,
    venue: str,
    asset_id: int | None,
    limit: int,
) -> list[SelectionCandidate]:
    asset_filter_sql = ""
    params: list[Any] = [
        venue,
        venue,
        venue,
        venue,
        venue,
    ]

    if asset_id is not None:
        asset_filter_sql = "AND a.asset_id = %s"
        params.append(asset_id)

    params.append(limit)

    sql = f"""
    WITH quality_latest AS (
        SELECT q.*
        FROM v_asset_interval_quality_v3 q
        JOIN (
            SELECT
                asset_id,
                venue,
                interval_code,
                MAX(asof_ts_utc) AS max_asof_ts_utc
            FROM v_asset_interval_quality_v3
            WHERE venue = %s
            GROUP BY asset_id, venue, interval_code
        ) x
          ON x.asset_id = q.asset_id
         AND x.venue = q.venue
         AND x.interval_code = q.interval_code
         AND x.max_asof_ts_utc = q.asof_ts_utc
        WHERE q.venue = %s
    ),
    signal_latest AS (
        SELECT s.*
        FROM signal_engine_state s
        JOIN (
            SELECT
                asset_id,
                venue,
                interval_code,
                MAX(signal_ts_utc) AS max_signal_ts_utc
            FROM signal_engine_state
            WHERE venue = %s
            GROUP BY asset_id, venue, interval_code
        ) x
          ON x.asset_id = s.asset_id
         AND x.venue = s.venue
         AND x.interval_code = s.interval_code
         AND x.max_signal_ts_utc = s.signal_ts_utc
        WHERE s.venue = %s
    )
    SELECT
        a.asset_id,
        a.symbol,
        %s AS venue,

        COALESCE(q1d.quality_status, 'BLOCKED') AS quality_status_1d,
        COALESCE(q4h.quality_status, 'BLOCKED') AS quality_status_4h,
        COALESCE(q1h.quality_status, 'BLOCKED') AS quality_status_1h,

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

        CAST(
            GREATEST(
                COALESCE(q1d.asof_ts_utc, '1970-01-01 00:00:00'),
                COALESCE(q4h.asof_ts_utc, '1970-01-01 00:00:00'),
                COALESCE(q1h.asof_ts_utc, '1970-01-01 00:00:00')
            ) AS CHAR
        ) AS latest_quality_asof_ts_utc,

        CAST(sig1h.signal_ts_utc AS CHAR) AS advice_ts_1h_utc,
        CAST(sig4h.signal_ts_utc AS CHAR) AS advice_ts_4h_utc

    FROM asset a
    LEFT JOIN quality_latest q1d
      ON q1d.asset_id = a.asset_id
     AND q1d.interval_code = '1d'
    LEFT JOIN quality_latest q4h
      ON q4h.asset_id = a.asset_id
     AND q4h.interval_code = '4h'
    LEFT JOIN quality_latest q1h
      ON q1h.asset_id = a.asset_id
     AND q1h.interval_code = '1h'

    LEFT JOIN signal_latest sig1d
      ON sig1d.asset_id = a.asset_id
     AND sig1d.interval_code = '1d'
    LEFT JOIN signal_latest sig4h
      ON sig4h.asset_id = a.asset_id
     AND sig4h.interval_code = '4h'
    LEFT JOIN signal_latest sig1h
      ON sig1h.asset_id = a.asset_id
     AND sig1h.interval_code = '1h'

    WHERE a.is_enabled = 1
      AND a.is_tradeable = 1
      {asset_filter_sql}

    ORDER BY a.asset_id
    LIMIT %s
    """

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    out: list[SelectionCandidate] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict cursor rows")

        out.append(
            SelectionCandidate(
                asset_id=int(row["asset_id"]),
                symbol=str(row["symbol"]),
                venue=str(row["venue"]),
                quality_status_1d=str(row.get("quality_status_1d") or "BLOCKED"),
                quality_status_4h=str(row.get("quality_status_4h") or "BLOCKED"),
                quality_status_1h=str(row.get("quality_status_1h") or "BLOCKED"),
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


def write_csv(path: str, rows: list[dict[str, Any]]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        output_path.write_text("", encoding="utf-8")
        return

    fieldnames = list(rows[0].keys())
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _print_rows(printable_rows: list[dict[str, Any]]) -> None:
    print(
        "asset_id,symbol,selection_state,selection_bias,selection_score,"
        "priority_rank,allow_trade_flag,allowed_sleeves,blocked_reason,"
        "trade_quality_score,timing_refinement_score,quality_penalty,"
        "quality_status_1d,quality_status_4h,quality_status_1h,"
        "advice_ts_1h_utc,advice_ts_4h_utc"
    )
    for row in printable_rows:
        print(
            f"{row['asset_id']},"
            f"{row['symbol']},"
            f"{row['selection_state']},"
            f"{row['selection_bias']},"
            f"{row['selection_score']},"
            f"{row['priority_rank']},"
            f"{row['allow_trade_flag']},"
            f"\"{row['allowed_sleeves']}\","
            f"{row['blocked_reason']},"
            f"{row['trade_quality_score']},"
            f"{row['timing_refinement_score']},"
            f"{row['quality_penalty']},"
            f"{row['quality_status_1d']},"
            f"{row['quality_status_4h']},"
            f"{row['quality_status_1h']},"
            f"{row['advice_ts_1h_utc']},"
            f"{row['advice_ts_4h_utc']}"
        )


def _derive_regime_label_4h(row: SelectionRow) -> str | None:
    if row.quality_status_4h == "BLOCKED":
        return None

    if row.selection_state == "BUY_READY":
        return "TREND_UP"

    if row.selection_state == "PREPARE":
        if row.selection_bias in {"BULLISH", "NEUTRAL_POSITIVE"}:
            return "TREND_UP"
        return "RANGE"

    if row.selection_state == "WATCHLIST":
        return "RANGE"

    if row.selection_state == "NEUTRAL":
        return "RANGE"

    return None


def _derive_regime_label_1h(row: SelectionRow) -> str | None:
    if row.quality_status_1h == "BLOCKED":
        return None

    if row.selection_state in {"BUY_READY", "PREPARE"}:
        return "TREND_UP"

    if row.selection_state == "WATCHLIST":
        return "RANGE"

    return None


def _derive_advice_state_4h(row: SelectionRow) -> str | None:
    if row.selection_state == "BUY_READY":
        return "ENTER_LONG"
    if row.selection_state == "PREPARE":
        return "PREPARE"
    if row.selection_state == "WATCHLIST":
        return "WATCH"
    return "NO_ACTION"


def _derive_advice_state_1h(row: SelectionRow) -> str | None:
    if row.quality_status_1h == "BLOCKED":
        return "NO_ACTION"
    if row.selection_state == "BUY_READY":
        return "ENTRY_REFINEMENT"
    if row.selection_state == "PREPARE":
        return "WATCH"
    return "NO_ACTION"


def _selection_row_to_db_params(
    row: SelectionRow,
    *,
    run_asof_ts_utc: datetime,
    engine_name: str,
    engine_version: str,
) -> tuple[Any, ...]:
    regime_label_1h = _derive_regime_label_1h(row)
    regime_label_4h = _derive_regime_label_4h(row)
    advice_state_1h = _derive_advice_state_1h(row)
    advice_state_4h = _derive_advice_state_4h(row)

    return (
        row.asset_id,
        row.venue,
        run_asof_ts_utc,
        row.advice_ts_1h_utc,
        row.advice_ts_4h_utc,
        row.selection_state,
        row.selection_bias,
        row.selection_score,
        regime_label_1h,
        regime_label_4h,
        advice_state_1h,
        advice_state_4h,
        None,
        None,
        None,
        None,
        row.priority_rank,
        row.summary,
        engine_name,
        engine_version,
    )


def write_selection_state_rows(
    conn,
    *,
    rows: list[SelectionRow],
    run_asof_ts_utc: datetime,
    engine_name: str,
    engine_version: str,
) -> int:
    if not rows:
        return 0

    sql = """
    INSERT INTO selection_state (
        asset_id,
        venue,
        asof_ts_utc,
        advice_ts_1h_utc,
        advice_ts_4h_utc,
        selection_state,
        selection_bias,
        selection_score,
        regime_label_1h,
        regime_label_4h,
        advice_state_1h,
        advice_state_4h,
        opportunity_score_1h,
        opportunity_score_4h,
        risk_score_1h,
        risk_score_4h,
        priority_rank,
        summary_text,
        engine_name,
        engine_version
    ) VALUES (
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s
    )
    ON DUPLICATE KEY UPDATE
        advice_ts_1h_utc = VALUES(advice_ts_1h_utc),
        advice_ts_4h_utc = VALUES(advice_ts_4h_utc),
        selection_state = VALUES(selection_state),
        selection_bias = VALUES(selection_bias),
        selection_score = VALUES(selection_score),
        regime_label_1h = VALUES(regime_label_1h),
        regime_label_4h = VALUES(regime_label_4h),
        advice_state_1h = VALUES(advice_state_1h),
        advice_state_4h = VALUES(advice_state_4h),
        opportunity_score_1h = VALUES(opportunity_score_1h),
        opportunity_score_4h = VALUES(opportunity_score_4h),
        risk_score_1h = VALUES(risk_score_1h),
        risk_score_4h = VALUES(risk_score_4h),
        priority_rank = VALUES(priority_rank),
        summary_text = VALUES(summary_text),
        engine_name = VALUES(engine_name),
        engine_version = VALUES(engine_version)
    """

    params = [
        _selection_row_to_db_params(
            row,
            run_asof_ts_utc=run_asof_ts_utc,
            engine_name=engine_name,
            engine_version=engine_version,
        )
        for row in rows
    ]

    with conn.cursor() as cur:
        cur.executemany(sql, params)

    conn.commit()
    return len(rows)


def main() -> int:
    args = parse_args()

    if args.dry_run and args.write_db:
        raise ValueError("--dry-run and --write-db are mutually exclusive")

    config = load_selection_config(args.config)

    conn = get_connection()
    try:
        candidates = fetch_selection_candidates(
            conn,
            venue=args.venue,
            asset_id=args.asset_id,
            limit=args.limit,
        )

        rows = rank_candidates(candidates, config)

        if not rows:
            print("[DONE] no selection rows")
            return 0

        printable_rows: list[dict[str, Any]] = [asdict(row) for row in rows]
        _print_rows(printable_rows)

        if args.out_csv:
            write_csv(args.out_csv, printable_rows)
            print(f"[DONE] wrote csv -> {args.out_csv}")

        if args.dry_run:
            print("[DONE] dry-run complete")
            return 0

        if args.write_db:
            run_asof_ts_utc = datetime.now(UTC).replace(tzinfo=None)
            written = write_selection_state_rows(
                conn,
                rows=rows,
                run_asof_ts_utc=run_asof_ts_utc,
                engine_name=str(args.engine_name),
                engine_version=str(args.engine_version),
            )
            print(
                "[DONE] wrote selection_state rows "
                f"count={written} asof_ts_utc={run_asof_ts_utc.isoformat(sep=' ')} "
                f"engine={args.engine_name} version={args.engine_version}"
            )
            return 0

        print("[DONE] engine evaluation complete (no DB write yet)")
        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
