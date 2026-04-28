from __future__ import annotations

"""
Synth v2 - Paper Candidate Decision Gate Preview V1.

LAYER:
research / paper-candidate adapter preview

BOUNDARY:
Allowed:
- read validated paper-candidate staging rows
- map staged market-only candidates into DecisionGate-compatible input rows
- fetch account-aware permission context through DecisionGateRepository
- call evaluate_selection_for_account as a read-only preview
- report decision_gate preview results

Forbidden:
- decision_state writes
- execution_intent writes
- execution_plan writes
- order handling
- broker/exchange actions
- executor calls
- database writes

Purpose:
Preview how staged research paper candidates would be classified by the
account-aware decision_gate, without promoting them into execution.
"""

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.decision_gate.decision_gate_v1 import evaluate_selection_for_account
from src.decision_gate.models import DecisionGateConfig, SelectionInputRow
from src.decision_gate.repository import DecisionGateRepository


DEFAULT_DATABASE = "synth_bt"
DEFAULT_TABLE = "research_paper_candidate_signal"
DEFAULT_SIGNAL_STATUS = "VALIDATED"
DEFAULT_POLICY_NAME = "swing_pullback_recovery_v5"
DEFAULT_SETUP_FILTER_STATE = "PASS"
TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


ALLOWED_EXECUTION_REGIME_LABELS = frozenset(
    {
        "TREND_UP",
        "RANGE",
        "TREND_DOWN",
    }
)


@dataclass(frozen=True)
class StagedCandidateRow:
    candidate_id: int
    candidate_key: str
    contract_version: str
    policy_name: str
    policy_version: str
    candidate_state: str
    signal_status: str
    asset_id: int
    symbol: str
    venue: str
    asof_ts_utc: str | None
    selection_state: str
    priority_rank: int | None
    selection_score: Decimal | None
    btc_prior_24h: Decimal | None
    rotation_bucket: str | None
    classification_code: str | None
    execution_regime_label: str | None
    sleeve_fit_code: str | None
    simulated_horizon_hours: int
    simulated_net_return: Decimal | None
    source_table: str
    source_replay_id: int
    load_batch_id: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview decision_gate outcomes for staged paper candidates without writes."
    )
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--signal-status", default=DEFAULT_SIGNAL_STATUS)
    parser.add_argument("--policy-name", default=DEFAULT_POLICY_NAME)
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--sleeve-code", required=True)
    parser.add_argument("--min-available-equity-eur", default="25.00")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def validate_table_name(table_name: str) -> str:
    if not TABLE_NAME_PATTERN.fullmatch(table_name):
        raise ValueError(f"Unsafe table name: {table_name}")
    return table_name


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=' ')
    return str(value)


def build_filters(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    filters = [
        "signal_status = %(signal_status)s",
        "policy_name = %(policy_name)s",
        "venue = %(venue)s",
    ]
    params: dict[str, Any] = {
        "signal_status": args.signal_status,
        "policy_name": args.policy_name,
        "venue": args.venue,
        "limit": int(args.limit),
    }
    if args.batch_id:
        filters.append("load_batch_id = %(batch_id)s")
        params["batch_id"] = args.batch_id
    return " AND ".join(filters), params


def fetch_staged_candidates(args: argparse.Namespace) -> list[StagedCandidateRow]:
    safe_table = validate_table_name(args.table)
    where_sql, params = build_filters(args)
    sql = f'''
        SELECT
            candidate_id, candidate_key, contract_version, policy_name, policy_version,
            candidate_state, signal_status, asset_id, symbol, venue,
            CAST(asof_ts_utc AS CHAR) AS asof_ts_utc,
            selection_state, priority_rank, selection_score, btc_prior_24h,
            rotation_bucket, classification_code, execution_regime_label, sleeve_fit_code,
            simulated_horizon_hours, simulated_net_return,
            source_table, source_replay_id, load_batch_id
        FROM {safe_table}
        WHERE {where_sql}
        ORDER BY asof_ts_utc, priority_rank IS NULL, priority_rank, symbol
        LIMIT %(limit)s
    '''
    conn = get_connection(database=args.database)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
    finally:
        conn.close()

    out: list[StagedCandidateRow] = []
    for row in rows:
        out.append(
            StagedCandidateRow(
                candidate_id=int(row["candidate_id"]),
                candidate_key=str(row["candidate_key"]),
                contract_version=str(row["contract_version"]),
                policy_name=str(row["policy_name"]),
                policy_version=str(row["policy_version"]),
                candidate_state=str(row["candidate_state"]),
                signal_status=str(row["signal_status"]),
                asset_id=int(row["asset_id"]),
                symbol=str(row["symbol"]),
                venue=str(row["venue"]),
                asof_ts_utc=str(row["asof_ts_utc"]) if row.get("asof_ts_utc") else None,
                selection_state=str(row["selection_state"]).upper(),
                priority_rank=int(row["priority_rank"]) if row.get("priority_rank") is not None else None,
                selection_score=to_decimal(row.get("selection_score")),
                btc_prior_24h=to_decimal(row.get("btc_prior_24h")),
                rotation_bucket=str(row["rotation_bucket"]) if row.get("rotation_bucket") else None,
                classification_code=str(row["classification_code"]) if row.get("classification_code") else None,
                execution_regime_label=str(row["execution_regime_label"]) if row.get("execution_regime_label") else None,
                sleeve_fit_code=str(row["sleeve_fit_code"]) if row.get("sleeve_fit_code") else None,
                simulated_horizon_hours=int(row["simulated_horizon_hours"]),
                simulated_net_return=to_decimal(row.get("simulated_net_return")),
                source_table=str(row["source_table"]),
                source_replay_id=int(row["source_replay_id"]),
                load_batch_id=str(row["load_batch_id"]),
            )
        )
    return out



def require_execution_regime_label(row: StagedCandidateRow) -> str:
    value = row.execution_regime_label
    if value not in ALLOWED_EXECUTION_REGIME_LABELS:
        raise ValueError(
            "Invalid or missing execution_regime_label for "
            f"candidate_id={row.candidate_id} "
            f"symbol={row.symbol} "
            f"rotation_bucket={row.rotation_bucket} "
            f"classification_code={row.classification_code} "
            f"execution_regime_label={value}"
        )
    return value


def staged_candidate_to_selection_input(row: StagedCandidateRow) -> SelectionInputRow:
    allowed_sleeves = row.sleeve_fit_code
    target_horizon = f'{row.simulated_horizon_hours}h'
    setup_reason = f'PAPER_CANDIDATE_{row.policy_name}_VALIDATED'
    summary_text = (
        f'paper_candidate_id={row.candidate_id}; '
        f'policy={row.policy_name}; '
        f'policy_version={row.policy_version}; '
        f'source={row.source_table}:{row.source_replay_id}; '
        f'batch={row.load_batch_id}'
    )
    regime_label_4h = require_execution_regime_label(row)

    return SelectionInputRow(
        selection_state_id=row.candidate_id,
        asset_id=row.asset_id,
        symbol=row.symbol,
        venue=row.venue,
        asof_ts_utc=row.asof_ts_utc,
        selection_state=row.selection_state,
        selection_bias='PAPER_CANDIDATE',
        priority_rank=row.priority_rank,
        effective_selection_score=row.selection_score,
        allowed_sleeves=allowed_sleeves,
        summary_text=summary_text,
        regime_label_4h=regime_label_4h,
        setup_filter_state=DEFAULT_SETUP_FILTER_STATE,
        setup_filter_reason=setup_reason,
        target_horizon=target_horizon,
    )


def preview_decisions(args: argparse.Namespace) -> list[dict[str, Any]]:
    repo = DecisionGateRepository()
    rows = fetch_staged_candidates(args)
    sleeve_state = repo.fetch_sleeve_state(
        account_id=args.account_id,
        sleeve_code=args.sleeve_code,
    )
    config = DecisionGateConfig(
        min_available_equity_eur=Decimal(str(args.min_available_equity_eur))
    )

    out: list[dict[str, Any]] = []
    for staged in rows:
        selection_row = staged_candidate_to_selection_input(staged)
        duplicate_state = repo.fetch_duplicate_state(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            asset_id=staged.asset_id,
            venue=staged.venue,
        )
        has_open_order = repo.fetch_open_order_flag(
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            asset_id=staged.asset_id,
            venue=staged.venue,
        )
        decision = evaluate_selection_for_account(
            row=selection_row,
            account_id=args.account_id,
            sleeve_code=args.sleeve_code,
            sleeve_state=sleeve_state,
            duplicate_state=duplicate_state,
            config=config,
            has_open_order=has_open_order,
        )
        out.append(
            {
                "candidate_id": staged.candidate_id,
                "load_batch_id": staged.load_batch_id,
                "source_replay_id": staged.source_replay_id,
                "symbol": staged.symbol,
                "asset_id": staged.asset_id,
                "venue": staged.venue,
                "asof_ts_utc": staged.asof_ts_utc,
                "policy_name": staged.policy_name,
                "policy_version": staged.policy_version,
                "signal_status": staged.signal_status,
                "selection_state": staged.selection_state,
                "priority_rank": staged.priority_rank,
                "selection_score": staged.selection_score,
                "allowed_sleeves": selection_row.allowed_sleeves,
                "setup_filter_state": selection_row.setup_filter_state,
                "setup_filter_reason": selection_row.setup_filter_reason,
                "target_horizon": selection_row.target_horizon,
                "simulated_net_return": staged.simulated_net_return,
                "account_id": args.account_id,
                "sleeve_code": args.sleeve_code,
                "decision_state": decision.decision_state,
                "decision_reason": decision.decision_reason,
                "execution_intent": decision.execution_intent,
                "available_equity_eur": decision.available_equity_eur,
                "min_available_equity_eur": decision.min_available_equity_eur,
                "has_active_plan": decision.has_active_plan,
                "has_open_position": decision.has_open_position,
                "has_open_order": has_open_order,
            }
        )
    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decision_counts: dict[str, int] = {}
    intent_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    for row in rows:
        decision_counts[str(row["decision_state"])] = decision_counts.get(str(row["decision_state"]), 0) + 1
        intent_counts[str(row["execution_intent"])] = intent_counts.get(str(row["execution_intent"]), 0) + 1
        reason_counts[str(row["decision_reason"])] = reason_counts.get(str(row["decision_reason"]), 0) + 1
    return {
        "rows_total": len(rows),
        "symbols": len({row["symbol"] for row in rows}),
        "decision_counts": decision_counts,
        "execution_intent_counts": intent_counts,
        "decision_reason_counts": reason_counts,
    }


def print_table(rows: list[dict[str, Any]]) -> None:
    print("Paper candidate decision-gate preview")
    summary = summarize(rows)
    for key, value in summary.items():
        print(f'{key}: {value}')
    print()
    print("candidate_id | ts | symbol | score | sleeve | decision_state | execution_intent | reason")
    print("-" * 132)
    for row in rows:
        print(
            f"{row['candidate_id']} | "
            f"{row['asof_ts_utc']} | "
            f"{row['symbol']} | "
            f"{row['selection_score']} | "
            f"{row['allowed_sleeves']} | "
            f"{row['decision_state']} | "
            f"{row['execution_intent']} | "
            f"{row['decision_reason']}"
        )


def main() -> int:
    args = parse_args()
    rows = preview_decisions(args)
    payload = {
        "summary": summarize(rows),
        "rows": rows,
    }
    if args.output == 'json':
        print(json.dumps(payload, default=json_default, indent=2, sort_keys=True))
    else:
        print_table(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
