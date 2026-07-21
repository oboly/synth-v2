from __future__ import annotations

from datetime import UTC, datetime

from src.common.db_env_v1 import load_database_environment


load_database_environment()


from src.common.db_core_v1 import get_connection  # noqa: E402

def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def fetch_idle_plans(conn, limit: int = 50):
    sql = """
        SELECT *
        FROM execution_plan
        WHERE plan_state = 'IDLE'
          AND BINARY execution_mode = BINARY 'PAPER'
          AND BINARY action_type = BINARY 'PLACE_ORDER'
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
    if str(plan.get("execution_mode")) != "PAPER":
        insert_execution_event(
            conn,
            plan,
            event_type="EXECUTOR_REJECTED",
            reason="EXECUTION_MODE_NOT_CANONICAL_PAPER",
        )
        return
    if str(plan.get("action_type")) != "PLACE_ORDER":
        insert_execution_event(
            conn,
            plan,
            event_type="EXECUTOR_REJECTED",
            reason="PAPER_ACTION_NOT_SUPPORTED",
        )
        return
    requested_side = plan.get("requested_side")
    if requested_side not in {"BUY", "SELL"} or plan.get("side") != requested_side:
        insert_execution_event(
            conn,
            plan,
            event_type="EXECUTOR_REJECTED",
            reason="REQUESTED_SIDE_NOT_CANONICAL",
        )
        return

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
