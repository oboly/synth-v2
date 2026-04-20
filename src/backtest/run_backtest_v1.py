from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pymysql


DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "cursorclass": pymysql.cursors.DictCursor,
}

SOURCE_DB = "synth"
BT_DB = "synth_bt"


@dataclass(frozen=True)
class SignalRow:
    asset_id: int
    symbol: str
    venue: str
    advice_ts_1h_utc: Any
    selection_state: str
    selection_score: Decimal
    entry_price: Decimal
    exit_ts_utc: Any
    exit_price: Decimal


def get_connection(db_name: str):
    return pymysql.connect(**{**DB_CONFIG, "database": db_name})


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def fetch_signals() -> list[SignalRow]:
    sql = """
    WITH selection_base AS (
        SELECT
            s.asset_id,
            a.symbol,
            s.venue,
            s.advice_ts_1h_utc,
            s.selection_state,
            s.selection_score
        FROM selection_state s
        JOIN asset a
          ON a.asset_id = s.asset_id
        WHERE s.engine_name = 'selection_engine_v2'
          AND s.engine_version = '2.0'
          AND s.selection_state IN ('PREPARE', 'BUY_READY')
          AND s.advice_ts_1h_utc IS NOT NULL
    ),
    candle_with_forward AS (
        SELECT
            c.asset_id,
            c.venue,
            c.open_ts_utc,
            c.close_price AS entry_price,
            LEAD(c.open_ts_utc, 4) OVER (
                PARTITION BY c.asset_id, c.venue, c.interval_code
                ORDER BY c.open_ts_utc
            ) AS exit_ts_utc,
            LEAD(c.close_price, 4) OVER (
                PARTITION BY c.asset_id, c.venue, c.interval_code
                ORDER BY c.open_ts_utc
            ) AS exit_price
        FROM obs_market_candle c
        WHERE c.interval_code = '1h'
    )
    SELECT
        sb.asset_id,
        sb.symbol,
        sb.venue,
        sb.advice_ts_1h_utc,
        sb.selection_state,
        sb.selection_score,
        cf.entry_price,
        cf.exit_ts_utc,
        cf.exit_price
    FROM selection_base sb
    JOIN candle_with_forward cf
      ON cf.asset_id = sb.asset_id
     AND cf.venue = sb.venue
     AND cf.open_ts_utc = sb.advice_ts_1h_utc
    WHERE cf.exit_price IS NOT NULL
    ORDER BY sb.symbol, sb.advice_ts_1h_utc
    """

    conn = get_connection(SOURCE_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall() or []
    finally:
        conn.close()

    out: list[SignalRow] = []
    for row in rows:
        out.append(
            SignalRow(
                asset_id=int(row["asset_id"]),
                symbol=str(row["symbol"]),
                venue=str(row["venue"]),
                advice_ts_1h_utc=row["advice_ts_1h_utc"],
                selection_state=str(row["selection_state"]),
                selection_score=_to_decimal(row["selection_score"]),
                entry_price=_to_decimal(row["entry_price"]),
                exit_ts_utc=row["exit_ts_utc"],
                exit_price=_to_decimal(row["exit_price"]),
            )
        )
    return out


def ensure_bt_tables() -> None:
    sql_statements = [
        """
        CREATE TABLE IF NOT EXISTS bt_run (
            bt_run_id BIGINT AUTO_INCREMENT PRIMARY KEY,
            run_name VARCHAR(100),
            strategy_name VARCHAR(100),
            created_ts_utc DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
            notes TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bt_trade (
            bt_trade_id BIGINT AUTO_INCREMENT PRIMARY KEY,
            bt_run_id BIGINT NOT NULL,
            asset_id INT NOT NULL,
            symbol VARCHAR(20),
            entry_ts_utc DATETIME(6),
            entry_price DECIMAL(20,10),
            exit_ts_utc DATETIME(6),
            exit_price DECIMAL(20,10),
            qty DECIMAL(20,10),
            pnl_eur DECIMAL(20,10),
            return_pct DECIMAL(10,6),
            holding_seconds INT,
            created_ts_utc DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
            INDEX idx_bt_run (bt_run_id),
            INDEX idx_asset (asset_id),
            INDEX idx_entry_ts (entry_ts_utc)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bt_equity_curve (
            bt_run_id BIGINT,
            ts_utc DATETIME(6),
            equity_eur DECIMAL(20,10),
            PRIMARY KEY (bt_run_id, ts_utc)
        )
        """,
    ]

    conn = get_connection(BT_DB)
    try:
        with conn.cursor() as cur:
            for sql in sql_statements:
                cur.execute(sql)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_backtest() -> None:
    ensure_bt_tables()
    signals = fetch_signals()

    if not signals:
        print("No signals found.")
        return

    notional_per_trade = Decimal("100")
    equity = Decimal("10000")
    wins = 0
    trades_written = 0
    total_return = Decimal("0")

    conn_bt = get_connection(BT_DB)
    try:
        with conn_bt.cursor() as cur:
            cur.execute(
                """
                INSERT INTO bt_run (run_name, strategy_name, notes)
                VALUES (%s, %s, %s)
                """,
                (
                    "selection_v2_prepare_buyready_forward_4h",
                    "SELECTION_V2_FORWARD_4H",
                    "Entry on advice_ts_1h_utc 1h close; exit after 4x 1h candles; no fees/slippage.",
                ),
            )
            bt_run_id = int(cur.lastrowid)

            for signal in signals:
                if signal.entry_price <= Decimal("0"):
                    continue

                qty = notional_per_trade / signal.entry_price
                pnl_eur = (signal.exit_price - signal.entry_price) * qty
                return_pct = ((signal.exit_price - signal.entry_price) / signal.entry_price).quantize(
                    Decimal("0.000001")
                )

                equity += pnl_eur
                total_return += return_pct

                if pnl_eur > 0:
                    wins += 1

                cur.execute(
                    """
                    INSERT INTO bt_trade (
                        bt_run_id,
                        asset_id,
                        symbol,
                        entry_ts_utc,
                        entry_price,
                        exit_ts_utc,
                        exit_price,
                        qty,
                        pnl_eur,
                        return_pct,
                        holding_seconds
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        bt_run_id,
                        signal.asset_id,
                        signal.symbol,
                        signal.advice_ts_1h_utc,
                        signal.entry_price,
                        signal.exit_ts_utc,
                        signal.exit_price,
                        qty,
                        pnl_eur,
                        return_pct,
                        4 * 3600,
                    ],
                )

                cur.execute(
                    """
                    INSERT INTO bt_equity_curve (
                        bt_run_id,
                        ts_utc,
                        equity_eur
                    ) VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        equity_eur = VALUES(equity_eur)
                    """,
                    [
                        bt_run_id,
                        signal.exit_ts_utc,
                        equity,
                    ],
                )

                trades_written += 1

        conn_bt.commit()

    except Exception:
        conn_bt.rollback()
        raise
    finally:
        conn_bt.close()

    avg_return = (total_return / Decimal(str(trades_written))) if trades_written > 0 else Decimal("0")
    winrate = (Decimal(str(wins)) / Decimal(str(trades_written))) if trades_written > 0 else Decimal("0")

    print("=== BACKTEST RESULT ===")
    print(f"bt_run_id={bt_run_id}")
    print(f"trades={trades_written}")
    print(f"winrate={winrate.quantize(Decimal('0.0001'))}")
    print(f"avg_return_pct={avg_return.quantize(Decimal('0.000001'))}")
    print(f"final_equity_eur={equity.quantize(Decimal('0.000000'))}")


if __name__ == "__main__":
    run_backtest()
