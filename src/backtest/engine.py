from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol

import pandas as pd

from src.common.db import db_cursor
from src.backtest.types import BacktestConfig, BacktestResult, Trade


DECIMAL_ZERO = Decimal("0")


class StrategyProtocol(Protocol):
    name: str

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        ...

    def should_enter_long(self, row: pd.Series) -> bool:
        ...

    def should_exit_long(self, row: pd.Series) -> tuple[bool, str]:
        ...


def to_decimal(value: Any) -> Decimal:
    return Decimal(str(round(float(value), 10)))


def fetch_asset_metadata(symbol: str) -> dict[str, Any] | None:
    sql = """
    SELECT
        asset_id,
        symbol,
        sector,
        asset_class
    FROM asset
    WHERE symbol = %s
    LIMIT 1
    """

    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql, (symbol,))
        row = cur.fetchone()

    return row


def fetch_candles(symbol: str, interval_code: str, days: int) -> pd.DataFrame:
    sql = """
    SELECT
        c.open_ts_utc,
        c.close_ts_utc,
        c.open_price,
        c.high_price,
        c.low_price,
        c.close_price,
        c.volume_base,
        c.volume_quote_eur
    FROM obs_market_candle c
    JOIN asset a
      ON a.asset_id = c.asset_id
    WHERE a.symbol = %s
      AND c.venue = 'bitvavo'
      AND c.interval_code = %s
      AND c.open_ts_utc >= UTC_TIMESTAMP() - INTERVAL %s DAY
    ORDER BY c.open_ts_utc ASC
    """

    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql, (symbol, interval_code, days))
        rows = cur.fetchall()

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    numeric_cols = [
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume_base",
        "volume_quote_eur",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def max_drawdown(equity_curve: list[Decimal]) -> Decimal:
    if not equity_curve:
        return DECIMAL_ZERO

    peak = equity_curve[0]
    max_dd = DECIMAL_ZERO

    for eq in equity_curve:
        if eq > peak:
            peak = eq
        if peak > DECIMAL_ZERO:
            dd = ((peak - eq) / peak) * Decimal("100")
            if dd > max_dd:
                max_dd = dd

    return max_dd.quantize(Decimal("0.01"))


def run_backtest(
    config: BacktestConfig,
    strategy: StrategyProtocol,
) -> tuple[pd.DataFrame, BacktestResult]:
    raw_df = fetch_candles(config.symbol, config.interval, config.days)
    if raw_df.empty:
        raise ValueError("No candle data found for requested symbol/interval/range.")

    df = strategy.prepare_features(raw_df)
    df = df.dropna().reset_index(drop=True)

    if df.empty:
        raise ValueError("Not enough candle history after feature calculation.")

    trades: list[Trade] = []
    equity_curve: list[Decimal] = []

    cash = config.starting_cash
    qty = DECIMAL_ZERO
    entry_price = DECIMAL_ZERO
    entry_ts = None
    fee_rate = config.fee_bps / Decimal("10000")

    for _, row in df.iterrows():
        close_price = to_decimal(row["close_price"])
        close_ts = row["close_ts_utc"]

        equity = cash + (qty * close_price)
        equity_curve.append(equity)

        if qty == DECIMAL_ZERO:
            if strategy.should_enter_long(row):
                fee_cost = cash * fee_rate
                net_cash_to_deploy = cash - fee_cost

                if net_cash_to_deploy > DECIMAL_ZERO:
                    qty = (net_cash_to_deploy / close_price).quantize(Decimal("0.00000001"))
                    entry_price = close_price
                    entry_ts = close_ts
                    cash = DECIMAL_ZERO
        else:
            should_exit, reason = strategy.should_exit_long(row)
            if should_exit:
                gross_value = qty * close_price
                fee_cost = gross_value * fee_rate
                net_value = gross_value - fee_cost

                pnl_eur = net_value - (qty * entry_price)
                pnl_pct = (
                    ((close_price - entry_price) / entry_price) * Decimal("100")
                    if entry_price > DECIMAL_ZERO
                    else DECIMAL_ZERO
                )

                trades.append(
                    Trade(
                        entry_ts_utc=entry_ts,
                        exit_ts_utc=close_ts,
                        entry_price=entry_price,
                        exit_price=close_price,
                        qty=qty,
                        pnl_eur=pnl_eur.quantize(Decimal("0.01")),
                        pnl_pct=pnl_pct.quantize(Decimal("0.01")),
                        reason=reason,
                    )
                )

                cash = net_value
                qty = DECIMAL_ZERO
                entry_price = DECIMAL_ZERO
                entry_ts = None

    if qty > DECIMAL_ZERO:
        last_close = to_decimal(df.iloc[-1]["close_price"])
        equity_curve[-1] = cash + (qty * last_close)

    start_price = to_decimal(df.iloc[0]["close_price"])
    end_price = to_decimal(df.iloc[-1]["close_price"])
    ending_equity = equity_curve[-1] if equity_curve else config.starting_cash

    total_return_pct = (
        ((ending_equity - config.starting_cash) / config.starting_cash) * Decimal("100")
        if config.starting_cash > DECIMAL_ZERO
        else DECIMAL_ZERO
    ).quantize(Decimal("0.01"))

    buy_hold_return_pct = (
        ((end_price - start_price) / start_price) * Decimal("100")
        if start_price > DECIMAL_ZERO
        else DECIMAL_ZERO
    ).quantize(Decimal("0.01"))

    wins = [t for t in trades if t.pnl_eur > 0]
    losses = [t for t in trades if t.pnl_eur <= 0]

    win_rate_pct = (
        (Decimal(len(wins)) / Decimal(len(trades)) * Decimal("100"))
        if trades
        else DECIMAL_ZERO
    ).quantize(Decimal("0.01"))

    avg_win_eur = (
        sum((t.pnl_eur for t in wins), DECIMAL_ZERO) / Decimal(len(wins))
        if wins
        else DECIMAL_ZERO
    ).quantize(Decimal("0.01"))

    avg_loss_eur = (
        sum((t.pnl_eur for t in losses), DECIMAL_ZERO) / Decimal(len(losses))
        if losses
        else DECIMAL_ZERO
    ).quantize(Decimal("0.01"))

    result = BacktestResult(
        trades=trades,
        equity_curve=equity_curve,
        ending_equity=ending_equity.quantize(Decimal("0.01")),
        total_return_pct=total_return_pct,
        buy_hold_return_pct=buy_hold_return_pct,
        max_drawdown_pct=max_drawdown(equity_curve),
        trade_count=len(trades),
        win_rate_pct=win_rate_pct,
        avg_win_eur=avg_win_eur,
        avg_loss_eur=avg_loss_eur,
        candles=len(df),
    )

    return df, result


def print_backtest_report(
    config: BacktestConfig,
    result: BacktestResult,
) -> None:
    metadata = fetch_asset_metadata(config.symbol)
    sector = metadata["sector"] if metadata and metadata.get("sector") is not None else "-"
    asset_class = metadata["asset_class"] if metadata and metadata.get("asset_class") is not None else "-"

    print("=== SIMPLE BACKTEST REPORT ===")
    print()
    print(f"symbol={config.symbol}")
    print(f"asset_class={asset_class}")
    print(f"sector={sector}")
    print(f"interval={config.interval}")
    print(f"days={config.days}")
    print(f"candles={result.candles}")
    print(f"starting_cash_eur={config.starting_cash.quantize(Decimal('0.01'))}")
    print(f"ending_equity_eur={result.ending_equity}")
    print(f"total_return_pct={result.total_return_pct}")
    print(f"buy_hold_return_pct={result.buy_hold_return_pct}")
    print(f"max_drawdown_pct={result.max_drawdown_pct}")
    print(f"trade_count={result.trade_count}")
    print(f"win_rate_pct={result.win_rate_pct}")
    print(f"avg_win_eur={result.avg_win_eur}")
    print(f"avg_loss_eur={result.avg_loss_eur}")
    print()
    print("LAST TRADES")
    print()

    if not result.trades:
        print("(none)")
        return

    for trade in result.trades[-10:]:
        print(
            f"entry={trade.entry_ts_utc} exit={trade.exit_ts_utc} "
            f"entry_price={trade.entry_price} exit_price={trade.exit_price} "
            f"pnl_eur={trade.pnl_eur} pnl_pct={trade.pnl_pct} reason={trade.reason}"
        )
