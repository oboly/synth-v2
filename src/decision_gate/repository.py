from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.common.db import db_cursor
from src.decision_gate.models import (
    ACTIVE_PLAN_STATES,
    DuplicateState,
    OPEN_POSITION_STATUSES,
    SelectionInputRow,
    SleeveState,
)


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _unwrap_cursor(db_obj: Any) -> Any:
    if isinstance(db_obj, tuple):
        return db_obj[1]
    return db_obj


@dataclass
class DecisionGateRepository:

    def fetch_selection_rows(
        self,
        venue: str,
        asset_id: int | None = None,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> list[SelectionInputRow]:

        clauses = ["venue = %(venue)s"]
        params: dict[str, Any] = {"venue": venue}

        if asset_id is not None:
            clauses.append("asset_id = %(asset_id)s")
            params["asset_id"] = asset_id

        if symbol is not None:
            clauses.append("symbol = %(symbol)s")
            params["symbol"] = symbol

        sql = f"""
        SELECT
            selection_state_id,
            asset_id,
            symbol,
            venue,
            asof_ts_utc,
            selection_state,
            selection_bias,
            priority_rank,
            effective_selection_score,
            summary_text,
            regime_label_4h
        FROM v_selection_latest_effective
        WHERE {" AND ".join(clauses)}
        ORDER BY
            priority_rank IS NULL,
            priority_rank ASC,
            effective_selection_score DESC,
            symbol ASC
        """

        if limit is not None:
            sql += "\nLIMIT %(limit)s"
            params["limit"] = int(limit)

        with db_cursor() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        return [
            SelectionInputRow(
                selection_state_id=int(r["selection_state_id"]),
                asset_id=int(r["asset_id"]),
                symbol=str(r["symbol"]),
                venue=str(r["venue"]),
                asof_ts_utc=str(r["asof_ts_utc"]) if r["asof_ts_utc"] else None,
                selection_state=str(r["selection_state"]).upper(),
                selection_bias=str(r["selection_bias"]) if r["selection_bias"] else None,
                priority_rank=int(r["priority_rank"]) if r["priority_rank"] else None,
                effective_selection_score=_to_decimal(r["effective_selection_score"]) if r["effective_selection_score"] else None,
                summary_text=str(r["summary_text"]) if r["summary_text"] else None,
                regime_label_4h=str(r["regime_label_4h"]) if r["regime_label_4h"] else None,
            )
            for r in rows
        ]

    def fetch_sleeve_state(self, account_id: int, sleeve_code: str) -> SleeveState | None:
        sql = """
        SELECT
            account_id,
            sleeve_code,
            sleeve_status,
            target_weight,
            allocated_equity_eur,
            reserved_equity_eur,
            deployed_equity_eur,
            available_equity_eur
        FROM portfolio_sleeve
        WHERE account_id = %(account_id)s
          AND sleeve_code = %(sleeve_code)s
        LIMIT 1
        """

        with db_cursor() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(sql, {"account_id": account_id, "sleeve_code": sleeve_code})
            r = cursor.fetchone()

        if not r:
            return None

        return SleeveState(
            account_id=int(r["account_id"]),
            sleeve_code=str(r["sleeve_code"]),
            sleeve_status=str(r["sleeve_status"]).upper(),
            target_weight=_to_decimal(r["target_weight"]),
            allocated_equity_eur=_to_decimal(r["allocated_equity_eur"]),
            reserved_equity_eur=_to_decimal(r["reserved_equity_eur"]),
            deployed_equity_eur=_to_decimal(r["deployed_equity_eur"]),
            available_equity_eur=_to_decimal(r["available_equity_eur"]),
        )

    def fetch_duplicate_state(self, account_id: int, sleeve_code: str, asset_id: int, venue: str) -> DuplicateState:
        with db_cursor() as db_obj:
            cursor = _unwrap_cursor(db_obj)

            cursor.execute(
                f"""
                SELECT EXISTS(
                    SELECT 1
                    FROM execution_plan
                    WHERE account_id = %s
                      AND sleeve_code = %s
                      AND asset_id = %s
                      AND venue = %s
                      AND plan_state IN ({",".join(["%s"] * len(ACTIVE_PLAN_STATES))})
                ) AS v
                """,
                [account_id, sleeve_code, asset_id, venue, *sorted(ACTIVE_PLAN_STATES)],
            )
            plan = cursor.fetchone()["v"]

            cursor.execute(
                f"""
                SELECT EXISTS(
                    SELECT 1
                    FROM portfolio_position
                    WHERE account_id = %s
                      AND sleeve_code = %s
                      AND asset_id = %s
                      AND venue = %s
                      AND position_status IN ({",".join(["%s"] * len(OPEN_POSITION_STATUSES))})
                      AND qty > 0
                ) AS v
                """,
                [account_id, sleeve_code, asset_id, venue, *sorted(OPEN_POSITION_STATUSES)],
            )
            pos = cursor.fetchone()["v"]

        return DuplicateState(bool(plan), bool(pos))

    def fetch_open_order_flag(self, account_id: int, sleeve_code: str, asset_id: int, venue: str) -> bool:
        return False
