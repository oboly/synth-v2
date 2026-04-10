from __future__ import annotations

from src.common.db import db_cursor
from src.backtest.types import BacktestConfig, BacktestResult


def persist_backtest_run_scratch(
    config: BacktestConfig,
    strategy_name: str,
    result: BacktestResult,
    notes: str | None = None,
    keep_flag: bool = False,
) -> int:
    insert_run_sql = """
    INSERT INTO bt_run_scratch (
        strategy_name,
        symbol,
        interval_code,
        days_back,
        starting_cash_eur,
        fee_bps,
        candles,
        ending_equity_eur,
        total_return_pct,
        buy_hold_return_pct,
        max_drawdown_pct,
        trade_count,
        win_rate_pct,
        avg_win_eur,
        avg_loss_eur,
        keep_flag,
        notes
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    """

    insert_trade_sql = """
    INSERT INTO bt_trade_scratch (
        bt_run_id,
        entry_ts_utc,
        exit_ts_utc,
        entry_price,
        exit_price,
        qty,
        pnl_eur,
        pnl_pct,
        reason
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    """

    with db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            insert_run_sql,
            (
                strategy_name,
                config.symbol,
                config.interval,
                config.days,
                config.starting_cash,
                config.fee_bps,
                result.candles,
                result.ending_equity,
                result.total_return_pct,
                result.buy_hold_return_pct,
                result.max_drawdown_pct,
                result.trade_count,
                result.win_rate_pct,
                result.avg_win_eur,
                result.avg_loss_eur,
                1 if keep_flag else 0,
                notes,
            ),
        )
        bt_run_id = int(cur.lastrowid)

        if result.trades:
            trade_rows = [
                (
                    bt_run_id,
                    trade.entry_ts_utc,
                    trade.exit_ts_utc,
                    trade.entry_price,
                    trade.exit_price,
                    trade.qty,
                    trade.pnl_eur,
                    trade.pnl_pct,
                    trade.reason,
                )
                for trade in result.trades
            ]
            cur.executemany(insert_trade_sql, trade_rows)

    return bt_run_id


def cleanup_backtest_scratch(days_to_keep: int = 3) -> int:
    sql = f"""
    DELETE FROM bt_run_scratch
    WHERE keep_flag = 0
      AND created_ts_utc < UTC_TIMESTAMP() - INTERVAL {int(days_to_keep)} DAY
    """

    with db_cursor(commit=True) as (_conn, cur):
        affected = cur.execute(sql)

    return int(affected)
