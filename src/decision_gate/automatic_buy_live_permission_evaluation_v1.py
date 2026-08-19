"""Issue #399 Phase 7A: typed BUY LIVE decision-gate permission evaluation.

Loads persisted account-scoped evidence, resolves it through the pure BUY
LIVE permission contract, and returns a typed GRANTED/DENIED result. Missing,
malformed, ambiguous, stale, or unsupported evidence fails closed. This is
decision-gate permission only and never executor authority, credential,
kill-switch, broker access, or order authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from src.decision_gate.automatic_buy_live_permission_contract_v1 import (
    SUPPORTED_PERMISSION_VERSIONS,
    AutomaticBuyLivePermissionContractError,
    resolve_automatic_buy_live_decision_gate_permission_v1,
)
from src.decision_gate.automatic_buy_live_permission_repository_v1 import (
    AutomaticBuyLivePermissionRepositoryError,
    load_automatic_buy_live_permission_history_v1,
    load_automatic_buy_live_permission_revocation_history_v1,
)

EVALUATION_CONTRACT_VERSION: Final[str] = "1"
DECISION_GRANTED: Final[str] = "GRANTED"
DECISION_DENIED: Final[str] = "DENIED"
SUPPORTED_DECISION_STATES: Final[frozenset[str]] = frozenset({DECISION_GRANTED, DECISION_DENIED})
REASON_OK: Final[str] = "OK"
REASON_LIVE_PERMISSION_NOT_GRANTED: Final[str] = "AUTOMATIC_BUY_LIVE_PERMISSION_NOT_GRANTED"
REASON_LIVE_PERMISSION_EVIDENCE_UNRESOLVED: Final[str] = "AUTOMATIC_BUY_LIVE_PERMISSION_EVIDENCE_UNRESOLVED"


class AutomaticBuyLivePermissionEvaluationError(ValueError):
    """Fail-closed binding violation. ``args[0]`` is the reason code."""


@dataclass(frozen=True)
class AutomaticBuyLivePermissionEvaluationV1:
    evaluation_contract_version: str
    trading_account_id: int
    decision_state: str
    reason_code: str
    permission_id: int | None
    permission_version: str | None
    evaluated_ts_utc: datetime


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _denied(
    *,
    trading_account_id: int,
    reason: str,
    at: datetime,
    permission_id: int | None = None,
    permission_version: str | None = None,
) -> AutomaticBuyLivePermissionEvaluationV1:
    return AutomaticBuyLivePermissionEvaluationV1(
        evaluation_contract_version=EVALUATION_CONTRACT_VERSION,
        trading_account_id=trading_account_id,
        decision_state=DECISION_DENIED,
        reason_code=reason,
        permission_id=permission_id,
        permission_version=permission_version,
        evaluated_ts_utc=at,
    )


def evaluate_automatic_buy_live_permission_v1(
    conn: object,
    *,
    trading_account_id: int,
    evaluation_ts_utc: datetime,
) -> AutomaticBuyLivePermissionEvaluationV1:
    try:
        permissions = load_automatic_buy_live_permission_history_v1(
            conn, trading_account_id=trading_account_id,
        )
        revocations = load_automatic_buy_live_permission_revocation_history_v1(
            conn, trading_account_id=trading_account_id,
        )
        resolved = resolve_automatic_buy_live_decision_gate_permission_v1(
            permissions,
            revocations,
            trading_account_id=trading_account_id,
            at=evaluation_ts_utc,
        )
    except (AutomaticBuyLivePermissionRepositoryError, AutomaticBuyLivePermissionContractError):
        return _denied(
            trading_account_id=trading_account_id,
            reason=REASON_LIVE_PERMISSION_EVIDENCE_UNRESOLVED,
            at=evaluation_ts_utc,
        )

    if resolved is None:
        return _denied(
            trading_account_id=trading_account_id,
            reason=REASON_LIVE_PERMISSION_NOT_GRANTED,
            at=evaluation_ts_utc,
        )
    if not resolved.live_execution_permitted:
        return _denied(
            trading_account_id=trading_account_id,
            reason=REASON_LIVE_PERMISSION_NOT_GRANTED,
            at=evaluation_ts_utc,
            permission_id=resolved.permission_id,
            permission_version=resolved.permission_version,
        )
    return AutomaticBuyLivePermissionEvaluationV1(
        evaluation_contract_version=EVALUATION_CONTRACT_VERSION,
        trading_account_id=trading_account_id,
        decision_state=DECISION_GRANTED,
        reason_code=REASON_OK,
        permission_id=resolved.permission_id,
        permission_version=resolved.permission_version,
        evaluated_ts_utc=evaluation_ts_utc,
    )


def validate_automatic_buy_live_permission_evaluation_binding_v1(
    evaluation: AutomaticBuyLivePermissionEvaluationV1,
    *,
    trading_account_id: int,
    evaluation_ts_utc: datetime,
) -> None:
    """Require an exact account/timestamp-bound typed LIVE permission result."""
    if (
        evaluation.evaluation_contract_version != EVALUATION_CONTRACT_VERSION
        or evaluation.decision_state not in SUPPORTED_DECISION_STATES
        or evaluation.trading_account_id != trading_account_id
        or not _aware(evaluation_ts_utc)
        or not _aware(evaluation.evaluated_ts_utc)
        or evaluation.evaluated_ts_utc != evaluation_ts_utc
    ):
        raise AutomaticBuyLivePermissionEvaluationError("INVALID_LIVE_PERMISSION_EVALUATION_BINDING")

    if evaluation.decision_state == DECISION_GRANTED and (
        evaluation.permission_id is None
        or evaluation.permission_id <= 0
        or evaluation.permission_version not in SUPPORTED_PERMISSION_VERSIONS
        or evaluation.reason_code != REASON_OK
    ):
        raise AutomaticBuyLivePermissionEvaluationError("INVALID_GRANTED_LIVE_PERMISSION_EVALUATION")
