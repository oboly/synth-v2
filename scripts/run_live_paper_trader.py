from __future__ import annotations

import time
from decimal import Decimal

from src.common.db import db_cursor


SLEEP_SECONDS = 60
STARTING_CASH = Decimal("1000")

cash = STARTING_CASH
position_qty = Decimal("0")
last_price = None


def fetch_latest_decision():
    sql = """
    SELECT *
    FROM decision_log
    ORDER BY created_ts_utc DESC
    LIMIT 1
    """
    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql)
        row = cur.fetchone()
    return row


def fetch_price(asset_id: int):
    sql = """
    SELECT close_price
    FROM obs_market_candle
    WHERE asset_id = %s
    ORDER BY open_ts_utc DESC
    LIMIT 1
    """
    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql, (asset_id,))
        row = cur.fetchone()
    return Decimal(str(row["close_price"])) if row else None


def main():
    global cash, position_qty, last_price

    print("=== LIVE PAPER TRADER STARTED ===")

    while True:
        try:
            decision = fetch_latest_decision()
            if not decision:
                time.sleep(SLEEP_SECONDS)
                continue

            asset_id = decision["asset_id"]
            action = decision["action"]  # verwacht BUY / SELL / HOLD

            price = fetch_price(asset_id)
            if price is None:
                time.sleep(SLEEP_SECONDS)
                continue

            last_price = price

            print(f"\nPRICE={price} ACTION={action}")

            # BUY
            if action == "BUY" and position_qty == 0:
                qty = cash / price
                position_qty = qty
                cash = Decimal("0")

                print(f"[BUY] qty={qty:.6f} @ {price}")

            # SELL
            elif action == "SELL" and position_qty > 0:
                cash = position_qty * price
                print(f"[SELL] qty={position_qty:.6f} @ {price} cash={cash:.2f}")
                position_qty = Decimal("0")

            # EQUITY
            equity = cash + (position_qty * price)

            print(
                f"[STATE] cash={cash:.2f} qty={position_qty:.6f} equity={equity:.2f}"
            )

        except Exception as e:
            print("ERROR:", e)

        time.sleep(SLEEP_SECONDS)


if __name__ == "__main__":
    main()
