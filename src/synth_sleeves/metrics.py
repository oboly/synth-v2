"""
SYNTH v2
Module: synth_sleeves.metrics
Purpose:
    Aggregate daily metrics from closed trade lots and transition events.
Boundary:
    - Pure computation helpers
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal


DECIMAL_ZERO = Decimal("0")


def build_strategy_metrics_daily(trade_rows: list[dict], prepare_transition_rows: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in trade_rows:
        key = (
            row["metric_date_utc"],
            row["sleeve_code"],
            row["strategy_name"],
            row.get("strategy_version_id"),
        )
        grouped[key].append(row)

    prep_counts: dict[tuple, dict[str, int]] = defaultdict(lambda: {"prepare_to_enter_count": 0, "prepare_fail_count": 0})
    for row in prepare_transition_rows:
        key = (
            row["metric_date_utc"],
            row["sleeve_code"],
            row["strategy_name"],
            row.get("strategy_version_id"),
        )
        if row["to_state"] == "ENTER_LONG":
            prep_counts[key]["prepare_to_enter_count"] += int(row["transition_count"])
        elif row["to_state"] in {"WATCH", "AVOID", "EXIT", "BLOCK"}:
            prep_counts[key]["prepare_fail_count"] += int(row["transition_count"])

    result: list[dict] = []
    for key, rows in grouped.items():
        metric_date_utc, sleeve_code, strategy_name, strategy_version_id = key
        trades_closed = len(rows)
        wins = sum(1 for row in rows if Decimal(str(row["realized_pnl_eur"])) > DECIMAL_ZERO)
        losses = sum(1 for row in rows if Decimal(str(row["realized_pnl_eur"])) <= DECIMAL_ZERO)
        gross_profit = sum((Decimal(str(row["realized_pnl_eur"])) for row in rows if Decimal(str(row["realized_pnl_eur"])) > DECIMAL_ZERO), start=DECIMAL_ZERO)
        gross_loss_abs = sum((abs(Decimal(str(row["realized_pnl_eur"]))) for row in rows if Decimal(str(row["realized_pnl_eur"])) <= DECIMAL_ZERO), start=DECIMAL_ZERO)
        avg_pnl_eur = sum((Decimal(str(row["realized_pnl_eur"])) for row in rows), start=DECIMAL_ZERO) / Decimal(trades_closed)
        avg_pnl_pct = sum((Decimal(str(row["realized_pnl_pct"])) for row in rows), start=DECIMAL_ZERO) / Decimal(trades_closed)
        avg_holding = sum((Decimal(str(row["holding_minutes"])) for row in rows), start=DECIMAL_ZERO) / Decimal(trades_closed)
        profit_factor = (gross_profit / gross_loss_abs) if gross_loss_abs > DECIMAL_ZERO else Decimal("999999")

        prep = prep_counts[key]

        result.append(
            {
                "metric_date_utc": metric_date_utc,
                "sleeve_code": sleeve_code,
                "strategy_name": strategy_name,
                "strategy_version_id": strategy_version_id,
                "trades_closed": trades_closed,
                "wins": wins,
                "losses": losses,
                "win_rate": (Decimal(wins) / Decimal(trades_closed)) if trades_closed else DECIMAL_ZERO,
                "avg_realized_pnl_pct": avg_pnl_pct,
                "avg_realized_pnl_eur": avg_pnl_eur,
                "gross_profit_eur": gross_profit,
                "gross_loss_eur": gross_loss_abs,
                "profit_factor": profit_factor,
                "avg_holding_minutes": avg_holding,
                "prepare_to_enter_count": prep["prepare_to_enter_count"],
                "prepare_fail_count": prep["prepare_fail_count"],
            }
        )

    return result
