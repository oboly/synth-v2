import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from src.decision_gate.automatic_exit_gate_v1 import (
    REASON_ACCOUNT_EVIDENCE_STALE,
    REASON_ACCOUNT_DISABLED,
    REASON_BLOCKING_CONFLICT,
    REASON_CANDIDATE_EVIDENCE_STALE,
    REASON_EXECUTION_PERMISSION_DISABLED,
    REASON_FREE_QUANTITY_EVIDENCE_STALE,
    REASON_IDENTITY_MISMATCH,
    REASON_INVALID_CANDIDATE,
    REASON_INVALID_POSITION_EVIDENCE,
    REASON_INVALID_TIMESTAMP,
    REASON_LIVE_EXECUTION_NOT_GRANTED,
    REASON_NO_FREE_QUANTITY,
    REASON_POSITION_EVIDENCE_STALE,
    REASON_RISK_BOUND_UNRESOLVED,
    REASON_UNSUPPORTED_POLICY_CONTRACT,
    STATE_APPROVED,
    STATE_DENIED,
    STATE_NON_ACTIONABLE,
    AutomaticExitGateContextV1,
    evaluate_automatic_exit_candidate_permission_v1,
)
from src.exit_policy import POLICY_NAME, POLICY_VERSION
from src.exit_policy.automatic_exit_candidate_v1 import AutomaticExitCandidateV1


NOW = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)


def _candidate(**changes: object) -> AutomaticExitCandidateV1:
    values: dict[str, object] = dict(
        trading_account_id=7, position_reference="position-9", venue="bitvavo",
        asset_id=42, market="SOL-EUR", candidate_action="REDUCE",
        reduction_fraction_candidate=Decimal("0.25"), urgency_candidate="NORMAL",
        reason_code="TARGET_REACHED", evidence_id="evidence-1", exit_profile_id="profile-1",
        exit_profile_version="1", target_price=Decimal("100"), invalidation_price=Decimal("80"),
        observed_ts_utc=NOW,
    )
    values.update(changes)
    return AutomaticExitCandidateV1(**values)  # type: ignore[arg-type]


def _context(**changes: object) -> AutomaticExitGateContextV1:
    values: dict[str, object] = dict(
        trading_account_id=7, position_reference="position-9", venue="bitvavo", asset_id=42,
        market="SOL-EUR", position_snapshot_id="snapshot-1", held_quantity_base=Decimal("10"),
        free_quantity_base=Decimal("8"), account_observed_ts_utc=NOW,
        position_observed_ts_utc=NOW, free_quantity_observed_ts_utc=NOW,
        account_enabled=True, account_mode="paper", automatic_exit_execution_enabled=True,
        live_trading_enabled=False, blocking_conflict=False, evaluation_ts_utc=NOW,
    )
    values.update(changes)
    return AutomaticExitGateContextV1(**values)  # type: ignore[arg-type]


def _evaluate(**changes: object):
    return evaluate_automatic_exit_candidate_permission_v1(candidate=_candidate(), context=_context(**changes))


def test_healthy_candidate_is_approved_with_account_safe_ceiling_and_preserved_provenance() -> None:
    candidate = _candidate()
    result = evaluate_automatic_exit_candidate_permission_v1(candidate=candidate, context=_context())
    assert result.state == STATE_APPROVED
    assert result.candidate is candidate
    assert result.approved_fraction_candidate == Decimal("0.25")
    assert result.approved_quantity_ceiling_base == Decimal("2.50")


def test_stale_account_is_non_actionable() -> None:
    result = _evaluate(account_observed_ts_utc=NOW - timedelta(minutes=16))
    assert (result.state, result.reason_code) == (STATE_NON_ACTIONABLE, REASON_ACCOUNT_EVIDENCE_STALE)


def test_stale_free_quantity_is_non_actionable() -> None:
    result = _evaluate(free_quantity_observed_ts_utc=NOW - timedelta(minutes=16))
    assert (result.state, result.reason_code) == (STATE_NON_ACTIONABLE, REASON_FREE_QUANTITY_EVIDENCE_STALE)


def test_stale_position_and_candidate_evidence_are_non_actionable() -> None:
    position_result = _evaluate(position_observed_ts_utc=NOW - timedelta(minutes=16))
    candidate_result = evaluate_automatic_exit_candidate_permission_v1(
        candidate=_candidate(observed_ts_utc=NOW - timedelta(minutes=16)), context=_context()
    )
    assert (position_result.state, position_result.reason_code) == (STATE_NON_ACTIONABLE, REASON_POSITION_EVIDENCE_STALE)
    assert (candidate_result.state, candidate_result.reason_code) == (STATE_NON_ACTIONABLE, REASON_CANDIDATE_EVIDENCE_STALE)


def test_future_and_naive_timestamps_are_non_actionable() -> None:
    future_result = _evaluate(position_observed_ts_utc=NOW + timedelta(seconds=1))
    naive_result = _evaluate(position_observed_ts_utc=NOW.replace(tzinfo=None))
    assert (future_result.state, future_result.reason_code) == (STATE_NON_ACTIONABLE, REASON_POSITION_EVIDENCE_STALE)
    assert (naive_result.state, naive_result.reason_code) == (STATE_NON_ACTIONABLE, REASON_INVALID_TIMESTAMP)


def test_account_identity_and_market_identity_mismatches_are_non_actionable() -> None:
    assert _evaluate(trading_account_id=8).reason_code == REASON_IDENTITY_MISMATCH
    assert _evaluate(venue="other").reason_code == REASON_IDENTITY_MISMATCH
    assert _evaluate(asset_id=99).reason_code == REASON_IDENTITY_MISMATCH
    assert _evaluate(market="ETH-EUR").reason_code == REASON_IDENTITY_MISMATCH


def test_zero_free_quantity_and_conflicts_are_denied() -> None:
    assert _evaluate(free_quantity_base=Decimal("0")).reason_code == REASON_NO_FREE_QUANTITY
    result = _evaluate(blocking_conflict=True)
    assert (result.state, result.reason_code) == (STATE_DENIED, REASON_BLOCKING_CONFLICT)


def test_disabled_execution_permission_is_denied() -> None:
    result = _evaluate(automatic_exit_execution_enabled=False)
    assert (result.state, result.reason_code) == (STATE_DENIED, REASON_EXECUTION_PERMISSION_DISABLED)


def test_account_disabled_live_enabled_and_non_paper_modes_are_denied() -> None:
    assert _evaluate(account_enabled=False).reason_code == REASON_ACCOUNT_DISABLED
    assert _evaluate(live_trading_enabled=True).reason_code == REASON_LIVE_EXECUTION_NOT_GRANTED
    assert _evaluate(account_mode="live").reason_code == REASON_LIVE_EXECUTION_NOT_GRANTED


def test_quantity_is_capped_but_fraction_is_never_rewritten() -> None:
    result = _evaluate(free_quantity_base=Decimal("1"))
    assert result.state == STATE_APPROVED
    assert result.approved_fraction_candidate == Decimal("0.25")
    assert result.approved_quantity_ceiling_base == Decimal("1")


def test_risk_cap_reduces_approved_ceiling_and_zero_cap_fails_closed() -> None:
    capped = _evaluate(max_automatic_exit_quantity_base=Decimal("1.5"))
    zero_cap = _evaluate(max_automatic_exit_quantity_base=Decimal("0"))
    assert capped.approved_quantity_ceiling_base == Decimal("1.5")
    assert (zero_cap.state, zero_cap.reason_code) == (STATE_DENIED, REASON_RISK_BOUND_UNRESOLVED)


def test_negative_position_or_free_quantity_is_non_actionable() -> None:
    assert _evaluate(held_quantity_base=Decimal("-1")).reason_code == REASON_INVALID_POSITION_EVIDENCE
    assert _evaluate(free_quantity_base=Decimal("-1")).reason_code == REASON_INVALID_POSITION_EVIDENCE


def test_malformed_candidate_provenance_is_non_actionable() -> None:
    for changes in ({"evidence_id": ""}, {"exit_profile_id": ""}, {"exit_profile_version": ""}):
        result = evaluate_automatic_exit_candidate_permission_v1(candidate=_candidate(**changes), context=_context())
        assert (result.state, result.reason_code) == (STATE_NON_ACTIONABLE, REASON_INVALID_CANDIDATE)


def test_policy_contract_must_match_canonical_exit_policy_constants() -> None:
    assert _candidate().policy_name == POLICY_NAME
    assert _candidate().policy_version == POLICY_VERSION
    for changes in ({"policy_name": "other"}, {"policy_version": "2"}):
        result = evaluate_automatic_exit_candidate_permission_v1(candidate=_candidate(**changes), context=_context())
        assert (result.state, result.reason_code) == (STATE_NON_ACTIONABLE, REASON_UNSUPPORTED_POLICY_CONTRACT)


def test_approved_ceiling_never_exceeds_candidate_free_or_risk_bounds() -> None:
    candidate = _candidate(reduction_fraction_candidate=Decimal("0.4"))
    context = _context(held_quantity_base=Decimal("10"), free_quantity_base=Decimal("3"), max_automatic_exit_quantity_base=Decimal("2.5"))
    result = evaluate_automatic_exit_candidate_permission_v1(candidate=candidate, context=context)
    assert result.state == STATE_APPROVED
    assert result.approved_quantity_ceiling_base is not None
    assert result.approved_quantity_ceiling_base <= context.held_quantity_base * candidate.reduction_fraction_candidate
    assert result.approved_quantity_ceiling_base <= context.free_quantity_base
    assert result.approved_quantity_ceiling_base <= context.max_automatic_exit_quantity_base


def test_same_input_has_same_output() -> None:
    candidate, context = _candidate(), _context()
    assert evaluate_automatic_exit_candidate_permission_v1(candidate=candidate, context=context) == evaluate_automatic_exit_candidate_permission_v1(candidate=candidate, context=context)


def test_gate_has_no_planner_executor_broker_or_manual_dependencies() -> None:
    tree = ast.parse((Path("src/decision_gate") / "automatic_exit_gate_v1.py").read_text())
    imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    ]
    assert not any(any(word in name for word in ("execution_planner", "executor", "broker", "manual_execution", "approval")) for name in imports)


def test_gate_does_not_re_evaluate_target_or_invalidation_strategy() -> None:
    tree = ast.parse((Path("src/decision_gate") / "automatic_exit_gate_v1.py").read_text())
    candidate_attributes = {
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "candidate"
    }
    assert not {"target_price", "invalidation_price"} & candidate_attributes
