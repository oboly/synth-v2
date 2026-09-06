from datetime import UTC, datetime, timedelta
from decimal import Decimal
import ast
import inspect

import pytest

from src.market_rules.price_tick_normalization_v1 import TickRule, TICK_RULE_SOURCE_MISSING, TICK_RULE_SOURCE_STATIC
from src.research.execution_offset_preview_paper_validation_v1 import (
    CONFIDENCE_INSUFFICIENT,
    CONFIDENCE_SUFFICIENT,
    OUTCOME_AMBIGUOUS,
    OUTCOME_INVALIDATION,
    OUTCOME_NOT_AVAILABLE,
    OUTCOME_TARGET,
    REASON_INVALID_INVALIDATION_GEOMETRY,
    REASON_MISSING_TICK_RULE,
    STATE_NON_ACTIONABLE,
    STATE_PREVIEW,
    ExecutionOffsetValidationError,
    PaperCostAssumptionsV1,
    PaperOutcomeContextV1,
    PaperValidationInputV1,
    build_execution_offset_preview,
    build_paper_validation_report,
    render_paper_validation_report_json,
)
from src.research.execution_offset_replay_v1 import (
    ExecutionOffsetEpisodeV1,
    ExecutionOffsetPolicyV1,
    POLICY_EXACT_LEVEL,
    POLICY_STATIC_BUFFER,
    POLICY_VOLATILITY_SCALED_BUFFER,
    ReplayCandle,
    SIDE_BUY,
    SIDE_SELL,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
EXACT = ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1")
STATIC = ExecutionOffsetPolicyV1(POLICY_STATIC_BUFFER, "v1", buffer_pct=Decimal("0.01"))
ATR = ExecutionOffsetPolicyV1(POLICY_VOLATILITY_SCALED_BUFFER, "v1", atr_multiple=Decimal("0.25"))
POLICIES = (EXACT, STATIC, ATR)
COSTS = PaperCostAssumptionsV1(Decimal("25"), Decimal("5"))


def episode(eid="ep-1", side=SIDE_BUY, symbol="SOL", regime="RANGE", canonical="100"):
    return ExecutionOffsetEpisodeV1(
        episode_id=eid, symbol=symbol, venue="bitvavo", horizon="4h", side=side,
        fib_level_id="F0.618", canonical_level=Decimal(canonical), issued_ts_utc=T0,
        valid_until_ts_utc=T0 + timedelta(hours=5),
        invalidation_price=Decimal("90") if side == SIDE_BUY else Decimal("110"),
        atr_at_issue=Decimal("4"), regime_state=regime, source_map_id=f"map-{eid}",
    )


def candle(i, low, high, close=None):
    start=T0+timedelta(hours=i)
    lo=Decimal(low); hi=Decimal(high)
    cl=Decimal(close) if close is not None else (lo+hi)/2
    return ReplayCandle(start, start+timedelta(hours=1), hi, lo, cl)


def tick(side=SIDE_BUY):
    return TickRule("bitvavo", "SOL-EUR", Decimal("0.1"), 1, TICK_RULE_SOURCE_STATIC)


def test_preview_preserves_ideal_level_and_applies_buy_static_buffer_with_tick_rounding():
    p=build_execution_offset_preview(episode=episode(), policy=STATIC, tick_rule=tick())
    assert p.state == STATE_PREVIEW
    assert p.ideal_market_level == Decimal("100")
    assert p.raw_policy_execution_price == Decimal("101.00")
    assert p.execution_price == Decimal("101.0")
    assert p.execution_offset_pct == Decimal("1.00")
    assert p.preview_only and not p.decision_permission and not p.execution_intent
    assert p.source_map_id == "map-ep-1"


def test_preview_sell_rounds_up_and_preserves_canonical():
    p=build_execution_offset_preview(episode=episode(side=SIDE_SELL), policy=STATIC, tick_rule=tick())
    assert p.state == STATE_PREVIEW
    assert p.raw_policy_execution_price == Decimal("99.00")
    assert p.execution_price == Decimal("99.0")
    assert p.ideal_market_level == Decimal("100")


def test_preview_rejects_tick_rounded_candidate_that_crosses_invalidation():
    ep=episode(side=SIDE_SELL)
    ep=ep.__class__(**{**ep.__dict__, "invalidation_price": Decimal("99.5")})
    p=build_execution_offset_preview(episode=ep, policy=STATIC, tick_rule=tick())
    assert p.state == STATE_NON_ACTIONABLE
    assert p.reason_code == REASON_INVALID_INVALIDATION_GEOMETRY
    assert p.execution_price is None
    assert p.execution_offset_pct == Decimal("-1.00")
    assert p.ideal_market_level == Decimal("100")


def test_preview_missing_tick_rule_fails_closed():
    missing=TickRule("bitvavo","ZZZ-EUR",Decimal("0"),0,TICK_RULE_SOURCE_MISSING)
    p=build_execution_offset_preview(episode=episode(), policy=EXACT, tick_rule=missing)
    assert p.state == STATE_NON_ACTIONABLE
    assert p.reason_code == REASON_MISSING_TICK_RULE
    assert p.execution_price is None
    assert p.ideal_market_level == Decimal("100")


def paper_input(eid="ep-1", *, symbol="SOL", regime="RANGE", target="110", candles=None):
    ep=episode(eid=eid,symbol=symbol,regime=regime)
    rows = candles or (
        candle(0,"99","102"),       # BUY fill at 100/101 depending policy
        candle(1,"99","103"),
        candle(2,"99","111"),       # target after fill
        candle(3,"95","105"),
    )
    ctx=None if target is None else PaperOutcomeContextV1(eid, Decimal(target))
    return PaperValidationInputV1(ep, tuple(rows), tick(), ctx)


def _policy_summary(report, policy_id):
    return next(x for x in report["overall"] if x["policy_id"] == policy_id)


def test_paper_replay_uses_tick_rounded_preview_price_not_raw_policy_price():
    ep=episode(canonical="100.04")
    # 1% BUY buffer -> raw 101.0404, tick .1 floors to 101.0. Low 101.02
    # would fill the unrounded theoretical price but must NOT fill the actual
    # tick-valid paper proposal.
    rows=(candle(0,"101.02","102"), candle(1,"101.2","103"))
    inp=PaperValidationInputV1(ep, rows, tick(), None)
    report=build_paper_validation_report([inp], POLICIES, costs=COSTS, min_sample_threshold=1)
    static_row=next(r for r in report["rows"] if r.policy_id == POLICY_STATIC_BUFFER)
    assert static_row.execution_price == Decimal("101.0")
    assert static_row.canonical_level == Decimal("100.04")
    assert static_row.filled is False


def test_paper_validation_requires_all_three_policy_families():
    with pytest.raises(ExecutionOffsetValidationError, match="REQUIRED_POLICY_FAMILIES_MISSING"):
        build_paper_validation_report([paper_input()], (EXACT, STATIC), costs=COSTS, min_sample_threshold=1)


def test_fee_slippage_cost_and_adjusted_mfe_proxy_are_explicit():
    report=build_paper_validation_report([paper_input()], POLICIES, costs=COSTS, min_sample_threshold=1)
    row=next(r for r in report["rows"] if r.policy_id == POLICY_EXACT_LEVEL)
    assert row.fee_slippage_cost_pct == Decimal("0.60")
    assert row.max_favorable_excursion_pct is not None
    assert row.fee_slippage_adjusted_mfe_proxy_pct == row.max_favorable_excursion_pct - Decimal("0.60")


def test_target_hit_after_fill_is_measured_strictly_after_fill_candle():
    report=build_paper_validation_report([paper_input()], POLICIES, costs=COSTS, min_sample_threshold=1)
    row=next(r for r in report["rows"] if r.policy_id == POLICY_EXACT_LEVEL)
    assert row.post_fill_outcome == OUTCOME_TARGET
    assert _policy_summary(report, POLICY_EXACT_LEVEL)["post_fill_target_hit_rate_pct"] == Decimal("100")


def test_invalidation_after_fill_is_measured():
    inp=paper_input(candles=(candle(0,"99","102"),candle(1,"89","105"),candle(2,"95","109")))
    report=build_paper_validation_report([inp], POLICIES, costs=COSTS, min_sample_threshold=1)
    row=next(r for r in report["rows"] if r.policy_id == POLICY_EXACT_LEVEL)
    assert row.post_fill_outcome == OUTCOME_INVALIDATION


def test_buy_profit_target_on_loss_side_is_rejected_even_without_invalidation():
    ep=episode()
    ep=ep.__class__(**{**ep.__dict__, "invalidation_price": None})
    inp=PaperValidationInputV1(
        ep,
        (candle(0,"99","102"), candle(1,"94","105")),
        tick(),
        PaperOutcomeContextV1(ep.episode_id, Decimal("95")),
    )
    with pytest.raises(ExecutionOffsetValidationError, match="INVALID_OUTCOME_GEOMETRY"):
        build_paper_validation_report([inp], POLICIES, costs=COSTS, min_sample_threshold=1)


def test_sell_profit_target_on_loss_side_is_rejected_even_without_invalidation():
    ep=episode(side=SIDE_SELL)
    ep=ep.__class__(**{**ep.__dict__, "invalidation_price": None})
    inp=PaperValidationInputV1(
        ep,
        (candle(0,"98","101"), candle(1,"95","106")),
        tick(),
        PaperOutcomeContextV1(ep.episode_id, Decimal("105")),
    )
    with pytest.raises(ExecutionOffsetValidationError, match="INVALID_OUTCOME_GEOMETRY"):
        build_paper_validation_report([inp], POLICIES, costs=COSTS, min_sample_threshold=1)


def test_paper_invalidation_must_be_on_loss_side_for_entry_side():
    bad_buy=episode()
    bad_buy=bad_buy.__class__(**{**bad_buy.__dict__, "invalidation_price": Decimal("105")})
    inp=PaperValidationInputV1(bad_buy,(candle(0,"99","102"),),tick(),None)
    with pytest.raises(ExecutionOffsetValidationError, match="INVALID_OUTCOME_GEOMETRY"):
        build_paper_validation_report([inp], POLICIES, costs=COSTS, min_sample_threshold=1)


def test_same_candle_target_invalidation_after_fill_is_explicit_ambiguity():
    inp=paper_input(candles=(candle(0,"99","102"),candle(1,"89","111")))
    report=build_paper_validation_report([inp], POLICIES, costs=COSTS, min_sample_threshold=1)
    row=next(r for r in report["rows"] if r.policy_id == POLICY_EXACT_LEVEL)
    assert row.post_fill_outcome == OUTCOME_AMBIGUOUS


def test_missing_profit_target_is_not_invented_but_invalidation_is_still_measured():
    inp=paper_input(target=None, candles=(candle(0,"99","102"),candle(1,"89","105")))
    report=build_paper_validation_report([inp], POLICIES, costs=COSTS, min_sample_threshold=1)
    row=next(r for r in report["rows"] if r.policy_id == POLICY_EXACT_LEVEL)
    assert row.post_fill_target_available is False
    assert row.post_fill_target_hit is None
    assert row.post_fill_invalidation_available is True
    assert row.post_fill_invalidation_hit is True
    assert row.post_fill_outcome == OUTCOME_INVALIDATION
    summary=_policy_summary(report, POLICY_EXACT_LEVEL)
    assert summary["post_fill_target_eligible_count"] == 0
    assert summary["post_fill_invalidation_eligible_count"] == 1
    assert summary["post_fill_invalidation_hit_rate_pct"] == Decimal("100")


def test_symbol_regime_segments_and_confidence_threshold():
    inputs=[paper_input("a",symbol="SOL",regime="RANGE"),paper_input("b",symbol="BTC",regime=None)]
    report=build_paper_validation_report(inputs, POLICIES, costs=COSTS, min_sample_threshold=2)
    assert {x["segment_value"] for x in report["segments"]["symbol"]} == {"BTC","SOL"}
    assert {x["segment_value"] for x in report["segments"]["regime"]} == {"RANGE","UNKNOWN_REGIME"}
    assert all(x["confidence_state"] == CONFIDENCE_INSUFFICIENT for x in report["segments"]["symbol"])
    assert all(x["confidence_state"] == CONFIDENCE_SUFFICIENT for x in report["overall"])


def test_empty_and_duplicate_validation_cohorts_fail_closed():
    with pytest.raises(ExecutionOffsetValidationError, match="NO_VALIDATION_INPUTS"):
        build_paper_validation_report([], POLICIES, costs=COSTS, min_sample_threshold=1)
    duplicate=paper_input("dup")
    with pytest.raises(ExecutionOffsetValidationError, match="DUPLICATE_EPISODE_IDENTITY"):
        build_paper_validation_report([duplicate, duplicate], POLICIES, costs=COSTS, min_sample_threshold=1)


def test_non_actionable_preview_aborts_batch_instead_of_silent_exclusion():
    good=paper_input("good")
    missing=TickRule("bitvavo","UNKNOWN-EUR",Decimal("0"),0,TICK_RULE_SOURCE_MISSING)
    bad=paper_input("bad")
    bad=PaperValidationInputV1(bad.episode, bad.candles, missing, bad.outcome_context)
    with pytest.raises(ExecutionOffsetValidationError, match="PAPER_PREVIEW_NON_ACTIONABLE:MISSING_TICK_RULE"):
        build_paper_validation_report([good,bad], POLICIES, costs=COSTS, min_sample_threshold=1)


def test_post_fill_outcomes_do_not_leak_past_episode_validity_window():
    ep=episode()
    ep=ep.__class__(**{**ep.__dict__, "valid_until_ts_utc": T0+timedelta(hours=2)})
    rows=(
        candle(0,"99","102"),
        candle(1,"99","105"),
        candle(2,"99","111"),  # closes at hour 3, outside validity; must not count target
    )
    inp=PaperValidationInputV1(ep, rows, tick(), PaperOutcomeContextV1(ep.episode_id, Decimal("110")))
    report=build_paper_validation_report([inp], POLICIES, costs=COSTS, min_sample_threshold=1)
    exact=next(r for r in report["rows"] if r.policy_id == POLICY_EXACT_LEVEL)
    assert exact.filled is True
    assert exact.post_fill_target_hit is False


def test_negative_costs_and_noninteger_threshold_fail_closed():
    with pytest.raises(ExecutionOffsetValidationError, match="NEGATIVE_FEE_OR_SLIPPAGE"):
        build_paper_validation_report([paper_input()], POLICIES, costs=PaperCostAssumptionsV1(Decimal("-1"),Decimal("0")))
    with pytest.raises(ExecutionOffsetValidationError, match="INVALID_MIN_SAMPLE_THRESHOLD"):
        build_paper_validation_report([paper_input()], POLICIES, costs=COSTS, min_sample_threshold=0.5)  # type: ignore[arg-type]


def test_report_is_input_order_independent_and_decimal_safe():
    a=paper_input("a",symbol="BTC"); b=paper_input("b",symbol="SOL")
    r1=build_paper_validation_report([a,b], POLICIES, costs=COSTS, min_sample_threshold=1)
    r2=build_paper_validation_report([b,a], tuple(reversed(POLICIES)), costs=COSTS, min_sample_threshold=1)
    assert render_paper_validation_report_json(r1) == render_paper_validation_report_json(r2)
    assert r1["report_fingerprint"] == r2["report_fingerprint"]
    assert '"canonical_level": "100"' in render_paper_validation_report_json(r1)


def test_module_has_no_account_permission_planner_executor_or_broker_imports():
    import src.research.execution_offset_preview_paper_validation_v1 as module
    tree=ast.parse(inspect.getsource(module))
    imports={alias.name for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom)) for alias in node.names}
    forbidden=("decision_gate","execution_planner","executor","manual_execution","broker","account")
    assert not any(term in imported for imported in imports for term in forbidden)
    field_names={name for cls in (PaperValidationInputV1,PaperCostAssumptionsV1) for name in cls.__dataclass_fields__}
    assert not any(term in name for name in field_names for term in ("account","balance","quantity","permission"))
