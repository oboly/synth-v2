from __future__ import annotations

import argparse
from typing import Any

from src.common.db import get_connection


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Breathline/A+ research report from derived views."
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist cluster and divergence snapshots into research tables.",
    )
    return parser.parse_args()


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


def _print_table(title: str, rows: list[dict[str, Any]]) -> None:
    print()
    print(f"=== {title} ===")

    if not rows:
        print("(no rows)")
        return

    columns = list(rows[0].keys())
    print("\t".join(columns))

    for row in rows:
        print("\t".join("" if row.get(col) is None else str(row.get(col)) for col in columns))


def _print_report(conn) -> None:
    report_queries = [
        (
            "LATEST BREATHLINE SNAPSHOTS",
            """
            SELECT
                prediction_ts_utc,
                COUNT(*) AS token_count,
                MIN(run_count) AS min_run_count,
                MAX(run_count) AS max_run_count,
                ROUND(AVG(token_consistency_score), 4) AS avg_consistency
            FROM breathline_token_consistency
            GROUP BY prediction_ts_utc
            ORDER BY prediction_ts_utc DESC
            LIMIT 10
            """,
        ),
        (
            "CLASS PERFORMANCE 4H",
            """
            SELECT
                aplus_final_class,
                COUNT(*) AS n,
                ROUND(AVG(return_4h), 6) AS avg_return_4h,
                ROUND(SUM(CASE WHEN return_4h > 0 THEN 1 ELSE 0 END) / COUNT(*), 4) AS winrate_4h
            FROM vw_aplus_research_with_returns
            WHERE return_4h IS NOT NULL
            GROUP BY aplus_final_class
            ORDER BY avg_return_4h DESC, aplus_final_class ASC
            """,
        ),
        (
            "LEADER AVOID CONFLICT 4H",
            """
            SELECT
                leader_avoid_conflict,
                COUNT(*) AS n,
                ROUND(AVG(return_4h), 6) AS avg_return_4h,
                ROUND(SUM(CASE WHEN return_4h > 0 THEN 1 ELSE 0 END) / COUNT(*), 4) AS winrate_4h
            FROM vw_aplus_research_with_returns
            WHERE return_4h IS NOT NULL
            GROUP BY leader_avoid_conflict
            ORDER BY leader_avoid_conflict DESC
            """,
        ),
        (
            "HIGH CONSISTENCY 4H",
            """
            SELECT
                high_consistency,
                COUNT(*) AS n,
                ROUND(AVG(return_4h), 6) AS avg_return_4h,
                ROUND(SUM(CASE WHEN return_4h > 0 THEN 1 ELSE 0 END) / COUNT(*), 4) AS winrate_4h
            FROM vw_aplus_research_with_returns
            WHERE return_4h IS NOT NULL
            GROUP BY high_consistency
            ORDER BY high_consistency DESC
            """,
        ),
        (
            "DIVERGENCE SUMMARY 4H",
            """
            SELECT
                divergence_flag,
                COUNT(*) AS n,
                ROUND(AVG(return_4h), 6) AS avg_return_4h,
                ROUND(SUM(CASE WHEN return_4h > 0 THEN 1 ELSE 0 END) / COUNT(*), 4) AS winrate_4h
            FROM vw_aplus_divergence
            WHERE return_4h IS NOT NULL
            GROUP BY divergence_flag
            ORDER BY divergence_flag DESC
            """,
        ),
        (
            "REVIEW QUEUE",
            """
            SELECT
                symbol,
                selection_state,
                selection_bias,
                selection_score,
                aplus_final_class,
                token_consistency_score,
                research_bucket,
                review_priority
            FROM vw_selection_breathline_review_queue
            ORDER BY review_priority ASC, selection_score DESC, symbol ASC
            """,
        ),
        (
            "CLUSTERS",
            """
            SELECT
                asof_ts_utc,
                cluster_members,
                cluster_size,
                ROUND(cluster_strength, 4) AS cluster_strength
            FROM vw_aplus_clusters
            ORDER BY asof_ts_utc DESC
            LIMIT 10
            """,
        ),
    ]

    for title, sql in report_queries:
        _print_table(title, _fetch_all(conn, sql))


def _persist_cluster_snapshots(conn) -> int:
    rows = _fetch_all(
        conn,
        """
        SELECT
            asof_ts_utc,
            cluster_members,
            cluster_size,
            cluster_strength
        FROM vw_aplus_clusters
        """,
    )

    if not rows:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO breathline_cluster_snapshot (
                asof_ts_utc,
                cluster_members,
                cluster_size,
                cluster_strength
            ) VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                cluster_members = VALUES(cluster_members),
                cluster_size = VALUES(cluster_size),
                cluster_strength = VALUES(cluster_strength)
            """,
            [
                (
                    row["asof_ts_utc"],
                    row["cluster_members"],
                    row["cluster_size"],
                    row["cluster_strength"],
                )
                for row in rows
            ],
        )

    return len(rows)


def _persist_divergence_log(conn) -> int:
    rows = _fetch_all(
        conn,
        """
        SELECT
            asset_id,
            asof_ts_utc,
            divergence_flag,
            expected_dir,
            realized_dir,
            return_4h
        FROM vw_aplus_divergence
        WHERE return_4h IS NOT NULL
        """,
    )

    if not rows:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO breathline_divergence_log (
                asset_id,
                asof_ts_utc,
                divergence_flag,
                expected_dir,
                realized_dir,
                return_4h
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                divergence_flag = VALUES(divergence_flag),
                expected_dir = VALUES(expected_dir),
                realized_dir = VALUES(realized_dir),
                return_4h = VALUES(return_4h)
            """,
            [
                (
                    row["asset_id"],
                    row["asof_ts_utc"],
                    row["divergence_flag"],
                    row["expected_dir"],
                    row["realized_dir"],
                    row["return_4h"],
                )
                for row in rows
            ],
        )

    return len(rows)


def main() -> None:
    args = _parse_args()

    print("[RUN] Breathline/A+ research report")

    conn = get_connection()
    try:
        _print_report(conn)

        if args.persist:
            cluster_count = _persist_cluster_snapshots(conn)
            divergence_count = _persist_divergence_log(conn)
            conn.commit()

            print()
            print("=== PERSISTED ===")
            print(f"cluster_snapshots={cluster_count}")
            print(f"divergence_rows={divergence_count}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
