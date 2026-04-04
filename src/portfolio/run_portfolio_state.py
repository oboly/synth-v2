from __future__ import annotations

from typing import Any

from src.common.db import get_db_connection
from src.common.utc import utc_now


def ensure_tables(conn) -> None:
    sql_statements = [
        """
        CREATE TABLE IF NOT EXISTS portfolio_state (
          portfolio_state_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
          asset_id INT NOT NULL,
          portfolio_ts_utc DATETIME(6) NOT NULL,

          target_action VARCHAR(32) DEFAULT NULL,
          target_position_size_pct DECIMAL(6,4) DEFAULT NULL,
          portfolio_slot INT DEFAULT NULL,
          portfolio_bucket VARCHAR(32) DEFAULT NULL,
          source_risk_action VARCHAR(32) DEFAULT NULL,
          source_decision_action VARCHAR(32) DEFAULT NULL,
          portfolio_reasoning VARCHAR(512) DEFAULT NULL,

          created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

          PRIMARY KEY (portfolio_state_id),
          UNIQUE KEY uq_portfolio_state (asset_id, portfolio_ts_utc),
          KEY ix_portfolio_slot (portfolio_slot, target_position_size_pct),

          CONSTRAINT fk_portfolio_state_asset
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


def fetch_latest_risk_rows(conn) -> list[dict[str, Any]]:
    sql = """
    SELECT
      r.*
    FROM risk_state r
    JOIN (
      SELECT
        asset_id,
        MAX(risk_ts_utc) AS max_risk_ts_utc
      FROM risk_state
      GROUP BY asset_id
    ) latest
      ON latest.asset_id = r.asset_id
     AND latest.max_risk_ts_utc = r.risk_ts_utc
    ORDER BY
      CASE
        WHEN r.portfolio_slot IS NULL THEN 999
        ELSE r.portfolio_slot
      END,
      r.approved_position_size_pct DESC,
      r.asset_id
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


def map_portfolio_target(row: dict[str, Any]) -> tuple[str, float, str]:
    risk_action = str(row["risk_action"])
    approved = float(row["approved_position_size_pct"] or 0.0)
    bucket = str(row["portfolio_bucket"] or "")

    if risk_action == "APPROVE" and approved > 0.0:
        return (
            "TARGET_ACTIVE",
            approved,
            f"Approved active portfolio position in bucket={bucket}.",
        )

    if risk_action == "REPLACE" and approved > 0.0:
        return (
            "TARGET_ACTIVE",
            approved,
            f"Replacement-selected active portfolio position in bucket={bucket}.",
        )

    if risk_action == "PREPARE" and approved > 0.0:
        return (
            "TARGET_PREPARE",
            approved,
            "Prepare candidate with reserved sizing but not active execution.",
        )

    if risk_action == "TACTICAL" and approved > 0.0:
        return (
            "TARGET_TACTICAL",
            approved,
            "Tactical short-horizon candidate with capped size.",
        )

    return (
        "TARGET_NONE",
        0.0,
        "No active target position for this asset.",
    )


def upsert_portfolio_rows(conn, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    sql = """
    INSERT INTO portfolio_state (
      asset_id,
      portfolio_ts_utc,
      target_action,
      target_position_size_pct,
      portfolio_slot,
      portfolio_bucket,
      source_risk_action,
      source_decision_action,
      portfolio_reasoning
    ) VALUES (
      %(asset_id)s,
      %(portfolio_ts_utc)s,
      %(target_action)s,
      %(target_position_size_pct)s,
      %(portfolio_slot)s,
      %(portfolio_bucket)s,
      %(source_risk_action)s,
      %(source_decision_action)s,
      %(portfolio_reasoning)s
    )
    ON DUPLICATE KEY UPDATE
      target_action = VALUES(target_action),
      target_position_size_pct = VALUES(target_position_size_pct),
      portfolio_slot = VALUES(portfolio_slot),
      portfolio_bucket = VALUES(portfolio_bucket),
      source_risk_action = VALUES(source_risk_action),
      source_decision_action = VALUES(source_decision_action),
      portfolio_reasoning = VALUES(portfolio_reasoning)
    """

    with conn.cursor() as cur:
        cur.executemany(sql, rows)

    conn.commit()
    return len(rows)


def run() -> int:
    conn = get_db_connection()

    try:
        ensure_tables(conn)
        risk_rows = fetch_latest_risk_rows(conn)
        portfolio_ts_utc = utc_now().replace(tzinfo=None)

        out_rows: list[dict[str, Any]] = []

        for row in risk_rows:
            target_action, target_size, reasoning = map_portfolio_target(row)

            out_rows.append(
                {
                    "asset_id": int(row["asset_id"]),
                    "portfolio_ts_utc": portfolio_ts_utc,
                    "target_action": target_action,
                    "target_position_size_pct": round(target_size, 4),
                    "portfolio_slot": row["portfolio_slot"],
                    "portfolio_bucket": row["portfolio_bucket"],
                    "source_risk_action": row["risk_action"],
                    "source_decision_action": row["decision_action"],
                    "portfolio_reasoning": reasoning,
                }
            )

        written = upsert_portfolio_rows(conn, out_rows)
        print(f"[DONE] portfolio rows={written}")
        return written

    finally:
        conn.close()


if __name__ == "__main__":
    run()
