from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_db_connection


ENGINE_NAME = "selection_engine"
ENGINE_VERSION = "1.1"
RANKING_VERSION = "v2"
STRUCTURE_ENGINE_NAME = "structure_state_engine"
STRUCTURE_ENGINE_VERSION = "1.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Synth selection engine from ranking + structure states"
    )
    parser.add_argument("--ranking-version", default=RANKING_VERSION)
    return parser.parse_args()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fetch_ranking_rows(conn, *, ranking_version: str) -> list[dict[str, Any]]:
    sql = """
    SELECT
        symbol,
        asset_class,
        sector,
        asset_id,
        venue,
        interval_code,
        asof_ts_utc,
        trade_quality_score,
        rotation_bucket,
        classification_code,
        sleeve_fit_code
    FROM vw_ranking_latest
    WHERE ranking_version = %s
      AND interval_code IN ('1h', '4h', '1d')
    ORDER BY symbol, interval_code
    """

    with conn.cursor() as cur:
        cur.execute(sql, (ranking_version,))
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows")
        out.append(row)
    return out


def fetch_latest_advice_rows(conn) -> list[dict[str, Any]]:
    sql = """
    WITH latest_per_interval AS (
        SELECT
            interval_code,
            MAX(asof_ts_utc) AS max_ts
        FROM advice_state
        WHERE interval_code IN ('1h', '4h')
        GROUP BY interval_code
    )
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
    JOIN latest_per_interval l
      ON a.interval_code = l.interval_code
     AND a.asof_ts_utc = l.max_ts
    WHERE a.interval_code IN ('1h', '4h')
    """

    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows")
        out.append(row)
    return out


def fetch_structure_rows(conn) -> list[dict[str, Any]]:
    sql = """
    SELECT
        asset_id,
        venue,
        interval_code,
        asof_ts_utc,
        trend_state,
        pullback_state,
        reclaim_state,
        trend_score,
        pullback_score,
        reclaim_score
    FROM vw_structure_state_latest
    WHERE engine_name = %s
      AND engine_version = %s
      AND interval_code IN ('1h', '4h', '1d')
    ORDER BY asset_id, interval_code
    """

    with conn.cursor() as cur:
        cur.execute(sql, (STRUCTURE_ENGINE_NAME, STRUCTURE_ENGINE_VERSION))
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows")
        out.append(row)
    return out


def group_by_asset(rows: list[dict[str, Any]]) -> dict[int, dict[str, dict[str, Any]]]:
    grouped: dict[int, dict[str, dict[str, Any]]] = {}
    for row in rows:
        asset_id = int(row["asset_id"])
        interval_code = str(row["interval_code"])
        grouped.setdefault(asset_id, {})
        grouped[asset_id][interval_code] = row
    return grouped


def derive_selection_state(
    row_4h_rank: dict[str, Any] | None,
    row_1h_rank: dict[str, Any] | None,
    row_1d_rank: dict[str, Any] | None,
    row_4h_struct: dict[str, Any] | None,
    row_1h_struct: dict[str, Any] | None,
    row_1d_struct: dict[str, Any] | None,
) -> str:
    c4h = str((row_4h_rank or {}).get("classification_code") or "")
    c1h = str((row_1h_rank or {}).get("classification_code") or "")
    c1d = str((row_1d_rank or {}).get("classification_code") or "")
    asset_class = str((row_4h_rank or row_1h_rank or row_1d_rank or {}).get("asset_class") or "")

    trend_4h = str((row_4h_struct or {}).get("trend_state") or "")
    pullback_1h = str((row_1h_struct or {}).get("pullback_state") or "")
    reclaim_4h = str((row_4h_struct or {}).get("reclaim_state") or "")
    reclaim_1d = str((row_1d_struct or {}).get("reclaim_state") or "")

    if asset_class == "MEME":
        return "TACTICAL_ONLY"

    if (
        c4h in {"LEADER", "CONTINUATION_CANDIDATE"}
        and c1h == "CONTINUATION_CANDIDATE"
        and trend_4h in {"UPTREND_STRONG", "UPTREND_WEAK"}
    ):
        return "BUY_READY"

    if (
        c4h in {"LEADER", "CONTINUATION_CANDIDATE"}
        and (
            c1h == "PULLBACK_WATCH"
            or pullback_1h == "HEALTHY_PULLBACK"
            or reclaim_4h in {"RECLAIM_ATTEMPT", "RECLAIM_CONFIRMED"}
        )
    ):
        return "PREPARE"

    if (
        c4h == "PULLBACK_WATCH"
        or reclaim_4h in {"RECLAIM_ATTEMPT", "RECLAIM_CONFIRMED"}
        or reclaim_1d in {"RECLAIM_ATTEMPT", "RECLAIM_CONFIRMED"}
    ):
        return "WATCHLIST"

    if c4h in {"RANGE_TRADER", "SPECULATIVE_HIGH_BETA"}:
        return "TACTICAL_ONLY"

    if c1d == "PULLBACK_WATCH":
        return "WATCHLIST"

    return "AVOID"


def derive_selection_bias(selection_state: str) -> str:
    return {
        "BUY_READY": "BULLISH",
        "PREPARE": "BULLISH",
        "WATCHLIST": "NEUTRAL_POSITIVE",
        "TACTICAL_ONLY": "TACTICAL",
        "AVOID": "DEFENSIVE",
    }.get(selection_state, "DEFENSIVE")


def compute_selection_score(
    row_4h_rank: dict[str, Any] | None,
    row_1h_rank: dict[str, Any] | None,
    row_1d_rank: dict[str, Any] | None,
    row_4h_struct: dict[str, Any] | None,
    row_1h_struct: dict[str, Any] | None,
    row_1d_struct: dict[str, Any] | None,
    selection_state: str,
) -> Decimal:
    score_4h = _to_decimal((row_4h_rank or {}).get("trade_quality_score"), "0")
    score_1h = _to_decimal((row_1h_rank or {}).get("trade_quality_score"), "0")
    score_1d = _to_decimal((row_1d_rank or {}).get("trade_quality_score"), "0")

    trend_score_4h = _to_decimal((row_4h_struct or {}).get("trend_score"), "0")
    pullback_score_1h = _to_decimal((row_1h_struct or {}).get("pullback_score"), "0")
    reclaim_score_4h = _to_decimal((row_4h_struct or {}).get("reclaim_score"), "0")
    reclaim_score_1d = _to_decimal((row_1d_struct or {}).get("reclaim_score"), "0")

    score = (
        Decimal("0.45") * score_4h
        + Decimal("0.25") * score_1h
        + Decimal("0.10") * score_1d
        + Decimal("0.10") * trend_score_4h
        + Decimal("0.05") * pullback_score_1h
        + Decimal("0.03") * reclaim_score_4h
        + Decimal("0.02") * reclaim_score_1d
    )

    state_bonus = {
        "BUY_READY": Decimal("0.12"),
        "PREPARE": Decimal("0.08"),
        "WATCHLIST": Decimal("0.03"),
        "TACTICAL_ONLY": Decimal("-0.02"),
        "AVOID": Decimal("-0.10"),
    }.get(selection_state, Decimal("0"))

    return (score + state_bonus).quantize(Decimal("0.000001"))


def build_summary(
    symbol: str,
    selection_state: str,
    row_4h_rank: dict[str, Any] | None,
    row_1h_rank: dict[str, Any] | None,
    row_1d_rank: dict[str, Any] | None,
    row_4h_struct: dict[str, Any] | None,
    row_1h_struct: dict[str, Any] | None,
    row_1d_struct: dict[str, Any] | None,
) -> str:
    c4h = str((row_4h_rank or {}).get("classification_code") or "-")
    c1h = str((row_1h_rank or {}).get("classification_code") or "-")
    c1d = str((row_1d_rank or {}).get("classification_code") or "-")

    t4h = str((row_4h_struct or {}).get("trend_state") or "-")
    p1h = str((row_1h_struct or {}).get("pullback_state") or "-")
    r4h = str((row_4h_struct or {}).get("reclaim_state") or "-")
    r1d = str((row_1d_struct or {}).get("reclaim_state") or "-")

    return (
        f"{symbol}; selection_state={selection_state}; "
        f"rank[4h={c4h},1h={c1h},1d={c1d}]; "
        f"struct[4h_trend={t4h},1h_pullback={p1h},4h_reclaim={r4h},1d_reclaim={r1d}]"
    )[:512]


def upsert_selection_rows(conn, rows: list[dict[str, Any]]) -> int:
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
        %(asset_id)s,
        %(venue)s,
        %(asof_ts_utc)s,
        %(advice_ts_1h_utc)s,
        %(advice_ts_4h_utc)s,
        %(selection_state)s,
        %(selection_bias)s,
        %(selection_score)s,
        %(regime_label_1h)s,
        %(regime_label_4h)s,
        %(advice_state_1h)s,
        %(advice_state_4h)s,
        %(opportunity_score_1h)s,
        %(opportunity_score_4h)s,
        %(risk_score_1h)s,
        %(risk_score_4h)s,
        %(priority_rank)s,
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

    with conn.cursor() as cur:
        cur.executemany(sql, rows)

    conn.commit()
    return len(rows)


def run(*, ranking_version: str) -> int:
    conn = get_db_connection()

    try:
        ranking_rows = fetch_ranking_rows(conn, ranking_version=ranking_version)
        advice_rows = fetch_latest_advice_rows(conn)
        structure_rows = fetch_structure_rows(conn)

        ranking_by_asset = group_by_asset(ranking_rows)
        advice_by_asset = group_by_asset(advice_rows)
        structure_by_asset = group_by_asset(structure_rows)

        if not ranking_by_asset:
            print("[WARN] no ranking rows found")
            return 0

        asof_ts = None
        for by_tf in ranking_by_asset.values():
            if "4h" in by_tf:
                asof_ts = by_tf["4h"]["asof_ts_utc"]
                break
        if asof_ts is None:
            for by_tf in ranking_by_asset.values():
                for row in by_tf.values():
                    asof_ts = row["asof_ts_utc"]
                    break
                if asof_ts is not None:
                    break

        asof_ts = _ensure_utc(asof_ts)
        if asof_ts is None:
            print("[WARN] no ranking snapshot timestamp found")
            return 0

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

        state_bias = {
            "BUY_READY": 5,
            "PREPARE": 4,
            "WATCHLIST": 3,
            "TACTICAL_ONLY": 2,
            "AVOID": 1,
        }

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

        written = upsert_selection_rows(conn, out_rows)
        print(
            f"[DONE] selection rows={written} "
            f"engine={ENGINE_NAME} version={ENGINE_VERSION} "
            f"asof_ts_utc={asof_ts.isoformat()}"
        )
        return written

    finally:
        conn.close()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(run(ranking_version=args.ranking_version))
