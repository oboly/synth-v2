"""Issue #279: deterministic permit/block evaluation for account-scoped
strategy-bucket participation.

Consumes the resolved ``StrategyBucketAccountConfigV1`` (see
``strategy_bucket_account_config_contract_v1``) plus a small set of
pre-derived, caller-supplied account/bucket state facts (current bucket
allocation, current open-position count, current asset exposure). It does
not read a broker, compute a portfolio ledger, create execution intent, or
perform persistence. No market-regime logic and no order placement --
``decision_gate`` owns permission only; ``execution_planner``/``executor``
remain downstream and out of scope.

This module does not validate strategy performance (#232's responsibility)
and never marks a bucket validated, paper-ready, or live-ready; it only
answers whether an already-validated, market-only candidate may currently
participate in this account's configured bucket.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final

from src.decision_gate.strategy_bucket_account_config_contract_v1 import (
    StrategyBucketAccountConfigError,
    StrategyBucketAccountConfigV1,
    resolve_strategy_bucket_account_config_v1,
)


REQUEST_KIND_NEW_ENTRY: Final[str] = "NEW_ENTRY"
REQUEST_KIND_REDUCE_REVIEW: Final[str] = "REDUCE_REVIEW"
SUPPORTED_REQUEST_KINDS: Final[frozenset[str]] = frozenset({REQUEST_KIND_NEW_ENTRY, REQUEST_KIND_REDUCE_REVIEW})

DECISION_PERMITTED: Final[str] = "PERMITTED"
DECISION_BLOCKED: Final[str] = "BLOCKED"

REASON_CONFIGURATION_UNRESOLVED: Final[str] = "STRATEGY_BUCKET_CONFIGURATION_UNRESOLVED"
REASON_BUCKET_DISABLED: Final[str] = "STRATEGY_BUCKET_DISABLED"
REASON_NEW_ENTRIES_NOT_ALLOWED: Final[str] = "STRATEGY_BUCKET_NEW_ENTRIES_NOT_ALLOWED"
REASON_REDUCE_REVIEWS_NOT_ALLOWED: Final[str] = "STRATEGY_BUCKET_REDUCE_REVIEWS_NOT_ALLOWED"
REASON_POSITION_AMOUNT_CEILING_EXCEEDED: Final[str] = "STRATEGY_BUCKET_POSITION_AMOUNT_CEILING_EXCEEDED"
REASON_BUCKET_AMOUNT_CEILING_EXCEEDED: Final[str] = "STRATEGY_BUCKET_AMOUNT_CEILING_EXCEEDED"
REASON_ASSET_EXPOSURE_CEILING_EXCEEDED: Final[str] = "STRATEGY_BUCKET_ASSET_EXPOSURE_CEILING_EXCEEDED"
REASON_OPEN_POSITIONS_CEILING_EXCEEDED: Final[str] = "STRATEGY_BUCKET_OPEN_POSITIONS_CEILING_EXCEEDED"
REASON_INVALID_REQUEST: Final[str] = "INVALID_STRATEGY_BUCKET_PARTICIPATION_REQUEST"
REASON_PERMITTED: Final[str] = "STRATEGY_BUCKET_PARTICIPATION_PERMITTED"

EVALUATION_CONTRACT_VERSION: Final[str] = "1"


class StrategyBucketParticipationEvaluationError(ValueError):
    """Invalid participation-request input; never raised for BLOCKED decisions."""


@dataclass(frozen=True)
class StrategyBucketParticipationRequestV1:
    """One already-validated, market-only candidate's request to participate
    in one account's configured strategy bucket.

    ``proposed_position_amount_eur`` is the candidate's proposed new
    position sizing. ``current_bucket_amount_eur`` and
    ``current_open_positions`` are the account's own already-observed
    bucket-scoped state (no ledger recomputation happens here).
    ``current_asset_exposure_pct`` is the account's already-observed
    exposure to this candidate's asset, expressed 0-100.
    """

    trading_account_id: int
    strategy_bucket_id: str
    request_kind: str
    proposed_position_amount_eur: Decimal
    current_bucket_amount_eur: Decimal
    current_open_positions: int
    current_asset_exposure_pct: Decimal
    evaluation_ts_utc: datetime


@dataclass(frozen=True)
class StrategyBucketParticipationDecisionV1:
    evaluation_contract_version: str
    decision_state: str
    reason_code: str
    trading_account_id: int
    strategy_bucket_id: str
    request_kind: str
    evaluated_ts_utc: datetime


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _is_nonnegative_decimal(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value >= 0


def _blocked(request: StrategyBucketParticipationRequestV1, *, reason: str) -> StrategyBucketParticipationDecisionV1:
    return StrategyBucketParticipationDecisionV1(
        evaluation_contract_version=EVALUATION_CONTRACT_VERSION,
        decision_state=DECISION_BLOCKED,
        reason_code=reason,
        trading_account_id=request.trading_account_id,
        strategy_bucket_id=request.strategy_bucket_id,
        request_kind=request.request_kind,
        evaluated_ts_utc=request.evaluation_ts_utc,
    )


def _validate_request(request: StrategyBucketParticipationRequestV1) -> None:
    if (
        request.trading_account_id <= 0
        or not isinstance(request.strategy_bucket_id, str)
        or not request.strategy_bucket_id.strip()
        or request.request_kind not in SUPPORTED_REQUEST_KINDS
        or not _is_nonnegative_decimal(request.proposed_position_amount_eur)
        or not _is_nonnegative_decimal(request.current_bucket_amount_eur)
        or isinstance(request.current_open_positions, bool)
        or not isinstance(request.current_open_positions, int)
        or request.current_open_positions < 0
        or not _is_nonnegative_decimal(request.current_asset_exposure_pct)
        or request.current_asset_exposure_pct > 100
        or not _aware(request.evaluation_ts_utc)
    ):
        raise StrategyBucketParticipationEvaluationError("INVALID_STRATEGY_BUCKET_PARTICIPATION_REQUEST")


def evaluate_strategy_bucket_participation_v1(
    config_rows: tuple,
    config_revocations: tuple = (),
    *,
    request: StrategyBucketParticipationRequestV1,
) -> StrategyBucketParticipationDecisionV1:
    """Evaluate one participation request against the resolved account config.

    Fails closed (returns a typed ``BLOCKED`` decision, never raises for a
    data-quality condition) when the configuration is missing, ambiguous,
    disabled, unsupported-version, or any configured ceiling is exceeded.
    Raises :class:`StrategyBucketParticipationEvaluationError` only for a
    malformed request supplied by the caller itself.
    """
    _validate_request(request)

    try:
        config: StrategyBucketAccountConfigV1 = resolve_strategy_bucket_account_config_v1(
            config_rows,
            config_revocations,
            trading_account_id=request.trading_account_id,
            strategy_bucket_id=request.strategy_bucket_id,
            at=request.evaluation_ts_utc,
        )
    except StrategyBucketAccountConfigError:
        return _blocked(request, reason=REASON_CONFIGURATION_UNRESOLVED)

    if not config.is_enabled:
        return _blocked(request, reason=REASON_BUCKET_DISABLED)

    if request.request_kind == REQUEST_KIND_NEW_ENTRY and not config.allow_new_entries:
        return _blocked(request, reason=REASON_NEW_ENTRIES_NOT_ALLOWED)
    if request.request_kind == REQUEST_KIND_REDUCE_REVIEW and not config.allow_reduce_reviews:
        return _blocked(request, reason=REASON_REDUCE_REVIEWS_NOT_ALLOWED)

    if (
        config.max_position_amount_eur is not None
        and request.proposed_position_amount_eur > config.max_position_amount_eur
    ):
        return _blocked(request, reason=REASON_POSITION_AMOUNT_CEILING_EXCEEDED)

    if config.max_bucket_amount_eur is not None:
        projected_bucket_amount = request.current_bucket_amount_eur + request.proposed_position_amount_eur
        if projected_bucket_amount > config.max_bucket_amount_eur:
            return _blocked(request, reason=REASON_BUCKET_AMOUNT_CEILING_EXCEEDED)

    if (
        config.max_asset_exposure_pct is not None
        and request.current_asset_exposure_pct > config.max_asset_exposure_pct
    ):
        return _blocked(request, reason=REASON_ASSET_EXPOSURE_CEILING_EXCEEDED)

    if (
        request.request_kind == REQUEST_KIND_NEW_ENTRY
        and config.max_open_positions is not None
        and request.current_open_positions >= config.max_open_positions
    ):
        return _blocked(request, reason=REASON_OPEN_POSITIONS_CEILING_EXCEEDED)

    return StrategyBucketParticipationDecisionV1(
        evaluation_contract_version=EVALUATION_CONTRACT_VERSION,
        decision_state=DECISION_PERMITTED,
        reason_code=REASON_PERMITTED,
        trading_account_id=request.trading_account_id,
        strategy_bucket_id=request.strategy_bucket_id,
        request_kind=request.request_kind,
        evaluated_ts_utc=request.evaluation_ts_utc,
    )
