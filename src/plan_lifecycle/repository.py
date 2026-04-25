from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.plan_lifecycle.models import LifecyclePlanRow, LifecycleReservationRow


EXPIRABLE_PLAN_STATES = {"IDLE", "PLANNED"}
RELEASABLE_PLAN_STATES = {"CANCELLED", "ABORTED", "EXPIRED"}
INVALIDATABLE_PLAN_STATES = {"IDLE", "PLANNED"}


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass
class PlanLifecycleRepository:
    def fetch_invalidatable_plans(
        self,
        *,
        account_id: int | None = None,
        sleeve_code: str | None = None,
        venue: str | None = None,
        limit: int = 100,
    ) -> list[LifecyclePlanRow]:
        clauses = [
            f"p.plan_state IN ({','.join(['%s'] * len(INVALIDATABLE_PLAN_STATES))})"
        ]
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

        params.append(limit)

        sql = f"""
        SELECT
            p.execution_plan_id,
            p.account_id,
            p.asset_id,
            a.symbol,
            p.sleeve_code,
            p.venue,
            p.desired_action,
            p.execution_mode,
            p.plan_state,
            p.valid_until_ts_utc,
            p.notes,
            s.selection_state,
            s.effective_selection_score
        FROM execution_plan p
        JOIN asset a
          ON a.asset_id = p.asset_id
        LEFT JOIN v_selection_latest_effective s
          ON s.asset_id = p.asset_id
         AND s.venue = p.venue
        WHERE {" AND ".join(clauses)}
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

        return [
            LifecyclePlanRow(
                execution_plan_id=int(row["execution_plan_id"]),
                account_id=int(row["account_id"]),
                asset_id=int(row["asset_id"]),
                symbol=str(row["symbol"]) if row["symbol"] is not None else None,
                sleeve_code=str(row["sleeve_code"]),
                venue=str(row["venue"]),
                desired_action=str(row["desired_action"]),
                execution_mode=str(row["execution_mode"]),
                plan_state=str(row["plan_state"]),
                valid_until_ts_utc=row["valid_until_ts_utc"],
                notes=str(row["notes"]) if row["notes"] is not None else None,
                selection_state=(
                    str(row["selection_state"]).upper()
                    if row["selection_state"] is not None
                    else None
                ),
                effective_selection_score=(
                    _to_decimal(row["effective_selection_score"])
                    if row["effective_selection_score"] is not None
                    else None
                ),
            )
            for row in rows
        ]

    def abort_plan(
        self,
        *,
        plan: LifecyclePlanRow,
        reason: str,
    ) -> None:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution_plan
                    SET
                        plan_state = 'ABORTED',
                        notes = CONCAT(COALESCE(notes, ''), ' | ABORTED: ', %s),
                        updated_ts_utc = CURRENT_TIMESTAMP()
                    WHERE execution_plan_id = %s
                    """,
                    [reason, plan.execution_plan_id],
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
                        "PLAN_ABORTED",
                        reason,
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

            conn.commit()
            return reservation.reserved_amount_eur
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
