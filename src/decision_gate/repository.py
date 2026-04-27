from __future__ import annotations

import json
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


TRADE_SETUP_FILTER_TABLE = "synth_bt.trade_setup_filter_observation"
TRADE_SETUP_FILTER_NAME = "trade_setup_filter_v1"
TRADE_SETUP_FILTER_VERSION = "1.0"
TRADE_SETUP_FILTER_ASSET_SUITABILITY_MODE = "candidate_weak_set"


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _to_optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return _to_decimal(value)


def _unwrap_cursor(db_obj: Any) -> Any:
    if isinstance(db_obj, tuple):
        return db_obj[1]
    return db_obj


def _parse_source_ref_json(value: Any) -> dict[str, Any]:
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}

    if isinstance(parsed, dict):
        return parsed

    return {}


def _extract_allowed_sleeves_from_summary(summary_text: str | None) -> str | None:
    if not summary_text:
        return None

    marker = "sleeves="
    if marker not in summary_text:
        return None

    tail = summary_text.split(marker, 1)[1]
    value = tail.split(";", 1)[0].strip()

    if not value:
        return None

    return value


def _extract_allowed_sleeves(source_ref_json: Any, summary_text: str | None) -> str | None:
    payload = _parse_source_ref_json(source_ref_json)

    for key in ("allowed_sleeves", "effective_allowed_sleeves", "sleeves"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            items = [str(item).strip() for item in value if str(item).strip()]
            if items:
                return ",".join(items)

    return _extract_allowed_sleeves_from_summary(summary_text)


@dataclass
class DecisionGateRepository:
    def fetch_selection_rows(
        self,
        venue: str,
        asset_id: int | None = None,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> list[SelectionInputRow]:
        clauses = ["s.venue = %(venue)s"]
        params: dict[str, Any] = {
            "venue": venue,
            "filter_name": TRADE_SETUP_FILTER_NAME,
            "filter_version": TRADE_SETUP_FILTER_VERSION,
            "asset_suitability_mode": TRADE_SETUP_FILTER_ASSET_SUITABILITY_MODE,
        }

        if asset_id is not None:
            clauses.append("s.asset_id = %(asset_id)s")
            params["asset_id"] = asset_id

        if symbol is not None:
            clauses.append("a.symbol = %(symbol)s")
            params["symbol"] = symbol

        sql = f"""
        WITH latest_selection_snapshot AS (
            SELECT MAX(asof_ts_utc) AS asof_ts_utc
            FROM selection_state
            WHERE venue = %(venue)s
        )
        SELECT
            s.selection_state_id,
            s.asset_id,
            a.symbol,
            s.venue,
            CAST(s.asof_ts_utc AS CHAR) AS asof_ts_utc,
            s.selection_state,
            s.selection_bias,
            s.priority_rank,
            s.selection_score AS effective_selection_score,
            s.summary_text,
            s.source_ref_json,
            s.regime_label_4h,

            f.setup_filter_state,
            f.setup_filter_reason,
            f.target_horizon

        FROM selection_state s
        JOIN latest_selection_snapshot latest
          ON latest.asof_ts_utc = s.asof_ts_utc
        JOIN asset a
          ON a.asset_id = s.asset_id
        LEFT JOIN {TRADE_SETUP_FILTER_TABLE} f
          ON f.asset_id = s.asset_id
         AND f.venue = s.venue
         AND f.asof_ts_utc = s.asof_ts_utc
         AND f.filter_name = %(filter_name)s
         AND f.filter_version = %(filter_version)s
         AND f.asset_suitability_mode = %(asset_suitability_mode)s
        WHERE {" AND ".join(clauses)}
        ORDER BY
            s.priority_rank IS NULL,
            s.priority_rank ASC,
            s.selection_score DESC,
            a.symbol ASC
        """

        if limit is not None:
            sql += "\nLIMIT %(limit)s"
            params["limit"] = int(limit)

        with db_cursor() as db_obj:
            cursor = _unwrap_cursor(db_obj)
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        result: list[SelectionInputRow] = []

        for row in rows:
            summary_text = str(row["summary_text"]) if row.get("summary_text") else None

            result.append(
                SelectionInputRow(
                    selection_state_id=int(row["selection_state_id"]),
                    asset_id=int(row["asset_id"]),
                    symbol=str(row["symbol"]),
                    venue=str(row["venue"]),
                    asof_ts_utc=str(row["asof_ts_utc"]) if row.get("asof_ts_utc") else None,
                    selection_state=str(row["selection_state"]).upper(),
                    selection_bias=str(row["selection_bias"]) if row.get("selection_bias") else None,
                    priority_rank=int(row["priority_rank"]) if row.get("priority_rank") is not None else None,
                    effective_selection_score=_to_optional_decimal(row.get("effective_selection_score")),
                    allowed_sleeves=_extract_allowed_sleeves(row.get("source_ref_json"), summary_text),
                    summary_text=summary_text,
                    regime_label_4h=str(row["regime_label_4h"]) if row.get("regime_label_4h") else None,
                    setup_filter_state=str(row["setup_filter_state"]).upper() if row.get("setup_filter_state") else None,
                    setup_filter_reason=str(row["setup_filter_reason"]) if row.get("setup_filter_reason") else None,
                    target_horizon=str(row["target_horizon"]) if row.get("target_horizon") else None,
                )
            )

        return result

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
            row = cursor.fetchone()

        if not row:
            return None

        return SleeveState(
            account_id=int(row["account_id"]),
            sleeve_code=str(row["sleeve_code"]),
            sleeve_status=str(row["sleeve_status"]).upper(),
            target_weight=_to_decimal(row["target_weight"]),
            allocated_equity_eur=_to_decimal(row["allocated_equity_eur"]),
            reserved_equity_eur=_to_decimal(row["reserved_equity_eur"]),
            deployed_equity_eur=_to_decimal(row["deployed_equity_eur"]),
            available_equity_eur=_to_decimal(row["available_equity_eur"]),
        )

    def fetch_duplicate_state(
        self,
        account_id: int,
        sleeve_code: str,
        asset_id: int,
        venue: str,
    ) -> DuplicateState:
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

    def fetch_open_order_flag(
        self,
        account_id: int,
        sleeve_code: str,
        asset_id: int,
        venue: str,
    ) -> bool:
        return False
