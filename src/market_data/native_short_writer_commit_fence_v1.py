from __future__ import annotations

"""Transient commit-time fence for the canonical Native SHORT writer.

The fence reads only the canonical persisted scope and cadence authorities. It
persists no fence state: the writer keeps the start snapshot in memory and
re-reads the same authority rows with locking reads immediately before commit.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from src.market_data.native_short_map_lifecycle_v1 import (
    NativeShortMapScopeKey,
    NativeShortMapScopeSupportState,
)

REASON_SCOPE_IDENTITY_CHANGED = "WRITER_COMMIT_FENCE_SCOPE_IDENTITY_CHANGED"
REASON_SUPPORT_WITHDRAWN = "WRITER_COMMIT_FENCE_SUPPORT_WITHDRAWN"
REASON_SUPPORT_GENERATION_CHANGED = "WRITER_COMMIT_FENCE_SUPPORT_GENERATION_CHANGED"
REASON_ACTIVE_CADENCE_CHANGED = "WRITER_COMMIT_FENCE_ACTIVE_CADENCE_CHANGED"

_SCOPE_KEY_WHERE = (
    "venue = %s AND symbol = %s AND quote_currency = %s "
    "AND fib_trading_horizon = %s AND primary_interval = %s "
    "AND supporting_interval = %s"
)


class NativeShortWriterCommitFenceError(RuntimeError):
    """The canonical writer's current authority no longer matches its start."""


@dataclass(frozen=True)
class NativeShortActiveCadenceState:
    cadence_config_id: int
    cadence_contract_version: str
    target_evaluation_interval: str
    primary_source_freshness_limit_seconds: int
    supporting_source_freshness_limit_seconds: int
    evaluation_grace_seconds: int
    recent_scope_grace_seconds: int
    effective_from_utc: datetime
    effective_to_utc: datetime | None
    is_active: int
    activation_operation_id: int | None
    deactivation_operation_id: int | None
    support_generation: int | None


@dataclass(frozen=True)
class NativeShortWriterCommitFence:
    key: NativeShortMapScopeKey
    scope_id: int
    scope_support_state: str
    support_generation: int | None
    active_cadence_rows: tuple[NativeShortActiveCadenceState, ...]


def _scope_key_params(key: NativeShortMapScopeKey) -> tuple[str, ...]:
    return (
        key.venue,
        key.symbol,
        key.quote_currency,
        key.fib_trading_horizon,
        key.primary_interval,
        key.supporting_interval,
    )


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def read_writer_commit_fence(
    conn: Any,
    key: NativeShortMapScopeKey,
    *,
    for_update: bool,
) -> NativeShortWriterCommitFence:
    """Read exact current scope and active-cadence authority for one scope."""

    lock = " FOR UPDATE" if for_update else ""
    params = _scope_key_params(key)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT scope_id, venue, symbol, quote_currency,
                   fib_trading_horizon, primary_interval, supporting_interval,
                   scope_support_state, support_generation
            FROM native_short_map_scope_v1
            WHERE {_SCOPE_KEY_WHERE}
            ORDER BY scope_id ASC{lock}
            """,
            params,
        )
        scope_rows = [dict(row) for row in cur.fetchall()]

    if len(scope_rows) != 1:
        raise NativeShortWriterCommitFenceError(
            f"{REASON_SCOPE_IDENTITY_CHANGED} "
            f"scope={key.venue}:{key.symbol} row_count={len(scope_rows)}"
        )

    scope_row = scope_rows[0]
    current_key = NativeShortMapScopeKey(
        venue=str(scope_row["venue"]),
        symbol=str(scope_row["symbol"]).upper(),
        quote_currency=str(scope_row["quote_currency"]),
        fib_trading_horizon=str(scope_row["fib_trading_horizon"]),
        primary_interval=str(scope_row["primary_interval"]),
        supporting_interval=str(scope_row["supporting_interval"]),
    )
    if current_key != key:
        raise NativeShortWriterCommitFenceError(
            f"{REASON_SCOPE_IDENTITY_CHANGED} "
            f"expected={key!r} current={current_key!r}"
        )

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT cadence_config_id, cadence_contract_version,
                   target_evaluation_interval,
                   primary_source_freshness_limit_seconds,
                   supporting_source_freshness_limit_seconds,
                   evaluation_grace_seconds, recent_scope_grace_seconds,
                   effective_from_utc, effective_to_utc, is_active,
                   activation_operation_id, deactivation_operation_id,
                   support_generation
            FROM native_short_scope_cadence_config_v1
            WHERE {_SCOPE_KEY_WHERE}
              AND is_active = 1
            ORDER BY cadence_config_id ASC{lock}
            """,
            params,
        )
        cadence_rows = tuple(
            NativeShortActiveCadenceState(
                cadence_config_id=int(row["cadence_config_id"]),
                cadence_contract_version=str(row["cadence_contract_version"]),
                target_evaluation_interval=str(row["target_evaluation_interval"]),
                primary_source_freshness_limit_seconds=int(
                    row["primary_source_freshness_limit_seconds"]
                ),
                supporting_source_freshness_limit_seconds=int(
                    row["supporting_source_freshness_limit_seconds"]
                ),
                evaluation_grace_seconds=int(row["evaluation_grace_seconds"]),
                recent_scope_grace_seconds=int(row["recent_scope_grace_seconds"]),
                effective_from_utc=row["effective_from_utc"],
                effective_to_utc=row.get("effective_to_utc"),
                is_active=int(row["is_active"]),
                activation_operation_id=_optional_int(
                    row.get("activation_operation_id")
                ),
                deactivation_operation_id=_optional_int(
                    row.get("deactivation_operation_id")
                ),
                support_generation=_optional_int(row.get("support_generation")),
            )
            for row in (dict(value) for value in cur.fetchall())
        )

    return NativeShortWriterCommitFence(
        key=key,
        scope_id=int(scope_row["scope_id"]),
        scope_support_state=str(scope_row["scope_support_state"]),
        support_generation=_optional_int(scope_row.get("support_generation")),
        active_cadence_rows=cadence_rows,
    )


def capture_writer_commit_fences(
    conn: Any,
    scopes: Sequence[NativeShortMapScopeKey],
) -> tuple[NativeShortWriterCommitFence, ...]:
    """Capture the exact authority state under which this bounded run starts."""

    fences: list[NativeShortWriterCommitFence] = []
    for key in scopes:
        fence = read_writer_commit_fence(conn, key, for_update=False)
        if (
            fence.scope_support_state
            != NativeShortMapScopeSupportState.SUPPORTED.value
        ):
            raise NativeShortWriterCommitFenceError(
                f"{REASON_SUPPORT_WITHDRAWN} "
                f"scope={key.venue}:{key.symbol} "
                f"state={fence.scope_support_state}"
            )
        if len(fence.active_cadence_rows) != 1:
            raise NativeShortWriterCommitFenceError(
                f"{REASON_ACTIVE_CADENCE_CHANGED} "
                f"scope={key.venue}:{key.symbol} "
                f"active_row_count={len(fence.active_cadence_rows)}"
            )
        fences.append(fence)
    return tuple(fences)


def revalidate_writer_commit_fences(
    conn: Any,
    expected_fences: Sequence[NativeShortWriterCommitFence],
) -> None:
    """Locking re-read of every start fence immediately before commit."""

    for expected in expected_fences:
        current = read_writer_commit_fence(conn, expected.key, for_update=True)
        if current.scope_id != expected.scope_id or current.key != expected.key:
            raise NativeShortWriterCommitFenceError(
                f"{REASON_SCOPE_IDENTITY_CHANGED} "
                f"scope={expected.key.venue}:{expected.key.symbol} "
                f"expected_scope_id={expected.scope_id} "
                f"current_scope_id={current.scope_id}"
            )
        if (
            current.scope_support_state
            != NativeShortMapScopeSupportState.SUPPORTED.value
            or current.scope_support_state != expected.scope_support_state
        ):
            raise NativeShortWriterCommitFenceError(
                f"{REASON_SUPPORT_WITHDRAWN} "
                f"scope={expected.key.venue}:{expected.key.symbol} "
                f"expected={expected.scope_support_state} "
                f"current={current.scope_support_state}"
            )
        if current.support_generation != expected.support_generation:
            raise NativeShortWriterCommitFenceError(
                f"{REASON_SUPPORT_GENERATION_CHANGED} "
                f"scope={expected.key.venue}:{expected.key.symbol} "
                f"expected={expected.support_generation} "
                f"current={current.support_generation}"
            )
        if current.active_cadence_rows != expected.active_cadence_rows:
            raise NativeShortWriterCommitFenceError(
                f"{REASON_ACTIVE_CADENCE_CHANGED} "
                f"scope={expected.key.venue}:{expected.key.symbol}"
            )
