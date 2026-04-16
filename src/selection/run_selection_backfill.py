from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_db_connection
from src.selection.run_selection_engine import (
    ENGINE_NAME,
    ENGINE_VERSION,
    STRUCTURE_ENGINE_NAME,
    STRUCTURE_ENGINE_VERSION,
    _ensure_utc,
    build_summary,
    compute_selection_score,
    derive_selection_bias,
    derive_selection_state,
    group_by_asset,
    upsert_selection_rows,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill Synth selection_state from historical ranking/advice/structure snapshots"
    )
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--ranking-version", default="v2")
    parser.add_argument(
        "--limit-snapshots",
        type=int,
        default=None,
        help="Optional cap on number of snapshot timestamps to process.",
    )
    return parser.parse_args()


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _ensure_utc(dt)  # type: ignore[return-value]


def fetch_snapshot_timestamps(
    conn,
    *,
    from_ts: datetime,
    to_ts: datetime,
    ranking_version: str,
    limit_snapshots: int | None,
) -> list[datetime]:
    sql = """
    SELECT DISTINCT rs.asof_ts_utc
    FROM ranking_state rs
    WHERE rs.ranking_version = %s
      AND rs.interval_code IN ('1h', '4h', '1d')
      AND rs.asof_ts_utc >= %s
      AND rs.asof_ts_utc <= %s
    ORDER BY rs.asof_ts_utc
    """

    params: list[Any] = [
        ranking_version,
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
        dt = row["asof_ts_utc"]
        dt = _ensure_utc(dt)
        if dt is None:
            continue
        out.append(dt)
    return out


def fetch_ranking_rows_for_snapshot(
    conn,
    *,
    asof_ts: datetime,
    ranking_version: str,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        a.symbol,
        a.asset_class,
        a.sector,
        rs.asset_id,
        rs.venue,
        rs.interval_code,
        rs.asof_ts_utc,
        rs.trade_quality_score,
        rs.rotation_bucket,
        rs.classification_code,
        rs.sleeve_fit_code
    FROM ranking_state rs
    JOIN asset a
      ON a.asset_id = rs.asset_id
    WHERE rs.ranking_version = %s
      AND rs.interval_code IN ('1h', '4h', '1d')
      AND rs.asof_ts_utc = %s
    ORDER BY a.symbol, rs.interval_code
    """

    with conn.cursor() as cur:
        cur.execute(sql, (ranking_version, asof_ts.replace(tzinfo=None)))
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows")
        out.append(row)
    return out


def fetch_latest_advice_rows_asof(
    conn,
    *,
    asof_ts: datetime,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        a.asset_id,
        a.venue,
        a.interval_code,
        a.asof_ts_utc,
        a.regime_label,
        a.advice_state,
        a.opportunity_score,
        a.risk_score
    FROM advice_state a
    JOIN (
        SELECT
            asset_id,
            venue,
            interval_code,
            MAX(asof_ts_utc) AS max_ts
        FROM advice_state
        WHERE interval_code IN ('1h', '4h')
          AND asof_ts_utc <= %s
        GROUP BY asset_id, venue, interval_code
    ) x
      ON x.asset_id = a.asset_id
     AND x.venue = a.venue
     AND x.interval_code = a.interval_code
     AND x.max_ts = a.asof_ts_utc
    WHERE a.interval_code IN ('1h', '4h')
    """

    with conn.cursor() as cur:
        cur.execute(sql, (asof_ts.replace(tzinfo=None),))
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows")
        out.append(row)
    return out


def fetch_structure_rows_asof(
    conn,
    *,
    asof_ts: datetime,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        s.asset_id,
        s.venue,
        s.interval_code,
        s.asof_ts_utc,
        s.trend_state,
        s.pullback_state,
        s.reclaim_state,
        s.trend_score,
        s.pullback_score,
        s.reclaim_score
    FROM structure_state s
    JOIN (
        SELECT
            asset_id,
            venue,
            interval_code,
            MAX(asof_ts_utc) AS max_ts
        FROM structure_state
        WHERE engine_name = %s
          AND engine_version = %s
          AND interval_code IN ('1h', '4h', '1d')
          AND asof_ts_utc <= %s
        GROUP BY asset_id, venue, interval_code
    ) x
      ON x.asset_id = s.asset_id
     AND x.venue = s.venue
     AND x.interval_code = s.interval_code
     AND x.max_ts = s.asof_ts_utc
    WHERE s.engine_name = %s
      AND s.engine_version = %s
      AND s.interval_code IN ('1h', '4h', '1d')
    """

    params = (
        STRUCTURE_ENGINE_NAME,
        STRUCTURE_ENGINE_VERSION,
        asof_ts.replace(tzinfo=None),
        STRUCTURE_ENGINE_NAME,
        STRUCTURE_ENGINE_VERSION,
    )

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows")
        out.append(row)
    return out


def build_rows_for_snapshot(
    *,
    asof_ts: datetime,
    ranking_rows: list[dict[str, Any]],
    advice_rows: list[dict[str, Any]],
    structure_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ranking_by_asset = group_by_asset(ranking_rows)
    advice_by_asset = group_by_asset(advice_rows)
    structure_by_asset = group_by_asset(structure_rows)

    state_bias = {
        "BUY_READY": 5,
        "PREPARE": 4,
        "WATCHLIST": 3,
        "TACTICAL_ONLY": 2,
        "AVOID": 1,
    }

    out_rows: list[dict[str, Any]] = []

    for asset_id, rank_tf in ranking_by_asset.items():
        row_1h_rank = rank_tf.get("1h")
        row_4h_rank = rank_tf.get("4h")
        row_1d_rank = rank_tf.get("1d")

        advice_1h = advice_by_asset.get(asset_id, {}).get("1h")
        advice_4h = advice_by_asset.get(asset_id, {}).get("4h")

        row_1h_struct = structure_by_asset.get(asset_id, {}).get("1h")
        row_4h_struct = structure_by_asset.get(asset_id, {}).get("4h")
        row_1d_struct = structure_by_asset.get(asset_id, {}).get("1d")

        symbol = str((row_4h_rank or row_1h_rank or row_1d_rank or {}).get("symbol") or f"asset_{asset_id}")
        venue = str((row_4h_rank or row_1h_rank or row_1d_rank or {}).get("venue") or "bitvavo")

        selection_state = derive_selection_state(
            row_4h_rank,
            row_1h_rank,
            row_1d_rank,
            row_4h_struct,
            row_1h_struct,
            row_1d_struct,
        )
        selection_bias = derive_selection_bias(selection_state)
        selection_score = compute_selection_score(
            row_4h_rank,
            row_1h_rank,
            row_1d_rank,
            row_4h_struct,
            row_1h_struct,
            row_1d_struct,
            selection_state,
        )

        out_rows.append(
            {
                "asset_id": asset_id,
                "venue": venue,
                "asof_ts_utc": asof_ts.replace(tzinfo=None),
                "advice_ts_1h_utc": None if advice_1h is None else advice_1h["asof_ts_utc"],
                "advice_ts_4h_utc": None if advice_4h is None else advice_4h["asof_ts_utc"],
                "selection_state": selection_state,
                "selection_bias": selection_bias,
                "selection_score": str(selection_score),
                "regime_label_1h": None if advice_1h is None else advice_1h["regime_label"],
                "regime_label_4h": None if advice_4h is None else advice_4h["regime_label"],
                "advice_state_1h": None if advice_1h is None else advice_1h["advice_state"],
                "advice_state_4h": None if advice_4h is None else advice_4h["advice_state"],
                "opportunity_score_1h": None if advice_1h is None else advice_1h["opportunity_score"],
                "opportunity_score_4h": None if advice_4h is None else advice_4h["opportunity_score"],
                "risk_score_1h": None if advice_1h is None else advice_1h["risk_score"],
                "risk_score_4h": None if advice_4h is None else advice_4h["risk_score"],
                "priority_rank": None,
                "summary_text": build_summary(
                    symbol,
                    selection_state,
                    row_4h_rank,
                    row_1h_rank,
                    row_1d_rank,
                    row_4h_struct,
                    row_1h_struct,
                    row_1d_struct,
                ),
                "engine_name": ENGINE_NAME,
                "engine_version": ENGINE_VERSION,
            }
        )

    out_rows.sort(
        key=lambda r: (
            state_bias.get(r["selection_state"], 0),
            Decimal(r["selection_score"]),
            r["asset_id"],
        ),
        reverse=True,
    )

    for idx, row in enumerate(out_rows, start=1):
        row["priority_rank"] = idx

    return out_rows


def run(
    *,
    from_ts: datetime,
    to_ts: datetime,
    ranking_version: str,
    limit_snapshots: int | None,
) -> int:
    conn = get_db_connection()

    try:
        snapshots = fetch_snapshot_timestamps(
            conn,
            from_ts=from_ts,
            to_ts=to_ts,
            ranking_version=ranking_version,
            limit_snapshots=limit_snapshots,
        )

        if not snapshots:
            print("[WARN] no ranking snapshots found in requested range")
            return 0

        total_written = 0

        for idx, snapshot_ts in enumerate(snapshots, start=1):
            ranking_rows = fetch_ranking_rows_for_snapshot(
                conn,
                asof_ts=snapshot_ts,
                ranking_version=ranking_version,
            )
            if not ranking_rows:
                print(f"[SKIP] snapshot={snapshot_ts.isoformat()} no ranking rows")
                continue

            advice_rows = fetch_latest_advice_rows_asof(conn, asof_ts=snapshot_ts)
            structure_rows = fetch_structure_rows_asof(conn, asof_ts=snapshot_ts)

            out_rows = build_rows_for_snapshot(
                asof_ts=snapshot_ts,
                ranking_rows=ranking_rows,
                advice_rows=advice_rows,
                structure_rows=structure_rows,
            )

            written = upsert_selection_rows(conn, out_rows)
            total_written += written

            print(
                f"[SNAPSHOT] {idx}/{len(snapshots)} "
                f"asof_ts_utc={snapshot_ts.isoformat()} rows={written}"
            )

        print(
            f"[DONE] backfill selection rows={total_written} "
            f"snapshots={len(snapshots)} engine={ENGINE_NAME} version={ENGINE_VERSION}"
        )
        return total_written

    finally:
        conn.close()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(
        run(
            from_ts=_parse_ts(args.from_ts),
            to_ts=_parse_ts(args.to_ts),
            ranking_version=args.ranking_version,
            limit_snapshots=args.limit_snapshots,
        )
    )
