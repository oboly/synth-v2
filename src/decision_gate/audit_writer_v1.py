from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from src.common.db import db_cursor
from src.common.utc import ensure_utc, utc_now


VALID_EXECUTION_MODES: Final[set[str]] = {
    "PAPER",
    "LIVE_DRY_RUN",
    "LIVE_ARMED",
    "LIVE",
}

WRITABLE_EXECUTION_MODES_V1: Final[set[str]] = {
    "PAPER",
    "LIVE_DRY_RUN",
}

DEFAULT_SAFETY_MARKERS: Final[dict[str, Any]] = {
    "broker_private_calls": 0,
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "execution_planner": "none",
    "executor": "none",
}


@dataclass(frozen=True)
class DecisionGateAuditRecord:
    trading_account_id: int
    venue: str
    asset_id: int
    interval_code: str
    asof_ts_utc: str
    execution_mode: str
    decision_state: str
    permission_state: str
    decision_reason: str | None = None
    user_id: int | None = None
    strategy_profile_id: int | None = None
    strategy_candidate_id: int | None = None
    symbol: str | None = None
    lifecycle_state: str | None = None
    execution_intent: str | None = None
    action_type: str | None = None
    requested_side: str | None = None
    requested_notional_eur: Decimal | None = None
    requested_quantity_base: Decimal | None = None
    limit_price: Decimal | None = None
    reason_codes_json: Any = None
    safety_markers_json: Any = None
    upstream_ref_type: str | None = None
    upstream_ref_id: str | None = None
    created_ts_utc: str | None = None


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return ensure_utc(value).isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _json_dumps_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)


def _created_ts_utc(value: str | None) -> str:
    if value:
        return value
    return utc_now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _normalize_execution_mode(value: str) -> str:
    mode = str(value).strip().upper()
    if mode not in VALID_EXECUTION_MODES:
        allowed = ", ".join(sorted(VALID_EXECUTION_MODES))
        raise ValueError(f"execution_mode must be one of: {allowed}")
    return mode


def _validate_record(record: DecisionGateAuditRecord) -> None:
    if int(record.trading_account_id) < 0:
        raise ValueError("trading_account_id must be >= 0")
    if int(record.asset_id) < 0:
        raise ValueError("asset_id must be >= 0")
    if not str(record.venue).strip():
        raise ValueError("venue is required")
    if not str(record.interval_code).strip():
        raise ValueError("interval_code is required")
    if not str(record.asof_ts_utc).strip():
        raise ValueError("asof_ts_utc is required")
    if not str(record.decision_state).strip():
        raise ValueError("decision_state is required")
    if not str(record.permission_state).strip():
        raise ValueError("permission_state is required")

    mode = _normalize_execution_mode(record.execution_mode)
    if mode not in WRITABLE_EXECUTION_MODES_V1:
        allowed = ", ".join(sorted(WRITABLE_EXECUTION_MODES_V1))
        raise ValueError(
            f"decision_gate_audit_writer_v1 only writes execution_mode in: {allowed}"
        )


def build_decision_gate_audit_payload(record: DecisionGateAuditRecord) -> dict[str, Any]:
    _validate_record(record)

    safety_markers = dict(DEFAULT_SAFETY_MARKERS)
    if isinstance(record.safety_markers_json, dict):
        safety_markers.update(record.safety_markers_json)
    elif record.safety_markers_json is not None:
        safety_markers = record.safety_markers_json

    return {
        "user_id": record.user_id,
        "trading_account_id": int(record.trading_account_id),
        "strategy_profile_id": record.strategy_profile_id,
        "strategy_candidate_id": record.strategy_candidate_id,
        "venue": str(record.venue),
        "asset_id": int(record.asset_id),
        "symbol": record.symbol,
        "interval_code": str(record.interval_code),
        "execution_mode": _normalize_execution_mode(record.execution_mode),
        "lifecycle_state": record.lifecycle_state,
        "permission_state": str(record.permission_state),
        "decision_state": str(record.decision_state),
        "decision_reason": record.decision_reason,
        "execution_intent": record.execution_intent,
        "action_type": record.action_type,
        "requested_side": (
            None if record.requested_side is None else str(record.requested_side).upper()
        ),
        "requested_notional_eur": record.requested_notional_eur,
        "requested_quantity_base": record.requested_quantity_base,
        "limit_price": record.limit_price,
        "reason_codes_json": _json_dumps_or_none(record.reason_codes_json),
        "safety_markers_json": _json_dumps_or_none(safety_markers),
        "upstream_ref_type": record.upstream_ref_type,
        "upstream_ref_id": record.upstream_ref_id,
        "asof_ts_utc": record.asof_ts_utc,
        "created_ts_utc": _created_ts_utc(record.created_ts_utc),
    }


def insert_decision_gate_audit_record(record: DecisionGateAuditRecord) -> int:
    payload = build_decision_gate_audit_payload(record)

    sql = """
    INSERT INTO decision_gate_audit_log (
        user_id,
        trading_account_id,
        strategy_profile_id,
        strategy_candidate_id,
        venue,
        asset_id,
        symbol,
        interval_code,
        execution_mode,
        lifecycle_state,
        permission_state,
        decision_state,
        decision_reason,
        execution_intent,
        action_type,
        requested_side,
        requested_notional_eur,
        requested_quantity_base,
        limit_price,
        reason_codes_json,
        safety_markers_json,
        upstream_ref_type,
        upstream_ref_id,
        asof_ts_utc,
        created_ts_utc
    )
    VALUES (
        %(user_id)s,
        %(trading_account_id)s,
        %(strategy_profile_id)s,
        %(strategy_candidate_id)s,
        %(venue)s,
        %(asset_id)s,
        %(symbol)s,
        %(interval_code)s,
        %(execution_mode)s,
        %(lifecycle_state)s,
        %(permission_state)s,
        %(decision_state)s,
        %(decision_reason)s,
        %(execution_intent)s,
        %(action_type)s,
        %(requested_side)s,
        %(requested_notional_eur)s,
        %(requested_quantity_base)s,
        %(limit_price)s,
        %(reason_codes_json)s,
        %(safety_markers_json)s,
        %(upstream_ref_type)s,
        %(upstream_ref_id)s,
        %(asof_ts_utc)s,
        %(created_ts_utc)s
    )
    """

    with db_cursor(commit=True) as db_obj:
        cur = db_obj[1]
        cur.execute(sql, payload)
        return int(cur.lastrowid)


def count_decision_gate_audit_rows() -> int:
    sql = "SELECT COUNT(*) AS row_count FROM decision_gate_audit_log"
    with db_cursor() as db_obj:
        cur = db_obj[1]
        cur.execute(sql)
        row = cur.fetchone()
    return int(row["row_count"])
