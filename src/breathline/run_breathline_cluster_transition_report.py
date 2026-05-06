from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from src.common.db import get_connection


@dataclass(frozen=True)
class ClusterSnapshot:
    prediction_ts: Any
    members: set[str]
    cluster_size: int
    cluster_strength: Any


def _fetch_all(conn, sql: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql)
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


def _load_snapshots(conn) -> list[ClusterSnapshot]:
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

    snapshots: list[ClusterSnapshot] = []
    for row in rows:
        snapshots.append(
            ClusterSnapshot(
                prediction_ts=row["prediction_ts"],
                members=_parse_members(row["cluster_members"]),
                cluster_size=int(row["cluster_size"]),
                cluster_strength=row["cluster_strength"],
            )
        )

    return snapshots


def _format_members(members: set[str]) -> str:
    if not members:
        return "-"
    return ",".join(sorted(members))


def _print_transition_report(snapshots: list[ClusterSnapshot]) -> None:
    print("[RUN] Breathline cluster transition report")
    print("[INFO] Source view: vw_aplus_clusters")
    print("[INFO] Read-only report; no DB writes")

    print()
    print("=== SNAPSHOT SUMMARY ===")
    print("prediction_ts\tcluster_size\tcluster_strength\tmembers")

    for snap in snapshots:
        print(
            f"{snap.prediction_ts}\t"
            f"{snap.cluster_size}\t"
            f"{snap.cluster_strength}\t"
            f"{_format_members(snap.members)}"
        )

    print()
    print("=== CLUSTER TRANSITIONS ===")

    if len(snapshots) < 2:
        print("(need at least 2 snapshots)")
        return

    print("from_ts\tto_ts\tadded\tremoved\tpersistent\tadded_count\tremoved_count\tpersistent_count")

    for prev, curr in zip(snapshots[:-1], snapshots[1:], strict=False):
        added = curr.members - prev.members
        removed = prev.members - curr.members
        persistent = curr.members & prev.members

        print(
            f"{prev.prediction_ts}\t"
            f"{curr.prediction_ts}\t"
            f"{_format_members(added)}\t"
            f"{_format_members(removed)}\t"
            f"{_format_members(persistent)}\t"
            f"{len(added)}\t"
            f"{len(removed)}\t"
            f"{len(persistent)}"
        )

    latest_prev = snapshots[-2]
    latest = snapshots[-1]
    latest_added = latest.members - latest_prev.members
    latest_removed = latest_prev.members - latest.members
    latest_persistent = latest.members & latest_prev.members

    print()
    print("=== LATEST TRANSITION ===")
    print(f"from_ts: {latest_prev.prediction_ts}")
    print(f"to_ts:   {latest.prediction_ts}")
    print(f"added:   {_format_members(latest_added)}")
    print(f"removed: {_format_members(latest_removed)}")
    print(f"held:    {_format_members(latest_persistent)}")

    print()
    print("=== MEMBER PERSISTENCE ===")
    print("symbol\tappearances\tfirst_seen\tlast_seen\tactive_now\tcurrent_streak")

    appearances: dict[str, int] = defaultdict(int)
    first_seen: dict[str, Any] = {}
    last_seen: dict[str, Any] = {}

    for snap in snapshots:
        for symbol in snap.members:
            appearances[symbol] += 1
            first_seen.setdefault(symbol, snap.prediction_ts)
            last_seen[symbol] = snap.prediction_ts

    all_symbols = sorted(appearances.keys())

    for symbol in all_symbols:
        streak = 0
        for snap in reversed(snapshots):
            if symbol in snap.members:
                streak += 1
            else:
                break

        active_now = 1 if symbol in snapshots[-1].members else 0

        print(
            f"{symbol}\t"
            f"{appearances[symbol]}\t"
            f"{first_seen[symbol]}\t"
            f"{last_seen[symbol]}\t"
            f"{active_now}\t"
            f"{streak}"
        )


def main() -> None:
    conn = get_connection()
    try:
        snapshots = _load_snapshots(conn)
        _print_transition_report(snapshots)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
