"""Automatic-exit profile promotion contract/infrastructure (Issue #657 Phase A.2).

Policy-independent infrastructure only: typed promotion-candidate contract,
provenance envelope, deterministic candidate identity, exactly-one-effective
/ conflict-fail-closed validation, supersession/rollback planning, a
read-only repository abstraction, and a read-only preview renderer with an
explicit operator-approval boundary.

This module never invents target/invalidation values, never promotes the
unvalidated 2021 Fib Exit Ladder buckets, and never writes to
``automatic_exit_profile_v1``. Per the reviewed design in
``docs/architecture/automatic_exit_profile_promotion_v1.md``, a real
producer wiring real evidence into this contract stays BLOCKED until that
document's Phase B entry criteria are satisfied. No database, broker,
decision_gate, execution_planner, or executor imports are permitted here.
"""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Final, Iterable

from src.execution_capability.execution_capability_v1 import capability_for_mode
from src.exit_policy.automatic_exit_runtime_contract_v1 import (
    PROFILE_CONTRACT_VERSION,
    AutomaticExitProfileV1,
)

PROMOTION_CONTRACT_VERSION: Final[str] = "1"

APPROVAL_STATE_PENDING: Final[str] = "PENDING_OPERATOR_REVIEW"
APPROVAL_STATE_APPROVED: Final[str] = "OPERATOR_APPROVED"
APPROVAL_STATE_REJECTED: Final[str] = "OPERATOR_REJECTED"
APPROVAL_STATES: Final[frozenset[str]] = frozenset(
    {APPROVAL_STATE_PENDING, APPROVAL_STATE_APPROVED, APPROVAL_STATE_REJECTED}
)


class AutomaticExitProfilePromotionError(ValueError):
    pass


@dataclass(frozen=True)
class PromotionEvidenceEnvelope:
    """Canonical provenance for one promotion candidate (contract §9/§2).

    Presence and non-emptiness of every field is enforced by
    ``validate_promotion_candidate``; the values themselves must come from a
    genuinely reviewed evidence artifact -- this module never fabricates
    them.
    """

    evidence_id: str
    evidence_provenance: str
    method_version: str
    review_reference: str
    observed_ts_utc: datetime
    sample_size: int
    average_return: Decimal
    median_return: Decimal
    winrate: Decimal
    profit_factor: Decimal
    out_of_sample_validated: bool


@dataclass(frozen=True)
class AutomaticExitProfilePromotionCandidate:
    """One proposed (not yet written) automatic-exit profile row.

    Deliberately carries no ``trading_account_id`` or any account-scoped
    field -- profiles are global per contract §4, and no account-aware
    branching may be added to this contract.
    """

    venue: str
    asset_id: int
    market: str
    execution_mode: str
    active_target_price: Decimal | None
    invalidation_price: Decimal | None
    evidence: PromotionEvidenceEnvelope
    effective_from_ts_utc: datetime


@dataclass(frozen=True)
class AutomaticExitProfilePromotionSupersessionPlan:
    """Atomic window-transition plan (contract §6/§8/§10). A plan only --
    applying it (closing the prior row's window, inserting the new row) is a
    Phase B write-path responsibility, not performed here."""

    superseded_profile_id: str | None
    superseded_profile_version: str | None
    window_close_ts_utc: datetime | None
    new_profile_id: str
    new_profile_version: str
    new_effective_from_ts_utc: datetime


@dataclass(frozen=True)
class AutomaticExitProfilePromotionPreviewItem:
    profile_id: str
    profile_version: str
    venue: str
    asset_id: int
    market: str
    execution_mode: str
    active_target_price: Decimal | None
    invalidation_price: Decimal | None
    evidence_id: str
    evidence_provenance: str
    observed_ts_utc: datetime
    effective_from_ts_utc: datetime


@dataclass(frozen=True)
class AutomaticExitProfilePromotionPreviewBatch:
    promotion_contract_version: str
    generated_ts_utc: datetime
    approval_state: str
    items: tuple[AutomaticExitProfilePromotionPreviewItem, ...]
    approved_by: str | None = None
    approved_ts_utc: datetime | None = None


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _normalize_market(market: str) -> str:
    return market.strip().upper().replace("/", "-")


def _normalize_venue(venue: str) -> str:
    return venue.strip().lower()


def promotion_candidate_identity(
    candidate: AutomaticExitProfilePromotionCandidate,
) -> tuple[str, str]:
    """Deterministic ``(profile_id, profile_version)`` for one candidate.

    Same evidence input (venue/asset/market/evidence_id/method_version/
    effective_from) always yields the same identity; no clock, random, or
    network dependency. ``profile_version`` is pinned to the resolver's
    contract version, per §5.
    """
    canonical = {
        "venue": _normalize_venue(candidate.venue),
        "asset_id": candidate.asset_id,
        "market": _normalize_market(candidate.market),
        "evidence_id": candidate.evidence.evidence_id.strip(),
        "method_version": candidate.evidence.method_version.strip(),
        "effective_from_ts_utc": candidate.effective_from_ts_utc.astimezone(
            timezone.utc
        ).isoformat(),
    }
    serialized = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:32]
    return f"aep-promo-{digest}", PROFILE_CONTRACT_VERSION


def validate_promotion_candidate(candidate: AutomaticExitProfilePromotionCandidate) -> None:
    """Fail-closed structural/eligibility validation. Never falls back to a
    default or best-guess value; every failure raises."""
    if not candidate.venue.strip() or candidate.asset_id <= 0 or not candidate.market.strip():
        raise AutomaticExitProfilePromotionError("INVALID_MARKET_IDENTITY")

    capability = capability_for_mode(candidate.execution_mode)
    if not capability.automated_execution_eligible:
        raise AutomaticExitProfilePromotionError(
            f"EXECUTION_MODE_NOT_ELIGIBLE_FOR_PROMOTION:{capability.execution_mode}"
        )

    evidence = candidate.evidence
    if (
        not evidence.evidence_id.strip()
        or not evidence.evidence_provenance.strip()
        or not evidence.method_version.strip()
        or not evidence.review_reference.strip()
        or evidence.sample_size <= 0
        or evidence.winrate < 0
        or evidence.profit_factor < 0
        or not _aware(evidence.observed_ts_utc)
    ):
        raise AutomaticExitProfilePromotionError("INCOMPLETE_PROMOTION_EVIDENCE_PROVENANCE")

    if not _aware(candidate.effective_from_ts_utc):
        raise AutomaticExitProfilePromotionError("EFFECTIVE_FROM_MUST_BE_TIMEZONE_AWARE")

    if candidate.effective_from_ts_utc < evidence.observed_ts_utc:
        raise AutomaticExitProfilePromotionError("EFFECTIVE_FROM_PRECEDES_EVIDENCE_OBSERVATION")

    if candidate.active_target_price is None and candidate.invalidation_price is None:
        raise AutomaticExitProfilePromotionError("PROFILE_REQUIRES_TARGET_OR_INVALIDATION")
    if candidate.active_target_price is not None and candidate.active_target_price <= 0:
        raise AutomaticExitProfilePromotionError("INVALID_ACTIVE_TARGET_PRICE")
    if candidate.invalidation_price is not None and candidate.invalidation_price <= 0:
        raise AutomaticExitProfilePromotionError("INVALID_INVALIDATION_PRICE")


def _reject_conflicting_candidates(
    candidates: list[AutomaticExitProfilePromotionCandidate],
) -> None:
    """Every candidate proposes an open-ended new row (§6), so more than one
    candidate for the same ``(venue, asset_id, market)`` in a single preview
    batch always overlaps and is always a conflict; fail closed rather than
    picking one."""
    seen: dict[tuple[str, int, str], AutomaticExitProfilePromotionCandidate] = {}
    for candidate in candidates:
        key = (
            _normalize_venue(candidate.venue),
            candidate.asset_id,
            _normalize_market(candidate.market),
        )
        if key in seen:
            raise AutomaticExitProfilePromotionError(
                f"CONFLICTING_PROMOTION_CANDIDATES_FOR_MARKET:{key[0]}:{key[1]}:{key[2]}"
            )
        seen[key] = candidate


def build_supersession_plan(
    *,
    existing_profile: AutomaticExitProfileV1 | None,
    new_candidate: AutomaticExitProfilePromotionCandidate,
) -> AutomaticExitProfilePromotionSupersessionPlan:
    """Compute the atomic window-transition plan for promoting
    ``new_candidate``, optionally superseding ``existing_profile``.

    Fails closed rather than proposing an overlapping or backdated window:
    an already-closed ``existing_profile`` (an ``effective_until_ts_utc`` in
    the past relative to nothing new) cannot be re-superseded here, and a
    new candidate may never claim to start at or before the row it
    supersedes.
    """
    new_profile_id, new_profile_version = promotion_candidate_identity(new_candidate)

    if existing_profile is None:
        return AutomaticExitProfilePromotionSupersessionPlan(
            superseded_profile_id=None,
            superseded_profile_version=None,
            window_close_ts_utc=None,
            new_profile_id=new_profile_id,
            new_profile_version=new_profile_version,
            new_effective_from_ts_utc=new_candidate.effective_from_ts_utc,
        )

    if (
        _normalize_venue(existing_profile.venue) != _normalize_venue(new_candidate.venue)
        or existing_profile.asset_id != new_candidate.asset_id
        or _normalize_market(existing_profile.market) != _normalize_market(new_candidate.market)
    ):
        raise AutomaticExitProfilePromotionError("SUPERSESSION_MARKET_IDENTITY_MISMATCH")

    if existing_profile.effective_until_ts_utc is not None:
        raise AutomaticExitProfilePromotionError("EXISTING_PROFILE_ALREADY_SUPERSEDED")

    if new_candidate.effective_from_ts_utc <= existing_profile.effective_from_ts_utc:
        raise AutomaticExitProfilePromotionError("NON_MONOTONIC_SUPERSESSION_WINDOW")

    return AutomaticExitProfilePromotionSupersessionPlan(
        superseded_profile_id=existing_profile.profile_id,
        superseded_profile_version=existing_profile.profile_version,
        window_close_ts_utc=new_candidate.effective_from_ts_utc,
        new_profile_id=new_profile_id,
        new_profile_version=new_profile_version,
        new_effective_from_ts_utc=new_candidate.effective_from_ts_utc,
    )


def build_rollback_candidate(
    *,
    prior_profile: AutomaticExitProfileV1,
    rollback_evidence: PromotionEvidenceEnvelope,
    effective_from_ts_utc: datetime,
) -> AutomaticExitProfilePromotionCandidate:
    """Rollback is never a delete or an update of the superseding row (§10):
    it is a new candidate that re-asserts ``prior_profile``'s target/
    invalidation values under fresh provenance identifying this as a
    rollback, preserving full append-only history."""
    return AutomaticExitProfilePromotionCandidate(
        venue=prior_profile.venue,
        asset_id=prior_profile.asset_id,
        market=prior_profile.market,
        execution_mode="AUTOMATED",
        active_target_price=prior_profile.active_target_price,
        invalidation_price=prior_profile.invalidation_price,
        evidence=rollback_evidence,
        effective_from_ts_utc=effective_from_ts_utc,
    )


def render_promotion_preview(
    candidates: Iterable[AutomaticExitProfilePromotionCandidate],
    *,
    generated_ts_utc: datetime,
) -> AutomaticExitProfilePromotionPreviewBatch:
    """Read-only preview renderer. Performs no DB write, no broker call, and
    no runtime wiring. Any invalid or conflicting candidate rejects the
    entire batch -- there is no partial/best-guess preview output."""
    if not _aware(generated_ts_utc):
        raise AutomaticExitProfilePromotionError("GENERATED_TS_MUST_BE_TIMEZONE_AWARE")

    candidate_list = list(candidates)
    for candidate in candidate_list:
        validate_promotion_candidate(candidate)
    _reject_conflicting_candidates(candidate_list)

    items = tuple(
        AutomaticExitProfilePromotionPreviewItem(
            profile_id=profile_id,
            profile_version=profile_version,
            venue=candidate.venue,
            asset_id=candidate.asset_id,
            market=candidate.market,
            execution_mode=candidate.execution_mode,
            active_target_price=candidate.active_target_price,
            invalidation_price=candidate.invalidation_price,
            evidence_id=candidate.evidence.evidence_id,
            evidence_provenance=candidate.evidence.evidence_provenance,
            observed_ts_utc=candidate.evidence.observed_ts_utc,
            effective_from_ts_utc=candidate.effective_from_ts_utc,
        )
        for candidate in candidate_list
        for profile_id, profile_version in [promotion_candidate_identity(candidate)]
    )

    return AutomaticExitProfilePromotionPreviewBatch(
        promotion_contract_version=PROMOTION_CONTRACT_VERSION,
        generated_ts_utc=generated_ts_utc,
        approval_state=APPROVAL_STATE_PENDING,
        items=items,
    )


def approve_promotion_preview(
    batch: AutomaticExitProfilePromotionPreviewBatch,
    *,
    approved_by: str,
    approved_ts_utc: datetime,
) -> AutomaticExitProfilePromotionPreviewBatch:
    """Explicit human-operator approval transition (§13). Still performs no
    DB write -- it only marks the in-memory preview as reviewed; a separate,
    separately-scoped Phase B write path is required to act on it."""
    if not approved_by.strip():
        raise AutomaticExitProfilePromotionError("APPROVER_IDENTITY_REQUIRED")
    if not _aware(approved_ts_utc):
        raise AutomaticExitProfilePromotionError("APPROVED_TS_MUST_BE_TIMEZONE_AWARE")
    if batch.approval_state != APPROVAL_STATE_PENDING:
        raise AutomaticExitProfilePromotionError("PREVIEW_NOT_PENDING_OPERATOR_REVIEW")
    return replace(
        batch,
        approval_state=APPROVAL_STATE_APPROVED,
        approved_by=approved_by.strip(),
        approved_ts_utc=approved_ts_utc,
    )


def reject_promotion_preview(
    batch: AutomaticExitProfilePromotionPreviewBatch,
    *,
    rejected_by: str,
    rejected_ts_utc: datetime,
) -> AutomaticExitProfilePromotionPreviewBatch:
    if not rejected_by.strip():
        raise AutomaticExitProfilePromotionError("REJECTOR_IDENTITY_REQUIRED")
    if not _aware(rejected_ts_utc):
        raise AutomaticExitProfilePromotionError("REJECTED_TS_MUST_BE_TIMEZONE_AWARE")
    if batch.approval_state != APPROVAL_STATE_PENDING:
        raise AutomaticExitProfilePromotionError("PREVIEW_NOT_PENDING_OPERATOR_REVIEW")
    return replace(
        batch,
        approval_state=APPROVAL_STATE_REJECTED,
        approved_by=rejected_by.strip(),
        approved_ts_utc=rejected_ts_utc,
    )


def preview_to_dict(batch: AutomaticExitProfilePromotionPreviewBatch) -> dict[str, Any]:
    """Pure, read-only serialization for a preview batch (dashboards/CLI
    review use only). No DB or network access."""

    def convert(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        if isinstance(value, tuple):
            return [convert(item) for item in value]
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        return value

    return {
        "promotion_contract_version": batch.promotion_contract_version,
        "generated_ts_utc": convert(batch.generated_ts_utc),
        "approval_state": batch.approval_state,
        "approved_by": batch.approved_by,
        "approved_ts_utc": convert(batch.approved_ts_utc) if batch.approved_ts_utc else None,
        "items": [
            {
                "profile_id": item.profile_id,
                "profile_version": item.profile_version,
                "venue": item.venue,
                "asset_id": item.asset_id,
                "market": item.market,
                "execution_mode": item.execution_mode,
                "active_target_price": convert(item.active_target_price),
                "invalidation_price": convert(item.invalidation_price),
                "evidence_id": item.evidence_id,
                "evidence_provenance": item.evidence_provenance,
                "observed_ts_utc": convert(item.observed_ts_utc),
                "effective_from_ts_utc": convert(item.effective_from_ts_utc),
            }
            for item in batch.items
        ],
        "notes": (
            "preview_only=1; no_db_writes=1; no_broker_calls=1; "
            "no_runtime_wiring=1; no_decision_gate=1; no_execution_planner=1; "
            "no_executor=1"
        ),
    }


class AutomaticExitProfilePromotionRepositoryV1(ABC):
    """Read-only repository seam for the future Phase B writer.

    Only read methods are abstract; ``write_promotion`` is deliberately a
    concrete, always-failing method here so no Phase A.2 caller can obtain a
    working write path by accident. Implementing a real write requires a
    separately reviewed Phase B change once
    ``docs/architecture/automatic_exit_profile_promotion_v1.md``'s Phase B
    entry criteria are satisfied.
    """

    @abstractmethod
    def load_current_profile(
        self, *, venue: str, asset_id: int, market: str
    ) -> AutomaticExitProfileV1 | None:
        """Return the currently open-ended (``effective_until_ts_utc is
        None``) profile row for this market, or ``None`` if none exists.
        Read-only."""
        raise NotImplementedError

    @abstractmethod
    def load_promoted_evidence_ids(
        self, *, venue: str, asset_id: int, market: str
    ) -> frozenset[str]:
        """Return every ``evidence_id`` already promoted for this market, so
        a producer can avoid proposing a duplicate candidate for evidence
        already written. Read-only."""
        raise NotImplementedError

    def write_promotion(self, *args: Any, **kwargs: Any) -> None:
        raise AutomaticExitProfilePromotionError(
            "NO_PRODUCTION_WRITE_PATH_PHASE_A2: promotion writes are blocked "
            "until the Phase B entry criteria in "
            "docs/architecture/automatic_exit_profile_promotion_v1.md are met"
        )
