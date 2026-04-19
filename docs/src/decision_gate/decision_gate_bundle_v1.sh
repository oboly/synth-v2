#!/usr/bin/env bash
set -e

mkdir -p src/decision_gate

cat > src/decision_gate/models.py << 'PY'
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final


ELIGIBLE_SELECTION_STATES: Final[set[str]] = {"PREPARE", "BUY_READY"}

ACTIVE_PLAN_STATES: Final[set[str]] = {
    "IDLE",
    "PLANNED",
    "PLACED",
    "MONITOR_QUEUE",
    "REPRICE_PENDING",
    "ESCALATED",
}

OPEN_POSITION_STATUSES: Final[set[str]] = {"OPEN"}

ACTIVE_SLEEVE_STATUSES: Final[set[str]] = {"ACTIVE"}


@dataclass(frozen=True)
class SelectionInputRow:
    selection_state_id: int
    asset_id: int
    symbol: str
    venue: str
    asof_ts_utc: str | None
    selection_state: str
    selection_bias: str | None
    priority_rank: int | None
    effective_selection_score: Decimal | None
    summary_text: str | None


@dataclass(frozen=True)
class SleeveState:
    account_id: int
    sleeve_code: str
    sleeve_status: str
    target_weight: Decimal
    allocated_equity_eur: Decimal
    reserved_equity_eur: Decimal
    deployed_equity_eur: Decimal
    available_equity_eur: Decimal


@dataclass(frozen=True)
class DuplicateState:
    has_active_plan: bool
    has_open_position: bool


@dataclass(frozen=True)
class DecisionGateConfig:
    min_available_equity_eur: Decimal = Decimal("25.00")


@dataclass(frozen=True)
class DecisionResult:
    account_id: int
    sleeve_code: str
    selection_state_id: int
    asset_id: int
    symbol: str
    venue: str
    asof_ts_utc: str | None
    selection_state: str
    decision_state: str
    decision_reason: str
    execution_intent: str
    min_available_equity_eur: Decimal
    available_equity_eur: Decimal | None
    has_active_plan: bool
    has_open_position: bool
    summary_text: str | None
PY


cat > src/decision_gate/repository.py << 'PY'
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
            summary_text
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

        with db_cursor() as cursor:
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
            )
            for r in rows
        ]

    def fetch_sleeve_state(self, account_id: int, sleeve_code: str) -> SleeveState | None:
        sql = """
        SELECT *
        FROM portfolio_sleeve
        WHERE account_id = %(account_id)s
          AND sleeve_code = %(sleeve_code)s
        LIMIT 1
        """

        with db_cursor() as cursor:
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
        with db_cursor() as cursor:
            cursor.execute(f"""
                SELECT EXISTS(
                    SELECT 1 FROM execution_plan
                    WHERE account_id=%s AND sleeve_code=%s AND asset_id=%s AND venue=%s
                    AND plan_state IN ({",".join(["%s"]*len(ACTIVE_PLAN_STATES))})
                ) AS v
            """, [account_id, sleeve_code, asset_id, venue, *ACTIVE_PLAN_STATES])
            plan = cursor.fetchone()["v"]

            cursor.execute(f"""
                SELECT EXISTS(
                    SELECT 1 FROM portfolio_position
                    WHERE account_id=%s AND sleeve_code=%s AND asset_id=%s AND venue=%s
                    AND position_status IN ({",".join(["%s"]*len(OPEN_POSITION_STATUSES))})
                    AND qty > 0
                ) AS v
            """, [account_id, sleeve_code, asset_id, venue, *OPEN_POSITION_STATUSES])
            pos = cursor.fetchone()["v"]

        return DuplicateState(bool(plan), bool(pos))

    def fetch_open_order_flag(self, *_) -> bool:
        return False
PY


cat > src/decision_gate/decision_gate_v1.py << 'PY'
from __future__ import annotations

from src.decision_gate.models import (
    ACTIVE_SLEEVE_STATUSES,
    DecisionGateConfig,
    DecisionResult,
    DuplicateState,
    ELIGIBLE_SELECTION_STATES,
    SelectionInputRow,
    SleeveState,
)


def evaluate_selection_for_account(
    row: SelectionInputRow,
    account_id: int,
    sleeve_code: str,
    sleeve_state: SleeveState | None,
    duplicate_state: DuplicateState,
    config: DecisionGateConfig,
    has_open_order: bool = False,
) -> DecisionResult:

    if row.selection_state not in ELIGIBLE_SELECTION_STATES:
        return DecisionResult(account_id, sleeve_code, row.selection_state_id, row.asset_id, row.symbol, row.venue,
            row.asof_ts_utc, row.selection_state, "NO_ACTION", "SELECTION_NOT_ELIGIBLE", "NONE",
            config.min_available_equity_eur, None, False, False, row.summary_text)

    if sleeve_state is None:
        return DecisionResult(account_id, sleeve_code, row.selection_state_id, row.asset_id, row.symbol, row.venue,
            row.asof_ts_utc, row.selection_state, "BLOCKED_SLEEVE", "SLEEVE_NOT_FOUND", "NONE",
            config.min_available_equity_eur, None, duplicate_state.has_active_plan, duplicate_state.has_open_position, row.summary_text)

    if sleeve_state.sleeve_status not in ACTIVE_SLEEVE_STATUSES:
        return DecisionResult(account_id, sleeve_code, row.selection_state_id, row.asset_id, row.symbol, row.venue,
            row.asof_ts_utc, row.selection_state, "BLOCKED_SLEEVE", "SLEEVE_NOT_ACTIVE", "NONE",
            config.min_available_equity_eur, sleeve_state.available_equity_eur, duplicate_state.has_active_plan, duplicate_state.has_open_position, row.summary_text)

    if has_open_order:
        return DecisionResult(account_id, sleeve_code, row.selection_state_id, row.asset_id, row.symbol, row.venue,
            row.asof_ts_utc, row.selection_state, "BLOCKED_OPEN_ORDER", "OPEN_ORDER", "NONE",
            config.min_available_equity_eur, sleeve_state.available_equity_eur, duplicate_state.has_active_plan, duplicate_state.has_open_position, row.summary_text)

    if duplicate_state.has_active_plan:
        return DecisionResult(account_id, sleeve_code, row.selection_state_id, row.asset_id, row.symbol, row.venue,
            row.asof_ts_utc, row.selection_state, "BLOCKED_ACTIVE_PLAN", "ACTIVE_PLAN", "NONE",
            config.min_available_equity_eur, sleeve_state.available_equity_eur, True, duplicate_state.has_open_position, row.summary_text)

    if duplicate_state.has_open_position:
        return DecisionResult(account_id, sleeve_code, row.selection_state_id, row.asset_id, row.symbol, row.venue,
            row.asof_ts_utc, row.selection_state, "BLOCKED_POSITION", "POSITION_EXISTS", "NONE",
            config.min_available_equity_eur, sleeve_state.available_equity_eur, duplicate_state.has_active_plan, True, row.summary_text)

    if sleeve_state.available_equity_eur < config.min_available_equity_eur:
        return DecisionResult(account_id, sleeve_code, row.selection_state_id, row.asset_id, row.symbol, row.venue,
            row.asof_ts_utc, row.selection_state, "BLOCKED_BALANCE", "INSUFFICIENT_BALANCE", "NONE",
            config.min_available_equity_eur, sleeve_state.available_equity_eur, duplicate_state.has_active_plan, duplicate_state.has_open_position, row.summary_text)

    if row.selection_state == "PREPARE":
        return DecisionResult(account_id, sleeve_code, row.selection_state_id, row.asset_id, row.symbol, row.venue,
            row.asof_ts_utc, row.selection_state, "PREPARE_ALLOWED", "OK", "PREPARE_PLAN",
            config.min_available_equity_eur, sleeve_state.available_equity_eur, False, False, row.summary_text)

    if row.selection_state == "BUY_READY":
        return DecisionResult(account_id, sleeve_code, row.selection_state_id, row.asset_id, row.symbol, row.venue,
            row.asof_ts_utc, row.selection_state, "EXECUTION_ALLOWED", "OK", "PLACE_PASSIVE_LIMIT",
            config.min_available_equity_eur, sleeve_state.available_equity_eur, False, False, row.summary_text)

    return DecisionResult(account_id, sleeve_code, row.selection_state_id, row.asset_id, row.symbol, row.venue,
        row.asof_ts_utc, row.selection_state, "NO_ACTION", "FALLBACK", "NONE",
        config.min_available_equity_eur, sleeve_state.available_equity_eur, False, False, row.summary_text)
PY


cat > src/decision_gate/run_decision_gate_v1.py << 'PY'
from __future__ import annotations

import argparse
from decimal import Decimal

from src.decision_gate.decision_gate_v1 import evaluate_selection_for_account
from src.decision_gate.models import DecisionGateConfig
from src.decision_gate.repository import DecisionGateRepository


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--account-id", type=int, required=True)
    p.add_argument("--sleeve-code", required=True)
    p.add_argument("--venue", default="bitvavo")
    p.add_argument("--limit", type=int, default=20)
    args = p.parse_args()

    repo = DecisionGateRepository()
    cfg = DecisionGateConfig(min_available_equity_eur=Decimal("25"))

    rows = repo.fetch_selection_rows(args.venue, limit=args.limit)
    sleeve = repo.fetch_sleeve_state(args.account_id, args.sleeve_code)

    for r in rows:
        dup = repo.fetch_duplicate_state(args.account_id, args.sleeve_code, r.asset_id, r.venue)
        res = evaluate_selection_for_account(r, args.account_id, args.sleeve_code, sleeve, dup, cfg)
        print(r.symbol, r.selection_state, "->", res.decision_state, res.execution_intent)


if __name__ == "__main__":
    main()
PY

echo "decision_gate_v1 files created"
