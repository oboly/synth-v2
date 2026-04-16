from __future__ import annotations

import argparse
from typing import Any

from src.common.db import get_db_connection


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run extended trade report from vw_selection_enriched"
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--min-priority-rank", type=int, default=None)
    parser.add_argument("--selection-state", default=None)
    return parser.parse_args()


def fetch_rows(
    conn,
    *,
    limit: int,
    min_priority_rank: int | None,
    selection_state: str | None,
) -> list[dict[str, Any]]:
    where = ["1=1"]
    params: list[Any] = []

    if min_priority_rank is not None:
        where.append("v.priority_rank >= %s")
        params.append(min_priority_rank)

    if selection_state:
        where.append("v.selection_state = %s")
        params.append(selection_state)

    where_sql = " AND ".join(where)

    sql = f"""
    SELECT
        v.asset_id,
        a.symbol,
        v.venue,
        v.selection_asof_ts_utc,
        v.selection_state,
        v.selection_bias,
        v.selection_score,
        v.priority_rank,

        v.ranking_version,
        v.ranking_4h_asof_ts_utc,
        v.ranking_final_rank_4h,
        v.trade_quality_score,
        v.relative_strength_score,
        v.context_score,
        v.pullback_quality_score,
        v.expansion_position_score,
        v.signal_confidence_score,
        v.rotation_bucket,
        v.classification_code,
        v.sleeve_fit_code,

        v.advice_1h_asof_ts_utc,
        v.advice_regime_label_1h,
        v.time_horizon_hint_1h,
        v.advice_state_latest_1h,
        v.regime_fit_score_1h,
        v.advice_opportunity_score_1h,
        v.advice_risk_score_1h,
        v.advice_priority_rank_1h,

        v.advice_4h_asof_ts_utc,
        v.advice_regime_label_4h,
        v.time_horizon_hint_4h,
        v.advice_state_latest_4h,
        v.regime_fit_score_4h,
        v.advice_opportunity_score_4h,
        v.advice_risk_score_4h,
        v.advice_priority_rank_4h,

        v.trend_state_1h,
        v.pullback_state_1h,
        v.reclaim_state_1h,
        v.trend_score_1h,
        v.pullback_score_1h,
        v.reclaim_score_1h,

        v.trend_state_4h,
        v.pullback_state_4h,
        v.reclaim_state_4h,
        v.trend_score_4h,
        v.pullback_score_4h,
        v.reclaim_score_4h,

        v.trend_state_1d,
        v.pullback_state_1d,
        v.reclaim_state_1d,
        v.trend_score_1d,
        v.pullback_score_1d,
        v.reclaim_score_1d,

        v.has_4h_trend_support,
        v.has_1h_pullback_timing,
        v.has_4h_reclaim_signal,
        v.has_1d_reclaim_signal,
        v.has_any_reclaim_signal,
        v.is_structure_aligned_minimal,
        v.is_structure_conflicted,
        v.selection_age_minutes

    FROM vw_selection_enriched v
    LEFT JOIN asset a
        ON a.asset_id = v.asset_id

    WHERE {where_sql}
    ORDER BY
        v.priority_rank ASC,
        v.selection_score DESC,
        v.asset_id ASC
    LIMIT %s
    """

    params.append(limit)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from database cursor")
        out.append(row)

    return out


def fmt(value: Any, width: int | None = None) -> str:
    if value is None:
        s = "-"
    elif isinstance(value, float):
        s = f"{value:.6f}"
    else:
        s = str(value)

    if width is None:
        return s
    return s.ljust(width)


def derive_technical_action_hint(row: dict[str, Any]) -> str:
    selection_state = str(row["selection_state"])
    has_trend = int(row["has_4h_trend_support"] or 0) == 1
    has_pullback = int(row["has_1h_pullback_timing"] or 0) == 1
    has_reclaim = int(row["has_any_reclaim_signal"] or 0) == 1
    aligned = int(row["is_structure_aligned_minimal"] or 0) == 1
    conflicted = int(row["is_structure_conflicted"] or 0) == 1

    if conflicted:
        return "NO_TRADE"

    if selection_state == "AVOID":
        return "NO_TRADE"

    if selection_state == "TACTICAL_ONLY":
        if has_pullback:
            return "TACTICAL_PULLBACK_SETUP"
        return "TACTICAL_ONLY"

    if aligned:
        return "STRUCTURAL_LONG_CANDIDATE"

    if selection_state in {"BUY_READY", "PREPARE"}:
        if has_trend and has_pullback and not has_reclaim:
            return "WAIT_FOR_RECLAIM"
        if has_trend and not has_pullback and has_reclaim:
            return "WAIT_FOR_PULLBACK"
        if has_trend and has_pullback:
            return "STRUCTURE_BUILDING"
        if has_trend:
            return "STRUCTURAL_WATCH"
        return "WATCH"

    if selection_state == "WATCHLIST":
        if has_trend and has_reclaim:
            return "WATCH_RECLAIM"
        if has_trend and has_pullback:
            return "WATCH_PULLBACK"
        if has_trend:
            return "WATCH_TREND"
        return "WATCH"

    return "UNDEFINED"


def print_header(title: str) -> None:
    print()
    print(title)
    print("=" * len(title))


def print_summary(rows: list[dict[str, Any]]) -> None:
    counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}

    for row in rows:
        state_key = str(row["selection_state"])
        counts[state_key] = counts.get(state_key, 0) + 1

        action_key = derive_technical_action_hint(row)
        action_counts[action_key] = action_counts.get(action_key, 0) + 1

    print_header("EXTENDED TRADE REPORT — SUMMARY")
    print(f"rows: {len(rows)}")

    print()
    print("selection_state distribution:")
    for key in sorted(counts.keys()):
        print(f"  {key}: {counts[key]}")

    print()
    print("technical_action_hint distribution:")
    for key in sorted(action_counts.keys()):
        print(f"  {key}: {action_counts[key]}")


def print_compact_table(rows: list[dict[str, Any]]) -> None:
    print_header("TOP SELECTIONS — COMPACT")

    headers = [
        fmt("asset", 16),
        fmt("state", 14),
        fmt("hint", 26),
        fmt("bias", 18),
        fmt("score", 10),
        fmt("rank", 6),
        fmt("r4h", 6),
        fmt("t4h", 16),
        fmt("pb1h", 18),
        fmt("rc4h", 18),
        fmt("rc1d", 18),
        fmt("align", 6),
        fmt("conf", 5),
    ]
    print(" | ".join(headers))
    print("-" * (sum(len(h) for h in headers) + 3 * (len(headers) - 1)))

    for row in rows:
        hint = derive_technical_action_hint(row)
        asset_label = f"{row.get('symbol') or '?'}({row['asset_id']})"

        print(
            " | ".join(
                [
                    fmt(asset_label, 16),
                    fmt(row["selection_state"], 14),
                    fmt(hint, 26),
                    fmt(row["selection_bias"], 18),
                    fmt(row["selection_score"], 10),
                    fmt(row["priority_rank"], 6),
                    fmt(row["ranking_final_rank_4h"], 6),
                    fmt(row["trend_state_4h"], 16),
                    fmt(row["pullback_state_1h"], 18),
                    fmt(row["reclaim_state_4h"], 18),
                    fmt(row["reclaim_state_1d"], 18),
                    fmt(row["is_structure_aligned_minimal"], 6),
                    fmt(row["is_structure_conflicted"], 5),
                ]
            )
        )


def print_detailed_sections(rows: list[dict[str, Any]]) -> None:
    print_header("DETAILED SECTIONS")

    for row in rows:
        hint = derive_technical_action_hint(row)
        asset_label = f"{row.get('symbol') or '?'}({row['asset_id']})"

        print(
            f"[{asset_label}] "
            f"{row['selection_state']} / {row['selection_bias']} / "
            f"score={fmt(row['selection_score'])} / priority={fmt(row['priority_rank'])}"
        )

        print(f"  hint: {hint}")

        print(
            f"  ranking: version={fmt(row['ranking_version'])} "
            f"rank_4h={fmt(row['ranking_final_rank_4h'])} "
            f"trade_q={fmt(row['trade_quality_score'])} "
            f"rs={fmt(row['relative_strength_score'])} "
            f"context={fmt(row['context_score'])} "
            f"signal_conf={fmt(row['signal_confidence_score'])}"
        )

        print(
            f"  advice: 1h={fmt(row['advice_state_latest_1h'])} "
            f"(opp={fmt(row['advice_opportunity_score_1h'])}, "
            f"risk={fmt(row['advice_risk_score_1h'])}) | "
            f"4h={fmt(row['advice_state_latest_4h'])} "
            f"(opp={fmt(row['advice_opportunity_score_4h'])}, "
            f"risk={fmt(row['advice_risk_score_4h'])})"
        )

        print(
            f"  structure: "
            f"1h[t={fmt(row['trend_state_1h'])}, pb={fmt(row['pullback_state_1h'])}, rc={fmt(row['reclaim_state_1h'])}] "
            f"4h[t={fmt(row['trend_state_4h'])}, pb={fmt(row['pullback_state_4h'])}, rc={fmt(row['reclaim_state_4h'])}] "
            f"1d[t={fmt(row['trend_state_1d'])}, pb={fmt(row['pullback_state_1d'])}, rc={fmt(row['reclaim_state_1d'])}]"
        )

        print(
            f"  flags: "
            f"trend4h={fmt(row['has_4h_trend_support'])} "
            f"pullback1h={fmt(row['has_1h_pullback_timing'])} "
            f"reclaim_any={fmt(row['has_any_reclaim_signal'])} "
            f"aligned={fmt(row['is_structure_aligned_minimal'])} "
            f"conflicted={fmt(row['is_structure_conflicted'])}"
        )

        print(
            f"  meta: "
            f"rotation={fmt(row['rotation_bucket'])} "
            f"classification={fmt(row['classification_code'])} "
            f"sleeve_fit={fmt(row['sleeve_fit_code'])} "
            f"age_min={fmt(row['selection_age_minutes'])}"
        )

        print()


def main() -> int:
    args = parse_args()
    conn = get_db_connection()

    try:
        rows = fetch_rows(
            conn,
            limit=args.limit,
            min_priority_rank=args.min_priority_rank,
            selection_state=args.selection_state,
        )
    finally:
        conn.close()

    if not rows:
        print("No rows found.")
        return 0

    print_summary(rows)
    print_compact_table(rows[: min(len(rows), 25)])
    print_detailed_sections(rows[: min(len(rows), 15)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
