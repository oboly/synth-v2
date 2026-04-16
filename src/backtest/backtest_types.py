from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(slots=True)
class Trade:
    entry_ts_utc: Any
    exit_ts_utc: Any
    entry_price: Decimal
    exit_price: Decimal
    qty: Decimal
    pnl_eur: Decimal
    pnl_pct: Decimal
    reason: str


@dataclass(slots=True)
class BacktestConfig:
    symbol: str
    interval: str
    days: int
    starting_cash: Decimal
    fee_bps: Decimal


@dataclass(slots=True)
class BacktestResult:
    trades: list[Trade]
    equity_curve: list[Decimal]
    ending_equity: Decimal
    total_return_pct: Decimal
    buy_hold_return_pct: Decimal
    max_drawdown_pct: Decimal
    trade_count: int
    win_rate_pct: Decimal
    avg_win_eur: Decimal
    avg_loss_eur: Decimal
    candles: int
