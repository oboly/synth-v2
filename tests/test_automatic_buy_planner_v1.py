from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.decision_gate.automatic_buy_gate_v1 import (
    STATE_APPROVED, STATE_DENIED, STATE_NON_ACTIONABLE, AutomaticBuyGateDecisionV1,
)
from src.entry_policy.automatic_buy_candidate_v1 import AutomaticBuyCandidateV1
from src.execution_planner.automatic_buy_planner_v1 import (
    AutomaticBuyPlanningContextV1, AutomaticBuyPlanningError, build_automatic_buy_plan_v1,
)
from src.market_rules.venue_execution_constraints_v1 import (
    DEFAULT_MAX_METADATA_AGE_SECONDS,
    STATUS_FRESH,
    VenueExecutionConstraints,
    resolve_venue_execution_constraints,
)


NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def _candidate(**overrides: object) -> AutomaticBuyCandidateV1:
    values: dict[str, object] = dict(venue="bitvavo", asset_id=42, market="SOL-EUR", strategy_id="strat-1", strategy_version="1", setup_id="setup-1", candidate_action="ENTER", reason_code="ENTRY_ZONE_REACHED", evidence_id="evidence-1", entry_zone_low=Decimal("90"), entry_zone_high=Decimal("100"), observed_ts_utc=NOW)
    values.update(overrides)
    return AutomaticBuyCandidateV1(**values)  # type: ignore[arg-type]


def _decision(**overrides: object) -> AutomaticBuyGateDecisionV1:
    values: dict[str, object] = dict(state=STATE_APPROVED, reason_code="OK", candidate=_candidate(), approved_notional_ceiling_eur=Decimal("257.03"))
    values.update(overrides)
    return AutomaticBuyGateDecisionV1(**values)  # type: ignore[arg-type]


def _constraints(**overrides: object) -> VenueExecutionConstraints:
    values: dict[str, object] = dict(venue="bitvavo", market="SOL-EUR", tick_size=Decimal("0.05"), qty_step_size=Decimal("0.1"), min_base_quantity=Decimal("0.1"), min_quote_notional=Decimal("5"), supported_order_types=("limit",), supported_time_in_force=("GTC",), source_provenance="PUBLIC", metadata_synced_ts_utc=NOW, status=STATUS_FRESH)
    values.update(overrides)
    return VenueExecutionConstraints(**values)  # type: ignore[arg-type]


def _context(**overrides: object) -> AutomaticBuyPlanningContextV1:
    values: dict[str, object] = dict(trading_account_id=7, venue="bitvavo", asset_id=42, market="SOL-EUR", reference_price=Decimal("100.01"), venue_constraints=_constraints(), planning_ts_utc=NOW)
    values.update(overrides)
    return AutomaticBuyPlanningContextV1(**values)  # type: ignore[arg-type]


def test_approved_gate_builds_deterministic_immutable_buy_ladder_with_provenance() -> None:
    plan = build_automatic_buy_plan_v1(decision=_decision(), context=_context())
    assert plan.side == "BUY"
    assert plan.final_quantity_base == Decimal("2.5")
    assert tuple(leg.quantity_base for leg in plan.legs) == (Decimal("1.2"), Decimal("1.3"))
    assert tuple(leg.limit_price for leg in plan.legs) == (Decimal("100.00"), Decimal("99.75"))
    assert all(leg.limit_price <= Decimal("100.01") for leg in plan.legs)
    assert sum(leg.quantity_base for leg in plan.legs) == plan.final_quantity_base
    assert plan.candidate_action == "ENTER"
    assert plan.candidate_evidence_id == "evidence-1"
    assert plan.strategy_id == "strat-1"
    assert plan.gate_approval.approved_notional_ceiling_eur == Decimal("257.03")
    assert plan == build_automatic_buy_plan_v1(decision=_decision(), context=_context())


@pytest.mark.parametrize("state", [STATE_DENIED, STATE_NON_ACTIONABLE])
def test_non_approved_gate_is_rejected(state: str) -> None:
    with pytest.raises(AutomaticBuyPlanningError, match="GATE_DECISION_NOT_APPROVED"):
        build_automatic_buy_plan_v1(decision=_decision(state=state, approved_notional_ceiling_eur=None), context=_context())


@pytest.mark.parametrize("ceiling", [None, Decimal("0"), Decimal("-1")])
def test_invalid_ceiling_is_rejected(ceiling: Decimal | None) -> None:
    with pytest.raises(AutomaticBuyPlanningError, match="APPROVED_NOTIONAL_CEILING_INVALID"):
        build_automatic_buy_plan_v1(decision=_decision(approved_notional_ceiling_eur=ceiling), context=_context())


def test_notional_ceiling_is_converted_to_base_quantity_via_reference_price() -> None:
    plan = build_automatic_buy_plan_v1(decision=_decision(approved_notional_ceiling_eur=Decimal("50.005")), context=_context())
    assert plan.final_quantity_base == Decimal("0.5")
    assert sum(leg.quote_notional for leg in plan.legs) <= Decimal("50.005")


def test_non_eight_decimal_venue_step_is_respected() -> None:
    plan = build_automatic_buy_plan_v1(
        decision=_decision(approved_notional_ceiling_eur=Decimal("236")),
        context=_context(reference_price=Decimal("100"), venue_constraints=_constraints(qty_step_size=Decimal("0.25"))),
    )
    assert plan.final_quantity_base == Decimal("2.25")
    assert all(leg.quantity_base % Decimal("0.25") == 0 for leg in plan.legs)


def test_limit_and_gtc_capabilities_are_required_case_insensitively() -> None:
    valid = _constraints(supported_order_types=(" LIMIT ",), supported_time_in_force=("gtc",))
    assert build_automatic_buy_plan_v1(decision=_decision(), context=_context(venue_constraints=valid)).side == "BUY"
    with pytest.raises(AutomaticBuyPlanningError, match="VENUE_LIMIT_ORDER_UNSUPPORTED"):
        build_automatic_buy_plan_v1(
            decision=_decision(), context=_context(venue_constraints=_constraints(supported_order_types=("market",)))
        )
    with pytest.raises(AutomaticBuyPlanningError, match="VENUE_GTC_UNSUPPORTED"):
        build_automatic_buy_plan_v1(
            decision=_decision(), context=_context(venue_constraints=_constraints(supported_time_in_force=("IOC",)))
        )


def test_raw_fresh_metadata_timestamps_are_validated_against_planning_time() -> None:
    with pytest.raises(AutomaticBuyPlanningError, match="VENUE_CONSTRAINTS_TIMESTAMP_STALE_OR_FUTURE"):
        build_automatic_buy_plan_v1(
            decision=_decision(),
            context=_context(venue_constraints=_constraints(metadata_synced_ts_utc=NOW - timedelta(seconds=DEFAULT_MAX_METADATA_AGE_SECONDS + 1))),
        )
    with pytest.raises(AutomaticBuyPlanningError, match="VENUE_CONSTRAINTS_TIMESTAMP_STALE_OR_FUTURE"):
        build_automatic_buy_plan_v1(
            decision=_decision(), context=_context(venue_constraints=_constraints(metadata_synced_ts_utc=NOW + timedelta(seconds=1)))
        )
    with pytest.raises(AutomaticBuyPlanningError, match="VENUE_CONSTRAINTS_TIMESTAMP_INVALID"):
        build_automatic_buy_plan_v1(
            decision=_decision(), context=_context(venue_constraints=_constraints(metadata_synced_ts_utc=NOW.replace(tzinfo=None)))
        )


def test_current_resolved_fresh_constraints_pass() -> None:
    constraints = _constraints()
    resolved = resolve_venue_execution_constraints(
        venue="bitvavo", market="SOL-EUR", db_rows={"SOL-EUR": constraints}, now=NOW,
    )
    assert resolved.status == STATUS_FRESH
    assert build_automatic_buy_plan_v1(decision=_decision(), context=_context(venue_constraints=resolved)).side == "BUY"


@pytest.mark.parametrize("ceiling,constraints,reason", [
    (Decimal("9"), _constraints(), "QUANTITY_ROUNDS_TO_ZERO"),
    (Decimal("257.03"), _constraints(min_base_quantity=Decimal("3")), "FINAL_QUANTITY_BELOW_MIN_BASE_QUANTITY"),
    (Decimal("257.03"), _constraints(min_quote_notional=Decimal("200")), "LADDER_LEG_1_INVALID:BELOW_MIN_QUOTE_NOTIONAL"),
])
def test_post_round_invalidity_fails_closed(ceiling: Decimal, constraints: VenueExecutionConstraints, reason: str) -> None:
    with pytest.raises(AutomaticBuyPlanningError, match=reason):
        build_automatic_buy_plan_v1(decision=_decision(approved_notional_ceiling_eur=ceiling), context=_context(venue_constraints=constraints))


def test_enter_and_re_enter_candidate_actions_are_preserved() -> None:
    candidate = _candidate(candidate_action="RE_ENTER")
    plan = build_automatic_buy_plan_v1(decision=_decision(candidate=candidate), context=_context())
    assert plan.candidate_action == "RE_ENTER"


def test_identity_and_provenance_mismatches_fail_closed() -> None:
    with pytest.raises(AutomaticBuyPlanningError, match="GATE_CANDIDATE_CONTEXT_IDENTITY_MISMATCH"):
        build_automatic_buy_plan_v1(decision=_decision(candidate=_candidate(market="ETH-EUR")), context=_context())
    with pytest.raises(AutomaticBuyPlanningError, match="CANDIDATE_PROVENANCE_INVALID"):
        build_automatic_buy_plan_v1(decision=_decision(candidate=_candidate(evidence_id="")), context=_context())
    with pytest.raises(AutomaticBuyPlanningError, match="CANDIDATE_PROVENANCE_INVALID"):
        build_automatic_buy_plan_v1(decision=_decision(candidate=_candidate(strategy_id="")), context=_context())
    with pytest.raises(AutomaticBuyPlanningError, match="CANDIDATE_PROVENANCE_INVALID"):
        build_automatic_buy_plan_v1(
            decision=_decision(candidate=_candidate(candidate_action="EXIT")), context=_context()
        )


def test_planning_context_invalid_fields_fail_closed() -> None:
    with pytest.raises(AutomaticBuyPlanningError, match="PLANNING_CONTEXT_INVALID"):
        build_automatic_buy_plan_v1(decision=_decision(), context=_context(reference_price=Decimal("0")))
    with pytest.raises(AutomaticBuyPlanningError, match="PLANNING_CONTEXT_INVALID"):
        build_automatic_buy_plan_v1(decision=_decision(), context=_context(trading_account_id=0))
    with pytest.raises(AutomaticBuyPlanningError, match="PLANNING_CONTEXT_INVALID"):
        build_automatic_buy_plan_v1(decision=_decision(), context=_context(planning_ts_utc=NOW.replace(tzinfo=None)))


def test_planner_has_no_manual_executor_broker_or_raw_candidate_entrypoint() -> None:
    tree = ast.parse(Path("src/execution_planner/automatic_buy_planner_v1.py").read_text())
    imports = [alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names]
    assert not any(any(word in name for word in ("manual_execution", "executor", "broker")) for name in imports)
    assert "candidate" not in build_automatic_buy_plan_v1.__annotations__
