"""Issue #392 Phase 6 blocker B: the single composition seam for decision-gate
LIVE automatic-exit permission evaluation on the real automatic-exit runtime
path.

Mirrors ``src/decision_gate/account_protection_evaluation_v1.py`` exactly:
loads persisted evidence, resolves it through the pure contract, and always
returns a typed result rather than raising or returning a bare boolean --
missing evidence resolves to an explicit denied evaluation, and
malformed/ambiguous evidence resolves to a typed fail-closed denied
evaluation rather than propagating an exception into the caller (a
data-quality condition, not a caller bug, so one bad account's evidence
cannot abort the whole runtime cycle).

This module is the only place decision-gate LIVE permission semantics are
resolved. ``exit_policy`` (including
``src/exit_policy/automatic_exit_runtime_repository_v1.py`` and
``src/exit_policy/automatic_exit_runtime_orchestrator_v1.py``) calls this
seam and forwards its typed result unchanged into
``AutomaticExitGateContextV1``; it never resolves LIVE permission itself.

No broker, executor, kill-switch, or credential import.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from src.decision_gate.automatic_exit_live_permission_contract_v1 import (
    AutomaticExitLivePermissionContractError,
    resolve_automatic_exit_live_decision_gate_permission_v1,
)
from src.decision_gate.automatic_exit_live_permission_repository_v1 import (
    AutomaticExitLivePermissionRepositoryError,
    load_automatic_exit_live_permission_history_v1,
    load_automatic_exit_live_permission_revocation_history_v1,
)


EVALUATION_CONTRACT_VERSION: Final[str] = "1"

DECISION_GRANTED: Final[str] = "GRANTED"
DECISION_DENIED: Final[str] = "DENIED"

REASON_OK: Final[str] = "OK"
REASON_LIVE_PERMISSION_NOT_GRANTED: Final[str] = "AUTOMATIC_EXIT_LIVE_PERMISSION_NOT_GRANTED"
REASON_LIVE_PERMISSION_EVIDENCE_UNRESOLVED: Final[str] = "AUTOMATIC_EXIT_LIVE_PERMISSION_EVIDENCE_UNRESOLVED"


@dataclass(frozen=True)
class AutomaticExitLivePermissionEvaluationV1:
    """Typed decision-gate LIVE permission evaluation outcome.

    Carries enough typed evidence to establish account identity, permission
    contract/version, effective evaluation timestamp, and the enabled/
    disabled decision with its reason -- never an unbound boolean. Grants
    decision-gate LIVE permission only; never executor authority, a kill
    switch, or broker/credential access.
    """

    evaluation_contract_version: str
    trading_account_id: int
    decision_state: str  # GRANTED | DENIED
    reason_code: str
    permission_id: int | None
    permission_version: str | None
    evaluated_ts_utc: datetime


def _denied(
    *, trading_account_id: int, reason: str, at: datetime,
    permission_id: int | None = None, permission_version: str | None = None,
) -> AutomaticExitLivePermissionEvaluationV1:
    return AutomaticExitLivePermissionEvaluationV1(
        evaluation_contract_version=EVALUATION_CONTRACT_VERSION,
        trading_account_id=trading_account_id,
        decision_state=DECISION_DENIED,
        reason_code=reason,
        permission_id=permission_id,
        permission_version=permission_version,
        evaluated_ts_utc=at,
    )


def evaluate_automatic_exit_live_permission_v1(
    conn: object, *, trading_account_id: int, evaluation_ts_utc: datetime,
) -> AutomaticExitLivePermissionEvaluationV1:
    """Evaluate decision-gate LIVE automatic-exit permission for one account.

    No row for the account, malformed/ambiguous permission history, or
    malformed/unsupported-version revocation evidence all resolve to a typed
    ``DENIED`` evaluation -- never an implicit grant and never a raised
    exception out of this seam.
    """
    try:
        permissions = load_automatic_exit_live_permission_history_v1(conn, trading_account_id=trading_account_id)
        revocations = load_automatic_exit_live_permission_revocation_history_v1(
            conn, trading_account_id=trading_account_id,
        )
        resolved = resolve_automatic_exit_live_decision_gate_permission_v1(
            permissions, revocations, trading_account_id=trading_account_id, at=evaluation_ts_utc,
        )
    except (AutomaticExitLivePermissionRepositoryError, AutomaticExitLivePermissionContractError):
        return _denied(
            trading_account_id=trading_account_id,
            reason=REASON_LIVE_PERMISSION_EVIDENCE_UNRESOLVED,
            at=evaluation_ts_utc,
        )

    if resolved is None:
        return _denied(
            trading_account_id=trading_account_id, reason=REASON_LIVE_PERMISSION_NOT_GRANTED, at=evaluation_ts_utc,
        )
    if not resolved.live_execution_permitted:
        return _denied(
            trading_account_id=trading_account_id,
            reason=REASON_LIVE_PERMISSION_NOT_GRANTED,
            at=evaluation_ts_utc,
            permission_id=resolved.permission_id,
            permission_version=resolved.permission_version,
        )
    return AutomaticExitLivePermissionEvaluationV1(
        evaluation_contract_version=EVALUATION_CONTRACT_VERSION,
        trading_account_id=trading_account_id,
        decision_state=DECISION_GRANTED,
        reason_code=REASON_OK,
        permission_id=resolved.permission_id,
        permission_version=resolved.permission_version,
        evaluated_ts_utc=evaluation_ts_utc,
    )
