from datetime import datetime, timedelta, timezone
from decimal import Decimal
import ast
import inspect

from src.exit_policy.automatic_exit_candidate_v1 import (
    ACTION_EXIT,
    ACTION_REDUCE,
    REASON_EXIT_CONTEXT_STALE,
    REASON_CONTEXT_MISMATCH,
    REASON_INVALID_CONTEXT,
    REASON_INVALID_TIMESTAMP,
    REASON_NO_EXIT_CONDITION,
    REASON_NO_HELD_POSITION,
    REASON_POSITION_STALE,
    STATE_CANDIDATE,
    STATE_NO_ACTION,
    STATE_NON_ACTIONABLE,
    AutomaticExitMarketContextV1,
    AutomaticExitPolicyConfigV1,
    AutomaticExitPositionContextV1,
    evaluate_automatic_exit_candidate_v1,
)


NOW = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)


def _position(**changes: object) -> AutomaticExitPositionContextV1:
    values: dict[str, object] = dict(
        trading_account_id=7, position_reference="account_position_snapshot:42",
        venue="bitvavo", asset_id=9, market="SOL-EUR",
        held_quantity_base=Decimal("10"), observed_ts_utc=NOW,
    )
    values.update(changes)
    return AutomaticExitPositionContextV1(**values)  # type: ignore[arg-type]


def _market(**changes: object) -> AutomaticExitMarketContextV1:
    values: dict[str, object] = dict(
        venue="bitvavo", asset_id=9, market="SOL-EUR", current_price=Decimal("150"),
        active_target_price=Decimal("160"), invalidation_price=Decimal("100"),
        exit_profile_id="native-short:SOL:2026-08-13", exit_profile_version="1",
        evidence_id="native-map-level:501", observed_ts_utc=NOW,
    )
    values.update(changes)
    return AutomaticExitMarketContextV1(**values)  # type: ignore[arg-type]


def _evaluate(**changes: object):
    position = changes.pop("position", _position())
    market = changes.pop("market", _market())
    return evaluate_automatic_exit_candidate_v1(
        position=position, market_context=market, evaluation_ts_utc=NOW, **changes
    )


def test_no_held_position_is_no_action() -> None:
    result = _evaluate(position=_position(held_quantity_base=Decimal("0")))
    assert (result.state, result.reason_code, result.candidate) == (STATE_NO_ACTION, REASON_NO_HELD_POSITION, None)


def test_healthy_position_without_exit_condition_is_no_action() -> None:
    result = _evaluate()
    assert (result.state, result.reason_code, result.candidate) == (STATE_NO_ACTION, REASON_NO_EXIT_CONDITION, None)


def test_target_reached_is_deterministic_reduce_candidate_with_provenance() -> None:
    result = _evaluate(market=_market(current_price=Decimal("160")))
    assert result.state == STATE_CANDIDATE
    assert result.candidate is not None
    assert result.candidate.candidate_action == ACTION_REDUCE
    assert result.candidate.reduction_fraction_candidate == Decimal("0.25")
    assert result.candidate.evidence_id == "native-map-level:501"
    assert result.candidate.exit_profile_id == "native-short:SOL:2026-08-13"
    assert result.candidate.observed_ts_utc == NOW
    assert _evaluate(market=_market(current_price=Decimal("160"))) == result


def test_invalidation_breach_is_full_fraction_exit_candidate() -> None:
    result = _evaluate(market=_market(current_price=Decimal("100")))
    assert result.candidate is not None
    assert result.candidate.candidate_action == ACTION_EXIT
    assert result.candidate.reduction_fraction_candidate == Decimal("1")


def test_stale_market_context_is_non_actionable() -> None:
    result = _evaluate(market=_market(observed_ts_utc=NOW - timedelta(minutes=16)))
    assert (result.state, result.reason_code, result.candidate) == (STATE_NON_ACTIONABLE, REASON_EXIT_CONTEXT_STALE, None)


def test_stale_position_context_is_non_actionable() -> None:
    result = _evaluate(position=_position(observed_ts_utc=NOW - timedelta(minutes=16)))
    assert (result.state, result.reason_code, result.candidate) == (STATE_NON_ACTIONABLE, REASON_POSITION_STALE, None)


def test_mismatched_position_and_market_context_is_non_actionable() -> None:
    result = _evaluate(market=_market(market="ETH-EUR"))
    assert (result.state, result.reason_code, result.candidate) == (STATE_NON_ACTIONABLE, REASON_CONTEXT_MISMATCH, None)


def test_missing_profile_provenance_is_non_actionable() -> None:
    for changes in (
        {"exit_profile_id": ""},
        {"exit_profile_version": ""},
        {"evidence_id": ""},
    ):
        result = _evaluate(market=_market(**changes))
        assert (result.state, result.reason_code, result.candidate) == (STATE_NON_ACTIONABLE, REASON_INVALID_CONTEXT, None)


def test_naive_timestamps_are_rejected_as_non_actionable() -> None:
    result = _evaluate(position=_position(observed_ts_utc=NOW.replace(tzinfo=None)))
    assert (result.state, result.reason_code, result.candidate) == (STATE_NON_ACTIONABLE, REASON_INVALID_TIMESTAMP, None)


def test_invalid_reduction_fraction_fails_closed_and_never_exceeds_safe_bounds() -> None:
    result = _evaluate(
        market=_market(current_price=Decimal("160")),
        config=AutomaticExitPolicyConfigV1(harvest_reduction_fraction=Decimal("1.01")),
    )
    assert result.state == STATE_NON_ACTIONABLE
    assert result.candidate is None


def test_module_has_no_decision_gate_bypass_or_execution_dependencies() -> None:
    import src.exit_policy.automatic_exit_candidate_v1 as module

    tree = ast.parse(inspect.getsource(module))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden = ("decision_gate", "execution_planner", "executor", "bitvavo", "broker", "manual_execution")
    assert not any(term in imported for imported in imports for term in forbidden)
    result = _evaluate(market=_market(current_price=Decimal("160")))
    assert result.candidate is not None
    assert not hasattr(result.candidate, "quantity_base")
    assert not hasattr(result.candidate, "broker_payload")


def test_exit_policy_package_has_no_decision_gate_dependency() -> None:
    import src.exit_policy as package

    tree = ast.parse(inspect.getsource(package))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any("decision_gate" in imported for imported in imports)
