from __future__ import annotations

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from src.advice_route.interfaces_v1 import (
    Action,
    ConfidenceBucket,
    ConfirmationState,
    FreshnessState,
    Horizon,
    StrategyProposal,
    StrengthBucket,
)
from src.advice_route.serialization_v1 import (
    from_dict_framework_context,
    from_dict_strategy_interpretation,
    from_dict_strategy_proposal,
    from_dict_synth_confirmation_context,
    to_dict,
)


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=123456)


def _make_strategy_proposal() -> StrategyProposal:
    return StrategyProposal(
        proposal_id="proposal-1",
        symbol="BTC",
        created_at_utc=_now(),
        route_version="v1",
        action=Action.SELL,
        horizon=Horizon.SHORT,
        setup_id="SELL_SHORT_SPIKE",
        framework_bias="FRAME_BULLISH",
        framework_horizon=Horizon.MID,
        confirmation_state=ConfirmationState.CONFIRMS,
        confirmation_strength_bucket=StrengthBucket.HIGH,
        confidence_bucket=ConfidenceBucket.MEDIUM,
        entry_zone_low=Decimal("100.125"),
        entry_zone_high=Decimal("110.625"),
        target_zone_low=Decimal("120.375"),
        target_zone_high=Decimal("130.875"),
        invalidation_level=Decimal("95.500"),
        source_interval="4h",
        anchor_interval="1d",
        map_horizon=Horizon.MID,
        wave_degree="PRIMARY",
        freshness_state=FreshnessState.PASS,
        quality_flags=("QUALITY_OK", "COVERAGE_OK"),
        conflict_flags=("NO_CONFLICT",),
        research_context_flags=("RESEARCH_ONLY_FRAMEWORK",),
        source_refs=("signal_engine_state:4h", "execution_zone_context:4h"),
        account_awareness=False,
        broker_write_allowed=False,
        order_submission=False,
        decision_required=True,
    )


def test_strategy_proposal_round_trip() -> None:
    proposal = _make_strategy_proposal()
    payload = to_dict(proposal)
    restored = from_dict_strategy_proposal(payload)
    assert restored == proposal


def test_decimal_fields_round_trip_as_strings() -> None:
    payload = to_dict(_make_strategy_proposal())
    assert payload["entry_zone_low"] == "100.125"
    assert payload["target_zone_high"] == "130.875"
    restored = from_dict_strategy_proposal(payload)
    assert restored.entry_zone_low == Decimal("100.125")
    assert restored.target_zone_high == Decimal("130.875")


def test_datetime_round_trip() -> None:
    proposal = _make_strategy_proposal()
    payload = to_dict(proposal)
    assert payload["created_at_utc"] == proposal.created_at_utc.isoformat()
    restored = from_dict_strategy_proposal(payload)
    assert restored.created_at_utc == proposal.created_at_utc


def test_tuple_fields_round_trip_as_lists() -> None:
    payload = to_dict(_make_strategy_proposal())
    assert payload["quality_flags"] == ["QUALITY_OK", "COVERAGE_OK"]
    assert payload["source_refs"] == ["signal_engine_state:4h", "execution_zone_context:4h"]
    restored = from_dict_strategy_proposal(payload)
    assert restored.quality_flags == ("QUALITY_OK", "COVERAGE_OK")
    assert restored.source_refs == ("signal_engine_state:4h", "execution_zone_context:4h")


def test_forbidden_input_fields_are_rejected() -> None:
    payload = to_dict(_make_strategy_proposal())
    payload["broker_order_payload"] = {"unsafe": True}
    try:
        from_dict_strategy_proposal(payload)
    except ValueError as exc:
        assert "Forbidden payload field" in str(exc)
        return
    raise AssertionError("Expected forbidden field rejection")


def test_account_awareness_true_is_rejected() -> None:
    payload = to_dict(_make_strategy_proposal())
    payload["account_awareness"] = True
    try:
        from_dict_strategy_proposal(payload)
    except ValueError as exc:
        assert "account-agnostic" in str(exc)
        return
    raise AssertionError("Expected account_awareness rejection")


def test_broker_write_allowed_true_is_rejected() -> None:
    payload = to_dict(_make_strategy_proposal())
    payload["broker_write_allowed"] = True
    try:
        from_dict_strategy_proposal(payload)
    except ValueError as exc:
        assert "broker writes" in str(exc)
        return
    raise AssertionError("Expected broker_write_allowed rejection")


def test_order_submission_true_is_rejected() -> None:
    payload = to_dict(_make_strategy_proposal())
    payload["order_submission"] = True
    try:
        from_dict_strategy_proposal(payload)
    except ValueError as exc:
        assert "order submission" in str(exc)
        return
    raise AssertionError("Expected order_submission rejection")


def test_context_helpers_round_trip() -> None:
    framework_payload = {
        "symbol": "ETH",
        "created_at_utc": _now().isoformat(),
        "framework_bias": "FRAME_PULLBACK",
        "framework_horizon": "LONG",
        "map_horizon": "MID",
        "source_interval": "1w",
        "anchor_interval": "1d",
        "target_zone_low": "2500.25",
        "target_zone_high": "2800.75",
        "invalidation_level": "2200.00",
        "framework_confidence_bucket": "HIGH",
        "research_context_flags": ["BREATH_FRAME", "FIBO_MAP"],
        "source_refs": ["fib:1w"],
    }
    confirmation_payload = {
        "symbol": "ETH",
        "created_at_utc": _now().isoformat(),
        "confirmation_state": "MIXED",
        "confirmation_strength_bucket": "MEDIUM",
        "freshness_state": "WARN",
        "conflict_flags": ["LTF_CONFLICT"],
        "quality_flags": ["COVERAGE_WARN"],
        "runtime_source_flags": ["signal_engine_state:4h"],
        "source_refs": ["selection_state"],
    }
    interpretation_payload = {
        "symbol": "ETH",
        "created_at_utc": _now().isoformat(),
        "action": "BUY",
        "horizon": "MID",
        "setup_id": "BUY_MID_RECLAIM",
        "framework_bias": "FRAME_PULLBACK",
        "confirmation_state": "MIXED",
        "confirmation_strength_bucket": "MEDIUM",
        "confidence_bucket": "LOW",
        "notes": ["needs confirmation"],
        "source_refs": ["signal_engine_state:4h"],
    }

    assert to_dict(from_dict_framework_context(framework_payload)) == framework_payload
    assert to_dict(from_dict_synth_confirmation_context(confirmation_payload)) == confirmation_payload
    assert to_dict(from_dict_strategy_interpretation(interpretation_payload)) == interpretation_payload


def test_module_has_no_forbidden_imports() -> None:
    source = Path("src/advice_route/serialization_v1.py").read_text(encoding="utf-8")
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
        "db",
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
        "src.common.db",
    )
    for dotted_ref in forbidden_dotted_refs:
        assert dotted_ref not in source, f"Forbidden module reference found: {dotted_ref}"


def main() -> None:
    tests = [
        test_strategy_proposal_round_trip,
        test_decimal_fields_round_trip_as_strings,
        test_datetime_round_trip,
        test_tuple_fields_round_trip_as_lists,
        test_forbidden_input_fields_are_rejected,
        test_account_awareness_true_is_rejected,
        test_broker_write_allowed_true_is_rejected,
        test_order_submission_true_is_rejected,
        test_context_helpers_round_trip,
        test_module_has_no_forbidden_imports,
    ]
    for test in tests:
        test()
    print("ok")


if __name__ == "__main__":
    main()
