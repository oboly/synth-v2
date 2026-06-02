from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from src.advice_route.interfaces_v1 import (
    Action,
    ConfidenceBucket,
    ConfirmationState,
    FrameworkContext,
    FreshnessState,
    Horizon,
    StrategyInterpretation,
    StrategyProposal,
    StrengthBucket,
    SynthConfirmationContext,
    validate_forbidden_fields_absent,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _make_strategy_proposal(**overrides: object) -> StrategyProposal:
    payload: dict[str, object] = {
        "proposal_id": "proposal-1",
        "symbol": "BTC",
        "created_at_utc": _now(),
        "route_version": "v1",
        "action": Action.SELL,
        "horizon": Horizon.SHORT,
        "setup_id": "SELL_SHORT_SPIKE",
        "framework_bias": "FRAME_BULLISH",
        "framework_horizon": Horizon.MID,
        "confirmation_state": ConfirmationState.CONFIRMS,
        "confirmation_strength_bucket": StrengthBucket.HIGH,
        "confidence_bucket": ConfidenceBucket.MEDIUM,
        "entry_zone_low": Decimal("100.0"),
        "entry_zone_high": Decimal("110.0"),
        "target_zone_low": Decimal("120.0"),
        "target_zone_high": Decimal("130.0"),
        "invalidation_level": Decimal("95.0"),
        "source_interval": "4h",
        "anchor_interval": "1d",
        "map_horizon": Horizon.MID,
        "wave_degree": "PRIMARY",
        "freshness_state": FreshnessState.PASS,
        "quality_flags": ("QUALITY_OK",),
        "conflict_flags": (),
        "research_context_flags": ("RESEARCH_ONLY_FRAMEWORK",),
        "source_refs": ("signal_engine_state:4h", "execution_zone_context:4h"),
        "account_awareness": False,
        "broker_write_allowed": False,
        "order_submission": False,
        "decision_required": True,
    }
    payload.update(overrides)
    return StrategyProposal(**payload)


def test_strategy_proposal_safe_defaults() -> None:
    proposal = _make_strategy_proposal()
    assert proposal.account_awareness is False
    assert proposal.broker_write_allowed is False
    assert proposal.order_submission is False
    assert proposal.decision_required is True


def test_strategy_proposal_rejects_account_awareness() -> None:
    try:
        _make_strategy_proposal(account_awareness=True)
    except ValueError as exc:
        assert "account-agnostic" in str(exc)
        return
    raise AssertionError("Expected ValueError for account_awareness=True")


def test_strategy_proposal_rejects_broker_write_permission() -> None:
    try:
        _make_strategy_proposal(broker_write_allowed=True)
    except ValueError as exc:
        assert "broker writes" in str(exc)
        return
    raise AssertionError("Expected ValueError for broker_write_allowed=True")


def test_strategy_proposal_rejects_order_submission() -> None:
    try:
        _make_strategy_proposal(order_submission=True)
    except ValueError as exc:
        assert "order submission" in str(exc)
        return
    raise AssertionError("Expected ValueError for order_submission=True")


def test_strategy_proposal_requires_downstream_decision() -> None:
    try:
        _make_strategy_proposal(decision_required=False)
    except ValueError as exc:
        assert "decision permission" in str(exc)
        return
    raise AssertionError("Expected ValueError for decision_required=False")


def test_forbidden_fields_absent() -> None:
    validate_forbidden_fields_absent(
        FrameworkContext,
        SynthConfirmationContext,
        StrategyInterpretation,
        StrategyProposal,
    )


def test_module_has_no_forbidden_runtime_imports() -> None:
    source = Path("src/advice_route/interfaces_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_terms = (
        "decision_gate",
        "execution_planner",
        "executor",
        "broker",
        "bitvavo_client",
        "account_position",
        "balance_snapshot",
        "order_snapshot",
    )
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    for module_name in imported_modules:
        parts = tuple(part for part in module_name.split(".") if part)
        for term in forbidden_terms:
            assert term not in parts, f"Forbidden module import found: {module_name}"

    forbidden_dotted_refs = (
        "src.decision_gate",
        "src.execution_planner",
        "src.executor",
        "src.broker",
        "src.execution",
    )
    for dotted_ref in forbidden_dotted_refs:
        assert dotted_ref not in source, f"Forbidden module reference found: {dotted_ref}"


def test_setup_id_format() -> None:
    _make_strategy_proposal(setup_id="SELL_SHORT_SPIKE")
    _make_strategy_proposal(
        action=Action.BUY,
        horizon=Horizon.MID,
        setup_id="BUY_MID_RECLAIM",
    )
    _make_strategy_proposal(
        action=Action.HOLD,
        horizon=Horizon.LONG,
        setup_id="HOLD_LONG_CORE_TREND",
    )
    try:
        _make_strategy_proposal(setup_id="SPIKE_SHORT_SELL")
    except ValueError as exc:
        assert "setup_id" in str(exc)
        return
    raise AssertionError("Expected ValueError for invalid setup_id format")


def test_dataclasses_are_frozen() -> None:
    framework = FrameworkContext(
        symbol="BTC",
        created_at_utc=_now(),
        framework_bias="FRAME_BULLISH",
        framework_horizon=Horizon.LONG,
        map_horizon=Horizon.LONG,
        source_interval="1w",
        anchor_interval="1d",
    )
    proposal = _make_strategy_proposal()
    interpretation = StrategyInterpretation(
        symbol="BTC",
        created_at_utc=_now(),
        action=Action.BUY,
        horizon=Horizon.SHORT,
        setup_id="BUY_SHORT_PULLBACK",
        framework_bias="FRAME_PULLBACK",
        confirmation_state=ConfirmationState.MIXED,
        confirmation_strength_bucket=StrengthBucket.MEDIUM,
        confidence_bucket=ConfidenceBucket.LOW,
    )
    confirmation = SynthConfirmationContext(
        symbol="BTC",
        created_at_utc=_now(),
        confirmation_state=ConfirmationState.CONFIRMS,
        confirmation_strength_bucket=StrengthBucket.HIGH,
        freshness_state=FreshnessState.PASS,
    )

    for instance, field_name, value in (
        (framework, "framework_bias", "OTHER"),
        (proposal, "framework_bias", "OTHER"),
        (interpretation, "framework_bias", "OTHER"),
        (confirmation, "freshness_state", FreshnessState.FAIL),
    ):
        try:
            setattr(instance, field_name, value)
        except FrozenInstanceError:
            continue
        raise AssertionError(f"Expected {instance.__class__.__name__} to be frozen")


def main() -> None:
    tests = [
        test_strategy_proposal_safe_defaults,
        test_strategy_proposal_rejects_account_awareness,
        test_strategy_proposal_rejects_broker_write_permission,
        test_strategy_proposal_rejects_order_submission,
        test_strategy_proposal_requires_downstream_decision,
        test_forbidden_fields_absent,
        test_module_has_no_forbidden_runtime_imports,
        test_setup_id_format,
        test_dataclasses_are_frozen,
    ]
    for test in tests:
        test()
    print("ok")


if __name__ == "__main__":
    main()
