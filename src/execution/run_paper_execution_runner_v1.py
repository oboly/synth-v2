from __future__ import annotations

import os
from datetime import UTC, datetime

import pymysql
from dotenv import load_dotenv


load_dotenv(".env")

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "charset": os.getenv("DB_CHARSET", "utf8mb4"),
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": False,
}


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def get_connection():
    return pymysql.connect(**DB_CONFIG)


def fetch_idle_plans(conn, limit: int = 50):
    sql = """
        SELECT *
        FROM execution_plan
        WHERE plan_state = 'IDLE'
        ORDER BY plan_ts_utc ASC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (limit,))
        return cur.fetchall()


def create_open_order(conn, plan):
    sql = """
        INSERT INTO open_order_state (
            execution_plan_id,
            account_id,
            asset_id,
            venue,
            side,
            order_type,
            price,
            qty,
            order_state,
            placed_ts_utc
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s
        )
    """

    qty = 1.0 if float(plan["target_fraction"]) > 0 else 0.0
    price = plan["passive_price_eur"] or plan["reference_price_eur"]

    values = (
        plan["execution_plan_id"],
        plan["account_id"],
        plan["asset_id"],
        plan["venue"],
        plan["side"],
        "LIMIT",
        price,
        qty,
        "PLACED",
        utc_now_naive(),
    )

    with conn.cursor() as cur:
        cur.execute(sql, values)
        return cur.lastrowid


def insert_execution_event(conn, plan, event_type: str, reason: str | None = None):
    sql = """
        INSERT INTO execution_event (
            execution_plan_id,
            account_id,
            asset_id,
            sleeve_code,
            event_ts_utc,
            event_type,
            event_reason,
            side,
            price,
            qty
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s
        )
    """

    values = (
        plan["execution_plan_id"],
        plan["account_id"],
        plan["asset_id"],
        plan["sleeve_code"],
        utc_now_naive(),
        event_type,
        reason,
        plan["side"],
        plan["passive_price_eur"] or plan["reference_price_eur"],
        1.0,
    )

    with conn.cursor() as cur:
        cur.execute(sql, values)


def update_plan_state(conn, plan_id: int, new_state: str):
    sql = """
        UPDATE execution_plan
        SET plan_state = %s,
            updated_ts_utc = UTC_TIMESTAMP()
        WHERE execution_plan_id = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (new_state, plan_id))


def process_plan(conn, plan):
    create_open_order(conn, plan)

    insert_execution_event(
        conn,
        plan,
        event_type="PAPER_PLACE_PASSIVE",
        reason="initial placement",
    )

    update_plan_state(conn, plan["execution_plan_id"], "PLACED")


def run():
    conn = get_connection()

    try:
        plans = fetch_idle_plans(conn)

        if not plans:
            print("[EXECUTION] No IDLE plans found.")
            return

        print(f"[EXECUTION] Found {len(plans)} plans")

        for plan in plans:
            process_plan(conn, plan)

        conn.commit()
        print("[EXECUTION] Done.")

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    run()
