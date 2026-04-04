from __future__ import annotations

from typing import Any

from src.common.db import get_db_connection
from src.common.utc import utc_now


MAX_ACTIVE_LONGS = 3
MAX_TOTAL_EXPOSURE = 2.00
MAX_POSITION_PER_CORE = 0.75

SCALP_CAP = 0.15
PREPARE_CAP = 0.30
WATCH_CAP = 0.00

BUCKET_PRIORITY: dict[str, int] = {
    "CORE_LONG": 1,
    "PREPARE": 2,
    "TACTICAL": 3,
    "WATCH": 4,
    "REJECT": 5,
}


# -------------------------------------------------
# DB helpers
# -------------------------------------------------

def fetch_current_active_longs(conn) -> list[dict[str, Any]]:
    sql = """
    SELECT r.asset_id, r.approved_position_size_pct, d.selection_score
    FROM risk_state r
    JOIN decision_state d ON d.asset_id = r.asset_id
    JOIN (
        SELECT asset_id, MAX(risk_ts_utc) AS ts
        FROM risk_state
        GROUP BY asset_id
    ) latest ON latest.asset_id = r.asset_id AND latest.ts = r.risk_ts_utc
    JOIN (
        SELECT asset_id, MAX(decision_ts_utc) AS ts
        FROM decision_state
        GROUP BY asset_id
    ) d_latest ON d_latest.asset_id = d.asset_id AND d_latest.ts = d.decision_ts_utc
    WHERE r.risk_action = 'APPROVE'
    """

    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    return rows or []


def ensure_table(conn) -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS risk_state (
      risk_state_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
      asset_id INT NOT NULL,
      risk_ts_utc DATETIME(6) NOT NULL,

      decision_action VARCHAR(32),
      decision_strength VARCHAR(16),
      raw_position_size_pct DECIMAL(6,4),

      risk_action VARCHAR(32),
      approved_position_size_pct DECIMAL(6,4),
      portfolio_slot INT,
      portfolio_bucket VARCHAR(32),
      risk_reasoning VARCHAR(512),

      created_ts_utc DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),

      PRIMARY KEY (risk_state_id),
      UNIQUE KEY uq_risk_state (asset_id, risk_ts_utc)
    )
    """

    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def fetch_latest_decisions(conn):
    sql = """
    SELECT d.*
    FROM decision_state d
    JOIN (
      SELECT asset_id, MAX(decision_ts_utc) AS ts
      FROM decision_state
      GROUP BY asset_id
    ) latest
      ON latest.asset_id = d.asset_id
     AND latest.ts = d.decision_ts_utc
    ORDER BY d.selection_score DESC
    """

    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


# -------------------------------------------------
# Logic
# -------------------------------------------------

def classify_bucket(row):
    if row["decision_action"] == "ENTER_LONG" and row["decision_strength"] == "HIGH":
        return "CORE_LONG"
    if row["decision_action"] == "PREPARE":
        return "PREPARE"
    if row["decision_action"] == "SCALP_ONLY":
        return "TACTICAL"
    if row["decision_action"] in {"WATCH", "CONDITIONAL"}:
        return "WATCH"
    return "REJECT"


# -------------------------------------------------
# Main
# -------------------------------------------------

def run() -> int:
    conn = get_db_connection()

    try:
        ensure_table(conn)

        decisions = fetch_latest_decisions(conn)
        active = fetch_current_active_longs(conn)

        risk_ts = utc_now().replace(tzinfo=None)

        remaining_exposure = MAX_TOTAL_EXPOSURE
        active_longs = 0

        # find weakest active
        weakest = None
        if active:
            weakest = min(active, key=lambda x: float(x["selection_score"]))

        out = []

        for row in decisions:
            bucket = classify_bucket(row)
            score = float(row["selection_score"])
            raw_size = float(row["position_size_pct"] or 0.0)

            risk_action = "BLOCK"
            approved = 0.0
            reason = ""

            # --- CORE LOGIC ---
            if bucket == "CORE_LONG":

                if active_longs < MAX_ACTIVE_LONGS:
                    approved = min(raw_size, MAX_POSITION_PER_CORE, remaining_exposure)
                    if approved > 0:
                        risk_action = "APPROVE"
                        active_longs += 1
                        remaining_exposure -= approved
                        reason = "New core position added."

                else:
                    if weakest and score > float(weakest["selection_score"]):
                        risk_action = "REPLACE"
                        approved = weakest["approved_position_size_pct"]
                        reason = "Replaced weaker position based on higher score."
                    else:
                        reason = "Blocked: weaker than current portfolio."

            elif bucket == "PREPARE":
                reason = "Prepare state."

            elif bucket == "TACTICAL":
                raw_size = float(row["position_size_pct"] or 0.0)

                approved = min(raw_size, SCALP_CAP, remaining_exposure)

                if approved <= 0.0:
                    risk_action = "BLOCK"
                    approved_size = 0.0
                    reason = "No remaining exposure for tactical allocation."
                else:
                    risk_action = "TACTICAL"
                    approved_size = round(approved, 4)
                    remaining_exposure = round(
                        max(0.0, remaining_exposure - approved_size), 4
                    )
                    reason = "Approved tactical scalp allocation."

            elif bucket == "WATCH":
                risk_action = "WATCH"
                reason = "Watch only."

            else:
                reason = "Rejected."

            out.append(
                {
                    "asset_id": row["asset_id"],
                    "risk_ts_utc": risk_ts,
                    "decision_action": row["decision_action"],
                    "decision_strength": row["decision_strength"],
                    "raw_position_size_pct": raw_size,
                    "risk_action": risk_action,
                    "approved_position_size_pct": round(approved, 4),
                    "portfolio_slot": None,
                    "portfolio_bucket": bucket,
                    "risk_reasoning": reason,
                }
            )

        # write
        sql = """
        INSERT INTO risk_state (
          asset_id, risk_ts_utc,
          decision_action, decision_strength,
          raw_position_size_pct,
          risk_action, approved_position_size_pct,
          portfolio_slot, portfolio_bucket, risk_reasoning
        ) VALUES (
          %(asset_id)s, %(risk_ts_utc)s,
          %(decision_action)s, %(decision_strength)s,
          %(raw_position_size_pct)s,
          %(risk_action)s, %(approved_position_size_pct)s,
          %(portfolio_slot)s, %(portfolio_bucket)s, %(risk_reasoning)s
        )
        """

        with conn.cursor() as cur:
            cur.executemany(sql, out)

        conn.commit()

        print(f"[DONE] risk rows={len(out)}")
        return len(out)

    finally:
        conn.close()


if __name__ == "__main__":
    run()
