"""Issue #399 Phase 4 runtime/replay contracts for automatic BUY.

This module is pure: no DB, executor, broker, credential, or order imports.
It defines the immutable runtime input snapshot identity and deterministic
idempotency evidence used by the automatic BUY runtime.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final


RUNTIME_INPUT_CONTRACT_VERSION: Final[str] = "1"
DEFAULT_MAX_RUNTIME_INPUT_AGE_SECONDS: Final[int] = 15 * 60


class AutomaticBuyRuntimeContractError(ValueError):
    pass


@dataclass(frozen=True)
class AutomaticBuyRuntimeInputV1:
    """One immutable, fully bound pre-evaluation input snapshot.

    ``evaluation_ts_utc`` is part of the immutable source snapshot. Replaying
    the same snapshot therefore evaluates Phase 1/2/3 at the same logical
    instant instead of depending on the wall clock of the replay process.
    Market/setup facts remain market-only; account facts are attached only at
    this runtime composition boundary and are consumed by decision_gate.
    """

    automatic_buy_runtime_input_id: int
    source_snapshot_key: str
    input_contract_version: str
    evaluation_ts_utc: datetime
    trading_account_id: int
    venue: str
    asset_id: int
    market: str
    strategy_bucket_id: str
    strategy_id: str
    strategy_version: str
    setup_id: str
    setup_ready: bool
    current_price: Decimal
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    re_entry_zone_low: Decimal | None
    re_entry_zone_high: Decimal | None
    setup_evidence_id: str
    setup_observed_ts_utc: datetime
    account_observed_ts_utc: datetime
    account_enabled: bool
    account_mode: str
    automatic_buy_execution_enabled: bool
    free_quote_balance_eur: Decimal
    free_quote_balance_observed_ts_utc: datetime
    blocking_conflict: bool
    proposed_position_amount_eur: Decimal
    current_bucket_amount_eur: Decimal
    current_open_positions: int
    current_asset_exposure_pct: Decimal
    max_automatic_buy_notional_eur: Decimal | None
    source_provenance: str


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_runtime_input_v1(
    value: AutomaticBuyRuntimeInputV1,
    *,
    max_age_seconds: int = DEFAULT_MAX_RUNTIME_INPUT_AGE_SECONDS,
) -> None:
    evaluation_ts_utc = value.evaluation_ts_utc
    if not _aware(evaluation_ts_utc) or max_age_seconds < 0:
        raise AutomaticBuyRuntimeContractError("INVALID_EVALUATION_TIMESTAMP")
    if (
        value.automatic_buy_runtime_input_id <= 0
        or value.input_contract_version != RUNTIME_INPUT_CONTRACT_VERSION
        or not _nonempty(value.source_snapshot_key)
        or len(value.source_snapshot_key) != 64
        or value.trading_account_id <= 0
        or value.asset_id <= 0
        or not all(_nonempty(item) for item in (
            value.venue,
            value.market,
            value.strategy_bucket_id,
            value.strategy_id,
            value.strategy_version,
            value.setup_id,
            value.setup_evidence_id,
            value.account_mode,
            value.source_provenance,
        ))
        or type(value.setup_ready) is not bool
        or type(value.account_enabled) is not bool
        or type(value.automatic_buy_execution_enabled) is not bool
        or type(value.blocking_conflict) is not bool
        or value.current_price <= 0
        or value.free_quote_balance_eur < 0
        or value.proposed_position_amount_eur <= 0
        or value.current_bucket_amount_eur < 0
        or value.current_open_positions < 0
        or value.current_asset_exposure_pct < 0
        or value.current_asset_exposure_pct > 100
        or (value.max_automatic_buy_notional_eur is not None and value.max_automatic_buy_notional_eur < 0)
    ):
        raise AutomaticBuyRuntimeContractError("INVALID_AUTOMATIC_BUY_RUNTIME_INPUT")
    if not all(_aware(item) for item in (
        value.setup_observed_ts_utc,
        value.account_observed_ts_utc,
        value.free_quote_balance_observed_ts_utc,
    )):
        raise AutomaticBuyRuntimeContractError("INVALID_AUTOMATIC_BUY_RUNTIME_TIMESTAMP")
    for observed in (
        value.setup_observed_ts_utc,
        value.account_observed_ts_utc,
        value.free_quote_balance_observed_ts_utc,
    ):
        age = evaluation_ts_utc - observed
        if age < timedelta(0) or age > timedelta(seconds=max_age_seconds):
            raise AutomaticBuyRuntimeContractError("STALE_OR_FUTURE_AUTOMATIC_BUY_RUNTIME_INPUT")


def automatic_buy_idempotency_key_v1(evidence: dict[str, Any]) -> str:
    """Hash the exact immutable source identities for one logical evaluation."""
    required = {
        "source_snapshot_key",
        "evaluation_ts_utc",
        "trading_account_id",
        "venue",
        "asset_id",
        "market",
        "strategy_id",
        "strategy_version",
        "setup_id",
        "setup_evidence_id",
        "strategy_bucket_config_ids",
        "strategy_bucket_revocation_ids",
        "account_protection_fingerprint",
        "venue_constraint_identity",
    }
    if set(evidence) != required:
        raise AutomaticBuyRuntimeContractError("INCOMPLETE_IDEMPOTENCY_EVIDENCE")
    if any(evidence[key] in (None, "") for key in required):
        raise AutomaticBuyRuntimeContractError("INCOMPLETE_IDEMPOTENCY_EVIDENCE")
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
