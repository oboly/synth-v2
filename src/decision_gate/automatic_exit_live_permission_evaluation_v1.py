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
    SUPPORTED_PERMISSION_VERSIONS,
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
SUPPORTED_DECISION_STATES: Final[frozenset[str]] = frozenset({DECISION_GRANTED, DECISION_DENIED})

REASON_OK: Final[str] = "OK"
REASON_LIVE_PERMISSION_NOT_GRANTED: Final[str] = "AUTOMATIC_EXIT_LIVE_PERMISSION_NOT_GRANTED"
REASON_LIVE_PERMISSION_EVIDENCE_UNRESOLVED: Final[str] = "AUTOMATIC_EXIT_LIVE_PERMISSION_EVIDENCE_UNRESOLVED"


class AutomaticExitLivePermissionEvaluationError(ValueError):
    """Fail-closed binding violation for a typed evaluation artifact. ``args[0]`` is the reason code."""


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


def _is_aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


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


def validate_automatic_exit_live_permission_evaluation_binding_v1(
    evaluation: AutomaticExitLivePermissionEvaluationV1,
    *,
    trading_account_id: int,
    evaluation_ts_utc: datetime,
) -> None:
    """Reject reuse, forgery, or staleness of a typed LIVE permission evaluation.

    ``automatic_exit_gate_v1`` never re-resolves DB permission itself, but it
    must not blindly trust the typed evaluation object either -- this mirrors
    ``account_protection_contract_v1.validate_account_protection_evaluation_binding_v1``
    exactly. A mismatched account, unsupported/malformed contract version,
    unsupported ``decision_state``, a naive timestamp, or an
    ``evaluated_ts_utc`` not exactly equal to this call's own
    ``evaluation_ts_utc`` (a stale reused evaluation, or a future-dated one)
    all fail closed -- there is no tolerance window; the evaluation must have
    been produced for this exact account at this exact evaluation instant.

    A ``GRANTED`` evaluation is validated further: it must carry a positive
    ``permission_id``, a supported ``permission_version``, and the canonical
    ``OK`` reason code. An incomplete or self-inconsistent ``GRANTED``
    evaluation is not trustworthy evidence of permission merely because its
    account and timestamp line up. A ``DENIED`` evaluation is never promoted
    by this validator -- it can only ever remain denied.
    """
    if (
        evaluation.evaluation_contract_version != EVALUATION_CONTRACT_VERSION
        or evaluation.decision_state not in SUPPORTED_DECISION_STATES
        or evaluation.trading_account_id != trading_account_id
        or not isinstance(evaluation_ts_utc, datetime)
        or not _is_aware(evaluation_ts_utc)
        or not _is_aware(evaluation.evaluated_ts_utc)
        or evaluation.evaluated_ts_utc != evaluation_ts_utc
    ):
        raise AutomaticExitLivePermissionEvaluationError("INVALID_LIVE_PERMISSION_EVALUATION_BINDING")

    if evaluation.decision_state == DECISION_GRANTED and (
        evaluation.permission_id is None
        or evaluation.permission_id <= 0
        or evaluation.permission_version not in SUPPORTED_PERMISSION_VERSIONS
        or evaluation.reason_code != REASON_OK
    ):
        raise AutomaticExitLivePermissionEvaluationError("INVALID_GRANTED_LIVE_PERMISSION_EVALUATION")
