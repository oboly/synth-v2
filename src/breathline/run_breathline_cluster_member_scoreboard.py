from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


@dataclass
class MemberStats:
    symbol: str
    appearances: int = 0
    first_seen: Any | None = None
    last_seen: Any | None = None
    active_now: int = 0
    current_streak: int = 0
    latest_aplus_class: str | None = None
    latest_selection_state: str | None = None
    latest_selection_bias: str | None = None
    latest_selection_score: Any | None = None
    latest_research_bucket: str | None = None
    n_24h: int = 0
    avg_24h: Any | None = None
    winrate_24h: Any | None = None
    n_72h: int = 0
    avg_72h: Any | None = None
    winrate_72h: Any | None = None
    n_168h: int = 0
    avg_168h: Any | None = None
    winrate_168h: Any | None = None


def _fetch_all(conn, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description or []]

    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(row)
        else:
            out.append(dict(zip(columns, row, strict=False)))
    return out


def _parse_members(raw_members: str | None) -> set[str]:
    if not raw_members:
        return set()

    return {
        item.strip()
        for item in raw_members.split(",")
        if item.strip()
    }


def _fmt(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, Decimal):
        return f"{float(value):.6f}"

    if isinstance(value, float):
        return f"{value:.6f}"

    return str(value)


def _load_cluster_snapshots(conn) -> list[dict[str, Any]]:
    rows = _fetch_all(
        conn,
        """
        SELECT
            asof_ts_utc AS prediction_ts,
            cluster_members,
            cluster_size,
            cluster_strength
        FROM vw_aplus_clusters
        ORDER BY asof_ts_utc ASC
        """,
    )

    for row in rows:
        row["members"] = _parse_members(row["cluster_members"])

    return rows


def _load_latest_context(conn) -> dict[str, dict[str, Any]]:
    rows = _fetch_all(
        conn,
        """
        SELECT
            d.symbol,
            d.aplus_final_class,
            d.selection_state,
            d.selection_bias,
            d.selection_score,
            q.research_bucket
        FROM vw_aplus_research_dataset d
        LEFT JOIN vw_selection_breathline_review_queue q
          ON q.symbol = d.symbol
        WHERE d.aplus_prediction_ts_utc = (
            SELECT MAX(aplus_prediction_ts_utc)
            FROM vw_aplus_research_dataset
        )
        """,
    )

    return {row["symbol"]: row for row in rows}


def _load_member_return_stats(conn) -> dict[str, dict[str, Any]]:
    rows = _fetch_all(
        conn,
        """
        SELECT
            symbol,

            COUNT(return_24h) AS n_24h,
            ROUND(AVG(return_24h), 6) AS avg_24h,
            ROUND(
                SUM(CASE WHEN return_24h > 0 THEN 1 ELSE 0 END)
                / NULLIF(COUNT(return_24h), 0),
                4
            ) AS winrate_24h,

            COUNT(return_72h) AS n_72h,
            ROUND(AVG(return_72h), 6) AS avg_72h,
            ROUND(
                SUM(CASE WHEN return_72h > 0 THEN 1 ELSE 0 END)
                / NULLIF(COUNT(return_72h), 0),
                4
            ) AS winrate_72h,

            COUNT(return_168h) AS n_168h,
            ROUND(AVG(return_168h), 6) AS avg_168h,
            ROUND(
                SUM(CASE WHEN return_168h > 0 THEN 1 ELSE 0 END)
                / NULLIF(COUNT(return_168h), 0),
                4
            ) AS winrate_168h

        FROM vw_aplus_research_with_returns
        WHERE aplus_final_class IN ('LEADER', 'ANCHOR')
          AND token_consistency_score >= 0.94
        GROUP BY symbol
        """,
    )

    return {row["symbol"]: row for row in rows}


def _build_scoreboard(
    snapshots: list[dict[str, Any]],
    latest_context: dict[str, dict[str, Any]],
    return_stats: dict[str, dict[str, Any]],
) -> list[MemberStats]:
    members_seen: dict[str, MemberStats] = {}

    for snap in snapshots:
        prediction_ts = snap["prediction_ts"]
        for symbol in snap["members"]:
            if symbol not in members_seen:
                members_seen[symbol] = MemberStats(symbol=symbol)
                members_seen[symbol].first_seen = prediction_ts

            stats = members_seen[symbol]
            stats.appearances += 1
            stats.last_seen = prediction_ts

    latest_members = snapshots[-1]["members"] if snapshots else set()

    for symbol, stats in members_seen.items():
        stats.active_now = 1 if symbol in latest_members else 0

        streak = 0
        for snap in reversed(snapshots):
            if symbol in snap["members"]:
                streak += 1
            else:
                break
        stats.current_streak = streak

        ctx = latest_context.get(symbol, {})
        stats.latest_aplus_class = ctx.get("aplus_final_class")
        stats.latest_selection_state = ctx.get("selection_state")
        stats.latest_selection_bias = ctx.get("selection_bias")
        stats.latest_selection_score = ctx.get("selection_score")
        stats.latest_research_bucket = ctx.get("research_bucket")

        perf = return_stats.get(symbol, {})
        stats.n_24h = int(perf.get("n_24h") or 0)
        stats.avg_24h = perf.get("avg_24h")
        stats.winrate_24h = perf.get("winrate_24h")
        stats.n_72h = int(perf.get("n_72h") or 0)
        stats.avg_72h = perf.get("avg_72h")
        stats.winrate_72h = perf.get("winrate_72h")
        stats.n_168h = int(perf.get("n_168h") or 0)
        stats.avg_168h = perf.get("avg_168h")
        stats.winrate_168h = perf.get("winrate_168h")

    return sorted(
        members_seen.values(),
        key=lambda item: (
            -item.active_now,
            -item.current_streak,
            -item.appearances,
            -(float(item.avg_72h) if item.avg_72h is not None else -999.0),
            item.symbol,
        ),
    )


def _print_scoreboard(scoreboard: list[MemberStats]) -> None:
    print("[RUN] Breathline cluster member scoreboard")
    print("[INFO] Source views: vw_aplus_clusters, vw_aplus_research_with_returns")
    print("[INFO] Read-only report; no DB writes")

    print()
    print("=== CLUSTER MEMBER SCOREBOARD ===")
    columns = [
        "symbol",
        "active_now",
        "appearances",
        "current_streak",
        "first_seen",
        "last_seen",
        "latest_aplus_class",
        "selection_state",
        "selection_bias",
        "selection_score",
        "research_bucket",
        "n_24h",
        "avg_24h",
        "winrate_24h",
        "n_72h",
        "avg_72h",
        "winrate_72h",
        "n_168h",
        "avg_168h",
        "winrate_168h",
    ]

    print("\t".join(columns))

    for row in scoreboard:
        values = [
            row.symbol,
            row.active_now,
            row.appearances,
            row.current_streak,
            row.first_seen,
            row.last_seen,
            row.latest_aplus_class,
            row.latest_selection_state,
            row.latest_selection_bias,
            row.latest_selection_score,
            row.latest_research_bucket,
            row.n_24h,
            row.avg_24h,
            row.winrate_24h,
            row.n_72h,
            row.avg_72h,
            row.winrate_72h,
            row.n_168h,
            row.avg_168h,
            row.winrate_168h,
        ]

        print("\t".join(_fmt(value) for value in values))

    print()
    print("=== CURRENT ACTIVE CORE ===")
    active = [row for row in scoreboard if row.active_now == 1]
    core = [row for row in active if row.current_streak >= 4]
    print(",".join(row.symbol for row in core) if core else "-")

    print()
    print("=== CURRENT NEWER MEMBERS ===")
    newer = [row for row in active if row.current_streak < 4]
    print(",".join(row.symbol for row in newer) if newer else "-")

    print()
    print("=== ROTATED OUT ===")
    inactive = [row for row in scoreboard if row.active_now == 0]
    print(",".join(row.symbol for row in inactive) if inactive else "-")


def main() -> None:
    conn = get_connection()
    try:
        snapshots = _load_cluster_snapshots(conn)
        latest_context = _load_latest_context(conn)
        return_stats = _load_member_return_stats(conn)

        scoreboard = _build_scoreboard(
            snapshots=snapshots,
            latest_context=latest_context,
            return_stats=return_stats,
        )

        _print_scoreboard(scoreboard)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
