from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.plan_lifecycle.models import LifecyclePlanRow, LifecycleReservationRow


EXPIRABLE_PLAN_STATES = {"IDLE", "PLANNED"}
RELEASABLE_PLAN_STATES = {"CANCELLED", "ABORTED", "EXPIRED"}
INVALIDATABLE_PLAN_STATES = {"IDLE", "PLANNED"}
VALID_SELECTION_STATES_FOR_ACTIVE_PLAN = {"PREPARE", "BUY_READY"}


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass
class PlanLifecycleRepository:
    def fetch_symbol(self, asset_id: int) -> str | None:
        sql = "SELECT symbol FROM asset WHERE asset_id = %s LIMIT 1"
        conn = get_connection()
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

    def fetch_invalidatable_active_plans(
        self,
        *,
        account_id: int | None = None,
        sleeve_code: str | None = None,
        venue: str | None = None,
        limit: int = 50,
    ) -> list[LifecyclePlanRow]:
        clauses = [f"p.plan_state IN ({','.join(['%s'] * len(INVALIDATABLE_PLAN_STATES))})"]
        params: list[Any] = sorted(INVALIDATABLE_PLAN_STATES)

        if account_id is not None:
            clauses.append("p.account_id = %s")
            params.append(account_id)

        if sleeve_code is not None:
            clauses.append("p.sleeve_code = %s")
            params.append(sleeve_code)

        if venue is not None:
            clauses.append("p.venue = %s")
            params.append(venue)

        valid_states_sql = ",".join(["%s"] * len(VALID_SELECTION_STATES_FOR_ACTIVE_PLAN))
        params.extend(sorted(VALID_SELECTION_STATES_FOR_ACTIVE_PLAN))
        params.append(limit)

        sql = f"""
        SELECT
            p.execution_plan_id,
            p.account_id,
            p.asset_id,
            p.sleeve_code,
            p.venue,
            p.desired_action,
            p.execution_mode,
            p.plan_state,
            p.valid_until_ts_utc,
            p.notes
        FROM execution_plan p
        WHERE {" AND ".join(clauses)}
          AND NOT EXISTS (
              SELECT 1
              FROM v_selection_latest_effective s
              WHERE s.asset_id = p.asset_id
                AND s.venue = p.venue
                AND s.selection_state IN ({valid_states_sql})
          )
        ORDER BY p.execution_plan_id ASC
        LIMIT %s
        """

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()

        out: list[LifecyclePlanRow] = []
        for row in rows:
            out.append(
                LifecyclePlanRow(
                    execution_plan_id=int(row["execution_plan_id"]),
                    account_id=int(row["account_id"]),
                    asset_id=int(row["asset_id"]),
                    sleeve_code=str(row["sleeve_code"]),
                    venue=str(row["venue"]),
                    desired_action=str(row["desired_action"]),
                    execution_mode=str(row["execution_mode"]),
                    plan_state=str(row["plan_state"]),
                    valid_until_ts_utc=row["valid_until_ts_utc"],
                    notes=str(row["notes"]) if row["notes"] is not None else None,
                )
            )
        return out

    def invalidate_plan_for_selection_drop(
        self,
        plan: LifecyclePlanRow,
    ) -> None:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution_plan
                    SET
                        plan_state = 'CANCELLED',
                        updated_ts_utc = CURRENT_TIMESTAMP()
                    WHERE execution_plan_id = %s
                      AND plan_state IN ('IDLE', 'PLANNED')
                    """,
                    [plan.execution_plan_id],
                )

                if cur.rowcount > 0:
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
                            notes
                        ) VALUES (
                            %s, %s, %s, %s, CURRENT_TIMESTAMP(),
                            %s, %s, %s, %s
                        )
                        """,
                        [
                            plan.execution_plan_id,
                            plan.account_id,
                            plan.asset_id,
                            plan.sleeve_code,
                            "PLAN_INVALIDATED",
                            "LATEST_SELECTION_NOT_ELIGIBLE",
                            None,
                            plan.notes,
                        ],
                    )

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def expire_due_plans(
        self,
        *,
        account_id: int | None = None,
        sleeve_code: str | None = None,
        venue: str | None = None,
    ) -> int:
        clauses = [f"plan_state IN ({','.join(['%s'] * len(EXPIRABLE_PLAN_STATES))})"]
        params: list[Any] = sorted(EXPIRABLE_PLAN_STATES)

        clauses.append("valid_until_ts_utc IS NOT NULL")
        clauses.append("valid_until_ts_utc < CURRENT_TIMESTAMP()")

        if account_id is not None:
            clauses.append("account_id = %s")
            params.append(account_id)

        if sleeve_code is not None:
            clauses.append("sleeve_code = %s")
            params.append(sleeve_code)

        if venue is not None:
            clauses.append("venue = %s")
            params.append(venue)

        sql = f"""
        UPDATE execution_plan
        SET
            plan_state = 'EXPIRED',
            updated_ts_utc = CURRENT_TIMESTAMP()
        WHERE {" AND ".join(clauses)}
        """

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(sql, params)
            conn.commit()
            return int(affected)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def fetch_releasable_plans(
        self,
        *,
        account_id: int | None = None,
        sleeve_code: str | None = None,
        venue: str | None = None,
        limit: int = 50,
    ) -> list[LifecyclePlanRow]:
        clauses = [f"p.plan_state IN ({','.join(['%s'] * len(RELEASABLE_PLAN_STATES))})"]
        params: list[Any] = sorted(RELEASABLE_PLAN_STATES)

        if account_id is not None:
            clauses.append("p.account_id = %s")
            params.append(account_id)

        if sleeve_code is not None:
            clauses.append("p.sleeve_code = %s")
            params.append(sleeve_code)

        if venue is not None:
            clauses.append("p.venue = %s")
            params.append(venue)

        params.append(limit)

        sql = f"""
        SELECT
            p.execution_plan_id,
            p.account_id,
            p.asset_id,
            p.sleeve_code,
            p.venue,
            p.desired_action,
            p.execution_mode,
            p.plan_state,
            p.valid_until_ts_utc,
            p.notes
        FROM execution_plan p
        WHERE {" AND ".join(clauses)}
          AND EXISTS (
              SELECT 1
              FROM capital_reservation cr
              WHERE cr.execution_plan_id = p.execution_plan_id
                AND cr.reservation_state = 'ACTIVE'
          )
        ORDER BY p.execution_plan_id ASC
        LIMIT %s
        """

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()

        out: list[LifecyclePlanRow] = []
        for row in rows:
            out.append(
                LifecyclePlanRow(
                    execution_plan_id=int(row["execution_plan_id"]),
                    account_id=int(row["account_id"]),
                    asset_id=int(row["asset_id"]),
                    sleeve_code=str(row["sleeve_code"]),
                    venue=str(row["venue"]),
                    desired_action=str(row["desired_action"]),
                    execution_mode=str(row["execution_mode"]),
                    plan_state=str(row["plan_state"]),
                    valid_until_ts_utc=row["valid_until_ts_utc"],
                    notes=str(row["notes"]) if row["notes"] is not None else None,
                )
            )
        return out

    def release_reservation_for_plan(
        self,
        plan: LifecyclePlanRow,
    ) -> Decimal:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
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
                    FOR UPDATE
                    """,
                    [plan.execution_plan_id],
                )
                row = cur.fetchone()

                if not row:
                    conn.rollback()
                    return Decimal("0")

                reservation = LifecycleReservationRow(
                    capital_reservation_id=int(row["capital_reservation_id"]),
                    execution_plan_id=int(row["execution_plan_id"]),
                    account_id=int(row["account_id"]),
                    sleeve_code=str(row["sleeve_code"]),
                    asset_id=int(row["asset_id"]),
                    reserved_amount_eur=_to_decimal(row["reserved_amount_eur"]),
                    reservation_state=str(row["reservation_state"]),
                )

                cur.execute(
                    """
                    SELECT
                        reserved_equity_eur,
                        available_equity_eur
                    FROM portfolio_sleeve
                    WHERE account_id = %s
                      AND sleeve_code = %s
                    FOR UPDATE
                    """,
                    [reservation.account_id, reservation.sleeve_code],
                )
                sleeve_row = cur.fetchone()

                if not sleeve_row:
                    raise ValueError(
                        f"portfolio_sleeve not found for account_id={reservation.account_id} "
                        f"sleeve_code={reservation.sleeve_code}"
                    )

                reserved_equity_eur = _to_decimal(sleeve_row["reserved_equity_eur"])
                available_equity_eur = _to_decimal(sleeve_row["available_equity_eur"])

                new_reserved = reserved_equity_eur - reservation.reserved_amount_eur
                if new_reserved < Decimal("0"):
                    new_reserved = Decimal("0")

                cur.execute(
                    """
                    UPDATE capital_reservation
                    SET
                        reservation_state = 'RELEASED',
                        released_ts_utc = CURRENT_TIMESTAMP(),
                        updated_ts_utc = CURRENT_TIMESTAMP()
                    WHERE capital_reservation_id = %s
                    """,
                    [reservation.capital_reservation_id],
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
                        new_reserved,
                        available_equity_eur + reservation.reserved_amount_eur,
                        reservation.account_id,
                        reservation.sleeve_code,
                    ],
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
                        notes
                    ) VALUES (
                        %s, %s, %s, %s, CURRENT_TIMESTAMP(),
                        %s, %s, %s, %s
                    )
                    """,
                    [
                        plan.execution_plan_id,
                        plan.account_id,
                        plan.asset_id,
                        plan.sleeve_code,
                        "CAPITAL_RESERVATION_RELEASED",
                        f"PLAN_{plan.plan_state}_RESERVATION_RELEASED",
                        None,
                        plan.notes,
                    ],
                )

            conn.commit()
            return reservation.reserved_amount_eur

        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
