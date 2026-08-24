"""Issue #474: canonical decision-gate-owned automatic BUY account-allocation
evidence projection.

Prior to this contract, the automatic BUY runtime lacked one coherent,
decision-gate-owned projection for:

- ``automatic_buy_execution_enabled``
- ``proposed_position_amount_eur``
- ``current_bucket_amount_eur``
- ``current_open_positions``
- ``current_asset_exposure_pct``

A prior attempt (PR #473, reverted) let these arrive as operator/caller JSON,
which made the acceptance harness an unauthorized account-permission/
allocation authority. This module is the pure, typed replacement: one
immutable, fully-bound evidence snapshot assembled exclusively from canonical
account/config/state sources by
``automatic_buy_account_allocation_evidence_repository_v1`` (decision_gate
DB reads only). It never accepts caller-supplied overrides for any of the
five fields above; every field on :class:`AutomaticBuyAccountAllocationEvidenceV1`
is either read verbatim from an authoritative table or deterministically
derived from one.

Field ownership (see ``docs/architecture/automatic_buy_account_allocation_evidence_v1.md``
for the full narrative):

- ``account_enabled`` / ``account_mode`` / ``live_trading_enabled``: bound
  verbatim from ``trading_account``.
- ``automatic_buy_execution_enabled``: resolved from
  ``automatic_buy_account_permission_contract_v1`` (new decision-gate-owned
  permission table; no canonical owner existed before #474).
- ``free_quote_balance_eur``: for LIVE, bound from the COMPLETE account-state
  bundle's ``trading_account_balance_snapshot`` EUR row. PAPER has no broker
  funding authority; when its canonical bundle has no EUR row this is zero
  with no balance-snapshot identity, and the gate uses bucket limits instead.
- ``current_open_positions`` / ``current_bucket_amount_eur``: derived from the
  same COMPLETE bundle's ``account_position_snapshot`` rows, valued in EUR at
  the latest fresh market price. Scoped to the whole account, not the
  individual strategy bucket, because the schema does not (yet) tag a
  position with the strategy bucket that opened it; this is a documented,
  deliberately conservative (never permission-widening) approximation.
- ``current_asset_exposure_pct``: the candidate asset's own position value as
  a percentage of total account NAV (positions + free quote balance).
- ``proposed_position_amount_eur``: bound verbatim from the account's already
  -resolved ``strategy_bucket_account_config_v1.max_position_amount_eur``
  (the account's own configured risk/allocation policy, never a caller
  choice); unresolved config yields ``Decimal("0")``, which the existing
  gate/candidate-amount validation rejects the same way it already rejects
  any other non-positive proposed amount.

This module is pure (no DB, executor, broker, credential, or order imports).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

EVIDENCE_CONTRACT_VERSION: Final[str] = "1"
SUPPORTED_EVIDENCE_CONTRACT_VERSIONS: Final[frozenset[str]] = frozenset({EVIDENCE_CONTRACT_VERSION})

ACCOUNT_MODE_PAPER: Final[str] = "paper"
ACCOUNT_MODE_LIVE: Final[str] = "live"
SUPPORTED_ACCOUNT_MODES: Final[frozenset[str]] = frozenset({ACCOUNT_MODE_PAPER, ACCOUNT_MODE_LIVE})

DEFAULT_MAX_EVIDENCE_AGE_SECONDS: Final[int] = 15 * 60


class AutomaticBuyAccountAllocationEvidenceContractError(ValueError):
    """Fail-closed contract violation. ``args[0]`` is the reason code."""


@dataclass(frozen=True)
class AutomaticBuyAccountAllocationEvidenceV1:
    """One immutable, fully-bound decision-gate account-allocation snapshot.

    Bound to exactly one ``trading_account_id`` + ``venue``/``asset_id``/
    ``market`` + one ``evaluation_ts_utc``. Every account-owned field is
    derived by the repository loader from canonical sources; this dataclass
    and its validator never accept a value on trust from a caller-supplied
    override.
    """

    evidence_contract_version: str
    trading_account_id: int
    venue: str
    asset_id: int
    market: str
    strategy_bucket_id: str
    evaluation_ts_utc: datetime
    account_observed_ts_utc: datetime
    account_enabled: bool
    account_mode: str
    live_trading_enabled: bool
    automatic_buy_execution_enabled: bool
    free_quote_balance_eur: Decimal
    free_quote_balance_observed_ts_utc: datetime
    blocking_conflict: bool
    proposed_position_amount_eur: Decimal
    current_bucket_amount_eur: Decimal
    current_open_positions: int
    current_asset_exposure_pct: Decimal
    account_state_snapshot_run_id: int
    trading_account_balance_snapshot_id: int | None


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _stale(observed: datetime, evaluation: datetime, max_age_seconds: int) -> bool:
    age = evaluation - observed
    return age < timedelta(0) or age > timedelta(seconds=max_age_seconds)


def validate_automatic_buy_account_allocation_evidence_v1(
    value: AutomaticBuyAccountAllocationEvidenceV1,
    *,
    max_age_seconds: int = DEFAULT_MAX_EVIDENCE_AGE_SECONDS,
) -> None:
    """Fail closed on any malformed, inconsistent, or stale evidence snapshot."""
    if (
        value.evidence_contract_version not in SUPPORTED_EVIDENCE_CONTRACT_VERSIONS
        or value.trading_account_id <= 0
        or value.asset_id <= 0
        or not _nonempty(value.venue)
        or not _nonempty(value.market)
        or not _nonempty(value.strategy_bucket_id)
        or value.account_state_snapshot_run_id <= 0
    ):
        raise AutomaticBuyAccountAllocationEvidenceContractError("INVALID_ACCOUNT_ALLOCATION_EVIDENCE_IDENTITY")

    if not all(_aware(item) for item in (
        value.evaluation_ts_utc,
        value.account_observed_ts_utc,
        value.free_quote_balance_observed_ts_utc,
    )):
        raise AutomaticBuyAccountAllocationEvidenceContractError("INVALID_ACCOUNT_ALLOCATION_EVIDENCE_TIMESTAMP")

    if max_age_seconds < 0:
        raise AutomaticBuyAccountAllocationEvidenceContractError("INVALID_ACCOUNT_ALLOCATION_EVIDENCE_MAX_AGE")
    for observed in (value.account_observed_ts_utc,):
        if _stale(observed, value.evaluation_ts_utc, max_age_seconds):
            raise AutomaticBuyAccountAllocationEvidenceContractError("STALE_ACCOUNT_ALLOCATION_EVIDENCE")

    if (
        type(value.account_enabled) is not bool
        or type(value.live_trading_enabled) is not bool
        or type(value.automatic_buy_execution_enabled) is not bool
        or type(value.blocking_conflict) is not bool
        or value.account_mode not in SUPPORTED_ACCOUNT_MODES
    ):
        raise AutomaticBuyAccountAllocationEvidenceContractError("INVALID_ACCOUNT_ALLOCATION_EVIDENCE_ACCOUNT_STATE")

    if value.account_mode == ACCOUNT_MODE_LIVE:
        if value.trading_account_balance_snapshot_id is None or value.trading_account_balance_snapshot_id <= 0:
            raise AutomaticBuyAccountAllocationEvidenceContractError("INVALID_ACCOUNT_ALLOCATION_EVIDENCE_IDENTITY")
        if _stale(value.free_quote_balance_observed_ts_utc, value.evaluation_ts_utc, max_age_seconds):
            raise AutomaticBuyAccountAllocationEvidenceContractError("STALE_ACCOUNT_ALLOCATION_EVIDENCE")
    elif value.trading_account_balance_snapshot_id is not None and value.trading_account_balance_snapshot_id <= 0:
        raise AutomaticBuyAccountAllocationEvidenceContractError("INVALID_ACCOUNT_ALLOCATION_EVIDENCE_IDENTITY")

    # Deliberately NOT rejected here: `account_mode == "live"` with
    # `live_trading_enabled == False` is a normal, expected, faithfully-bound
    # persisted `trading_account` state (e.g. production account 3), not
    # corrupt evidence. This projection's job is to bind that fact exactly as
    # persisted; automatic_buy_gate_v1 owns the decision to reject it
    # (REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT), with an audited outcome
    # rather than a hard evidence-loading failure.

    if (
        value.free_quote_balance_eur < 0
        or value.proposed_position_amount_eur < 0
        or value.current_bucket_amount_eur < 0
        or isinstance(value.current_open_positions, bool)
        or not isinstance(value.current_open_positions, int)
        or value.current_open_positions < 0
        or value.current_asset_exposure_pct < 0
        or value.current_asset_exposure_pct > 100
    ):
        raise AutomaticBuyAccountAllocationEvidenceContractError("INVALID_ACCOUNT_ALLOCATION_EVIDENCE_AMOUNTS")
