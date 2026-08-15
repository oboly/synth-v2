"""Pure automatic BUY entry-candidate policy evaluation.

Issue #399 Phase 1: the market-only, account-agnostic automatic BUY/re-entry
candidate contract. This module evaluates non-authoritative BUY entry-policy
intent from an explicit, already-decided market-only setup/strategy
observation. It does not grant permission, resolve a base quantity or
notional, construct a ladder, write state, or import execution/broker/account
code.

Design precedent: this module mirrors the structural discipline of
``src.exit_policy.automatic_exit_candidate_v1`` (typed market-context input
dataclass, immutable candidate dataclass, pure ``evaluate_*`` function with an
explicit ``evaluation_ts_utc``, explicit freshness/staleness bounds, explicit
fail-closed ``NON_ACTIONABLE`` state) rather than the exit-specific semantics
of that module.

Audit note (Issue #399 Phase 1 requirement to prefer an existing canonical
contract over inventing a parallel strategy-truth model):

- ``src.advice_route.interfaces_v1.StrategyProposal`` is the closest existing
  contract literally named "StrategyProposal" and already enforces
  account-agnosticism (``account_awareness``/``broker_write_allowed``/
  ``order_submission`` fixed to ``False``/``False``/``False`` and
  ``decision_required`` fixed to ``True``) via
  ``validate_forbidden_fields_absent``. It was evaluated first. It is a
  general multi-action (``BUY``/``SELL``/``HOLD``/``ROTATE``/``WARN``)
  framework/A+-narrative *paper-advice interpretation* contract (the
  ``advice / paper advice`` layer), keyed on a single ``symbol`` rather than
  an explicit ``venue``/``market`` pair, versioned by ``route_version`` (the
  advice-route schema version, not a strategy identity/version), and has no
  explicit numeric staleness bound comparable to
  ``max_setup_context_age_seconds`` below. Reusing it in place would either
  widen a paper-advice-interpretation contract to carry BUY-lane-specific
  identity/freshness semantics it was not designed for, or require
  action-specific subclassing that the frozen dataclass does not support.
- ``src.selection.selection_engine_v2.SelectionCandidate``/``SelectionRow``
  confirm ``selection_engine`` is genuinely market-only/account-agnostic
  (no balance/position/order fields), but they are raw multi-interval
  ranking-score rows, not an entry-candidate contract with entry/re-entry
  zone context or evidence/provenance ids.
- Neither existing contract binds the exact minimum field set Issue #399
  Phase 1 requires (venue, market, strategy identity/version, setup
  identity, asof/freshness, desired entry/re-entry market context,
  evidence/provenance) without reshaping an unrelated layer's contract.

This module therefore defines a new, narrowly-scoped BUY-only candidate
contract, and reuses the *pattern* of
``advice_route.interfaces_v1.validate_forbidden_fields_absent`` (a local,
BUY-lane-specific forbidden-field-substring guard below) rather than
importing and mutating the shared paper-advice module's global forbidden-list
constant, which is out of this task's scope. Like
``automatic_exit_candidate_v1``, this module consumes an already-decided
market-only ``strategy_id``/``strategy_version``/``setup_id`` and entry/
re-entry zone context as explicit input; it does not rank markets, score
setups, or recompute strategy logic itself, so it does not create a parallel
source of strategy truth.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final


POLICY_NAME: Final[str] = "automatic_buy_candidate_v1"
POLICY_VERSION: Final[str] = "1"

STATE_NO_ACTION: Final[str] = "NO_ACTION"
STATE_NON_ACTIONABLE: Final[str] = "NON_ACTIONABLE"
STATE_CANDIDATE: Final[str] = "CANDIDATE"

ACTION_ENTER: Final[str] = "ENTER"
ACTION_RE_ENTER: Final[str] = "RE_ENTER"

REASON_SETUP_NOT_READY: Final[str] = "SETUP_NOT_READY"
REASON_NO_ENTRY_CONDITION: Final[str] = "NO_ENTRY_CONDITION"
REASON_ENTRY_ZONE_REACHED: Final[str] = "ENTRY_ZONE_REACHED"
REASON_RE_ENTRY_ZONE_REACHED: Final[str] = "RE_ENTRY_ZONE_REACHED"
REASON_SETUP_CONTEXT_STALE: Final[str] = "SETUP_CONTEXT_STALE"
REASON_INVALID_CONTEXT: Final[str] = "INVALID_SETUP_CONTEXT"
REASON_INVALID_TIMESTAMP: Final[str] = "NAIVE_TIMESTAMP"
REASON_INVALID_POLICY_CONFIG: Final[str] = "INVALID_POLICY_CONFIG"

# Substrings that must never appear in a bound field name of this module's
# dataclasses. This candidate is market-only and account-agnostic by
# construction; account, balance, allocation, sizing, credential, and broker
# facts belong to decision_gate / execution_planner / executor, never here.
# Mirrors the enforcement pattern of
# ``src.advice_route.interfaces_v1.validate_forbidden_fields_absent`` with a
# BUY-lane-specific substring list; kept local (not imported) so this
# market-only module has no dependency on the paper-advice interpretation
# layer and can list every term Issue #399 explicitly forbids.
FORBIDDEN_FIELD_SUBSTRINGS: Final[tuple[str, ...]] = (
    "trading_account_id",
    "account_id",
    "balance",
    "wallet",
    "allocation",
    "permitted_quantity",
    "position_size",
    "position_qty",
    "credential",
    "api_key",
    "api_secret",
    "secret",
    "client_order_id",
    "broker",
    "order_submit",
    "submit_order",
    "cancel_order",
    "replace_order",
    "order_payload",
)


def validate_no_account_or_broker_fields(*dataclass_types: type[object]) -> None:
    """Fail closed if any bound field name looks account- or broker-aware."""
    for dataclass_type in dataclass_types:
        if not is_dataclass(dataclass_type):
            raise TypeError(f"{dataclass_type!r} is not a dataclass")
        for dataclass_field in fields(dataclass_type):
            normalized = dataclass_field.name.lower()
            for forbidden in FORBIDDEN_FIELD_SUBSTRINGS:
                if forbidden in normalized:
                    raise ValueError(
                        f"{dataclass_type.__name__}.{dataclass_field.name} contains forbidden field substring {forbidden!r}"
                    )


@dataclass(frozen=True)
class AutomaticBuySetupContextV1:
    """Validated market-only setup/strategy observation; no account facts.

    ``strategy_id``/``strategy_version`` identify the market-only strategy
    candidate that decided this setup is entry-eligible (upstream selection /
    signal / advice evidence). This contract does not recompute or re-rank
    strategy logic; it only evaluates entry/re-entry zone geometry against
    the current price for an already-decided, ready setup.
    """

    venue: str
    asset_id: int
    market: str
    strategy_id: str
    strategy_version: str
    setup_id: str
    setup_ready: bool
    current_price: Decimal
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    re_entry_zone_low: Decimal | None
    re_entry_zone_high: Decimal | None
    evidence_id: str
    observed_ts_utc: datetime


@dataclass(frozen=True)
class AutomaticBuyPolicyConfigV1:
    """V1 policy defaults, not account-permission defaults."""

    max_setup_context_age_seconds: int = 15 * 60


@dataclass(frozen=True)
class AutomaticBuyCandidateV1:
    venue: str
    asset_id: int
    market: str
    strategy_id: str
    strategy_version: str
    setup_id: str
    candidate_action: str  # ENTER | RE_ENTER
    reason_code: str
    evidence_id: str
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    observed_ts_utc: datetime
    policy_name: str = POLICY_NAME
    policy_version: str = POLICY_VERSION


@dataclass(frozen=True)
class AutomaticBuyEvaluationV1:
    state: str  # NO_ACTION | NON_ACTIONABLE | CANDIDATE
    reason_code: str
    candidate: AutomaticBuyCandidateV1 | None


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _is_stale(observed_ts_utc: datetime, evaluation_ts_utc: datetime, max_age_seconds: int) -> bool:
    age = evaluation_ts_utc - observed_ts_utc
    return age < timedelta(0) or age > timedelta(seconds=max_age_seconds)


def _valid_zone(low: Decimal | None, high: Decimal | None) -> bool:
    if low is not None and low <= 0:
        return False
    if high is not None and high <= 0:
        return False
    if low is not None and high is not None and low > high:
        return False
    return True


def _in_zone(price: Decimal, low: Decimal | None, high: Decimal | None) -> bool:
    if low is None or high is None:
        return False
    return low <= price <= high


def evaluate_automatic_buy_candidate_v1(
    *,
    setup_context: AutomaticBuySetupContextV1,
    evaluation_ts_utc: datetime,
    config: AutomaticBuyPolicyConfigV1 = AutomaticBuyPolicyConfigV1(),
) -> AutomaticBuyEvaluationV1:
    """Return a non-authoritative BUY candidate or fail closed.

    All timestamps must be timezone-aware UTC instants; naive timestamps are
    rejected as ``NON_ACTIONABLE`` rather than silently being assumed UTC.
    ``evaluation_ts_utc`` is explicit so equal inputs always produce equal
    output. This function only evaluates entry/re-entry zone geometry for an
    already-decided, ready setup; it does not choose strategies, rank
    markets, or resolve any quantity/notional.
    """
    if not setup_context.setup_ready:
        return AutomaticBuyEvaluationV1(STATE_NO_ACTION, REASON_SETUP_NOT_READY, None)

    if (
        not setup_context.venue.strip()
        or not setup_context.market.strip()
        or not setup_context.strategy_id.strip()
        or not setup_context.strategy_version.strip()
        or not setup_context.setup_id.strip()
        or not setup_context.evidence_id.strip()
        or setup_context.asset_id <= 0
    ):
        return AutomaticBuyEvaluationV1(STATE_NON_ACTIONABLE, REASON_INVALID_CONTEXT, None)

    if not _is_aware(setup_context.observed_ts_utc) or not _is_aware(evaluation_ts_utc):
        return AutomaticBuyEvaluationV1(STATE_NON_ACTIONABLE, REASON_INVALID_TIMESTAMP, None)

    if config.max_setup_context_age_seconds < 0:
        return AutomaticBuyEvaluationV1(STATE_NON_ACTIONABLE, REASON_INVALID_POLICY_CONFIG, None)

    if setup_context.current_price <= 0:
        return AutomaticBuyEvaluationV1(STATE_NON_ACTIONABLE, REASON_INVALID_CONTEXT, None)

    if not _valid_zone(setup_context.entry_zone_low, setup_context.entry_zone_high):
        return AutomaticBuyEvaluationV1(STATE_NON_ACTIONABLE, REASON_INVALID_CONTEXT, None)

    if not _valid_zone(setup_context.re_entry_zone_low, setup_context.re_entry_zone_high):
        return AutomaticBuyEvaluationV1(STATE_NON_ACTIONABLE, REASON_INVALID_CONTEXT, None)

    if _is_stale(setup_context.observed_ts_utc, evaluation_ts_utc, config.max_setup_context_age_seconds):
        return AutomaticBuyEvaluationV1(STATE_NON_ACTIONABLE, REASON_SETUP_CONTEXT_STALE, None)

    if _in_zone(setup_context.current_price, setup_context.entry_zone_low, setup_context.entry_zone_high):
        action, reason = ACTION_ENTER, REASON_ENTRY_ZONE_REACHED
    elif _in_zone(setup_context.current_price, setup_context.re_entry_zone_low, setup_context.re_entry_zone_high):
        action, reason = ACTION_RE_ENTER, REASON_RE_ENTRY_ZONE_REACHED
    else:
        return AutomaticBuyEvaluationV1(STATE_NO_ACTION, REASON_NO_ENTRY_CONDITION, None)

    return AutomaticBuyEvaluationV1(
        state=STATE_CANDIDATE,
        reason_code=reason,
        candidate=AutomaticBuyCandidateV1(
            venue=setup_context.venue,
            asset_id=setup_context.asset_id,
            market=setup_context.market,
            strategy_id=setup_context.strategy_id,
            strategy_version=setup_context.strategy_version,
            setup_id=setup_context.setup_id,
            candidate_action=action,
            reason_code=reason,
            evidence_id=setup_context.evidence_id,
            entry_zone_low=setup_context.entry_zone_low,
            entry_zone_high=setup_context.entry_zone_high,
            observed_ts_utc=evaluation_ts_utc,
        ),
    )


validate_no_account_or_broker_fields(
    AutomaticBuySetupContextV1,
    AutomaticBuyPolicyConfigV1,
    AutomaticBuyCandidateV1,
    AutomaticBuyEvaluationV1,
)
