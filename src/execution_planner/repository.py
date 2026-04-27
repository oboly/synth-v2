from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.execution_planner.models import OpenPositionForExit, PlannedExecution


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass
class ExecutionPlannerRepository:
    def fetch_reference_price_eur(
        self,
        asset_id: int,
        venue: str,
        interval_code: str = "1h",
    ) -> Decimal | None:
        sql = """
        SELECT close_price
        FROM obs_market_candle
        WHERE asset_id = %s
          AND venue = %s
          AND interval_code = %s
        ORDER BY close_ts_utc DESC
        LIMIT 1
        """

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, [asset_id, venue, interval_code])
                row = cur.fetchone()
        finally:
            conn.close()

        if not row:
            return None

        if isinstance(row, dict):
            return _to_decimal(row["close_price"])
        return _to_decimal(row[0])

    def fetch_open_position_for_exit(
        self,
        *,
        account_id: int,
        sleeve_code: str,
        venue: str,
        asset_id: int | None = None,
        symbol: str | None = None,
    ) -> OpenPositionForExit | None:
        clauses = [
            "pp.account_id = %s",
            "pp.sleeve_code = %s",
            "pp.venue = %s",
            "pp.position_status = 'OPEN'",
            "pp.qty > 0",
        ]
        params: list[Any] = [account_id, sleeve_code, venue]

        join_symbol = ""
        if symbol is not None:
            join_symbol = "JOIN asset a ON a.asset_id = pp.asset_id"
            clauses.append("a.symbol = %s")
            params.append(symbol)

        if asset_id is not None:
            clauses.append("pp.asset_id = %s")
            params.append(asset_id)

        sql = f"""
        SELECT
            pp.portfolio_position_id,
            pp.account_id,
            pp.sleeve_code,
            pp.asset_id,
            pp.venue,
            pp.qty,
            pp.avg_entry_price,
            pp.mark_price,
            pp.market_value_eur,
            pp.realized_pnl_eur,
            pp.unrealized_pnl_eur,
            pp.position_status
        FROM portfolio_position pp
        {join_symbol}
        WHERE {" AND ".join(clauses)}
        ORDER BY pp.portfolio_position_id DESC
        LIMIT 1
        """

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
        finally:
            conn.close()

        if not row:
            return None

        return OpenPositionForExit(
            portfolio_position_id=int(row["portfolio_position_id"]),
            account_id=int(row["account_id"]),
            sleeve_code=str(row["sleeve_code"]),
            asset_id=int(row["asset_id"]),
            venue=str(row["venue"]),
            qty=_to_decimal(row["qty"]),
            avg_entry_price=_to_decimal(row["avg_entry_price"]) if row["avg_entry_price"] is not None else None,
            mark_price=_to_decimal(row["mark_price"]) if row["mark_price"] is not None else None,
            market_value_eur=_to_decimal(row["market_value_eur"]),
            realized_pnl_eur=_to_decimal(row["realized_pnl_eur"]),
            unrealized_pnl_eur=_to_decimal(row["unrealized_pnl_eur"]),
            position_status=str(row["position_status"]),
        )

    def _insert_execution_plan(self, cur, plan: PlannedExecution) -> int:
        cur.execute(
            """
            INSERT INTO execution_plan (
                account_id,
                asset_id,
                sleeve_code,
                venue,
                side,
                desired_action,
                execution_mode,
                plan_ts_utc,
                valid_until_ts_utc,
                target_fraction,
                max_notional_eur,
                reference_price_eur,
                passive_price_eur,
                urgent_limit_price_eur,
                max_reprices,
                max_wait_seconds,
                max_chase_bps,
                min_spread_bps_for_capture,
                escalation_to_urgent_limit,
                abort_if_signal_invalidates,
                plan_state,
                notes
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            [
                plan.account_id,
                plan.asset_id,
                plan.sleeve_code,
                plan.venue,
                plan.side,
                plan.desired_action,
                plan.execution_mode,
                plan.plan_ts_utc,
                plan.valid_until_ts_utc,
                plan.target_fraction,
                plan.max_notional_eur,
                plan.reference_price_eur,
                plan.passive_price_eur,
                plan.urgent_limit_price_eur,
                plan.max_reprices,
                plan.max_wait_seconds,
                plan.max_chase_bps,
                plan.min_spread_bps_for_capture,
                int(plan.escalation_to_urgent_limit),
                int(plan.abort_if_signal_invalidates),
                plan.plan_state,
                plan.notes,
            ],
        )
        return int(cur.lastrowid)

    def create_plan_without_reservation(
        self,
        plan: PlannedExecution,
    ) -> int:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                execution_plan_id = self._insert_execution_plan(cur, plan)
            conn.commit()
            return execution_plan_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_plan_with_reservation(
        self,
        plan: PlannedExecution,
    ) -> tuple[int, int]:
        reserved_amount_eur = (
            _to_decimal(plan.max_notional_eur)
            if plan.max_notional_eur is not None
            else Decimal("0")
        )

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        portfolio_sleeve_id,
                        available_equity_eur,
                        reserved_equity_eur
                    FROM portfolio_sleeve
                    WHERE account_id = %s
                      AND sleeve_code = %s
                    FOR UPDATE
                    """,
                    [plan.account_id, plan.sleeve_code],
                )
                sleeve_row = cur.fetchone()

                available_equity_eur = _to_decimal(sleeve_row["available_equity_eur"])
                reserved_equity_existing = _to_decimal(sleeve_row["reserved_equity_eur"])

                if reserved_amount_eur > available_equity_eur:
                    raise ValueError("insufficient equity")

                execution_plan_id = self._insert_execution_plan(cur, plan)

                cur.execute(
                    """
                    INSERT INTO capital_reservation (
                        execution_plan_id,
                        account_id,
                        sleeve_code,
                        asset_id,
                        reserved_amount_eur,
                        reservation_state
                    ) VALUES (%s, %s, %s, %s, %s, 'ACTIVE')
                    """,
                    [
                        execution_plan_id,
                        plan.account_id,
                        plan.sleeve_code,
                        plan.asset_id,
                        reserved_amount_eur,
                    ],
                )

                cur.execute(
                    """
                    UPDATE portfolio_sleeve
                    SET
                        reserved_equity_eur = %s,
                        available_equity_eur = %s,
                        updated_ts_utc = CURRENT_TIMESTAMP()
                    WHERE account_id = %s
                      AND sleeve_code = %s
                    """,
                    [
                        reserved_equity_existing + reserved_amount_eur,
                        available_equity_eur - reserved_amount_eur,
                        plan.account_id,
                        plan.sleeve_code,
                    ],
                )

            conn.commit()
            return execution_plan_id, 1

        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_plan_without_reservation(
        self,
        plan: PlannedExecution,
    ) -> int:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution_plan (
                        account_id,
                        asset_id,
                        sleeve_code,
                        venue,
                        side,
                        desired_action,
                        execution_mode,
                        plan_ts_utc,
                        valid_until_ts_utc,
                        target_fraction,
                        max_notional_eur,
                        reference_price_eur,
                        passive_price_eur,
                        urgent_limit_price_eur,
                        max_reprices,
                        max_wait_seconds,
                        max_chase_bps,
                        min_spread_bps_for_capture,
                        escalation_to_urgent_limit,
                        abort_if_signal_invalidates,
                        plan_state,
                        notes
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    [
                        plan.account_id,
                        plan.asset_id,
                        plan.sleeve_code,
                        plan.venue,
                        plan.side,
                        plan.desired_action,
                        plan.execution_mode,
                        plan.plan_ts_utc,
                        plan.valid_until_ts_utc,
                        plan.target_fraction,
                        plan.max_notional_eur,
                        plan.reference_price_eur,
                        plan.passive_price_eur,
                        plan.urgent_limit_price_eur,
                        plan.max_reprices,
                        plan.max_wait_seconds,
                        plan.max_chase_bps,
                        plan.min_spread_bps_for_capture,
                        int(plan.escalation_to_urgent_limit),
                        int(plan.abort_if_signal_invalidates),
                        plan.plan_state,
                        plan.notes,
                    ],
                )
                execution_plan_id = int(cur.lastrowid)

            conn.commit()
            return execution_plan_id

        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


    def cancel_stale_preplan(
        self,
        *,
        execution_plan_id: int,
        reason: str,
    ) -> int:
        sql = """
        UPDATE execution_plan
        SET
            plan_state = 'CANCELLED',
            notes = CONCAT(
                COALESCE(notes, ''),
                ' | cancelled stale PREPARE_PLAN: ',
                %s
            ),
            updated_ts_utc = UTC_TIMESTAMP()
        WHERE execution_plan_id = %s
          AND desired_action = 'PREPARE_PLAN'
          AND plan_state = 'IDLE'
        """

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, [reason, execution_plan_id])
                affected_rows = int(cur.rowcount)
            conn.commit()
            return affected_rows
        finally:
            conn.close()


    def has_active_plan(
        self,
        *,
        account_id: int,
        sleeve_code: str,
        asset_id: int,
        venue: str,
    ) -> bool:
        sql = """
        SELECT 1
        FROM execution_plan
        WHERE account_id = %s
          AND sleeve_code = %s
          AND asset_id = %s
          AND venue = %s
          AND plan_state IN ('IDLE','PLANNED','PLACED','MONITOR_QUEUE','REPRICE_PENDING','ESCALATED')
        LIMIT 1
        """

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, [account_id, sleeve_code, asset_id, venue])
                return cur.fetchone() is not None
        finally:
            conn.close()


    def fetch_latest_active_plan(
        self,
        *,
        account_id: int,
        sleeve_code: str,
        asset_id: int,
        venue: str,
    ):
        sql = """
        SELECT *
        FROM execution_plan
        WHERE account_id = %s
          AND sleeve_code = %s
          AND asset_id = %s
          AND venue = %s
          AND plan_state IN ('IDLE','PLANNED','PLACED','MONITOR_QUEUE','REPRICE_PENDING','ESCALATED')
        ORDER BY execution_plan_id DESC
        LIMIT 1
        """

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, [account_id, sleeve_code, asset_id, venue])
                return cur.fetchone()
        finally:
            conn.close()


    def update_plan(
        self,
        *,
        execution_plan_id: int,
        target_fraction,
        desired_action: str,
        notes: str,
    ):
        sql = """
        UPDATE execution_plan
        SET
            target_fraction = %s,
            desired_action = %s,
            notes = %s,
            updated_ts_utc = CURRENT_TIMESTAMP()
        WHERE execution_plan_id = %s
        """

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, [
                    target_fraction,
                    desired_action,
                    notes,
                    execution_plan_id,
                ])
            conn.commit()
        finally:
            conn.close()

