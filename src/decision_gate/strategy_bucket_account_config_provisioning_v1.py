"""Issue #498: canonical provisioning path for ``strategy_bucket_account_config_v1``.

Unblocks Issue #456 Stage B: production has zero rows in this table for any
account, and ``resolve_strategy_bucket_account_config_v1`` (#279) is
fail-closed by design when no effective row exists, so no automatic-BUY
candidate can ever pass the gate until a real row is provisioned. Before this
module, the only way to write this table was direct SQL, which is forbidden
as an operational shortcut.

This is the sole writer for ``strategy_bucket_account_config_v1`` in the
repository. It provisions by canonical ``(account_code, venue)`` identity,
never a caller-supplied numeric ``trading_account_id``. It never updates or
deletes a row (the table is append-only by DB trigger); ending or replacing
an existing effective row is a revocation action deliberately out of this
module's scope, so a conflicting rerun fails closed instead of silently
superseding.

Idempotency: rerunning with values identical to the currently *effective* row
for ``(trading_account_id, strategy_bucket_id)`` at the requested
``effective_from_ts_utc`` is a no-op that returns the existing row. Rerunning
with different values while an effective row already covers that identity
fails closed with :class:`StrategyBucketAccountConfigConflictError`.

Concurrency note: there is no DB-level uniqueness constraint preventing two
concurrent provisioning calls for the same ``(trading_account_id,
strategy_bucket_id)`` from both inserting (a partial/conditional unique index
would also wrongly block the revoke-then-replace supersession flow the
existing schema already relies on). This is acceptable for a deliberate,
low-frequency, human-reviewed operator action; a race would surface later as
``AMBIGUOUS_STRATEGY_BUCKET_CONFIGURATION`` (fail closed), never as a
permissive default.

No broker, executor, credential, or order import. No market candidate
truth is created or modified.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from src.decision_gate.strategy_bucket_account_config_contract_v1 import (
    CONFIG_CONTRACT_VERSION,
    StrategyBucketAccountConfigError,
    StrategyBucketAccountConfigRevocationV1,
    StrategyBucketAccountConfigRowV1,
    resolve_strategy_bucket_account_config_v1,
)
from src.decision_gate.strategy_bucket_account_config_repository_v1 import (
    StrategyBucketAccountConfigRepositoryError,
    load_strategy_bucket_account_config_revocations_v1,
    load_strategy_bucket_account_config_rows_v1,
)

_STRATEGY_BUCKET_ID_MAX_LENGTH: Final[int] = 64
_RISK_PROFILE_MAX_LENGTH: Final[int] = 64
_SOURCE_PROVENANCE_MAX_LENGTH: Final[int] = 128
_IDENTITY_TOKEN_ALLOWED_EXTRA: Final[frozenset[str]] = frozenset({"_", "-"})

# Sentinel id for pre-insert validation only (never persisted). The bucket
# config contract does not validate id positivity, unlike the permission
# contract, so 0 is a safe placeholder here.
_PRE_VALIDATION_CONFIG_ID: Final[int] = 0


class StrategyBucketAccountConfigProvisioningError(RuntimeError):
    """Fail-closed provisioning error. ``args[0]`` is the reason code."""


class StrategyBucketAccountConfigConflictError(StrategyBucketAccountConfigProvisioningError):
    """An effective, non-revoked row already covers this identity with different values."""


@dataclass(frozen=True)
class StrategyBucketAccountConfigProvisioningRequestV1:
    """Operator-supplied bucket configuration. Resolved by canonical account identity only."""

    account_code: str
    venue: str
    strategy_bucket_id: str
    is_enabled: bool
    risk_profile: str
    max_position_amount_eur: Decimal | None
    max_bucket_amount_eur: Decimal | None
    max_asset_exposure_pct: Decimal | None
    max_open_positions: int | None
    allow_new_entries: bool
    allow_reduce_reviews: bool
    effective_from_ts_utc: datetime
    source_provenance: str


@dataclass(frozen=True)
class StrategyBucketAccountConfigProvisioningResultV1:
    trading_account_id: int
    strategy_bucket_account_config_id: int
    strategy_bucket_id: str
    idempotent: bool


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _valid_identity_token(value: str, *, max_length: int) -> bool:
    if not _nonempty(value) or value != value.strip() or len(value) > max_length:
        return False
    return all(ch.isascii() and (ch.isalnum() or ch in _IDENTITY_TOKEN_ALLOWED_EXTRA) for ch in value)


def _validate_request(request: StrategyBucketAccountConfigProvisioningRequestV1) -> None:
    if not _nonempty(request.account_code) or not _nonempty(request.venue):
        raise StrategyBucketAccountConfigProvisioningError("INVALID_ACCOUNT_IDENTITY")
    # No canonical strategy-bucket registry exists in this repository (#232
    # bucket definition/validation is out of scope). "Unknown bucket" is
    # therefore enforced as identity well-formedness only, the same trust
    # level every gate/planner module already applies to strategy_bucket_id.
    if not _valid_identity_token(request.strategy_bucket_id, max_length=_STRATEGY_BUCKET_ID_MAX_LENGTH):
        raise StrategyBucketAccountConfigProvisioningError("INVALID_STRATEGY_BUCKET_IDENTITY")
    if not _nonempty(request.risk_profile) or len(request.risk_profile) > _RISK_PROFILE_MAX_LENGTH:
        raise StrategyBucketAccountConfigProvisioningError("INVALID_RISK_PROFILE")
    if not _nonempty(request.source_provenance) or len(request.source_provenance) > _SOURCE_PROVENANCE_MAX_LENGTH:
        raise StrategyBucketAccountConfigProvisioningError("INVALID_SOURCE_PROVENANCE")
    if not _aware(request.effective_from_ts_utc):
        raise StrategyBucketAccountConfigProvisioningError("INVALID_EFFECTIVE_FROM_TIMESTAMP")
    if type(request.is_enabled) is not bool or type(request.allow_new_entries) is not bool or type(request.allow_reduce_reviews) is not bool:
        raise StrategyBucketAccountConfigProvisioningError("INVALID_BOOLEAN_FIELD")


def _resolve_trading_account_id(conn: Any, *, account_code: str, venue: str) -> int:
    sql = "SELECT trading_account_id FROM trading_account WHERE account_code = %s AND venue = %s LIMIT 1"
    with conn.cursor() as cur:
        cur.execute(sql, (account_code, venue))
        row = cur.fetchone()
    if row is None:
        raise StrategyBucketAccountConfigProvisioningError("UNKNOWN_TRADING_ACCOUNT")
    return int(row["trading_account_id"])


def _candidate_row(
    *, trading_account_id: int, request: StrategyBucketAccountConfigProvisioningRequestV1,
) -> StrategyBucketAccountConfigRowV1:
    return StrategyBucketAccountConfigRowV1(
        strategy_bucket_account_config_id=_PRE_VALIDATION_CONFIG_ID,
        trading_account_id=trading_account_id,
        strategy_bucket_id=request.strategy_bucket_id,
        config_version=CONFIG_CONTRACT_VERSION,
        is_enabled=request.is_enabled,
        risk_profile=request.risk_profile,
        max_position_amount_eur=request.max_position_amount_eur,
        max_bucket_amount_eur=request.max_bucket_amount_eur,
        max_asset_exposure_pct=request.max_asset_exposure_pct,
        max_open_positions=request.max_open_positions,
        allow_new_entries=request.allow_new_entries,
        allow_reduce_reviews=request.allow_reduce_reviews,
        effective_from_ts_utc=request.effective_from_ts_utc,
        effective_until_ts_utc=None,
        source_provenance=request.source_provenance,
    )


def _active_at(row: StrategyBucketAccountConfigRowV1, *, at: datetime) -> bool:
    return row.effective_from_ts_utc <= at and (row.effective_until_ts_utc is None or at < row.effective_until_ts_utc)


def _revoked_at(
    config_id: int, *, revocations: tuple[StrategyBucketAccountConfigRevocationV1, ...], at: datetime,
) -> bool:
    return any(row.strategy_bucket_account_config_id == config_id and row.effective_ts_utc <= at for row in revocations)


def _find_effective_raw_row(
    rows: tuple[StrategyBucketAccountConfigRowV1, ...],
    revocations: tuple[StrategyBucketAccountConfigRevocationV1, ...],
    *,
    trading_account_id: int,
    strategy_bucket_id: str,
    at: datetime,
) -> StrategyBucketAccountConfigRowV1:
    """Mirror the two ``resolve_strategy_bucket_account_config_v1`` predicates.

    Only called after that resolver has already proven exactly one such row
    exists, so this always finds exactly one match.
    """
    matches = [
        row for row in rows
        if row.trading_account_id == trading_account_id
        and row.strategy_bucket_id == strategy_bucket_id
        and _active_at(row, at=at)
        and not _revoked_at(row.strategy_bucket_account_config_id, revocations=revocations, at=at)
    ]
    if len(matches) != 1:
        raise StrategyBucketAccountConfigProvisioningError("STRATEGY_BUCKET_ACCOUNT_CONFIG_STATE_INVALID")
    return matches[0]


def _same_values(
    existing: StrategyBucketAccountConfigRowV1, request: StrategyBucketAccountConfigProvisioningRequestV1,
) -> bool:
    return (
        existing.config_version == CONFIG_CONTRACT_VERSION
        and existing.is_enabled == request.is_enabled
        and existing.risk_profile == request.risk_profile
        and existing.max_position_amount_eur == request.max_position_amount_eur
        and existing.max_bucket_amount_eur == request.max_bucket_amount_eur
        and existing.max_asset_exposure_pct == request.max_asset_exposure_pct
        and existing.max_open_positions == request.max_open_positions
        and existing.allow_new_entries == request.allow_new_entries
        and existing.allow_reduce_reviews == request.allow_reduce_reviews
        and existing.effective_from_ts_utc == request.effective_from_ts_utc
        and existing.effective_until_ts_utc is None
        and existing.source_provenance == request.source_provenance
    )


def provision_strategy_bucket_account_config_v1(
    conn: Any, *, request: StrategyBucketAccountConfigProvisioningRequestV1,
) -> StrategyBucketAccountConfigProvisioningResultV1:
    """Provision one durable, deterministic, idempotent bucket config row.

    Caller owns the DB transaction boundary (commit/rollback), matching the
    convention of ``write_automatic_buy_source_runtime_input_v1``.
    """
    _validate_request(request)
    trading_account_id = _resolve_trading_account_id(conn, account_code=request.account_code, venue=request.venue)

    candidate = _candidate_row(trading_account_id=trading_account_id, request=request)
    try:
        resolve_strategy_bucket_account_config_v1(
            (candidate,), (),
            trading_account_id=trading_account_id,
            strategy_bucket_id=request.strategy_bucket_id,
            at=request.effective_from_ts_utc,
        )
    except StrategyBucketAccountConfigError as exc:
        reason = exc.args[0] if exc.args else "INVALID_STRATEGY_BUCKET_ACCOUNT_CONFIG"
        raise StrategyBucketAccountConfigProvisioningError(reason) from exc

    try:
        existing_rows = load_strategy_bucket_account_config_rows_v1(conn, trading_account_id=trading_account_id)
        existing_revocations = load_strategy_bucket_account_config_revocations_v1(
            conn, trading_account_id=trading_account_id,
        )
    except StrategyBucketAccountConfigRepositoryError as exc:
        raise StrategyBucketAccountConfigProvisioningError("PERSISTED_STRATEGY_BUCKET_CONFIG_EVIDENCE_INVALID") from exc

    try:
        effective = resolve_strategy_bucket_account_config_v1(
            existing_rows, existing_revocations,
            trading_account_id=trading_account_id,
            strategy_bucket_id=request.strategy_bucket_id,
            at=request.effective_from_ts_utc,
        )
    except StrategyBucketAccountConfigError as exc:
        reason = exc.args[0] if exc.args else ""
        if reason != "STRATEGY_BUCKET_CONFIGURATION_UNRESOLVED":
            raise StrategyBucketAccountConfigProvisioningError(
                reason or "STRATEGY_BUCKET_ACCOUNT_CONFIG_STATE_INVALID"
            ) from exc
        effective = None

    if effective is not None:
        raw = _find_effective_raw_row(
            existing_rows, existing_revocations,
            trading_account_id=trading_account_id,
            strategy_bucket_id=request.strategy_bucket_id,
            at=request.effective_from_ts_utc,
        )
        if _same_values(raw, request):
            return StrategyBucketAccountConfigProvisioningResultV1(
                trading_account_id=trading_account_id,
                strategy_bucket_account_config_id=raw.strategy_bucket_account_config_id,
                strategy_bucket_id=request.strategy_bucket_id,
                idempotent=True,
            )
        raise StrategyBucketAccountConfigConflictError("CONFLICTING_STRATEGY_BUCKET_ACCOUNT_CONFIG")

    insert_sql = """
    INSERT INTO strategy_bucket_account_config_v1 (
        trading_account_id, strategy_bucket_id, config_version, is_enabled, risk_profile,
        max_position_amount_eur, max_bucket_amount_eur, max_asset_exposure_pct, max_open_positions,
        allow_new_entries, allow_reduce_reviews, effective_from_ts_utc, effective_until_ts_utc,
        source_provenance
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (
        trading_account_id, request.strategy_bucket_id, CONFIG_CONTRACT_VERSION, request.is_enabled,
        request.risk_profile, request.max_position_amount_eur, request.max_bucket_amount_eur,
        request.max_asset_exposure_pct, request.max_open_positions, request.allow_new_entries,
        request.allow_reduce_reviews, request.effective_from_ts_utc, None, request.source_provenance,
    )
    with conn.cursor() as cur:
        cur.execute(insert_sql, params)
        new_id = int(cur.lastrowid)

    return StrategyBucketAccountConfigProvisioningResultV1(
        trading_account_id=trading_account_id,
        strategy_bucket_account_config_id=new_id,
        strategy_bucket_id=request.strategy_bucket_id,
        idempotent=False,
    )
