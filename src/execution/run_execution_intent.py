from __future__ import annotations

from typing import Any

from src.common.db import get_db_connection
from src.common.utc import utc_now


EPSILON = 0.0001


def ensure_tables(conn) -> None:
    sql_statements = [
        """
        CREATE TABLE IF NOT EXISTS execution_intent (
          execution_intent_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
          asset_id INT NOT NULL,
          intent_ts_utc DATETIME(6) NOT NULL,

          previous_position_size_pct DECIMAL(6,4) DEFAULT NULL,
          target_position_size_pct DECIMAL(6,4) DEFAULT NULL,
          size_delta_pct DECIMAL(6,4) DEFAULT NULL,

          intent_action VARCHAR(32) DEFAULT NULL,
          intent_priority INT DEFAULT NULL,
          intent_reasoning VARCHAR(512) DEFAULT NULL,

          created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

          PRIMARY KEY (execution_intent_id),
          UNIQUE KEY uq_execution_intent (asset_id, intent_ts_utc),
          KEY ix_execution_intent_action (intent_action, intent_priority),

          CONSTRAINT fk_execution_intent_asset
            FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
        ) ENGINE=InnoDB
        DEFAULT CHARSET=utf8mb4
        COLLATE=utf8mb4_general_ci
        """,
    ]

    with conn.cursor() as cur:
        for sql in sql_statements:
            cur.execute(sql)

    conn.commit()


def fetch_latest_portfolio_snapshot(conn) -> list[dict[str, Any]]:
    sql = """
    SELECT
      p.*
    FROM portfolio_state p
    JOIN (
      SELECT
        asset_id,
        MAX(portfolio_ts_utc) AS max_portfolio_ts_utc
      FROM portfolio_state
      GROUP BY asset_id
    ) latest
      ON latest.asset_id = p.asset_id
     AND latest.max_portfolio_ts_utc = p.portfolio_ts_utc
    ORDER BY p.asset_id
    """

    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from database cursor")
        out.append(row)
    return out


def fetch_previous_portfolio_snapshot_map(conn) -> dict[int, dict[str, Any]]:
    sql = """
    SELECT
      p.*
    FROM portfolio_state p
    JOIN (
      SELECT portfolio_ts_utc
      FROM portfolio_state
      GROUP BY portfolio_ts_utc
      ORDER BY portfolio_ts_utc DESC
      LIMIT 1 OFFSET 1
    ) snap
      ON snap.portfolio_ts_utc = p.portfolio_ts_utc
    """

    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from database cursor")
        out[int(row["asset_id"])] = row
    return out


def classify_intent(previous_size: float, target_size: float, target_action: str) -> tuple[str, int, str]:
    delta = round(target_size - previous_size, 4)

    if target_action == "TARGET_NONE":
        if previous_size > EPSILON:
            return ("CLOSE", 1, "Target position removed; close prior allocation.")
        return ("IGNORE", 6, "No previous or target position.")

    if previous_size <= EPSILON and target_size > EPSILON:
        if target_action == "TARGET_TACTICAL":
            return ("OPEN", 2, "Open new tactical paper position.")
        if target_action == "TARGET_PREPARE":
            return ("OPEN", 3, "Open small prepare/pilot paper position.")
        return ("OPEN", 1, "Open new active paper position.")

    if previous_size > EPSILON and target_size > EPSILON:
        if delta > EPSILON:
            return ("ADD", 2, "Increase existing position toward new target size.")
        if delta < -EPSILON:
            return ("REDUCE", 2, "Reduce existing position toward lower target size.")
        return ("HOLD", 4, "Target size unchanged; hold current position.")

    return ("IGNORE", 6, "No execution change required.")


def upsert_execution_intents(conn, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    sql = """
    INSERT INTO execution_intent (
      asset_id,
      intent_ts_utc,
      previous_position_size_pct,
      target_position_size_pct,
      size_delta_pct,
      intent_action,
      intent_priority,
      intent_reasoning
    ) VALUES (
      %(asset_id)s,
      %(intent_ts_utc)s,
      %(previous_position_size_pct)s,
      %(target_position_size_pct)s,
      %(size_delta_pct)s,
      %(intent_action)s,
      %(intent_priority)s,
      %(intent_reasoning)s
    )
    ON DUPLICATE KEY UPDATE
      previous_position_size_pct = VALUES(previous_position_size_pct),
      target_position_size_pct = VALUES(target_position_size_pct),
      size_delta_pct = VALUES(size_delta_pct),
      intent_action = VALUES(intent_action),
      intent_priority = VALUES(intent_priority),
      intent_reasoning = VALUES(intent_reasoning)
    """

    with conn.cursor() as cur:
        cur.executemany(sql, rows)

    conn.commit()
    return len(rows)


def run() -> int:
    conn = get_db_connection()

    try:
        ensure_tables(conn)

        latest_portfolio = fetch_latest_portfolio_snapshot(conn)
        previous_map = fetch_previous_portfolio_snapshot_map(conn)

        intent_ts_utc = utc_now().replace(tzinfo=None)
        out_rows: list[dict[str, Any]] = []

        for row in latest_portfolio:
            asset_id = int(row["asset_id"])
            target_size = float(row["target_position_size_pct"] or 0.0)
            previous_size = float(previous_map.get(asset_id, {}).get("target_position_size_pct", 0.0) or 0.0)
            target_action = str(row["target_action"])

            intent_action, intent_priority, intent_reasoning = classify_intent(
                previous_size=previous_size,
                target_size=target_size,
                target_action=target_action,
            )

            out_rows.append(
                {
                    "asset_id": asset_id,
                    "intent_ts_utc": intent_ts_utc,
                    "previous_position_size_pct": round(previous_size, 4),
                    "target_position_size_pct": round(target_size, 4),
                    "size_delta_pct": round(target_size - previous_size, 4),
                    "intent_action": intent_action,
                    "intent_priority": intent_priority,
                    "intent_reasoning": intent_reasoning,
                }
            )

        written = upsert_execution_intents(conn, out_rows)
        print(f"[DONE] execution intents={written}")
        return written

    finally:
        conn.close()


if __name__ == "__main__":
    run()
