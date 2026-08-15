"""Issue #227 P1 pure contracts for account-aware protection locks.

This module defines the typed/versioned schema and pure composition rules
for account protections such as maximum drawdown, daily realized loss,
loss/stop streak, and cooldown blocks. It is schema/contract-only: there is
no database, broker, credential, execution_planner, executor, or live
account-evaluation code here, and nothing in this module reads real account
state or is wired into the existing ``decision_gate`` permission-evaluation
flow.

The pure resolver below (``resolve_account_protection_state_v1``) composes
caller-assembled :class:`ProtectionLockFactV1` rows into a single permission
signal. It does not compute drawdown, realized loss, or streaks from raw
fills/equity data; deriving those lock facts from canonical account truth is
the separately gated P2 runtime (Issue #318). This mirrors the Phase 4A shape
of ``src/exit_policy/automatic_exit_runtime_contract_v1.py``: pure
resolution over caller-supplied facts, plus an idempotency-key helper for
deterministic restart semantics.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Iterable


PROTECTION_CONTRACT_VERSION: Final[str] = "1"
LOCK_FACT_CONTRACT_VERSION: Final[str] = "1"
EVALUATION_CONTRACT_VERSION: Final[str] = "1"

DEFAULT_MAX_ACCOUNT_STATE_AGE_SECONDS: Final[int] = 15 * 60


class AccountProtectionContractError(ValueError):
    """Raised for malformed/inconsistent caller input (a caller bug), not for
    ordinary stale/missing account data. Stale or missing account data is a
    routine, fail-closed *decision* (``STATE_BLOCKED``), never an exception.
    """


# ---------------------------------------------------------------------------
# Protection codes and scope types
# ---------------------------------------------------------------------------

PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK: Final[str] = "MAX_ACCOUNT_DRAWDOWN_BLOCK"
PROTECTION_DAILY_REALIZED_LOSS_BLOCK: Final[str] = "DAILY_REALIZED_LOSS_BLOCK"
PROTECTION_REPEATED_STOPLOSS_BLOCK: Final[str] = "REPEATED_STOPLOSS_BLOCK"
PROTECTION_LOW_PROFIT_ASSET_COOLDOWN: Final[str] = "LOW_PROFIT_ASSET_COOLDOWN"
PROTECTION_POST_CLOSE_REENTRY_COOLDOWN: Final[str] = "POST_CLOSE_REENTRY_COOLDOWN"
PROTECTION_MANUAL_ACCOUNT_LOCK: Final[str] = "MANUAL_ACCOUNT_LOCK"

SUPPORTED_PROTECTION_CODES: Final[frozenset[str]] = frozenset({
    PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
    PROTECTION_DAILY_REALIZED_LOSS_BLOCK,
    PROTECTION_REPEATED_STOPLOSS_BLOCK,
    PROTECTION_LOW_PROFIT_ASSET_COOLDOWN,
    PROTECTION_POST_CLOSE_REENTRY_COOLDOWN,
    PROTECTION_MANUAL_ACCOUNT_LOCK,
})

SCOPE_ACCOUNT: Final[str] = "ACCOUNT"
SCOPE_SLEEVE: Final[str] = "SLEEVE"
SCOPE_ASSET: Final[str] = "ASSET"

SUPPORTED_SCOPE_TYPES: Final[frozenset[str]] = frozenset({SCOPE_ACCOUNT, SCOPE_SLEEVE, SCOPE_ASSET})

# Which scope types each protection code may legally use. Enforced at fact
# validation time so a malformed (protection_code, scope_type) pairing fails
# closed rather than silently evaluating.
PROTECTION_ALLOWED_SCOPES: Final[dict[str, frozenset[str]]] = {
    PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK: frozenset({SCOPE_ACCOUNT}),
    PROTECTION_DAILY_REALIZED_LOSS_BLOCK: frozenset({SCOPE_ACCOUNT}),
    PROTECTION_REPEATED_STOPLOSS_BLOCK: frozenset({SCOPE_ACCOUNT, SCOPE_ASSET}),
    PROTECTION_LOW_PROFIT_ASSET_COOLDOWN: frozenset({SCOPE_ASSET}),
    PROTECTION_POST_CLOSE_REENTRY_COOLDOWN: frozenset({SCOPE_ASSET}),
    PROTECTION_MANUAL_ACCOUNT_LOCK: frozenset({SCOPE_ACCOUNT, SCOPE_SLEEVE, SCOPE_ASSET}),
}

# Precedence when multiple locks are simultaneously in force for the same
# lookup: lower index wins. Manual authority always dominates automated
# blocks; the two hard account-level loss caps outrank the pattern-based
# streak block; cooldowns are the narrowest/least severe and rank last.
PROTECTION_PRECEDENCE_ORDER: Final[tuple[str, ...]] = (
    PROTECTION_MANUAL_ACCOUNT_LOCK,
    PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
    PROTECTION_DAILY_REALIZED_LOSS_BLOCK,
    PROTECTION_REPEATED_STOPLOSS_BLOCK,
    PROTECTION_POST_CLOSE_REENTRY_COOLDOWN,
    PROTECTION_LOW_PROFIT_ASSET_COOLDOWN,
)

# ---------------------------------------------------------------------------
# Lock fact lifecycle state (persisted-fact vocabulary; distinct from the
# evaluation decision_state below).
# ---------------------------------------------------------------------------

LOCK_STATE_ACTIVE: Final[str] = "ACTIVE"
LOCK_STATE_EXPIRED: Final[str] = "EXPIRED"
LOCK_STATE_RECOVERED: Final[str] = "RECOVERED"
LOCK_STATE_MANUALLY_CLEARED: Final[str] = "MANUALLY_CLEARED"

SUPPORTED_LOCK_STATES: Final[frozenset[str]] = frozenset({
    LOCK_STATE_ACTIVE, LOCK_STATE_EXPIRED, LOCK_STATE_RECOVERED, LOCK_STATE_MANUALLY_CLEARED,
})

# ---------------------------------------------------------------------------
# Evaluation decision_state and reason codes
# ---------------------------------------------------------------------------

STATE_PERMITTED: Final[str] = "PERMITTED"
STATE_BLOCKED: Final[str] = "BLOCKED"
SUPPORTED_DECISION_STATES: Final[frozenset[str]] = frozenset({STATE_PERMITTED, STATE_BLOCKED})

REASON_OK: Final[str] = "OK"
REASON_MAX_ACCOUNT_DRAWDOWN_TRIGGERED: Final[str] = "MAX_ACCOUNT_DRAWDOWN_TRIGGERED"
REASON_DAILY_REALIZED_LOSS_TRIGGERED: Final[str] = "DAILY_REALIZED_LOSS_TRIGGERED"
REASON_REPEATED_STOPLOSS_TRIGGERED: Final[str] = "REPEATED_STOPLOSS_TRIGGERED"
REASON_LOW_PROFIT_ASSET_COOLDOWN_ACTIVE: Final[str] = "LOW_PROFIT_ASSET_COOLDOWN_ACTIVE"
REASON_POST_CLOSE_REENTRY_COOLDOWN_ACTIVE: Final[str] = "POST_CLOSE_REENTRY_COOLDOWN_ACTIVE"
REASON_MANUAL_ACCOUNT_LOCK_ACTIVE: Final[str] = "MANUAL_ACCOUNT_LOCK_ACTIVE"
REASON_ACCOUNT_STATE_EVIDENCE_STALE: Final[str] = "ACCOUNT_STATE_EVIDENCE_STALE"
REASON_ACCOUNT_STATE_EVIDENCE_MISSING: Final[str] = "ACCOUNT_STATE_EVIDENCE_MISSING"

# protection_code -> reason_code surfaced when that protection is the
# highest-precedence active block.
_PROTECTION_TRIGGERED_REASON: Final[dict[str, str]] = {
    PROTECTION_MANUAL_ACCOUNT_LOCK: REASON_MANUAL_ACCOUNT_LOCK_ACTIVE,
    PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK: REASON_MAX_ACCOUNT_DRAWDOWN_TRIGGERED,
    PROTECTION_DAILY_REALIZED_LOSS_BLOCK: REASON_DAILY_REALIZED_LOSS_TRIGGERED,
    PROTECTION_REPEATED_STOPLOSS_BLOCK: REASON_REPEATED_STOPLOSS_TRIGGERED,
    PROTECTION_POST_CLOSE_REENTRY_COOLDOWN: REASON_POST_CLOSE_REENTRY_COOLDOWN_ACTIVE,
    PROTECTION_LOW_PROFIT_ASSET_COOLDOWN: REASON_LOW_PROFIT_ASSET_COOLDOWN_ACTIVE,
}


# ---------------------------------------------------------------------------
# Typed rows
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProtectionLockFactV1:
    """Immutable, append-only decision-gate fact for one triggered protection.

    Matches the "Required lock contract" shape in
    ``docs/todo/decision_gate_account_protections_v1.md``. This is a pure
    value object: nothing here persists, reads, or writes a database row.

    Recovery/expiry is represented by appending a *new* fact sharing the same
    idempotency identity (see :func:`account_protection_lock_idempotency_key_v1`)
    with a later ``triggered_ts_utc`` and a non-``ACTIVE`` ``lock_state``; the
    resolver below always treats the latest-triggered fact per idempotency
    identity as authoritative, so state is fully reconstructible from the
    append-only fact history on every restart.
    """

    protection_code: str
    protection_version: str
    trading_account_id: int
    scope_type: str
    scope_id: str
    observed_from_ts_utc: datetime
    observed_to_ts_utc: datetime
    triggered_ts_utc: datetime
    expires_ts_utc: datetime | None
    reason_code: str
    evidence_refs: tuple[str, ...]
    configuration_version: str
    lock_state: str = LOCK_STATE_ACTIVE


@dataclass(frozen=True)
class AccountProtectionEvaluationV1:
    """Pure evaluation outcome: an additional required permission signal.

    ``decision_state`` is ``PERMITTED`` or ``BLOCKED`` only; there is no
    third neutral state, per the fail-closed requirement that uncertain,
    stale, or missing account-state evidence blocks rather than permits.
    """

    evaluation_contract_version: str
    decision_state: str
    reason_code: str
    trading_account_id: int
    protection_code: str | None
    scope_type: str | None
    scope_id: str | None
    expires_ts_utc: datetime | None
    contributing_lock_facts: tuple[ProtectionLockFactV1, ...]
    evaluated_ts_utc: datetime


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_fact_shape(fact: ProtectionLockFactV1) -> None:
    if (
        fact.protection_code not in SUPPORTED_PROTECTION_CODES
        or fact.protection_version != LOCK_FACT_CONTRACT_VERSION
        or fact.trading_account_id <= 0
        or fact.scope_type not in SUPPORTED_SCOPE_TYPES
        or fact.scope_type not in PROTECTION_ALLOWED_SCOPES[fact.protection_code]
        or not _is_nonempty_string(fact.scope_id)
        or not _is_nonempty_string(fact.reason_code)
        or not _is_nonempty_string(fact.configuration_version)
        or fact.lock_state not in SUPPORTED_LOCK_STATES
        or not _is_aware(fact.observed_from_ts_utc)
        or not _is_aware(fact.observed_to_ts_utc)
        or not _is_aware(fact.triggered_ts_utc)
        or fact.observed_to_ts_utc <= fact.observed_from_ts_utc
        or (fact.expires_ts_utc is not None and not _is_aware(fact.expires_ts_utc))
        or (fact.expires_ts_utc is not None and fact.expires_ts_utc <= fact.triggered_ts_utc)
    ):
        raise AccountProtectionContractError("INVALID_PROTECTION_LOCK_FACT")


def _scope_matches(
    fact: ProtectionLockFactV1, *, trading_account_id: int, sleeve_code: str | None, asset_id: int | None,
) -> bool:
    if fact.scope_type == SCOPE_ACCOUNT:
        return fact.scope_id == str(trading_account_id)
    if fact.scope_type == SCOPE_SLEEVE:
        return sleeve_code is not None and fact.scope_id == sleeve_code
    if fact.scope_type == SCOPE_ASSET:
        return asset_id is not None and fact.scope_id == str(asset_id)
    return False


def _in_force(fact: ProtectionLockFactV1, *, at: datetime) -> bool:
    if fact.lock_state != LOCK_STATE_ACTIVE:
        return False
    if fact.triggered_ts_utc > at:
        return False
    if fact.expires_ts_utc is not None and at >= fact.expires_ts_utc:
        return False
    return True


def _authoritative_facts_by_identity(
    facts: Iterable[ProtectionLockFactV1],
) -> tuple[ProtectionLockFactV1, ...]:
    """Collapse append-only history to the latest-triggered fact per identity.

    This is the deterministic-restart rule: a fresh reader that loads the
    complete fact history and applies this reduction reconstructs identical
    state regardless of process restarts or input ordering.
    """
    latest_by_key: dict[str, ProtectionLockFactV1] = {}
    for fact in facts:
        key = _identity_key(fact)
        current = latest_by_key.get(key)
        if current is None or fact.triggered_ts_utc > current.triggered_ts_utc:
            latest_by_key[key] = fact
    # Deterministic ordering for reproducible test/audit output.
    return tuple(sorted(latest_by_key.values(), key=lambda f: (f.protection_code, f.scope_type, f.scope_id)))


def _identity_key(fact: ProtectionLockFactV1) -> str:
    return "|".join((
        fact.protection_code, fact.scope_type, fact.scope_id,
        fact.observed_from_ts_utc.isoformat(), fact.observed_to_ts_utc.isoformat(),
        fact.configuration_version,
    ))


def _stale(observed: datetime, at: datetime, max_age_seconds: int) -> bool:
    age = at - observed
    return age < timedelta(0) or age > timedelta(seconds=max_age_seconds)


# ---------------------------------------------------------------------------
# Pure resolver
# ---------------------------------------------------------------------------

def resolve_account_protection_state_v1(
    facts: Iterable[ProtectionLockFactV1],
    *,
    trading_account_id: int,
    sleeve_code: str | None,
    asset_id: int | None,
    account_state_observed_ts_utc: datetime,
    account_state_fresh: bool,
    at: datetime,
    max_account_state_age_seconds: int = DEFAULT_MAX_ACCOUNT_STATE_AGE_SECONDS,
) -> AccountProtectionEvaluationV1:
    """Compose caller-assembled lock facts into one permission signal.

    This is an *additional required check*, not a replacement for
    ``decision_gate.decision_gate_v1.evaluate_selection_for_account``: the
    caller must combine both (logical AND) before granting execution intent.
    See ``docs/architecture/account_protection_contract_v1.md`` for the
    composition contract.

    Fail-closed: any of (a) a naive/invalid ``at`` or
    ``account_state_observed_ts_utc``, (b) ``account_state_fresh=False``, or
    (c) stale ``account_state_observed_ts_utc`` relative to ``at`` resolves to
    ``STATE_BLOCKED``, never ``STATE_PERMITTED``. Malformed caller input
    (bad account id, bad fact shape, cross-account fact leakage) raises
    :class:`AccountProtectionContractError` instead, since that is a caller
    bug rather than ordinary stale/missing account data.
    """
    if (
        trading_account_id <= 0
        or not _is_aware(at)
        or not _is_aware(account_state_observed_ts_utc)
        or max_account_state_age_seconds < 0
        or (sleeve_code is not None and not _is_nonempty_string(sleeve_code))
        or (asset_id is not None and asset_id <= 0)
    ):
        raise AccountProtectionContractError("INVALID_EVALUATION_INPUT")

    materialized = tuple(facts)
    for fact in materialized:
        if fact.trading_account_id != trading_account_id:
            raise AccountProtectionContractError("CROSS_ACCOUNT_EVIDENCE_LEAKAGE")
        _validate_fact_shape(fact)

    if not account_state_fresh:
        return _blocked(
            trading_account_id=trading_account_id, reason=REASON_ACCOUNT_STATE_EVIDENCE_MISSING, at=at,
        )
    if _stale(account_state_observed_ts_utc, at, max_account_state_age_seconds):
        return _blocked(
            trading_account_id=trading_account_id, reason=REASON_ACCOUNT_STATE_EVIDENCE_STALE, at=at,
        )

    authoritative = _authoritative_facts_by_identity(materialized)
    in_scope = tuple(
        fact for fact in authoritative
        if _scope_matches(fact, trading_account_id=trading_account_id, sleeve_code=sleeve_code, asset_id=asset_id)
    )
    active = tuple(fact for fact in in_scope if _in_force(fact, at=at))
    if not active:
        return AccountProtectionEvaluationV1(
            evaluation_contract_version=EVALUATION_CONTRACT_VERSION,
            decision_state=STATE_PERMITTED,
            reason_code=REASON_OK,
            trading_account_id=trading_account_id,
            protection_code=None,
            scope_type=None,
            scope_id=None,
            expires_ts_utc=None,
            contributing_lock_facts=(),
            evaluated_ts_utc=at,
        )

    winner = min(active, key=lambda fact: PROTECTION_PRECEDENCE_ORDER.index(fact.protection_code))
    return AccountProtectionEvaluationV1(
        evaluation_contract_version=EVALUATION_CONTRACT_VERSION,
        decision_state=STATE_BLOCKED,
        reason_code=_PROTECTION_TRIGGERED_REASON[winner.protection_code],
        trading_account_id=trading_account_id,
        protection_code=winner.protection_code,
        scope_type=winner.scope_type,
        scope_id=winner.scope_id,
        expires_ts_utc=winner.expires_ts_utc,
        contributing_lock_facts=active,
        evaluated_ts_utc=at,
    )


def _blocked(*, trading_account_id: int, reason: str, at: datetime) -> AccountProtectionEvaluationV1:
    return AccountProtectionEvaluationV1(
        evaluation_contract_version=EVALUATION_CONTRACT_VERSION,
        decision_state=STATE_BLOCKED,
        reason_code=reason,
        trading_account_id=trading_account_id,
        protection_code=None,
        scope_type=None,
        scope_id=None,
        expires_ts_utc=None,
        contributing_lock_facts=(),
        evaluated_ts_utc=at,
    )


# ---------------------------------------------------------------------------
# Idempotency key (restart/audit determinism)
# ---------------------------------------------------------------------------

def account_protection_lock_idempotency_key_v1(evidence: dict[str, Any]) -> str:
    """SHA-256 over canonical JSON of immutable source identifiers only.

    Deliberately excludes ``triggered_ts_utc``, ``expires_ts_utc``,
    ``reason_code``, and ``evidence_refs`` so re-evaluating the same
    underlying observation window after a restart reproduces the same key
    (upsert semantics), while a genuinely new observation window or
    configuration version produces a new key.
    """
    required = {
        "protection_code", "protection_version", "trading_account_id",
        "scope_type", "scope_id", "observed_from_ts_utc", "observed_to_ts_utc",
        "configuration_version",
    }
    logical_evidence = {key: value for key, value in evidence.items() if key in required}
    if set(logical_evidence) != required or any(logical_evidence[key] in (None, "") for key in required):
        raise AccountProtectionContractError("INCOMPLETE_IDEMPOTENCY_EVIDENCE")
    serialized = json.dumps(logical_evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
