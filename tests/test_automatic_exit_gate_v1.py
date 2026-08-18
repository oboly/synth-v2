import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from src.decision_gate.automatic_exit_gate_v1 import (
    REASON_ACCOUNT_EVIDENCE_STALE,
    REASON_ACCOUNT_DISABLED,
    REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT,
    REASON_BLOCKING_CONFLICT,
    REASON_CANDIDATE_EVIDENCE_STALE,
    REASON_EXECUTION_PERMISSION_DISABLED,
    REASON_FREE_QUANTITY_EVIDENCE_STALE,
    REASON_IDENTITY_MISMATCH,
    REASON_INVALID_CANDIDATE,
    REASON_INVALID_POSITION_EVIDENCE,
    REASON_INVALID_TIMESTAMP,
    REASON_LIVE_EXECUTION_NOT_GRANTED,
    REASON_LIVE_PERMISSION_EVALUATION_BINDING_MISMATCH,
    REASON_NO_FREE_QUANTITY,
    REASON_POSITION_EVIDENCE_STALE,
    REASON_RISK_BOUND_UNRESOLVED,
    REASON_UNSUPPORTED_ACCOUNT_MODE,
    REASON_UNSUPPORTED_POLICY_CONTRACT,
    STATE_APPROVED,
    STATE_DENIED,
    STATE_NON_ACTIONABLE,
    AutomaticExitGateContextV1,
    evaluate_automatic_exit_candidate_permission_v1,
)
from src.decision_gate.account_protection_contract_v1 import (
    ACTION_EXIT,
    ACTION_REDUCE,
    LOCK_FACT_CONTRACT_VERSION,
    PROTECTION_MANUAL_ACCOUNT_LOCK,
    PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
    SCOPE_ACCOUNT,
    ProtectionLockFactV1,
    resolve_account_protection_state_for_action_v1,
)
from src.decision_gate.automatic_exit_live_permission_evaluation_v1 import (
    DECISION_DENIED as LIVE_PERMISSION_DENIED,
    DECISION_GRANTED as LIVE_PERMISSION_GRANTED,
    EVALUATION_CONTRACT_VERSION as LIVE_PERMISSION_EVALUATION_CONTRACT_VERSION,
    REASON_LIVE_PERMISSION_NOT_GRANTED,
    REASON_OK as LIVE_PERMISSION_REASON_OK,
    AutomaticExitLivePermissionEvaluationV1,
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
        live_trading_enabled=False,
        blocking_conflict=False, evaluation_ts_utc=NOW,
    )
    values.update(changes)
    return AutomaticExitGateContextV1(**values)  # type: ignore[arg-type]


def _evaluate(**changes: object):
    return evaluate_automatic_exit_candidate_permission_v1(candidate=_candidate(), context=_context(**changes))


def _live_permission(
    decision_state: str = LIVE_PERMISSION_GRANTED, *, trading_account_id: int = 7,
) -> AutomaticExitLivePermissionEvaluationV1:
    return AutomaticExitLivePermissionEvaluationV1(
        evaluation_contract_version=LIVE_PERMISSION_EVALUATION_CONTRACT_VERSION,
        trading_account_id=trading_account_id,
        decision_state=decision_state,
        reason_code=(LIVE_PERMISSION_REASON_OK if decision_state == LIVE_PERMISSION_GRANTED else REASON_LIVE_PERMISSION_NOT_GRANTED),
        permission_id=1,
        permission_version="1",
        evaluated_ts_utc=NOW,
    )


def _protection(action: str, *, manual: bool = False):
    code = PROTECTION_MANUAL_ACCOUNT_LOCK if manual else PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK
    lock = ProtectionLockFactV1(
        lifecycle_id=f"lifecycle-{code}", event_id=f"event-{code}", protection_code=code,
        protection_version=LOCK_FACT_CONTRACT_VERSION, trading_account_id=7,
        scope_type=SCOPE_ACCOUNT, scope_id="7", observed_from_ts_utc=NOW - timedelta(minutes=1),
        observed_to_ts_utc=NOW, triggered_ts_utc=NOW, expires_ts_utc=None,
        reason_code="TEST", evidence_refs=("canonical:lock:1",), configuration_version="policy-1",
    )
    return resolve_account_protection_state_for_action_v1(
        (lock,), trading_account_id=7, sleeve_code=None, asset_id=42,
        requested_action=action, account_state_observed_ts_utc=NOW,
        account_state_fresh=True, at=NOW,
    )


def test_healthy_candidate_is_approved_with_account_safe_ceiling_and_preserved_provenance() -> None:
    candidate = _candidate()
    result = evaluate_automatic_exit_candidate_permission_v1(candidate=candidate, context=_context())
    assert result.state == STATE_APPROVED
    assert result.candidate is candidate
    assert result.approved_fraction_candidate == Decimal("0.25")
    assert result.approved_quantity_ceiling_base == Decimal("2.50")


def test_risk_increase_protection_does_not_deny_reduce_or_exit() -> None:
    reduce = evaluate_automatic_exit_candidate_permission_v1(
        candidate=_candidate(candidate_action="REDUCE"),
        context=_context(account_protection_evaluation=_protection(ACTION_REDUCE)),
    )
    exit = evaluate_automatic_exit_candidate_permission_v1(
        candidate=_candidate(candidate_action="EXIT"),
        context=_context(account_protection_evaluation=_protection(ACTION_EXIT)),
    )
    assert reduce.state == STATE_APPROVED
    assert exit.state == STATE_APPROVED


def test_manual_lock_denies_reduce_and_exit_without_exit_policy_awareness() -> None:
    for action in (ACTION_REDUCE, ACTION_EXIT):
        result = evaluate_automatic_exit_candidate_permission_v1(
            candidate=_candidate(candidate_action=action),
            context=_context(account_protection_evaluation=_protection(action, manual=True)),
        )
        assert result.state == STATE_DENIED
        assert result.protection_code == PROTECTION_MANUAL_ACCOUNT_LOCK


def test_protection_evaluation_binding_mismatch_denies_an_otherwise_approved_candidate() -> None:
    """Issue #392 Phase 6 blocker C fail-closed matrix: a protection evaluation computed for a
    different requested_action than the candidate's own action must never be silently accepted."""
    mismatched = _protection(ACTION_EXIT)  # evaluated for EXIT, but the candidate below requests REDUCE
    result = evaluate_automatic_exit_candidate_permission_v1(
        candidate=_candidate(candidate_action="REDUCE"),
        context=_context(account_protection_evaluation=mismatched),
    )
    assert result.state == STATE_DENIED
    assert result.reason_code == "INVALID_PROTECTION_EVALUATION_BINDING"


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


def test_account_disabled_is_denied() -> None:
    assert _evaluate(account_enabled=False).reason_code == REASON_ACCOUNT_DISABLED


def test_paper_account_with_inconsistent_live_flag_is_non_actionable() -> None:
    """account_mode=paper with live_trading_enabled=True is inconsistent evidence, not a LIVE candidate."""
    result = _evaluate(live_trading_enabled=True)
    assert (result.state, result.reason_code) == (STATE_NON_ACTIONABLE, REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT)


def test_live_mode_without_live_trading_flag_is_non_actionable() -> None:
    """account_mode=live alone, without the matching account-level live_trading_enabled fact, is inconsistent."""
    result = _evaluate(account_mode="live", automatic_exit_live_permission_evaluation=_live_permission())
    assert (result.state, result.reason_code) == (STATE_NON_ACTIONABLE, REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT)


def test_live_mode_without_explicit_live_permission_is_denied() -> None:
    """account_mode=live alone (even with live_trading_enabled=True) is insufficient without explicit permission."""
    result = _evaluate(account_mode="live", live_trading_enabled=True)
    assert (result.state, result.reason_code) == (STATE_DENIED, REASON_LIVE_EXECUTION_NOT_GRANTED)


def test_legacy_live_trading_flag_alone_is_insufficient_for_paper_mode() -> None:
    """A retained live_trading_enabled=True flag never silently substitutes for explicit LIVE permission."""
    result = _evaluate(
        account_mode="paper", live_trading_enabled=True, automatic_exit_live_permission_evaluation=_live_permission(),
    )
    assert result.state != STATE_APPROVED
    assert result.reason_code == REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT


def test_live_mode_with_explicit_permission_and_healthy_evidence_is_approved() -> None:
    result = _evaluate(
        account_mode="live", live_trading_enabled=True, automatic_exit_live_permission_evaluation=_live_permission(),
    )
    assert result.state == STATE_APPROVED
    assert result.reason_code == "OK"
    assert result.approved_quantity_ceiling_base == Decimal("2.50")


def test_live_mode_permission_revoked_is_denied() -> None:
    result = _evaluate(
        account_mode="live", live_trading_enabled=True,
        automatic_exit_live_permission_evaluation=_live_permission(LIVE_PERMISSION_DENIED),
    )
    assert (result.state, result.reason_code) == (STATE_DENIED, REASON_LIVE_EXECUTION_NOT_GRANTED)


def test_live_mode_wrong_account_permission_evaluation_binding_is_denied() -> None:
    """A LIVE permission evaluation resolved for a different account must never grant this account permission."""
    result = _evaluate(
        account_mode="live", live_trading_enabled=True,
        automatic_exit_live_permission_evaluation=_live_permission(trading_account_id=999),
    )
    assert (result.state, result.reason_code) == (STATE_DENIED, REASON_LIVE_PERMISSION_EVALUATION_BINDING_MISMATCH)


def test_unsupported_account_mode_is_non_actionable() -> None:
    for mode in ("LIVE", "Paper", "demo", "", "sandbox"):
        result = _evaluate(account_mode=mode)
        assert (result.state, result.reason_code) == (STATE_NON_ACTIONABLE, REASON_UNSUPPORTED_ACCOUNT_MODE)


def test_live_mode_still_enforces_manual_lock_and_risk_protection_reduce_exit() -> None:
    """The #318 protection composition applies identically to LIVE as to paper."""
    live_context_kwargs = dict(
        account_mode="live", live_trading_enabled=True, automatic_exit_live_permission_evaluation=_live_permission(),
    )
    manual_reduce = evaluate_automatic_exit_candidate_permission_v1(
        candidate=_candidate(candidate_action="REDUCE"),
        context=_context(account_protection_evaluation=_protection(ACTION_REDUCE, manual=True), **live_context_kwargs),
    )
    manual_exit = evaluate_automatic_exit_candidate_permission_v1(
        candidate=_candidate(candidate_action="EXIT"),
        context=_context(account_protection_evaluation=_protection(ACTION_EXIT, manual=True), **live_context_kwargs),
    )
    drawdown_reduce = evaluate_automatic_exit_candidate_permission_v1(
        candidate=_candidate(candidate_action="REDUCE"),
        context=_context(account_protection_evaluation=_protection(ACTION_REDUCE), **live_context_kwargs),
    )
    drawdown_exit = evaluate_automatic_exit_candidate_permission_v1(
        candidate=_candidate(candidate_action="EXIT"),
        context=_context(account_protection_evaluation=_protection(ACTION_EXIT), **live_context_kwargs),
    )
    assert manual_reduce.state == STATE_DENIED and manual_reduce.protection_code == PROTECTION_MANUAL_ACCOUNT_LOCK
    assert manual_exit.state == STATE_DENIED and manual_exit.protection_code == PROTECTION_MANUAL_ACCOUNT_LOCK
    assert drawdown_reduce.state == STATE_APPROVED
    assert drawdown_exit.state == STATE_APPROVED


def test_live_mode_zero_free_quantity_and_invalid_risk_ceiling_fail_closed() -> None:
    live_context_kwargs = dict(
        account_mode="live", live_trading_enabled=True, automatic_exit_live_permission_evaluation=_live_permission(),
    )
    zero_free = _evaluate(free_quantity_base=Decimal("0"), **live_context_kwargs)
    assert (zero_free.state, zero_free.reason_code) == (STATE_DENIED, REASON_NO_FREE_QUANTITY)
    invalid_ceiling = _evaluate(max_automatic_exit_quantity_base=Decimal("-1"), **live_context_kwargs)
    assert invalid_ceiling.state == STATE_NON_ACTIONABLE
    assert invalid_ceiling.reason_code == REASON_RISK_BOUND_UNRESOLVED


def test_live_mode_stale_evidence_and_blocking_conflict_are_denied_or_non_actionable() -> None:
    live_context_kwargs = dict(
        account_mode="live", live_trading_enabled=True, automatic_exit_live_permission_evaluation=_live_permission(),
    )
    stale_account = _evaluate(account_observed_ts_utc=NOW - timedelta(minutes=16), **live_context_kwargs)
    assert (stale_account.state, stale_account.reason_code) == (STATE_NON_ACTIONABLE, REASON_ACCOUNT_EVIDENCE_STALE)
    stale_position = _evaluate(position_observed_ts_utc=NOW - timedelta(minutes=16), **live_context_kwargs)
    assert (stale_position.state, stale_position.reason_code) == (STATE_NON_ACTIONABLE, REASON_POSITION_EVIDENCE_STALE)
    stale_free = _evaluate(free_quantity_observed_ts_utc=NOW - timedelta(minutes=16), **live_context_kwargs)
    assert (stale_free.state, stale_free.reason_code) == (STATE_NON_ACTIONABLE, REASON_FREE_QUANTITY_EVIDENCE_STALE)
    conflict = _evaluate(blocking_conflict=True, **live_context_kwargs)
    assert (conflict.state, conflict.reason_code) == (STATE_DENIED, REASON_BLOCKING_CONFLICT)


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
