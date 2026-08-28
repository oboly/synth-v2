"""Canonical provisioning of a LIVE execution-capable ``trading_account`` row.

Closes the repo gap identified by the Issue #551 SELL LIVE readiness audit:
no canonical MariaDB service creates an ``account_mode='live'`` trading
account. ``src/account_provisioning/account_provisioning_service_v1.py`` is a
separate SQLite-backed self-service website onboarding path hardcoded to
``account_mode='paper'`` and is not reused here. This module provisions the
``trading_account`` row only -- credentials, executor bindings, decision-gate
LIVE permission, kill-switch state, and runtime capability activation are all
separate, later steps owned by other modules.

Safety:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none

Idempotency contract:
  - account_code absent -> insert the exact canonical row (``--apply`` only).
  - account_code present and every protected field matches exactly ->
    ``ALREADY_PROVISIONED``, no mutation.
  - account_code present but any protected field differs -> fail closed with
    ``ACCOUNT_IDENTITY_CONFLICT``. This module never auto-corrects an
    existing row.

The read-only source snapshot account (``live_readonly``) referenced by
``source_trading_account_id`` is validated but never written to -- this
module issues no ``UPDATE``/``DELETE`` against ``trading_account`` at all,
only ``SELECT`` (source validation, existing-row lookup) and ``INSERT``
(new-row creation).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Final

from src.account.account_mode_contract_v1 import (
    ACCOUNT_MODE_LIVE,
    ACCOUNT_MODE_LIVE_READONLY,
    is_account_mode_live_trading_enabled_consistent,
)

BITVAVO_VENUE: Final[str] = "bitvavo"

# The exact, canonical protected-field shape of a LIVE execution trading
# account. live_trading_enabled/account_mode consistency is asserted below
# against the shared contract rather than merely assumed.
TARGET_ACCOUNT_MODE: Final[str] = ACCOUNT_MODE_LIVE
TARGET_ENABLED: Final[bool] = True
TARGET_LIVE_TRADING_ENABLED: Final[bool] = True

assert is_account_mode_live_trading_enabled_consistent(
    TARGET_ACCOUNT_MODE, TARGET_LIVE_TRADING_ENABLED
), "live execution provisioning target violates the shared account_mode contract"

_PROTECTED_FIELDS: Final[tuple[str, ...]] = (
    "venue",
    "account_mode",
    "enabled",
    "live_trading_enabled",
    "description",
)


class LiveExecutionTradingAccountProvisioningError(ValueError):
    """Fail-closed provisioning error. ``args[0]`` is the reason code."""


@dataclass(frozen=True)
class LiveExecutionTradingAccountResolutionV1:
    """Read-only resolution outcome: what would/does exist, never a mutation."""

    status: str  # "WOULD_CREATE" | "ALREADY_PROVISIONED"
    trading_account_id: int | None
    account_code: str
    venue: str
    account_mode: str
    enabled: bool
    live_trading_enabled: bool
    description: str
    source_trading_account_id: int


@dataclass(frozen=True)
class LiveExecutionTradingAccountProvisioningResult:
    status: str  # "CREATED" | "ALREADY_PROVISIONED" | "WOULD_CREATE"
    trading_account_id: int | None
    created: bool
    account_code: str
    source_trading_account_id: int


def _value(row: Any, key: str, index: int) -> Any:
    return row[key] if isinstance(row, dict) else row[index]


def default_description(source_trading_account_id: int) -> str:
    return (
        "Bitvavo execution-capable LIVE trading identity paired with "
        f"read-only snapshot source trading_account_id={source_trading_account_id}"
    )


class LiveExecutionTradingAccountProvisioningRepository:
    """Non-secret ``trading_account`` metadata queries and inserts.

    Caller owns the transaction. This repository never touches
    ``trading_account_credential``, ``executor_credential_binding``, any
    decision_gate permission table, or any kill-switch table.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def _one(self, sql: str, params: tuple[Any, ...]) -> Any | None:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        if len(rows) > 1:
            raise LiveExecutionTradingAccountProvisioningError("AMBIGUOUS_ACCOUNT_CODE")
        return rows[0] if rows else None

    def find_source_account(self, *, trading_account_id: int) -> Any | None:
        return self._one(
            "SELECT trading_account_id, venue, account_mode, enabled "
            "FROM trading_account WHERE trading_account_id = %s",
            (trading_account_id,),
        )

    def find_by_account_code(self, *, account_code: str) -> Any | None:
        return self._one(
            "SELECT trading_account_id, account_code, venue, account_mode, enabled, "
            "live_trading_enabled, description FROM trading_account WHERE account_code = %s",
            (account_code,),
        )

    def insert_trading_account(
        self,
        *,
        account_code: str,
        venue: str,
        account_mode: str,
        enabled: bool,
        live_trading_enabled: bool,
        description: str,
        now_utc: datetime,
    ) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO trading_account (account_code, venue, account_mode, enabled, "
                "live_trading_enabled, description, created_ts_utc, updated_ts_utc) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    account_code,
                    venue,
                    account_mode,
                    int(enabled),
                    int(live_trading_enabled),
                    description,
                    now_utc.astimezone(UTC).replace(tzinfo=None),
                    now_utc.astimezone(UTC).replace(tzinfo=None),
                ),
            )
            return int(cur.lastrowid)


def _validate_source_account(row: Any | None, *, source_trading_account_id: int, venue: str) -> None:
    if row is None:
        raise LiveExecutionTradingAccountProvisioningError("SOURCE_ACCOUNT_NOT_FOUND")
    source_venue = str(_value(row, "venue", 1))
    source_account_mode = str(_value(row, "account_mode", 2))
    source_enabled = bool(_value(row, "enabled", 3))
    if source_venue != venue:
        raise LiveExecutionTradingAccountProvisioningError("SOURCE_ACCOUNT_VENUE_MISMATCH")
    if source_account_mode != ACCOUNT_MODE_LIVE_READONLY:
        raise LiveExecutionTradingAccountProvisioningError("SOURCE_ACCOUNT_NOT_LIVE_READONLY")
    if not source_enabled:
        raise LiveExecutionTradingAccountProvisioningError("SOURCE_ACCOUNT_DISABLED")


def _existing_row_conflicts(row: Any, *, venue: str, description: str) -> list[str]:
    expected = {
        "venue": venue,
        "account_mode": TARGET_ACCOUNT_MODE,
        "enabled": TARGET_ENABLED,
        "live_trading_enabled": TARGET_LIVE_TRADING_ENABLED,
        "description": description,
    }
    mismatched: list[str] = []
    for field in _PROTECTED_FIELDS:
        actual = _value(row, field, _PROTECTED_FIELDS.index(field) + 2)
        if field in ("enabled", "live_trading_enabled"):
            actual = bool(actual)
        else:
            actual = str(actual)
        if actual != expected[field]:
            mismatched.append(field)
    return mismatched


def resolve_live_execution_trading_account(
    *,
    account_code: str,
    venue: str,
    source_trading_account_id: int,
    description: str | None,
    repo: LiveExecutionTradingAccountProvisioningRepository,
) -> LiveExecutionTradingAccountResolutionV1:
    """Read-only resolution: validates the source, checks for an existing
    target row, and reports what would happen -- never mutates anything."""
    if venue != BITVAVO_VENUE:
        raise LiveExecutionTradingAccountProvisioningError("UNSUPPORTED_VENUE")
    if not account_code or not account_code.strip():
        raise LiveExecutionTradingAccountProvisioningError("ACCOUNT_CODE_REQUIRED")
    if account_code.strip() != account_code:
        raise LiveExecutionTradingAccountProvisioningError("ACCOUNT_CODE_MUST_NOT_HAVE_SURROUNDING_WHITESPACE")

    source_row = repo.find_source_account(trading_account_id=source_trading_account_id)
    _validate_source_account(source_row, source_trading_account_id=source_trading_account_id, venue=venue)

    resolved_description = description or default_description(source_trading_account_id)

    existing = repo.find_by_account_code(account_code=account_code)
    if existing is None:
        return LiveExecutionTradingAccountResolutionV1(
            status="WOULD_CREATE",
            trading_account_id=None,
            account_code=account_code,
            venue=venue,
            account_mode=TARGET_ACCOUNT_MODE,
            enabled=TARGET_ENABLED,
            live_trading_enabled=TARGET_LIVE_TRADING_ENABLED,
            description=resolved_description,
            source_trading_account_id=source_trading_account_id,
        )

    mismatched = _existing_row_conflicts(existing, venue=venue, description=resolved_description)
    if mismatched:
        raise LiveExecutionTradingAccountProvisioningError(
            f"ACCOUNT_IDENTITY_CONFLICT: account_code={account_code} mismatched_fields={sorted(mismatched)}"
        )

    return LiveExecutionTradingAccountResolutionV1(
        status="ALREADY_PROVISIONED",
        trading_account_id=int(_value(existing, "trading_account_id", 0)),
        account_code=account_code,
        venue=venue,
        account_mode=TARGET_ACCOUNT_MODE,
        enabled=TARGET_ENABLED,
        live_trading_enabled=TARGET_LIVE_TRADING_ENABLED,
        description=resolved_description,
        source_trading_account_id=source_trading_account_id,
    )


def provision_live_execution_trading_account(
    *,
    account_code: str,
    venue: str,
    source_trading_account_id: int,
    description: str | None,
    apply: bool,
    conn_factory: Callable[[], Any],
    repository_factory: Callable[[Any], LiveExecutionTradingAccountProvisioningRepository] = (
        LiveExecutionTradingAccountProvisioningRepository
    ),
    now_utc: datetime | None = None,
) -> LiveExecutionTradingAccountProvisioningResult:
    """Resolve, and only if ``apply=True`` and the row is absent, create it.

    ``apply=False`` (``--check``) never issues an ``INSERT`` and always rolls
    back/closes without committing, regardless of resolution outcome.
    """
    conn = conn_factory()
    try:
        repo = repository_factory(conn)
        resolution = resolve_live_execution_trading_account(
            account_code=account_code,
            venue=venue,
            source_trading_account_id=source_trading_account_id,
            description=description,
            repo=repo,
        )
        if resolution.status == "ALREADY_PROVISIONED":
            return LiveExecutionTradingAccountProvisioningResult(
                status="ALREADY_PROVISIONED",
                trading_account_id=resolution.trading_account_id,
                created=False,
                account_code=account_code,
                source_trading_account_id=source_trading_account_id,
            )
        # resolution.status == "WOULD_CREATE"
        if not apply:
            return LiveExecutionTradingAccountProvisioningResult(
                status="WOULD_CREATE",
                trading_account_id=None,
                created=False,
                account_code=account_code,
                source_trading_account_id=source_trading_account_id,
            )
        trading_account_id = repo.insert_trading_account(
            account_code=resolution.account_code,
            venue=resolution.venue,
            account_mode=resolution.account_mode,
            enabled=resolution.enabled,
            live_trading_enabled=resolution.live_trading_enabled,
            description=resolution.description,
            now_utc=now_utc or datetime.now(UTC),
        )
        conn.commit()
        return LiveExecutionTradingAccountProvisioningResult(
            status="CREATED",
            trading_account_id=trading_account_id,
            created=True,
            account_code=account_code,
            source_trading_account_id=source_trading_account_id,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
