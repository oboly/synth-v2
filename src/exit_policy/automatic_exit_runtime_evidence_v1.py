"""Phase 4/5 pure automatic-exit runtime cycle: evidence -> candidate -> gate -> planner.

This module is the sole orchestration seam that sequences the already-reviewed
Phase 1-3 pure contracts (candidate evaluator, decision_gate permission gate,
execution_planner immutable ladder) plus the Phase 4A persisted-input
contracts (`automatic_exit_runtime_contract_v1`) against one caller-assembled
evidence bundle for one exact account/position/market.

It performs NO database, broker, credential, executor, or manual-execution
call. Database rows are loaded by
`src.exit_policy.automatic_exit_runtime_repository_v1` and turned into the
`AutomaticExitRuntimeEvidenceV1` bundle this module consumes; DB persistence
of the resulting audit evidence is a separate write-only concern in
`src.exit_policy.automatic_exit_runtime_audit_writer_v1`.

Determinism: every fact carries its own observed timestamp and every
freshness check is evaluated against the caller-supplied
``evidence.evaluation_ts_utc`` -- never real wall-clock time. This is a
deliberate deviation from reusing
``src.decision_gate.free_base_quantity_v1.resolve_free_base_quantity``: that
resolver is hardwired to ``src.manual_execution._trusted_clock_v1.utc_now()``
(a real-time-only clock by design, see that module's docstring), which is
incompatible with a replayable, same-input/same-output runtime cycle. The
equivalent free-quantity formula (available minus not-yet-broker-reflected
reservations, fail closed while any reservation awaits reconciliation) is
reproduced here against the explicit evaluation instant instead.

Same-input/same-output: given equal ``AutomaticExitRuntimeEvidenceV1``, this
module always returns an equal ``AutomaticExitRuntimeCycleResultV1`` and the
same idempotency key.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=consumed_pure_contract_only
execution_planner=consumed_pure_contract_only
executor=none
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from src.account.account_state_snapshot_alignment_v1 import AccountStateSnapshotRunV1
from src.decision_gate.automatic_exit_gate_v1 import (
    STATE_APPROVED,
    AutomaticExitGateContextV1,
    AutomaticExitGateDecisionV1,
    evaluate_automatic_exit_candidate_permission_v1,
)
from src.decision_gate.free_base_quantity_v1 import WalletAvailableSnapshot, resolve_free_base_quantity_core_v1
from src.execution_planner.automatic_exit_planner_v1 import (
    AutomaticExitPlanningContextV1,
    AutomaticExitPlanningError,
    AutomaticExitPlanV1,
    build_automatic_exit_plan_v1,
)
from src.exit_policy.automatic_exit_candidate_v1 import (
    STATE_CANDIDATE,
    AutomaticExitCandidateV1,
    AutomaticExitMarketContextV1,
    AutomaticExitPolicyConfigV1,
    AutomaticExitPositionContextV1,
    evaluate_automatic_exit_candidate_v1,
)
from src.exit_policy.automatic_exit_runtime_contract_v1 import (
    DEFAULT_MAX_PROFILE_AGE_SECONDS,
    AutomaticExitPlanningPermissionV1,
    AutomaticExitProfileV1,
    AutomaticExitRuntimeContractError,
    automatic_exit_idempotency_key_v1,
    resolve_automatic_exit_planning_enabled,
    resolve_automatic_exit_profile,
)
from src.market_rules.venue_execution_constraints_v1 import (
    STATUS_FRESH,
    VenueExecutionConstraints,
)


RUNTIME_VERSION: Final[str] = "automatic_exit_runtime_cycle_v1"

PLANNER_STATE_NOT_ATTEMPTED: Final[str] = "NOT_ATTEMPTED"
PLANNER_STATE_REJECTED: Final[str] = "REJECTED"
PLANNER_STATE_PLANNED: Final[str] = "PLANNED"

DEFAULT_MAX_ACCOUNT_STATE_AGE_SECONDS: Final[int] = 15 * 60
DEFAULT_MAX_PRICE_AGE_SECONDS: Final[int] = 15 * 60

REASON_ACCOUNT_STATE_SNAPSHOT_IDENTITY_MISMATCH: Final[str] = "ACCOUNT_STATE_SNAPSHOT_IDENTITY_MISMATCH"
REASON_ACCOUNT_STATE_SNAPSHOT_STALE: Final[str] = "ACCOUNT_STATE_SNAPSHOT_STALE"
REASON_ACCOUNT_STATE_SNAPSHOT_TIMESTAMP_INVALID: Final[str] = "ACCOUNT_STATE_SNAPSHOT_TIMESTAMP_INVALID"
REASON_INCOMPLETE_WALLET_SNAPSHOT: Final[str] = "INCOMPLETE_WALLET_SNAPSHOT"
REASON_CONTRADICTORY_WALLET_SNAPSHOT: Final[str] = "CONTRADICTORY_WALLET_SNAPSHOT"
REASON_RESERVATION_RECONCILIATION_PENDING: Final[str] = "AUTOMATIC_EXIT_RESERVATION_RECONCILIATION_PENDING"
REASON_NEGATIVE_FREE_BASE_QUANTITY: Final[str] = "NEGATIVE_FREE_BASE_QUANTITY"
REASON_MARKET_PRICE_TIMESTAMP_INVALID: Final[str] = "MARKET_PRICE_TIMESTAMP_INVALID"
REASON_MARKET_PRICE_STALE: Final[str] = "MARKET_PRICE_STALE"
REASON_INVALID_MARKET_PRICE: Final[str] = "INVALID_MARKET_PRICE"
REASON_EVALUATION_TIMESTAMP_INVALID: Final[str] = "EVALUATION_TIMESTAMP_INVALID"


class AutomaticExitRuntimeCycleError(ValueError):
    """Fail-closed rejection of an evidence bundle before candidate evaluation."""


@dataclass(frozen=True)
class AutomaticExitRuntimeEvidenceV1:
    """One caller-assembled, already-fetched evidence bundle for one exact
    account/position/market runtime cycle. Every fact below must already be
    the freshest read available to the caller; this module only validates,
    it never fetches.
    """

    # Exact scope identity.
    trading_account_id: int
    venue: str
    asset_id: int
    symbol: str
    market: str
    position_reference: str
    evaluation_ts_utc: datetime

    # Phase 4A persisted account-scoped opt-in (empty tuple => disabled).
    permissions: tuple[AutomaticExitPlanningPermissionV1, ...]

    # Phase 4A persisted market-level policy profile.
    profiles: tuple[AutomaticExitProfileV1, ...]

    # Phase 4B aligned account-state evidence bundle header.
    account_state_snapshot: AccountStateSnapshotRunV1

    # Position/wallet fact bound to the aligned snapshot above.
    wallet_snapshot: WalletAvailableSnapshot
    balance_snapshot_id: int
    blocking_conflict: bool

    # Read-only reservation facts (see module docstring: not resolved via
    # resolve_free_base_quantity because that resolver is wall-clock only).
    approved_not_submitted_reservation_base: Decimal
    reconciliation_pending_reservation_count: int

    # Account flags.
    account_enabled: bool
    live_trading_enabled: bool
    account_mode: str

    # Market price fact.
    current_price: Decimal
    market_price_snapshot_id: int
    price_observed_ts_utc: datetime

    # Venue execution metadata.
    venue_constraints: VenueExecutionConstraints
    venue_constraint_id: int

    # Optional account risk ceiling (None = no additional cap).
    automatic_exit_max_quantity_base: Decimal | None = None

    # Explicit freshness bounds, all evaluated against evaluation_ts_utc.
    max_account_state_age_seconds: int = DEFAULT_MAX_ACCOUNT_STATE_AGE_SECONDS
    max_profile_age_seconds: int = DEFAULT_MAX_PROFILE_AGE_SECONDS
    max_price_age_seconds: int = DEFAULT_MAX_PRICE_AGE_SECONDS

    candidate_config: AutomaticExitPolicyConfigV1 = AutomaticExitPolicyConfigV1()
    runtime_version: str = RUNTIME_VERSION


@dataclass(frozen=True)
class AutomaticExitRuntimeCycleResultV1:
    """The one deterministic outcome of one runtime cycle over one evidence
    bundle. ``plan`` is DRY_RUN evidence only: it is never executor input.
    """

    candidate_state: str
    candidate_reason_code: str
    candidate: AutomaticExitCandidateV1 | None

    gate_state: str | None
    gate_reason_code: str | None
    approved_fraction_candidate: Decimal | None
    approved_quantity_ceiling_base: Decimal | None

    planner_state: str
    planner_reason_code: str | None
    plan: AutomaticExitPlanV1 | None

    evaluation_ts_utc: datetime
    planning_ts_utc: datetime | None

    # None when the evidence bundle cannot yet resolve a stable idempotency
    # identity (see _resolve_current_permission): callers must not persist a
    # non-auditable result to automatic_exit_evaluation_audit_v1.
    idempotency_key: str | None
    auditable: bool
    non_auditable_reason: str | None
    automatic_exit_permission_id: int | None

    runtime_version: str = RUNTIME_VERSION


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _stale(observed: datetime, at: datetime, max_age_seconds: int) -> bool:
    age = at - observed
    return age < timedelta(0) or age > timedelta(seconds=max_age_seconds)


def _non_actionable(
    *, evaluation_ts_utc: datetime, reason: str, planning_ts_utc: datetime | None = None,
) -> AutomaticExitRuntimeCycleResultV1:
    return AutomaticExitRuntimeCycleResultV1(
        candidate_state="NON_ACTIONABLE",
        candidate_reason_code=reason,
        candidate=None,
        gate_state=None,
        gate_reason_code=None,
        approved_fraction_candidate=None,
        approved_quantity_ceiling_base=None,
        planner_state=PLANNER_STATE_NOT_ATTEMPTED,
        planner_reason_code=None,
        plan=None,
        evaluation_ts_utc=evaluation_ts_utc,
        planning_ts_utc=planning_ts_utc,
        idempotency_key=None,
        auditable=False,
        non_auditable_reason=reason,
        automatic_exit_permission_id=None,
    )


def _resolve_current_permission(
    permissions: tuple[AutomaticExitPlanningPermissionV1, ...], *, trading_account_id: int, at: datetime,
) -> AutomaticExitPlanningPermissionV1 | None:
    """Return the single currently-effective permission row, if any.

    This only re-derives *which* row is in its effective window so its
    ``permission_id`` can anchor the idempotency identity; the authoritative
    enabled/disabled/conflict decision is made exclusively by
    ``resolve_automatic_exit_planning_enabled`` below.
    """
    matches = [
        row for row in permissions
        if row.trading_account_id == trading_account_id
        and _aware(row.effective_from_ts_utc)
        and (row.effective_until_ts_utc is None or _aware(row.effective_until_ts_utc))
        and row.effective_from_ts_utc <= at
        and (row.effective_until_ts_utc is None or at < row.effective_until_ts_utc)
    ]
    return matches[0] if len(matches) == 1 else None


def _idempotency_evidence(
    evidence: AutomaticExitRuntimeEvidenceV1, *, profile: AutomaticExitProfileV1, permission_id: int,
) -> dict[str, object]:
    return {
        "trading_account_id": evidence.trading_account_id,
        "position_reference": evidence.position_reference,
        "venue": evidence.venue,
        "asset_id": evidence.asset_id,
        "market": evidence.market,
        "position_snapshot_id": evidence.wallet_snapshot.snapshot_id,
        "balance_snapshot_id": evidence.balance_snapshot_id,
        "open_order_snapshot_run_id": evidence.account_state_snapshot.account_open_order_snapshot_run_id,
        "market_price_snapshot_id": evidence.market_price_snapshot_id,
        "automatic_exit_permission_id": permission_id,
        "exit_profile_id": profile.profile_id,
        "exit_profile_version": profile.profile_version,
        "exit_profile_observed_ts_utc": profile.observed_ts_utc.isoformat(),
        "venue_constraint_id": evidence.venue_constraint_id,
        "venue_metadata_synced_ts_utc": evidence.venue_constraints.metadata_synced_ts_utc.isoformat(),
    }


def run_automatic_exit_runtime_cycle_v1(
    evidence: AutomaticExitRuntimeEvidenceV1,
) -> AutomaticExitRuntimeCycleResultV1:
    """Run one deterministic candidate -> gate -> planner cycle.

    Fails closed to a NON_ACTIONABLE, non-auditable result on any stale,
    missing, contradictory, or malformed evidence. Never raises for
    ordinary evidence-quality problems; only truly programmer-error inputs
    (e.g. a non-callable evidence object) would raise.
    """
    at = evidence.evaluation_ts_utc
    if not _aware(at):
        return _non_actionable(evaluation_ts_utc=at, reason=REASON_EVALUATION_TIMESTAMP_INVALID)

    # 1. Aligned account-state bundle identity + freshness (Phase 4B reuse).
    bundle = evidence.account_state_snapshot
    if (
        bundle.trading_account_id != evidence.trading_account_id
        or bundle.venue.strip().lower() != evidence.venue.strip().lower()
    ):
        return _non_actionable(evaluation_ts_utc=at, reason=REASON_ACCOUNT_STATE_SNAPSHOT_IDENTITY_MISMATCH)
    if not _aware(bundle.snapshot_ts_utc):
        return _non_actionable(evaluation_ts_utc=at, reason=REASON_ACCOUNT_STATE_SNAPSHOT_TIMESTAMP_INVALID)
    if _stale(bundle.snapshot_ts_utc, at, evidence.max_account_state_age_seconds):
        return _non_actionable(evaluation_ts_utc=at, reason=REASON_ACCOUNT_STATE_SNAPSHOT_STALE)

    # 2. Canonical decision_gate free-quantity resolution.
    wallet = evidence.wallet_snapshot
    free_result = resolve_free_base_quantity_core_v1(
        wallet_snapshot=wallet,
        approved_not_submitted_reservation_base=evidence.approved_not_submitted_reservation_base,
        reconciliation_pending_reservation_count=evidence.reconciliation_pending_reservation_count,
        expected_trading_account_id=evidence.trading_account_id,
        expected_venue=evidence.venue,
        expected_asset_id=evidence.asset_id,
        evaluation_ts_utc=at,
    )
    if free_result.status != "OK":
        reason = free_result.blocking_reasons[0]
        if reason == "RECONCILIATION_PENDING":
            reason = REASON_RESERVATION_RECONCILIATION_PENDING
        return _non_actionable(evaluation_ts_utc=at, reason=reason)
    free_quantity_base = free_result.free_base_quantity
    assert free_quantity_base is not None

    # 4. Market price freshness.
    if not _aware(evidence.price_observed_ts_utc):
        return _non_actionable(evaluation_ts_utc=at, reason=REASON_MARKET_PRICE_TIMESTAMP_INVALID)
    if _stale(evidence.price_observed_ts_utc, at, evidence.max_price_age_seconds):
        return _non_actionable(evaluation_ts_utc=at, reason=REASON_MARKET_PRICE_STALE)
    if evidence.current_price <= 0:
        return _non_actionable(evaluation_ts_utc=at, reason=REASON_INVALID_MARKET_PRICE)

    # 5. Permission resolution (fail closed on conflicting history).
    try:
        planning_enabled = resolve_automatic_exit_planning_enabled(
            evidence.permissions, trading_account_id=evidence.trading_account_id, at=at,
        )
    except AutomaticExitRuntimeContractError as exc:
        return _non_actionable(evaluation_ts_utc=at, reason=str(exc))
    permission_row = _resolve_current_permission(
        evidence.permissions, trading_account_id=evidence.trading_account_id, at=at,
    )

    # 6. Market policy profile resolution (fail closed on missing/stale/
    #    conflicting/unsupported profile).
    try:
        profile = resolve_automatic_exit_profile(
            evidence.profiles, venue=evidence.venue, asset_id=evidence.asset_id, market=evidence.market,
            at=at, max_profile_age_seconds=evidence.max_profile_age_seconds,
        )
    except AutomaticExitRuntimeContractError as exc:
        return _non_actionable(evaluation_ts_utc=at, reason=str(exc))

    # 7. Candidate evaluation (position + market only; no permission input).
    position_ctx = AutomaticExitPositionContextV1(
        trading_account_id=evidence.trading_account_id,
        position_reference=evidence.position_reference,
        venue=evidence.venue,
        asset_id=evidence.asset_id,
        market=evidence.market,
        held_quantity_base=wallet.total_base_quantity,
        observed_ts_utc=bundle.snapshot_ts_utc,
    )
    market_ctx = AutomaticExitMarketContextV1(
        venue=evidence.venue,
        asset_id=evidence.asset_id,
        market=evidence.market,
        current_price=evidence.current_price,
        active_target_price=profile.active_target_price,
        invalidation_price=profile.invalidation_price,
        exit_profile_id=profile.profile_id,
        exit_profile_version=profile.profile_version,
        evidence_id=profile.evidence_id,
        observed_ts_utc=min(profile.observed_ts_utc, evidence.price_observed_ts_utc),
    )
    candidate_eval = evaluate_automatic_exit_candidate_v1(
        position=position_ctx, market_context=market_ctx, evaluation_ts_utc=at, config=evidence.candidate_config,
    )

    gate_state: str | None = None
    gate_reason: str | None = None
    approved_fraction: Decimal | None = None
    approved_ceiling: Decimal | None = None
    planner_state = PLANNER_STATE_NOT_ATTEMPTED
    planner_reason: str | None = None
    plan: AutomaticExitPlanV1 | None = None
    planning_ts_utc: datetime | None = None

    if candidate_eval.state == STATE_CANDIDATE:
        assert candidate_eval.candidate is not None
        gate_context = AutomaticExitGateContextV1(
            trading_account_id=evidence.trading_account_id,
            position_reference=evidence.position_reference,
            venue=evidence.venue,
            asset_id=evidence.asset_id,
            market=evidence.market,
            position_snapshot_id=str(wallet.snapshot_id),
            held_quantity_base=wallet.total_base_quantity,
            free_quantity_base=free_quantity_base,
            account_observed_ts_utc=bundle.snapshot_ts_utc,
            position_observed_ts_utc=bundle.snapshot_ts_utc,
            free_quantity_observed_ts_utc=bundle.snapshot_ts_utc,
            account_enabled=evidence.account_enabled,
            account_mode=evidence.account_mode,
            automatic_exit_execution_enabled=planning_enabled,
            live_trading_enabled=evidence.live_trading_enabled,
            blocking_conflict=evidence.blocking_conflict,
            evaluation_ts_utc=at,
            max_account_age_seconds=evidence.max_account_state_age_seconds,
            max_candidate_age_seconds=evidence.max_account_state_age_seconds,
            max_position_age_seconds=evidence.max_account_state_age_seconds,
            max_free_quantity_age_seconds=evidence.max_account_state_age_seconds,
            max_automatic_exit_quantity_base=evidence.automatic_exit_max_quantity_base,
        )
        gate_decision: AutomaticExitGateDecisionV1 = evaluate_automatic_exit_candidate_permission_v1(
            candidate=candidate_eval.candidate, context=gate_context,
        )
        gate_state = gate_decision.state
        gate_reason = gate_decision.reason_code
        approved_fraction = gate_decision.approved_fraction_candidate
        approved_ceiling = gate_decision.approved_quantity_ceiling_base

        if gate_decision.state == STATE_APPROVED:
            planning_ts_utc = at
            planning_context = AutomaticExitPlanningContextV1(
                trading_account_id=evidence.trading_account_id,
                position_reference=evidence.position_reference,
                venue=evidence.venue,
                asset_id=evidence.asset_id,
                market=evidence.market,
                reference_price=evidence.current_price,
                venue_constraints=evidence.venue_constraints,
                planning_ts_utc=planning_ts_utc,
            )
            try:
                plan = build_automatic_exit_plan_v1(decision=gate_decision, context=planning_context)
                planner_state = PLANNER_STATE_PLANNED
            except AutomaticExitPlanningError as exc:
                planner_state = PLANNER_STATE_REJECTED
                planner_reason = exc.reason_code

    if permission_row is None:
        idempotency_key = None
        auditable = False
        non_auditable_reason = "NO_CURRENT_AUTOMATIC_EXIT_PERMISSION_ROW"
    else:
        idempotency_key = automatic_exit_idempotency_key_v1(
            _idempotency_evidence(evidence, profile=profile, permission_id=permission_row.permission_id)
        )
        auditable = True
        non_auditable_reason = None

    return AutomaticExitRuntimeCycleResultV1(
        candidate_state=candidate_eval.state,
        candidate_reason_code=candidate_eval.reason_code,
        candidate=candidate_eval.candidate,
        gate_state=gate_state,
        gate_reason_code=gate_reason,
        approved_fraction_candidate=approved_fraction,
        approved_quantity_ceiling_base=approved_ceiling,
        planner_state=planner_state,
        planner_reason_code=planner_reason,
        plan=plan,
        evaluation_ts_utc=at,
        planning_ts_utc=planning_ts_utc,
        idempotency_key=idempotency_key,
        auditable=auditable,
        non_auditable_reason=non_auditable_reason,
        automatic_exit_permission_id=permission_row.permission_id if permission_row is not None else None,
    )


def _plan_to_json_dict(plan: AutomaticExitPlanV1) -> dict[str, object]:
    return {
        "trading_account_id": plan.trading_account_id,
        "position_reference": plan.position_reference,
        "venue": plan.venue,
        "asset_id": plan.asset_id,
        "market": plan.market,
        "side": plan.side,
        "final_quantity_base": str(plan.final_quantity_base),
        "legs": [
            {
                "leg_index": leg.leg_index,
                "side": leg.side,
                "limit_price": str(leg.limit_price),
                "quantity_base": str(leg.quantity_base),
                "quote_notional": str(leg.quote_notional),
                "post_only": leg.post_only,
                "time_in_force": leg.time_in_force,
            }
            for leg in plan.legs
        ],
        "candidate_action": plan.candidate_action,
        "candidate_reason_code": plan.candidate_reason_code,
        "candidate_evidence_id": plan.candidate_evidence_id,
        "exit_profile_id": plan.exit_profile_id,
        "exit_profile_version": plan.exit_profile_version,
        "gate_approval": {
            "state": plan.gate_approval.state,
            "reason_code": plan.gate_approval.reason_code,
            "approved_fraction_candidate": str(plan.gate_approval.approved_fraction_candidate),
            "approved_quantity_ceiling_base": str(plan.gate_approval.approved_quantity_ceiling_base),
        },
        "planner_version": plan.planner_version,
        "planning_ts_utc": plan.planning_ts_utc.isoformat(),
    }


def build_automatic_exit_audit_payload_v1(
    evidence: AutomaticExitRuntimeEvidenceV1,
    result: AutomaticExitRuntimeCycleResultV1,
    *,
    profile_for_idempotency: AutomaticExitProfileV1 | None = None,
) -> dict[str, object]:
    """Build the exact JSON-safe payload for `automatic_exit_evaluation_audit_v1`.

    Callers must not persist this when ``result.auditable`` is False: the
    idempotency identity (and therefore replay independence) is not resolved
    for that cycle. ``profile_for_idempotency`` lets a caller that already
    resolved the profile (e.g. the runner, which also needs it for logging)
    avoid re-resolving it; if omitted this recomputes it from ``evidence``,
    which is safe because profile resolution is itself pure and deterministic.
    """
    if not result.auditable or result.idempotency_key is None or result.automatic_exit_permission_id is None:
        raise AutomaticExitRuntimeCycleError("CANNOT_BUILD_AUDIT_PAYLOAD_FOR_NON_AUDITABLE_RESULT")

    profile = profile_for_idempotency
    if profile is None:
        profile = resolve_automatic_exit_profile(
            evidence.profiles, venue=evidence.venue, asset_id=evidence.asset_id, market=evidence.market,
            at=evidence.evaluation_ts_utc, max_profile_age_seconds=evidence.max_profile_age_seconds,
        )

    source_evidence = _idempotency_evidence(
        evidence, profile=profile, permission_id=result.automatic_exit_permission_id,
    )
    source_evidence["runtime_version"] = result.runtime_version

    return {
        "idempotency_key": result.idempotency_key,
        "runtime_version": result.runtime_version,
        "trading_account_id": evidence.trading_account_id,
        "position_reference": evidence.position_reference,
        "venue": evidence.venue,
        "asset_id": evidence.asset_id,
        "market": evidence.market,
        "source_evidence_json": source_evidence,
        "candidate_state": result.candidate_state,
        "candidate_action": result.candidate.candidate_action if result.candidate else None,
        "candidate_reason_code": result.candidate_reason_code,
        "candidate_evidence_id": result.candidate.evidence_id if result.candidate else None,
        "exit_profile_id": result.candidate.exit_profile_id if result.candidate else None,
        "exit_profile_version": result.candidate.exit_profile_version if result.candidate else None,
        "gate_state": result.gate_state,
        "gate_reason_code": result.gate_reason_code,
        "approved_fraction_candidate": (
            str(result.approved_fraction_candidate) if result.approved_fraction_candidate is not None else None
        ),
        "approved_quantity_ceiling_base": (
            str(result.approved_quantity_ceiling_base) if result.approved_quantity_ceiling_base is not None else None
        ),
        "planner_state": result.planner_state,
        "planner_reason_code": result.planner_reason_code,
        "immutable_plan_json": _plan_to_json_dict(result.plan) if result.plan is not None else None,
        "evaluation_ts_utc": result.evaluation_ts_utc.isoformat(),
        "planning_ts_utc": result.planning_ts_utc.isoformat() if result.planning_ts_utc is not None else None,
    }
