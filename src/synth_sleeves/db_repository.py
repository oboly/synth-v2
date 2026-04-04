"""
SYNTH v2
Module: synth_sleeves.db_repository
Purpose:
    MariaDB repository for sleeve targets, lots, trades, snapshots, metrics.
Boundary:
    - DB only
    - No strategy logic
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from src.synth_sleeves.models import ApprovedTarget, OpenLot, SleeveCode


class SleeveRepository:
    def __init__(self, connection_params: dict[str, Any]) -> None:
        self._connection_params = connection_params

    def _connect(self) -> pymysql.connections.Connection:
        return pymysql.connect(
            cursorclass=DictCursor,
            autocommit=False,
            charset="utf8mb4",
            **self._connection_params,
        )

    def get_next_position_lot_id(self) -> int:
        sql = "SELECT COALESCE(MAX(position_lot_id), 0) + 1 AS next_id FROM position_lot"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
            conn.commit()
        return int(row["next_id"])

    def fetch_open_lots(self) -> list[OpenLot]:
        sql = """
        SELECT
            position_lot_id,
            asset_id,
            sleeve_code,
            strategy_name,
            entry_state,
            open_ts_utc,
            entry_price_eur,
            COALESCE(latest_price_eur, entry_price_eur) AS latest_price_eur,
            current_fraction,
            entry_notional_eur,
            current_notional_eur,
            quantity_units,
            realized_pnl_eur,
            unrealized_pnl_eur,
            COALESCE(entry_reason, '') AS entry_reason,
            last_transition_state
        FROM position_lot
        WHERE status = 'OPEN'
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()

        result: list[OpenLot] = []
        for row in rows:
            result.append(
                OpenLot(
                    position_lot_id=int(row["position_lot_id"]),
                    asset_id=int(row["asset_id"]),
                    sleeve_code=SleeveCode(row["sleeve_code"]),
                    strategy_name=str(row["strategy_name"]),
                    entry_state=row["entry_state"],
                    open_ts_utc=row["open_ts_utc"],
                    entry_price_eur=Decimal(str(row["entry_price_eur"])),
                    latest_price_eur=Decimal(str(row["latest_price_eur"])),
                    current_fraction=Decimal(str(row["current_fraction"])),
                    entry_notional_eur=Decimal(str(row["entry_notional_eur"])),
                    current_notional_eur=Decimal(str(row["current_notional_eur"])),
                    quantity_units=Decimal(str(row["quantity_units"])),
                    realized_pnl_eur=Decimal(str(row["realized_pnl_eur"])),
                    unrealized_pnl_eur=Decimal(str(row["unrealized_pnl_eur"])),
                    entry_reason=str(row["entry_reason"]),
                    last_transition_state=row["last_transition_state"],
                )
            )
        return result

    def insert_portfolio_targets(self, targets: list[ApprovedTarget], strategy_version_lookup: dict[str, int]) -> None:
        if not targets:
            return

        sql = """
        INSERT INTO portfolio_target (
            run_ts_utc,
            asset_id,
            sleeve_code,
            strategy_name,
            strategy_version_id,
            desired_action,
            target_fraction,
            decision_strength,
            reasoning,
            source_state,
            current_price_eur
        ) VALUES (
            %(run_ts_utc)s,
            %(asset_id)s,
            %(sleeve_code)s,
            %(strategy_name)s,
            %(strategy_version_id)s,
            %(desired_action)s,
            %(target_fraction)s,
            %(decision_strength)s,
            %(reasoning)s,
            %(source_state)s,
            %(current_price_eur)s
        )
        ON DUPLICATE KEY UPDATE
            strategy_name = VALUES(strategy_name),
            strategy_version_id = VALUES(strategy_version_id),
            desired_action = VALUES(desired_action),
            target_fraction = VALUES(target_fraction),
            decision_strength = VALUES(decision_strength),
            reasoning = VALUES(reasoning),
            source_state = VALUES(source_state),
            current_price_eur = VALUES(current_price_eur)
        """
        payload = []
        for item in targets:
            payload.append(
                {
                    "run_ts_utc": item.run_ts_utc,
                    "asset_id": item.asset_id,
                    "sleeve_code": item.sleeve_code.value,
                    "strategy_name": item.strategy_name,
					                    "strategy_version_id": strategy_version_lookup.get(item.strategy_name),
                    "desired_action": item.desired_action.value,
                    "target_fraction": str(item.target_fraction),
                    "decision_strength": item.decision_strength,
                    "reasoning": item.reasoning,
                    "source_state": item.source_state,
                    "current_price_eur": str(item.latest_price_eur),
                }
            )

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, payload)
            conn.commit()

    def upsert_open_lot(self, lot: OpenLot) -> None:
        sql = """
        INSERT INTO position_lot (
            position_lot_id,
            asset_id,
            sleeve_code,
            strategy_name,
            entry_state,
            status,
            open_ts_utc,
            entry_price_eur,
            latest_price_eur,
            target_fraction_at_open,
            current_fraction,
            entry_notional_eur,
            current_notional_eur,
            realized_pnl_eur,
            unrealized_pnl_eur,
            quantity_units,
            entry_reason,
            last_transition_state,
            last_update_ts_utc
        ) VALUES (
            %(position_lot_id)s,
            %(asset_id)s,
            %(sleeve_code)s,
            %(strategy_name)s,
            %(entry_state)s,
            'OPEN',
            %(open_ts_utc)s,
            %(entry_price_eur)s,
            %(latest_price_eur)s,
            %(current_fraction)s,
            %(current_fraction)s,
            %(entry_notional_eur)s,
            %(current_notional_eur)s,
            %(realized_pnl_eur)s,
            %(unrealized_pnl_eur)s,
            %(quantity_units)s,
            %(entry_reason)s,
            %(last_transition_state)s,
            UTC_TIMESTAMP()
        )
        ON DUPLICATE KEY UPDATE
            latest_price_eur = VALUES(latest_price_eur),
            current_fraction = VALUES(current_fraction),
            current_notional_eur = VALUES(current_notional_eur),
            realized_pnl_eur = VALUES(realized_pnl_eur),
            unrealized_pnl_eur = VALUES(unrealized_pnl_eur),
            quantity_units = VALUES(quantity_units),
            last_transition_state = VALUES(last_transition_state),
            last_update_ts_utc = UTC_TIMESTAMP()
        """
        payload = {
            "position_lot_id": lot.position_lot_id,
            "asset_id": lot.asset_id,
            "sleeve_code": lot.sleeve_code.value,
            "strategy_name": lot.strategy_name,
            "entry_state": lot.entry_state.value if hasattr(lot.entry_state, "value") else str(lot.entry_state),
            "open_ts_utc": lot.open_ts_utc,
            "entry_price_eur": str(lot.entry_price_eur),
            "latest_price_eur": str(lot.latest_price_eur),
            "current_fraction": str(lot.current_fraction),
            "entry_notional_eur": str(lot.entry_notional_eur),
            "current_notional_eur": str(lot.current_notional_eur),
            "realized_pnl_eur": str(lot.realized_pnl_eur),
            "unrealized_pnl_eur": str(lot.unrealized_pnl_eur),
            "quantity_units": str(lot.quantity_units),
            "entry_reason": lot.entry_reason,
            "last_transition_state": lot.last_transition_state,
        }
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, payload)
            conn.commit()

    def close_lot(self, lot: OpenLot, close_ts_utc: datetime, exit_price_eur: Decimal, exit_reason: str, exit_state: str) -> None:
        holding_minutes = int((close_ts_utc - lot.open_ts_utc).total_seconds() // 60)
        realized_pct = Decimal("0")
        if lot.entry_notional_eur != Decimal("0"):
            realized_pct = (lot.realized_pnl_eur / lot.entry_notional_eur) * Decimal("100")

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE position_lot
                    SET
                        status = 'CLOSED',
                        close_ts_utc = %(close_ts_utc)s,
                        latest_price_eur = %(exit_price_eur)s,
                        current_fraction = 0,
                        current_notional_eur = 0,
                        unrealized_pnl_eur = 0,
                        exit_reason = %(exit_reason)s,
                        last_transition_state = %(exit_state)s,
                        last_update_ts_utc = UTC_TIMESTAMP()
                    WHERE position_lot_id = %(position_lot_id)s
                    """,
                    {
                        "close_ts_utc": close_ts_utc,
                        "exit_price_eur": str(exit_price_eur),
                        "exit_reason": exit_reason,
                        "exit_state": exit_state,
                        "position_lot_id": lot.position_lot_id,
                    },
                )
                cur.execute(
                    """
                    INSERT INTO trade_lot (
                        position_lot_id,
                        asset_id,
                        sleeve_code,
                        strategy_name,
                        entry_state,
                        exit_state,
                        open_ts_utc,
                        close_ts_utc,
                        entry_price_eur,
                        exit_price_eur,
                        entry_notional_eur,
                        exit_notional_eur,
                        quantity_units,
                        realized_pnl_eur,
                        realized_pnl_pct,
                        holding_minutes,
                        entry_reason,
                        exit_reason
                    ) VALUES (
                        %(position_lot_id)s,
                        %(asset_id)s,
                        %(sleeve_code)s,
                        %(strategy_name)s,
                        %(entry_state)s,
                        %(exit_state)s,
                        %(open_ts_utc)s,
                        %(close_ts_utc)s,
                        %(entry_price_eur)s,
                        %(exit_price_eur)s,
                        %(entry_notional_eur)s,
                        %(exit_notional_eur)s,
                        %(quantity_units)s,
                        %(realized_pnl_eur)s,
                        %(realized_pnl_pct)s,
                        %(holding_minutes)s,
                        %(entry_reason)s,
                        %(exit_reason)s
                    )
                    """,
                    {
                        "position_lot_id": lot.position_lot_id,
                        "asset_id": lot.asset_id,
                        "sleeve_code": lot.sleeve_code.value,
                        "strategy_name": lot.strategy_name,
                        "entry_state": str(lot.entry_state),
                        "exit_state": exit_state,
                        "open_ts_utc": lot.open_ts_utc,
                        "close_ts_utc": close_ts_utc,
                        "entry_price_eur": str(lot.entry_price_eur),
                        "exit_price_eur": str(exit_price_eur),
                        "entry_notional_eur": str(lot.entry_notional_eur),
                        "exit_notional_eur": str(lot.quantity_units * exit_price_eur),
                        "quantity_units": str(lot.quantity_units),
                        "realized_pnl_eur": str(lot.realized_pnl_eur),
                        "realized_pnl_pct": str(realized_pct),
                        "holding_minutes": holding_minutes,
                        "entry_reason": lot.entry_reason,
                        "exit_reason": exit_reason,
                    },
                )
            conn.commit()

    def insert_position_snapshot_asset_level(
        self,
        *,
        snapshot_ts_utc,
        asset_id,
        quantity,
        avg_entry_price_eur,
        market_value_eur,
        unrealized_pnl_eur,
    ) -> None:
        sql = """
        INSERT INTO position_snapshot (
            asset_id,
            snapshot_ts_utc,
            quantity,
            avg_entry_price_eur,
            market_value_eur,
            unrealized_pnl_eur
        ) VALUES (
            %(asset_id)s,
            %(snapshot_ts_utc)s,
            %(quantity)s,
            %(avg_entry_price_eur)s,
            %(market_value_eur)s,
            %(unrealized_pnl_eur)s
        )
        """

        payload = {
            "asset_id": asset_id,
            "snapshot_ts_utc": snapshot_ts_utc,
            "quantity": str(quantity),
            "avg_entry_price_eur": None if avg_entry_price_eur is None else str(avg_entry_price_eur),
            "market_value_eur": None if market_value_eur is None else str(market_value_eur),
            "unrealized_pnl_eur": None if unrealized_pnl_eur is None else str(unrealized_pnl_eur),
        }

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, payload)
            conn.commit()

    def insert_or_update_strategy_metrics_daily(self, row: dict[str, Any]) -> None:
        sql = """
        INSERT INTO strategy_metrics_daily (
            metric_date_utc,
            sleeve_code,
            strategy_name,
            strategy_version_id,
            trades_closed,
            wins,
            losses,
            win_rate,
            avg_realized_pnl_pct,
            avg_realized_pnl_eur,
            gross_profit_eur,
            gross_loss_eur,
            profit_factor,
            avg_holding_minutes,
            prepare_to_enter_count,
            prepare_fail_count
        ) VALUES (
            %(metric_date_utc)s,
            %(sleeve_code)s,
            %(strategy_name)s,
            %(strategy_version_id)s,
            %(trades_closed)s,
            %(wins)s,
            %(losses)s,
            %(win_rate)s,
            %(avg_realized_pnl_pct)s,
            %(avg_realized_pnl_eur)s,
            %(gross_profit_eur)s,
            %(gross_loss_eur)s,
            %(profit_factor)s,
            %(avg_holding_minutes)s,
            %(prepare_to_enter_count)s,
            %(prepare_fail_count)s
        )
        ON DUPLICATE KEY UPDATE
            trades_closed = VALUES(trades_closed),
            wins = VALUES(wins),
            losses = VALUES(losses),
            win_rate = VALUES(win_rate),
            avg_realized_pnl_pct = VALUES(avg_realized_pnl_pct),
            avg_realized_pnl_eur = VALUES(avg_realized_pnl_eur),
            gross_profit_eur = VALUES(gross_profit_eur),
            gross_loss_eur = VALUES(gross_loss_eur),
            profit_factor = VALUES(profit_factor),
            avg_holding_minutes = VALUES(avg_holding_minutes),
            prepare_to_enter_count = VALUES(prepare_to_enter_count),
            prepare_fail_count = VALUES(prepare_fail_count)
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, row)
            conn.commit()

    def insert_or_update_state_transition_daily(self, row: dict[str, Any]) -> None:
        sql = """
        INSERT INTO state_transition_daily (
            metric_date_utc,
            sleeve_code,
            strategy_name,
            from_state,
            to_state,
            transition_count,
            avg_forward_return_24h_pct,
            avg_forward_return_72h_pct
        ) VALUES (
            %(metric_date_utc)s,
            %(sleeve_code)s,
            %(strategy_name)s,
            %(from_state)s,
            %(to_state)s,
            %(transition_count)s,
            %(avg_forward_return_24h_pct)s,
            %(avg_forward_return_72h_pct)s
        )
        ON DUPLICATE KEY UPDATE
            transition_count = state_transition_daily.transition_count + VALUES(transition_count),
            avg_forward_return_24h_pct = VALUES(avg_forward_return_24h_pct),
            avg_forward_return_72h_pct = VALUES(avg_forward_return_72h_pct)
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, row)
            conn.commit()

    def close_zero_quantity_open_lots(self, close_ts_utc: datetime) -> int:
        sql = """
        UPDATE position_lot
        SET
            status = 'CLOSED',
            close_ts_utc = %(close_ts_utc)s,
            exit_reason = 'Auto-closed zombie open lot with zero fraction/quantity.',
            last_transition_state = 'EXIT',
            last_update_ts_utc = UTC_TIMESTAMP()
        WHERE status = 'OPEN'
          AND (
              current_fraction <= 0
              OR quantity_units <= 0
          )
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {"close_ts_utc": close_ts_utc})
                affected = cur.rowcount
            conn.commit()
        return int(affected)
