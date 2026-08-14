"""Phase 4A pure contracts for automatic-exit runtime inputs and replay keys.

No database, broker, credential, manual-execution, planner, or executor imports
are permitted here. Database rows are loaded by a later runtime repository.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Iterable


PROFILE_CONTRACT_VERSION: Final[str] = "1"
PERMISSION_CONTRACT_VERSION: Final[str] = "1"
DEFAULT_MAX_PROFILE_AGE_SECONDS: Final[int] = 15 * 60


class AutomaticExitRuntimeContractError(ValueError):
    pass


@dataclass(frozen=True)
class AutomaticExitPlanningPermissionV1:
    permission_id: int
    trading_account_id: int
    planning_enabled: bool
    effective_from_ts_utc: datetime
    effective_until_ts_utc: datetime | None
    permission_version: str
    source_provenance: str


@dataclass(frozen=True)
class AutomaticExitProfileV1:
    profile_id: str
    profile_version: str
    venue: str
    asset_id: int
    market: str
    active_target_price: Decimal | None
    invalidation_price: Decimal | None
    evidence_id: str
    evidence_provenance: str
    observed_ts_utc: datetime
    effective_from_ts_utc: datetime
    effective_until_ts_utc: datetime | None


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _active_at(*, effective_from: datetime, effective_until: datetime | None, at: datetime) -> bool:
    return effective_from <= at and (effective_until is None or at < effective_until)


def _validate_permission(row: AutomaticExitPlanningPermissionV1) -> None:
    if (
        row.permission_id <= 0
        or row.trading_account_id <= 0
        or row.permission_version != PERMISSION_CONTRACT_VERSION
        or not row.source_provenance.strip()
        or type(row.planning_enabled) is not bool
        or not _aware(row.effective_from_ts_utc)
        or (row.effective_until_ts_utc is not None and not _aware(row.effective_until_ts_utc))
        or (row.effective_until_ts_utc is not None and row.effective_until_ts_utc <= row.effective_from_ts_utc)
    ):
        raise AutomaticExitRuntimeContractError("INVALID_OR_UNSUPPORTED_AUTOMATIC_EXIT_PERMISSION")


def resolve_automatic_exit_planning_enabled(
    permissions: Iterable[AutomaticExitPlanningPermissionV1], *, trading_account_id: int, at: datetime,
) -> bool:
    """Default-disabled account permission resolver; overlap is fail-closed."""
    if trading_account_id <= 0 or not _aware(at):
        raise AutomaticExitRuntimeContractError("INVALID_PERMISSION_LOOKUP")
    account_rows = [row for row in permissions if row.trading_account_id == trading_account_id]
    for row in account_rows:
        _validate_permission(row)
    matches = [row for row in account_rows if _active_at(
        effective_from=row.effective_from_ts_utc, effective_until=row.effective_until_ts_utc, at=at,
    )]
    if not matches:
        return False
    if len(matches) != 1:
        raise AutomaticExitRuntimeContractError("CONFLICTING_AUTOMATIC_EXIT_PERMISSION")
    return matches[0].planning_enabled


def resolve_automatic_exit_profile(
    profiles: Iterable[AutomaticExitProfileV1], *, venue: str, asset_id: int, market: str, at: datetime,
    max_profile_age_seconds: int = DEFAULT_MAX_PROFILE_AGE_SECONDS,
) -> AutomaticExitProfileV1:
    """Return the one applicable V1 market profile or fail closed."""
    if not _aware(at) or max_profile_age_seconds < 0:
        raise AutomaticExitRuntimeContractError("INVALID_PROFILE_LOOKUP_TIMESTAMP")
    matches = [
        profile for profile in profiles
        if profile.venue.strip().lower() == venue.strip().lower()
        and profile.asset_id == asset_id
        and profile.market.strip().upper().replace("/", "-") == market.strip().upper().replace("/", "-")
        and _aware(profile.observed_ts_utc)
        and _aware(profile.effective_from_ts_utc)
        and (profile.effective_until_ts_utc is None or _aware(profile.effective_until_ts_utc))
        and _active_at(effective_from=profile.effective_from_ts_utc, effective_until=profile.effective_until_ts_utc, at=at)
    ]
    if len(matches) != 1:
        raise AutomaticExitRuntimeContractError("MISSING_OR_CONFLICTING_AUTOMATIC_EXIT_PROFILE")
    profile = matches[0]
    if (
        profile.profile_version != PROFILE_CONTRACT_VERSION
        or not profile.profile_id.strip()
        or not profile.evidence_id.strip()
        or not profile.evidence_provenance.strip()
        or at - profile.observed_ts_utc < timedelta(0)
        or at - profile.observed_ts_utc > timedelta(seconds=max_profile_age_seconds)
        or (profile.active_target_price is None and profile.invalidation_price is None)
        or (profile.active_target_price is not None and profile.active_target_price <= 0)
        or (profile.invalidation_price is not None and profile.invalidation_price <= 0)
    ):
        raise AutomaticExitRuntimeContractError("INVALID_OR_UNSUPPORTED_AUTOMATIC_EXIT_PROFILE")
    return profile


def automatic_exit_idempotency_key_v1(evidence: dict[str, Any]) -> str:
    """SHA-256 over canonical JSON of immutable source identifiers only."""
    required = {
        "trading_account_id", "position_reference", "venue", "asset_id", "market",
        "position_snapshot_id", "balance_snapshot_id", "open_order_snapshot_run_id",
        "market_price_snapshot_id", "automatic_exit_permission_id", "exit_profile_id",
        "exit_profile_version", "exit_profile_observed_ts_utc", "venue_constraint_id",
        "venue_metadata_synced_ts_utc",
    }
    logical_evidence = {key: value for key, value in evidence.items() if key != "runtime_version"}
    if set(logical_evidence) != required or any(logical_evidence[key] in (None, "") for key in required):
        raise AutomaticExitRuntimeContractError("INCOMPLETE_IDEMPOTENCY_EVIDENCE")
    serialized = json.dumps(logical_evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
