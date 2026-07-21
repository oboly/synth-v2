from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

from src.executor.models import CapitalReservationRow, ExecutionPlanRow


ACTIVE_EXECUTOR_PLAN_STATES = {"IDLE", "PLANNED"}

EXECUTABLE_DESIRED_ACTIONS = {
    "SPREAD_CAPTURE_PASSIVE",
    "ENTER",
    "ENTER_LONG",
    "CLOSE_POSITION_MARKET_PAPER",
}


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
class ExecutorRepository:
    connection_factory: Callable[..., Any] = field(
        default=_legacy_get_connection,
        repr=False,
        compare=False,
    )

    def fetch_open_plans(
        self,
        *,
        account_id: int | None = None,
        sleeve_code: str | None = None,
        venue: str | None = None,
        limit: int = 20,
    ) -> list[ExecutionPlanRow]:
        clauses = [
            f"plan_state IN ({','.join(['%s'] * len(ACTIVE_EXECUTOR_PLAN_STATES))})",
            f"desired_action IN ({','.join(['%s'] * len(EXECUTABLE_DESIRED_ACTIONS))})",
        ]
        params: list[Any] = [
            *sorted(ACTIVE_EXECUTOR_PLAN_STATES),
            *sorted(EXECUTABLE_DESIRED_ACTIONS),
        ]

        if account_id is not None:
            clauses.append("account_id = %s")
            params.append(account_id)

        if sleeve_code is not None:
            clauses.append("sleeve_code = %s")
            params.append(sleeve_code)

        if venue is not None:
            clauses.append("venue = %s")
            params.append(venue)

        params.append(limit)

        sql = f"""
        SELECT
            execution_plan_id,
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
        FROM execution_plan
        WHERE {" AND ".join(clauses)}
        ORDER BY execution_plan_id ASC
        LIMIT %s
        """

        conn = self.connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()

        out: list[ExecutionPlanRow] = []
        for row in rows:
            out.append(
                ExecutionPlanRow(
                    execution_plan_id=int(row["execution_plan_id"]),
                    account_id=int(row["account_id"]),
                    asset_id=int(row["asset_id"]),
                    sleeve_code=str(row["sleeve_code"]),
                    venue=str(row["venue"]),
                    side=str(row["side"]),
                    desired_action=str(row["desired_action"]),
                    execution_mode=str(row["execution_mode"]),
                    plan_ts_utc=row["plan_ts_utc"],
                    valid_until_ts_utc=row["valid_until_ts_utc"],
                    target_fraction=_to_decimal(row["target_fraction"]),
                    max_notional_eur=_to_decimal(row["max_notional_eur"]) if row["max_notional_eur"] is not None else None,
                    reference_price_eur=_to_decimal(row["reference_price_eur"]) if row["reference_price_eur"] is not None else None,
                    passive_price_eur=_to_decimal(row["passive_price_eur"]) if row["passive_price_eur"] is not None else None,
                    urgent_limit_price_eur=_to_decimal(row["urgent_limit_price_eur"]) if row["urgent_limit_price_eur"] is not None else None,
                    max_reprices=int(row["max_reprices"]),
                    max_wait_seconds=int(row["max_wait_seconds"]),
                    max_chase_bps=_to_decimal(row["max_chase_bps"]),
                    min_spread_bps_for_capture=_to_decimal(row["min_spread_bps_for_capture"]),
                    escalation_to_urgent_limit=bool(row["escalation_to_urgent_limit"]),
                    abort_if_signal_invalidates=bool(row["abort_if_signal_invalidates"]),
                    plan_state=str(row["plan_state"]),
                    notes=str(row["notes"]) if row["notes"] is not None else None,
                )
            )
        return out

    def fetch_symbol(self, asset_id: int) -> str | None:
        sql = "SELECT symbol FROM asset WHERE asset_id = %s LIMIT 1"
        conn = self.connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, [asset_id])
                row = cur.fetchone()
        finally:
            conn.close()

        if not row:
            return None
        if isinstance(row, dict):
            return str(row["symbol"])
        return str(row[0])

    def fetch_latest_price_eur(
        self,
        *,
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

    def fetch_active_reservation(self, execution_plan_id: int) -> CapitalReservationRow | None:
        sql = """
        SELECT
            capital_reservation_id,
            execution_plan_id,
            account_id,
            sleeve_code,
            asset_id,
            reserved_amount_eur,
            reservation_state
        FROM capital_reservation
        WHERE execution_plan_id = %s
          AND reservation_state = 'ACTIVE'
        LIMIT 1
        """
        conn = self.connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, [execution_plan_id])
                row = cur.fetchone()
        finally:
            conn.close()

        if not row:
            return None

        return CapitalReservationRow(
            capital_reservation_id=int(row["capital_reservation_id"]),
            execution_plan_id=int(row["execution_plan_id"]),
            account_id=int(row["account_id"]),
            sleeve_code=str(row["sleeve_code"]),
            asset_id=int(row["asset_id"]),
            reserved_amount_eur=_to_decimal(row["reserved_amount_eur"]),
            reservation_state=str(row["reservation_state"]),
        )

    def fill_passive_plan_paper(
        self,
        *,
        plan: ExecutionPlanRow,
        fill_price_eur: Decimal,
    ) -> tuple[Decimal, bool]:
        conn = self.connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        capital_reservation_id,
                        reserved_amount_eur
                    FROM capital_reservation
                    WHERE execution_plan_id = %s
                      AND reservation_state = 'ACTIVE'
                    LIMIT 1
                    FOR UPDATE
                    """,
                    [plan.execution_plan_id],
                )
                reservation_row = cur.fetchone()

                if not reservation_row:
                    raise ValueError(
                        f"Active capital_reservation not found for execution_plan_id={plan.execution_plan_id}"
                    )

                reserved_amount_eur = _to_decimal(reservation_row["reserved_amount_eur"])
                capital_reservation_id = int(reservation_row["capital_reservation_id"])

                if fill_price_eur <= Decimal("0"):
                    raise ValueError("fill_price_eur must be > 0")

                fill_qty = (reserved_amount_eur / fill_price_eur)

                cur.execute(
                    """
                    UPDATE execution_plan
                    SET
                        plan_state = 'FILLED',
                        passive_price_eur = %s,
                        updated_ts_utc = CURRENT_TIMESTAMP()
                    WHERE execution_plan_id = %s
                    """,
                    [fill_price_eur, plan.execution_plan_id],
                )

                cur.execute(
                    """
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
                        qty,
                        fill_qty,
                        fill_price,
                        notes
                    ) VALUES (
                        %s, %s, %s, %s, CURRENT_TIMESTAMP(),
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    [
                        plan.execution_plan_id,
                        plan.account_id,
                        plan.asset_id,
                        plan.sleeve_code,
                        "PAPER_FILL_PASSIVE",
                        "PASSIVE_PLAN_FILLED_IN_PAPER",
                        plan.side,
                        fill_price_eur,
                        fill_qty,
                        fill_qty,
                        fill_price_eur,
                        plan.notes,
                    ],
                )

                cur.execute(
                    """
                    INSERT INTO portfolio_position (
                        account_id,
                        sleeve_code,
                        asset_id,
                        venue,
                        position_side,
                        qty,
                        avg_entry_price,
                        mark_price,
                        market_value_eur,
                        realized_pnl_eur,
                        unrealized_pnl_eur,
                        position_status,
                        opened_ts_utc
                    ) VALUES (
                        %s, %s, %s, %s, 'LONG',
                        %s, %s, %s, %s, 0, 0, 'OPEN', CURRENT_TIMESTAMP()
                    )
                    ON DUPLICATE KEY UPDATE
                        qty = qty + VALUES(qty),
                        avg_entry_price = VALUES(avg_entry_price),
                        mark_price = VALUES(mark_price),
                        market_value_eur = market_value_eur + VALUES(market_value_eur),
                        position_status = 'OPEN',
                        updated_ts_utc = CURRENT_TIMESTAMP()
                    """,
                    [
                        plan.account_id,
                        plan.sleeve_code,
                        plan.asset_id,
                        plan.venue,
                        fill_qty,
                        fill_price_eur,
                        fill_price_eur,
                        reserved_amount_eur,
                    ],
                )

                cur.execute(
                    """
                    UPDATE capital_reservation
                    SET
                        reservation_state = 'RELEASED',
                        released_ts_utc = CURRENT_TIMESTAMP(),
                        updated_ts_utc = CURRENT_TIMESTAMP()
                    WHERE capital_reservation_id = %s
                    """,
                    [capital_reservation_id],
                )

                cur.execute(
                    """
                    SELECT
                        reserved_equity_eur,
                        deployed_equity_eur
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
                        f"portfolio_sleeve not found for account_id={plan.account_id} sleeve_code={plan.sleeve_code}"
                    )

                reserved_equity_eur = _to_decimal(sleeve_row["reserved_equity_eur"])
                deployed_equity_eur = _to_decimal(sleeve_row["deployed_equity_eur"])

                new_reserved = reserved_equity_eur - reserved_amount_eur
                if new_reserved < Decimal("0"):
                    new_reserved = Decimal("0")

                cur.execute(
                    """
                    UPDATE portfolio_sleeve
                    SET
                        reserved_equity_eur = %s,
                        deployed_equity_eur = %s,
                        updated_ts_utc = CURRENT_TIMESTAMP()
                    WHERE account_id = %s
                      AND sleeve_code = %s
                    """,
                    [
                        new_reserved,
                        deployed_equity_eur + reserved_amount_eur,
                        plan.account_id,
                        plan.sleeve_code,
                    ],
                )

            conn.commit()
            return fill_qty, True

        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def fill_close_position_market_paper(
        self,
        *,
        plan: ExecutionPlanRow,
        fill_price_eur: Decimal,
    ) -> tuple[Decimal, Decimal, bool]:
        conn = self.connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        portfolio_position_id,
                        qty,
                        avg_entry_price,
                        market_value_eur,
                        realized_pnl_eur
                    FROM portfolio_position
                    WHERE account_id = %s
                      AND sleeve_code = %s
                      AND asset_id = %s
                      AND venue = %s
                      AND position_status = 'OPEN'
                      AND qty > 0
                    LIMIT 1
                    FOR UPDATE
                    """,
                    [plan.account_id, plan.sleeve_code, plan.asset_id, plan.venue],
                )
                pos = cur.fetchone()

                if not pos:
                    raise ValueError(
                        f"Open portfolio_position not found for account_id={plan.account_id} "
                        f"sleeve_code={plan.sleeve_code} asset_id={plan.asset_id}"
                    )

                portfolio_position_id = int(pos["portfolio_position_id"])
                qty = _to_decimal(pos["qty"])
                avg_entry_price = _to_decimal(pos["avg_entry_price"]) if pos["avg_entry_price"] is not None else Decimal("0")
                current_market_value_eur = _to_decimal(pos["market_value_eur"])
                realized_pnl_existing = _to_decimal(pos["realized_pnl_eur"])

                exit_notional_eur = qty * fill_price_eur
                realized_pnl_delta = qty * (fill_price_eur - avg_entry_price)

                cur.execute(
                    """
                    UPDATE execution_plan
                    SET
                        plan_state = 'FILLED',
                        passive_price_eur = %s,
                        updated_ts_utc = CURRENT_TIMESTAMP()
                    WHERE execution_plan_id = %s
                    """,
                    [fill_price_eur, plan.execution_plan_id],
                )

                cur.execute(
                    """
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
                        qty,
                        fill_qty,
                        fill_price,
                        notes
                    ) VALUES (
                        %s, %s, %s, %s, CURRENT_TIMESTAMP(),
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    [
                        plan.execution_plan_id,
                        plan.account_id,
                        plan.asset_id,
                        plan.sleeve_code,
                        "PAPER_FILL_CLOSE",
                        "CLOSE_POSITION_FILLED_IN_PAPER",
                        plan.side,
                        fill_price_eur,
                        qty,
                        qty,
                        fill_price_eur,
                        plan.notes,
                    ],
                )

                cur.execute(
                    """
                    UPDATE portfolio_position
                    SET
                        qty = 0,
                        mark_price = %s,
                        market_value_eur = 0,
                        realized_pnl_eur = %s,
                        unrealized_pnl_eur = 0,
                        position_status = 'CLOSED',
                        updated_ts_utc = CURRENT_TIMESTAMP()
                    WHERE portfolio_position_id = %s
                    """,
                    [
                        fill_price_eur,
                        realized_pnl_existing + realized_pnl_delta,
                        portfolio_position_id,
                    ],
                )

                cur.execute(
                    """
                    SELECT
                        deployed_equity_eur,
                        available_equity_eur
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
                        f"portfolio_sleeve not found for account_id={plan.account_id} sleeve_code={plan.sleeve_code}"
                    )

                deployed_equity_eur = _to_decimal(sleeve_row["deployed_equity_eur"])
                available_equity_eur = _to_decimal(sleeve_row["available_equity_eur"])

                new_deployed = deployed_equity_eur - current_market_value_eur
                if new_deployed < Decimal("0"):
                    new_deployed = Decimal("0")

                cur.execute(
                    """
                    UPDATE portfolio_sleeve
                    SET
                        deployed_equity_eur = %s,
                        available_equity_eur = %s,
                        updated_ts_utc = CURRENT_TIMESTAMP()
                    WHERE account_id = %s
                      AND sleeve_code = %s
                    """,
                    [
                        new_deployed,
                        available_equity_eur + exit_notional_eur,
                        plan.account_id,
                        plan.sleeve_code,
                    ],
                )

            conn.commit()
            return qty, realized_pnl_delta, True

        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
