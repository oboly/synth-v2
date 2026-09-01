"""Tests for Issue #657 Phase A.2 promotion contract/infrastructure.

Covers: deterministic candidate identity, provenance completeness,
exactly-one-match, overlapping-window rejection, conflict fail-closed,
supersession/rollback semantics, MANUAL_RFQ/MANUAL/NONE exclusion,
read-only preview, zero DB writes, and architecture import guards.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.exit_policy.automatic_exit_profile_promotion_v1 import (
    APPROVAL_STATE_APPROVED,
    APPROVAL_STATE_PENDING,
    APPROVAL_STATE_REJECTED,
    AutomaticExitProfilePromotionCandidate,
    AutomaticExitProfilePromotionError,
    AutomaticExitProfilePromotionRepositoryV1,
    PromotionEvidenceEnvelope,
    approve_promotion_preview,
    build_rollback_candidate,
    build_supersession_plan,
    preview_to_dict,
    promotion_candidate_identity,
    reject_promotion_preview,
    render_promotion_preview,
    validate_promotion_candidate,
)
from src.exit_policy.automatic_exit_runtime_contract_v1 import (
    PROFILE_CONTRACT_VERSION,
    AutomaticExitProfileV1,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "src/exit_policy/automatic_exit_profile_promotion_v1.py"

T0 = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)


def _evidence(**overrides: object) -> PromotionEvidenceEnvelope:
    fields = dict(
        evidence_id="research-run-123",
        evidence_provenance="fib_exit_ladder_v1:method-2:research-run-123",
        method_version="method-2",
        review_reference="issue-270-comment-42",
        observed_ts_utc=T0 - timedelta(minutes=5),
        sample_size=42,
        average_return=Decimal("0.05"),
        median_return=Decimal("0.04"),
        winrate=Decimal("0.6"),
        profit_factor=Decimal("1.8"),
        out_of_sample_validated=True,
    )
    fields.update(overrides)
    return PromotionEvidenceEnvelope(**fields)


def _candidate(**overrides: object) -> AutomaticExitProfilePromotionCandidate:
    fields = dict(
        venue="binance",
        asset_id=101,
        market="LINK-EUR",
        execution_mode="AUTOMATED",
        active_target_price=Decimal("25.00"),
        invalidation_price=Decimal("10.00"),
        evidence=_evidence(),
        effective_from_ts_utc=T0,
    )
    fields.update(overrides)
    return AutomaticExitProfilePromotionCandidate(**fields)


def _existing_profile(**overrides: object) -> AutomaticExitProfileV1:
    fields = dict(
        profile_id="prior-profile",
        profile_version=PROFILE_CONTRACT_VERSION,
        venue="binance",
        asset_id=101,
        market="LINK-EUR",
        active_target_price=Decimal("20.00"),
        invalidation_price=Decimal("9.00"),
        evidence_id="research-run-000",
        evidence_provenance="fib_exit_ladder_v1:method-1:research-run-000",
        observed_ts_utc=T0 - timedelta(days=30),
        effective_from_ts_utc=T0 - timedelta(days=30),
        effective_until_ts_utc=None,
    )
    fields.update(overrides)
    return AutomaticExitProfileV1(**fields)


# ---------------------------------------------------------------------------
# deterministic candidate identity
# ---------------------------------------------------------------------------


def test_identity_is_deterministic_for_same_evidence() -> None:
    a = promotion_candidate_identity(_candidate())
    b = promotion_candidate_identity(_candidate())
    assert a == b


def test_identity_changes_with_evidence_id() -> None:
    a = promotion_candidate_identity(_candidate())
    b = promotion_candidate_identity(_candidate(evidence=_evidence(evidence_id="other-run")))
    assert a[0] != b[0]


def test_identity_profile_version_matches_resolver_contract_version() -> None:
    _profile_id, profile_version = promotion_candidate_identity(_candidate())
    assert profile_version == PROFILE_CONTRACT_VERSION


# ---------------------------------------------------------------------------
# provenance completeness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"evidence_id": ""},
        {"evidence_provenance": ""},
        {"method_version": ""},
        {"review_reference": ""},
        {"sample_size": 0},
    ],
)
def test_incomplete_provenance_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(AutomaticExitProfilePromotionError, match="INCOMPLETE_PROMOTION_EVIDENCE_PROVENANCE"):
        validate_promotion_candidate(_candidate(evidence=_evidence(**overrides)))


def test_naive_observed_ts_rejected() -> None:
    with pytest.raises(AutomaticExitProfilePromotionError, match="INCOMPLETE_PROMOTION_EVIDENCE_PROVENANCE"):
        validate_promotion_candidate(
            _candidate(evidence=_evidence(observed_ts_utc=datetime(2026, 9, 1)))
        )


def test_valid_candidate_passes_validation() -> None:
    validate_promotion_candidate(_candidate())


def test_missing_target_and_invalidation_rejected() -> None:
    with pytest.raises(AutomaticExitProfilePromotionError, match="PROFILE_REQUIRES_TARGET_OR_INVALIDATION"):
        validate_promotion_candidate(
            _candidate(active_target_price=None, invalidation_price=None)
        )


def test_effective_from_before_evidence_observed_rejected() -> None:
    with pytest.raises(AutomaticExitProfilePromotionError, match="EFFECTIVE_FROM_PRECEDES_EVIDENCE_OBSERVATION"):
        validate_promotion_candidate(
            _candidate(effective_from_ts_utc=T0 - timedelta(days=1))
        )


# ---------------------------------------------------------------------------
# MANUAL_RFQ / MANUAL / NONE exclusion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["MANUAL_RFQ", "MANUAL", "NONE"])
def test_non_automated_execution_mode_excluded(mode: str) -> None:
    with pytest.raises(AutomaticExitProfilePromotionError, match="EXECUTION_MODE_NOT_ELIGIBLE_FOR_PROMOTION"):
        validate_promotion_candidate(_candidate(execution_mode=mode))


def test_automated_execution_mode_accepted() -> None:
    validate_promotion_candidate(_candidate(execution_mode="AUTOMATED"))


# ---------------------------------------------------------------------------
# exactly-one-match / overlapping windows / conflict fail-closed
# ---------------------------------------------------------------------------


def test_single_candidate_preview_has_exactly_one_item() -> None:
    batch = render_promotion_preview([_candidate()], generated_ts_utc=T0)
    assert len(batch.items) == 1
    assert batch.approval_state == APPROVAL_STATE_PENDING


def test_two_candidates_same_market_rejected_as_conflict() -> None:
    with pytest.raises(AutomaticExitProfilePromotionError, match="CONFLICTING_PROMOTION_CANDIDATES_FOR_MARKET"):
        render_promotion_preview(
            [_candidate(), _candidate(evidence=_evidence(evidence_id="other-run"))],
            generated_ts_utc=T0,
        )


def test_conflict_produces_no_partial_preview() -> None:
    """A conflicting batch raises before constructing any preview items."""
    try:
        render_promotion_preview(
            [_candidate(active_target_price=Decimal("99")), _candidate()],
            generated_ts_utc=T0,
        )
        assert False, "expected AutomaticExitProfilePromotionError"
    except AutomaticExitProfilePromotionError:
        pass


def test_invalid_candidate_in_batch_rejects_whole_batch() -> None:
    with pytest.raises(AutomaticExitProfilePromotionError):
        render_promotion_preview(
            [_candidate(market="LINK-EUR"), _candidate(market="XLM-EUR", execution_mode="MANUAL")],
            generated_ts_utc=T0,
        )


def test_different_markets_both_included() -> None:
    batch = render_promotion_preview(
        [_candidate(market="LINK-EUR"), _candidate(market="XLM-EUR", asset_id=102)],
        generated_ts_utc=T0,
    )
    assert len(batch.items) == 2


# ---------------------------------------------------------------------------
# supersession / rollback semantics
# ---------------------------------------------------------------------------


def test_supersession_plan_no_existing_profile() -> None:
    plan = build_supersession_plan(existing_profile=None, new_candidate=_candidate())
    assert plan.superseded_profile_id is None
    assert plan.window_close_ts_utc is None


def test_supersession_plan_closes_prior_window_at_new_effective_from() -> None:
    existing = _existing_profile()
    new_candidate = _candidate(effective_from_ts_utc=T0)
    plan = build_supersession_plan(existing_profile=existing, new_candidate=new_candidate)
    assert plan.superseded_profile_id == existing.profile_id
    assert plan.window_close_ts_utc == new_candidate.effective_from_ts_utc == plan.new_effective_from_ts_utc


def test_supersession_rejects_already_closed_existing_profile() -> None:
    existing = _existing_profile(effective_until_ts_utc=T0 - timedelta(days=1))
    with pytest.raises(AutomaticExitProfilePromotionError, match="EXISTING_PROFILE_ALREADY_SUPERSEDED"):
        build_supersession_plan(existing_profile=existing, new_candidate=_candidate())


def test_supersession_rejects_non_monotonic_window() -> None:
    existing = _existing_profile(effective_from_ts_utc=T0)
    with pytest.raises(AutomaticExitProfilePromotionError, match="NON_MONOTONIC_SUPERSESSION_WINDOW"):
        build_supersession_plan(
            existing_profile=existing,
            new_candidate=_candidate(effective_from_ts_utc=T0 - timedelta(minutes=1)),
        )


def test_supersession_rejects_market_identity_mismatch() -> None:
    existing = _existing_profile(market="XLM-EUR")
    with pytest.raises(AutomaticExitProfilePromotionError, match="SUPERSESSION_MARKET_IDENTITY_MISMATCH"):
        build_supersession_plan(existing_profile=existing, new_candidate=_candidate(market="LINK-EUR"))


def test_rollback_candidate_reasserts_prior_values_under_new_evidence() -> None:
    prior = _existing_profile()
    rollback_evidence = _evidence(evidence_id="rollback-run-1")
    candidate = build_rollback_candidate(
        prior_profile=prior,
        rollback_evidence=rollback_evidence,
        effective_from_ts_utc=T0,
    )
    assert candidate.active_target_price == prior.active_target_price
    assert candidate.invalidation_price == prior.invalidation_price
    assert candidate.evidence.evidence_id == "rollback-run-1"
    validate_promotion_candidate(candidate)


# ---------------------------------------------------------------------------
# preview is read-only / operator approval boundary
# ---------------------------------------------------------------------------


def test_preview_to_dict_is_pure_and_read_only() -> None:
    batch = render_promotion_preview([_candidate()], generated_ts_utc=T0)
    payload = preview_to_dict(batch)
    assert payload["approval_state"] == APPROVAL_STATE_PENDING
    assert "no_db_writes=1" in payload["notes"]
    assert "no_executor=1" in payload["notes"]
    assert len(payload["items"]) == 1


def test_approve_preview_transitions_state_without_mutating_original() -> None:
    batch = render_promotion_preview([_candidate()], generated_ts_utc=T0)
    approved = approve_promotion_preview(batch, approved_by="reviewer", approved_ts_utc=T0)
    assert approved.approval_state == APPROVAL_STATE_APPROVED
    assert approved.approved_by == "reviewer"
    assert batch.approval_state == APPROVAL_STATE_PENDING  # original untouched (frozen dataclass)


def test_reject_preview_transitions_state() -> None:
    batch = render_promotion_preview([_candidate()], generated_ts_utc=T0)
    rejected = reject_promotion_preview(batch, rejected_by="reviewer", rejected_ts_utc=T0)
    assert rejected.approval_state == APPROVAL_STATE_REJECTED


def test_cannot_approve_already_approved_batch() -> None:
    batch = render_promotion_preview([_candidate()], generated_ts_utc=T0)
    approved = approve_promotion_preview(batch, approved_by="reviewer", approved_ts_utc=T0)
    with pytest.raises(AutomaticExitProfilePromotionError, match="PREVIEW_NOT_PENDING_OPERATOR_REVIEW"):
        approve_promotion_preview(approved, approved_by="reviewer2", approved_ts_utc=T0)


# ---------------------------------------------------------------------------
# repository abstraction: read-only seam, no production write path
# ---------------------------------------------------------------------------


class _FakeRepository(AutomaticExitProfilePromotionRepositoryV1):
    def load_current_profile(self, *, venue: str, asset_id: int, market: str) -> AutomaticExitProfileV1 | None:
        return None

    def load_promoted_evidence_ids(self, *, venue: str, asset_id: int, market: str) -> frozenset[str]:
        return frozenset()


def test_repository_write_promotion_always_raises() -> None:
    repo = _FakeRepository()
    with pytest.raises(AutomaticExitProfilePromotionError, match="NO_PRODUCTION_WRITE_PATH_PHASE_A2"):
        repo.write_promotion()


def test_repository_cannot_be_instantiated_without_read_methods() -> None:
    with pytest.raises(TypeError):
        AutomaticExitProfilePromotionRepositoryV1()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# zero DB writes / architecture import guards
# ---------------------------------------------------------------------------


def _imported_module_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


FORBIDDEN_IMPORT_PREFIXES = (
    "src.decision_gate",
    "src.execution_planner",
    "src.executor",
    "src.broker",
    "src.manual_execution",
)


def test_module_has_no_execution_layer_imports() -> None:
    imported = _imported_module_names(MODULE_PATH)
    for name in imported:
        for forbidden in FORBIDDEN_IMPORT_PREFIXES:
            assert not (name == forbidden or name.startswith(forbidden + ".")), (
                f"promotion module imports forbidden module {name}"
            )


def test_module_has_no_db_or_network_imports() -> None:
    imported = _imported_module_names(MODULE_PATH)
    forbidden_substrings = ("pymysql", "mariadb", "sqlalchemy", "requests", "httpx", "ccxt")
    for name in imported:
        for forbidden in forbidden_substrings:
            assert forbidden not in name.lower(), f"promotion module imports {name}"


def test_module_contains_no_sql_write_statements() -> None:
    text = MODULE_PATH.read_text()
    for keyword in ("INSERT INTO", "UPDATE ", "DELETE FROM", "cursor.execute"):
        assert keyword not in text, f"promotion module references {keyword!r}"


def test_module_source_never_calls_order_or_broker_functions() -> None:
    forbidden_call_names = {
        "submit_order", "place_order", "cancel_order", "broker_write",
        "grant_live_trading_authorization", "require_live_execution_permission",
    }
    tree = ast.parse(MODULE_PATH.read_text())
    for node in ast.walk(tree):
        name = None
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
        if name is not None:
            assert name not in forbidden_call_names
