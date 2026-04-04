from __future__ import annotations

from typing import Any

from src.common.db import get_db_connection
from src.common.utc import utc_now


def decide(row: dict[str, Any]) -> tuple[str, str, float, str]:
    state = str(row["selection_state"])
    bias = str(row["selection_bias"])
    score = float(row["selection_score"])

    if state == "STRONG_CANDIDATE" and bias == "LONG_BIAS":
        return (
            "ENTER_LONG",
            "HIGH",
            1.00,
            "Strong multi-timeframe alignment with long bias.",
        )

    if state == "PRE_ALIGNMENT":
        return (
            "PREPARE",
            "MEDIUM",
            0.50,
            "4h structure is constructive, waiting for 1h timing alignment.",
        )

    if state == "EARLY_WATCH":
        return (
            "WATCH",
            "LOW",
            0.20,
            "Constructive early structure, but not yet strong enough for full conviction.",
        )

    if state == "TRIGGER_NO_HTF_CONFIRM":
        size = 0.30 if score >= 0.50 else 0.20
        return (
            "SCALP_ONLY",
            "MEDIUM",
            size,
            "1h trigger is active, but higher timeframe confirmation is still limited.",
        )

    if state == "MIXED_NEUTRAL":
        return (
            "CONDITIONAL",
            "MEDIUM",
            0.40,
            "Mixed timeframe state; monitor closely before taking full action.",
        )

    if state.startswith("REJECTED"):
        return (
            "AVOID",
            "LOW",
            0.00,
            "Higher or lower timeframe structure is too weak for a valid trade candidate.",
        )

    if state == "LOW_PRIORITY":
        return (
            "WATCH",
            "LOW",
            0.10,
            "Low-priority candidate with limited current edge.",
        )

    return (
        "WATCH",
        "LOW",
        0.10,
        "Fallback state.",
    )


def ensure_table(conn) -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS decision_state (
      decision_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
      asset_id INT NOT NULL,
      decision_ts_utc DATETIME(6) NOT NULL,
      selection_state VARCHAR(64) DEFAULT NULL,
      selection_score DECIMAL(10,6) DEFAULT NULL,
      decision_action VARCHAR(32) DEFAULT NULL,
      decision_strength VARCHAR(16) DEFAULT NULL,
      position_size_pct DECIMAL(5,2) DEFAULT NULL,
      reasoning VARCHAR(512) DEFAULT NULL,
      created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      PRIMARY KEY (decision_id),
      UNIQUE KEY uq_decision_state (asset_id, decision_ts_utc),
      KEY ix_decision_action (decision_action, decision_strength),
      CONSTRAINT fk_decision_state_asset
        FOREIGN KEY (asset_id) REFERENCES asset(asset_id)
    ) ENGINE=InnoDB
    DEFAULT CHARSET=utf8mb4
    COLLATE=utf8mb4_general_ci
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def fetch_selection_rows(conn) -> list[dict[str, Any]]:
    sql = """
    SELECT
      s.*
    FROM selection_state s
    ORDER BY s.priority_rank
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


def upsert_decision_rows(conn, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    sql = """
    INSERT INTO decision_state (
      asset_id,
      decision_ts_utc,
      selection_state,
      selection_score,
      decision_action,
      decision_strength,
      position_size_pct,
      reasoning
    ) VALUES (
      %(asset_id)s,
      %(decision_ts_utc)s,
      %(selection_state)s,
      %(selection_score)s,
      %(decision_action)s,
      %(decision_strength)s,
      %(position_size_pct)s,
      %(reasoning)s
    )
    ON DUPLICATE KEY UPDATE
      selection_state = VALUES(selection_state),
      selection_score = VALUES(selection_score),
      decision_action = VALUES(decision_action),
      decision_strength = VALUES(decision_strength),
      position_size_pct = VALUES(position_size_pct),
      reasoning = VALUES(reasoning)
    """

    with conn.cursor() as cur:
        cur.executemany(sql, rows)

    conn.commit()
    return len(rows)


def run() -> int:
    conn = get_db_connection()

    try:
        ensure_table(conn)
        selection_rows = fetch_selection_rows(conn)

        decision_ts_utc = utc_now().replace(tzinfo=None)

        out_rows: list[dict[str, Any]] = []

        for row in selection_rows:
            decision_action, decision_strength, position_size_pct, reasoning = decide(row)

            out_rows.append(
                {
                    "asset_id": int(row["asset_id"]),
                    "decision_ts_utc": decision_ts_utc,
                    "selection_state": str(row["selection_state"]),
                    "selection_score": float(row["selection_score"]),
                    "decision_action": decision_action,
                    "decision_strength": decision_strength,
                    "position_size_pct": position_size_pct,
                    "reasoning": reasoning,
                }
            )

        written = upsert_decision_rows(conn, out_rows)
        print(f"[DONE] decision rows={written}")
        return written

    finally:
        conn.close()


if __name__ == "__main__":
    run()
