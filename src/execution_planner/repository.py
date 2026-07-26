from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

from src.execution_planner.sell_authority_guard_v1 import (
    UnauthorizedManualExecutionCallError,
)
from src.execution_planner.models import OpenPositionForExit, PlannedExecution


ACTIVE_PLAN_STATES: tuple[str, ...] = (
    "IDLE",
    "PLANNED",
    "PLACED",
    "MONITOR_QUEUE",
    "REPRICE_PENDING",
    "ESCALATED",
)


def _legacy_get_connection(*, database: str | None = None):
    from src.common.db import get_connection

    return get_connection(database=database)


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass
class ExecutionPlannerRepository:
    connection_factory: Callable[..., Any] = field(
        default=_legacy_get_connection,
        repr=False,
        compare=False,
    )

    @staticmethod
    def _validate_plan_contract(plan: PlannedExecution) -> None:
        if plan.side == "SELL" or plan.requested_side == "SELL":
            raise UnauthorizedManualExecutionCallError(
                "generic execution-plan persistence is BUY-only; manual SELL "
                "requires manual_execution_service_v1.process()"
            )
        if plan.trading_account_id is None or plan.trading_account_id <= 0:
            raise ValueError("TRADING_ACCOUNT_ID_REQUIRED")
        if plan.execution_mode not in {"PAPER", "LIVE"}:
            raise ValueError("EXECUTION_MODE_NOT_CANONICAL")
        if plan.execution_intent is None or plan.execution_intent == "":
            raise ValueError("EXECUTION_INTENT_REQUIRED")
        if plan.execution_intent != plan.execution_intent.strip():
            raise ValueError("EXECUTION_INTENT_NOT_CANONICAL")
        if plan.action_type not in {"PLACE_ORDER", "CANCEL_ORDER", "MONITOR_ORDER"}:
            raise ValueError("ACTION_TYPE_NOT_CANONICAL")
        if plan.requested_side not in {"BUY", "SELL"} or plan.side != plan.requested_side:
            raise ValueError("REQUESTED_SIDE_NOT_CANONICAL")
        if plan.market is None or plan.market == "" or plan.market != plan.market.strip():
            raise ValueError("MARKET_REQUIRED")

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

        conn = self.connection_factory()
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

        join_symbol = "JOIN asset a ON a.asset_id = pp.asset_id"
        if symbol is not None:
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
            CONCAT(a.symbol, '-EUR') AS market,
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

        conn = self.connection_factory()
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
            market=str(row["market"]),
            qty=_to_decimal(row["qty"]),
            avg_entry_price=_to_decimal(row["avg_entry_price"]) if row["avg_entry_price"] is not None else None,
            mark_price=_to_decimal(row["mark_price"]) if row["mark_price"] is not None else None,
            market_value_eur=_to_decimal(row["market_value_eur"]),
            realized_pnl_eur=_to_decimal(row["realized_pnl_eur"]),
            unrealized_pnl_eur=_to_decimal(row["unrealized_pnl_eur"]),
            position_status=str(row["position_status"]),
        )

    def _insert_execution_plan(self, cur: Any, plan: PlannedExecution) -> int:
        self._validate_plan_contract(plan)
        cur.execute(
            """
            INSERT INTO execution_plan (
                account_id,
                trading_account_id,
                asset_id,
                sleeve_code,
                venue,
                market,
                side,
                desired_action,
                execution_intent,
                action_type,
                requested_side,
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
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            [
                plan.account_id,
                plan.trading_account_id,
                plan.asset_id,
                plan.sleeve_code,
                plan.venue,
                plan.market,
                plan.side,
                plan.desired_action,
                plan.execution_intent,
                plan.action_type,
                plan.requested_side,
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
        self._validate_plan_contract(plan)
        conn = self.connection_factory()
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

    def create_exit_plan_without_reservation(
        self,
        plan: PlannedExecution,
    ) -> int:
        raise UnauthorizedManualExecutionCallError(
            "exit-plan persistence without the canonical manual approval is disabled"
        )

    def create_plan_with_reservation(
        self,
        plan: PlannedExecution,
    ) -> tuple[int, int]:
        self._validate_plan_contract(plan)
        reserved_amount_eur = (
            _to_decimal(plan.max_notional_eur)
            if plan.max_notional_eur is not None
            else Decimal("0")
        )

        conn = self.connection_factory()
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

                if not sleeve_row:
                    raise ValueError(
                        f"portfolio_sleeve not found for account_id={plan.account_id} "
                        f"sleeve_code={plan.sleeve_code}"
                    )

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

        conn = self.connection_factory()
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
        placeholders = ",".join(["%s"] * len(ACTIVE_PLAN_STATES))
        sql = f"""
        SELECT 1
        FROM execution_plan
        WHERE account_id = %s
          AND sleeve_code = %s
          AND asset_id = %s
          AND venue = %s
          AND plan_state IN ({placeholders})
        LIMIT 1
        """

        conn = self.connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    [
                        account_id,
                        sleeve_code,
                        asset_id,
                        venue,
                        *ACTIVE_PLAN_STATES,
                    ],
                )
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
    ) -> dict[str, Any] | None:
        placeholders = ",".join(["%s"] * len(ACTIVE_PLAN_STATES))
        sql = f"""
        SELECT *
        FROM execution_plan
        WHERE account_id = %s
          AND sleeve_code = %s
          AND asset_id = %s
          AND venue = %s
          AND plan_state IN ({placeholders})
        ORDER BY execution_plan_id DESC
        LIMIT 1
        """

        conn = self.connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    [
                        account_id,
                        sleeve_code,
                        asset_id,
                        venue,
                        *ACTIVE_PLAN_STATES,
                    ],
                )
                return cur.fetchone()
        finally:
            conn.close()

    def update_plan(
        self,
        *,
        execution_plan_id: int,
        plan: PlannedExecution,
    ) -> None:
        self._validate_plan_contract(plan)
        if plan.execution_mode == "LIVE" and plan.valid_until_ts_utc is None:
            raise ValueError("LIVE_PLAN_EXPIRY_REQUIRED")
        sql = """
        UPDATE execution_plan
        SET
            target_fraction = %s,
            desired_action = %s,
            execution_intent = %s,
            trading_account_id = %s,
            market = %s,
            side = %s,
            requested_side = %s,
            action_type = %s,
            execution_mode = %s,
            valid_until_ts_utc = %s,
            notes = %s,
            updated_ts_utc = CURRENT_TIMESTAMP()
        WHERE execution_plan_id = %s
        """

        conn = self.connection_factory()
        try:
            with conn.cursor() as cur:
                self._validate_plan_contract(plan)
                cur.execute(
                    sql,
                    [
                        plan.target_fraction,
                        plan.desired_action,
                        plan.execution_intent,
                        plan.trading_account_id,
                        plan.market,
                        plan.side,
                        plan.requested_side,
                        plan.action_type,
                        plan.execution_mode,
                        plan.valid_until_ts_utc,
                        plan.notes,
                        execution_plan_id,
                    ],
                )
                if cur.rowcount != 1:
                    raise ValueError("EXECUTION_PLAN_UPDATE_NOT_FOUND")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
