"""
Tests for src/execution_ladder/ — resolver logic, whitelist guards, and safety contracts.

All tests are pure Python (no DB, no broker, no network). They use minimal
inline fixtures matching the SELL_PPP_RECOVERY_V1 seeded configuration.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from src.execution_ladder.models import LadderLeg, LadderProfile
from src.execution_ladder.resolver import (
    ALLOWED_ANCHOR_TYPES,
    ALLOWED_RULE_TYPES,
    ALLOWED_VARIABLE_KEYS,
    resolve_anchor_price,
    resolve_ladder_preview,
    resolve_leg_base_quantity,
    resolve_leg_limit_price,
    resolve_sizing_suggestion,
    validate_variable_key,
)
from src.execution_ladder.models import SizingRule

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_profile(**overrides) -> LadderProfile:
    defaults = dict(
        ladder_profile_id=1,
        trading_account_id=1,
        profile_code="SELL_PPP_RECOVERY_V1",
        display_label="Sell PPP recovery ladder",
        description="Recovery exits below anchor high.",
        side="SELL",
        anchor_type="NATIVE_SHORT_ANCHOR_HIGH",
        default_sizing_rule_id=1,
        is_enabled=True,
        current_version=1,
    )
    defaults.update(overrides)
    return LadderProfile(**defaults)


def _default_legs() -> list[LadderLeg]:
    return [
        LadderLeg(
            ladder_leg_id=1,
            ladder_profile_id=1,
            profile_version=1,
            leg_number=1,
            price_offset_bps=-600,
            allocation_bps=5000,
            order_type="LIMIT",
            time_in_force="GTC",
            is_enabled=True,
        ),
        LadderLeg(
            ladder_leg_id=2,
            ladder_profile_id=1,
            profile_version=1,
            leg_number=2,
            price_offset_bps=-200,
            allocation_bps=5000,
            order_type="LIMIT",
            time_in_force="GTC",
            is_enabled=True,
        ),
    ]


def _manual_only_rule() -> SizingRule:
    return SizingRule(
        sizing_rule_id=1,
        trading_account_id=1,
        rule_code="MANUAL_ONLY_DEFAULT",
        display_label="Manual amount (no suggestion)",
        description="No derived suggestion required.",
        rule_type="MANUAL_ONLY",
        source_variable_key=None,
        multiplier_bps=None,
        fixed_quote_amount=None,
        floor_quote_amount=None,
        cap_quote_amount=None,
        is_enabled=True,
        version=1,
    )


# ---------------------------------------------------------------------------
# Variable key whitelist
# ---------------------------------------------------------------------------

def test_six_variable_keys_are_whitelisted() -> None:
    expected = {
        "MANUAL_QUOTE_AMOUNT",
        "FIXED_QUOTE_AMOUNT",
        "FREE_QUOTE_BALANCE",
        "TOTAL_WALLET_QUOTE_VALUE",
        "COIN_POSITION_QUOTE_VALUE",
        "FREE_BASE_QUANTITY",
    }
    assert ALLOWED_VARIABLE_KEYS == expected


def test_validate_variable_key_accepts_all_whitelisted() -> None:
    for key in ALLOWED_VARIABLE_KEYS:
        assert validate_variable_key(key) == key


def test_unknown_variable_key_rejected() -> None:
    with pytest.raises(ValueError, match="not in the allowed whitelist"):
        validate_variable_key("FREE_TEXT_FORMULA")


def test_ppp_variable_key_rejected() -> None:
    with pytest.raises(ValueError, match="not in the allowed whitelist"):
        validate_variable_key("PPP_PRICE")


# ---------------------------------------------------------------------------
# Rule type whitelist
# ---------------------------------------------------------------------------

def test_three_rule_types_whitelisted() -> None:
    assert ALLOWED_RULE_TYPES == {"MANUAL_ONLY", "FIXED_QUOTE", "PCT_OF_VARIABLE"}


def test_unsupported_rule_type_rejected() -> None:
    rule = SizingRule(
        sizing_rule_id=99,
        trading_account_id=1,
        rule_code="UNKNOWN",
        display_label="",
        description="",
        rule_type="CUSTOM_FORMULA",
        source_variable_key=None,
        multiplier_bps=None,
        fixed_quote_amount=None,
        floor_quote_amount=None,
        cap_quote_amount=None,
        is_enabled=True,
        version=1,
    )
    with pytest.raises(ValueError, match="not supported"):
        resolve_sizing_suggestion(rule, {})


def test_manual_only_returns_none() -> None:
    result = resolve_sizing_suggestion(_manual_only_rule(), {})
    assert result is None


def test_fixed_quote_returns_fixed_amount() -> None:
    rule = SizingRule(
        sizing_rule_id=2,
        trading_account_id=1,
        rule_code="FIXED_10",
        display_label="",
        description="",
        rule_type="FIXED_QUOTE",
        source_variable_key=None,
        multiplier_bps=None,
        fixed_quote_amount=Decimal("10.00"),
        floor_quote_amount=None,
        cap_quote_amount=None,
        is_enabled=True,
        version=1,
    )
    result = resolve_sizing_suggestion(rule, {})
    assert result == Decimal("10.00")


def test_pct_of_variable_resolves_correctly() -> None:
    rule = SizingRule(
        sizing_rule_id=3,
        trading_account_id=1,
        rule_code="PCT_2",
        display_label="",
        description="",
        rule_type="PCT_OF_VARIABLE",
        source_variable_key="FREE_QUOTE_BALANCE",
        multiplier_bps=200,
        fixed_quote_amount=None,
        floor_quote_amount=None,
        cap_quote_amount=None,
        is_enabled=True,
        version=1,
    )
    result = resolve_sizing_suggestion(rule, {"FREE_QUOTE_BALANCE": Decimal("500.00")})
    assert result == Decimal("10.00")


# ---------------------------------------------------------------------------
# Anchor type whitelist
# ---------------------------------------------------------------------------

def test_only_native_short_anchor_high_in_v1() -> None:
    assert ALLOWED_ANCHOR_TYPES == {"NATIVE_SHORT_ANCHOR_HIGH"}


def test_resolve_anchor_price_accepts_native_short_anchor_high() -> None:
    price = resolve_anchor_price(
        "NATIVE_SHORT_ANCHOR_HIGH",
        anchor_high_price=Decimal("1.00"),
    )
    assert price == Decimal("1.00")


def test_resolve_anchor_price_rejects_ppp_price() -> None:
    with pytest.raises(ValueError, match="not supported"):
        resolve_anchor_price("PPP_PRICE", anchor_high_price=Decimal("1.00"))


def test_resolve_anchor_price_rejects_active_sell_target_price() -> None:
    with pytest.raises(ValueError, match="not supported"):
        resolve_anchor_price("ACTIVE_SELL_TARGET_PRICE", anchor_high_price=Decimal("1.272"))


def test_missing_anchor_high_blocks_preview() -> None:
    with pytest.raises(ValueError, match="requires a non-null anchor_high_price"):
        resolve_anchor_price("NATIVE_SHORT_ANCHOR_HIGH", anchor_high_price=None)


def test_zero_anchor_high_blocked() -> None:
    with pytest.raises(ValueError, match="must be > 0"):
        resolve_anchor_price("NATIVE_SHORT_ANCHOR_HIGH", anchor_high_price=Decimal("0"))


# ---------------------------------------------------------------------------
# Per-leg price and quantity
# ---------------------------------------------------------------------------

def test_leg_limit_price_offset_minus_600_bps() -> None:
    price = resolve_leg_limit_price(Decimal("1.00"), -600)
    assert price == Decimal("0.9400")


def test_leg_limit_price_offset_minus_200_bps() -> None:
    price = resolve_leg_limit_price(Decimal("1.00"), -200)
    assert price == Decimal("0.9800")


def test_leg_base_quantity_from_notional_and_price() -> None:
    qty = resolve_leg_base_quantity(Decimal("5.00"), Decimal("0.94"))
    expected = Decimal("5.00") / Decimal("0.94")
    assert qty == expected


# ---------------------------------------------------------------------------
# Direct SELL ladder preview is hard-blocked
# ---------------------------------------------------------------------------

def test_sell_ppp_recovery_v1_is_hard_blocked_before_resolution() -> None:
    with pytest.raises(PermissionError, match="manual_execution_service_v1"):
        resolve_ladder_preview(
            _default_profile(),
            _default_legs(),
            anchor_price=Decimal("1.00"),
            quote_amount=Decimal("10.00"),
        )


# ---------------------------------------------------------------------------
# Guard: active_target must not be passed as recovery anchor
# The resolver signature accepts anchor_high_price, not active_target.
# This test verifies the resolver source does not reference active_target.
# ---------------------------------------------------------------------------

RESOLVER_SOURCE = Path("src/execution_ladder/resolver.py").read_text(encoding="utf-8")


def test_resolver_does_not_reference_active_target() -> None:
    assert "active_target" not in RESOLVER_SOURCE, (
        "resolver.py must not reference active_target; "
        "ProfitPlanCard.active_target is ext_1_272 / ext_1_618, not a recovery anchor."
    )


def test_resolver_does_not_reference_ppp_price_variable() -> None:
    assert "PPP_PRICE" not in RESOLVER_SOURCE or "PPP_PRICE" in {"NATIVE_SHORT_ANCHOR_HIGH"}, (
        "PPP_PRICE must not appear in the resolver as an accepted anchor type"
    )


# ---------------------------------------------------------------------------
# Safety: no eval/exec/compile in resolver or runner
# ---------------------------------------------------------------------------

def _ast_check_no_dangerous_calls(source_path: Path, banned: list[str]) -> None:
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in banned:
                raise AssertionError(
                    f"{source_path}: forbidden call {name!r} found at line {node.lineno}"
                )


@pytest.mark.parametrize("source_path", [
    Path("src/execution_ladder/resolver.py"),
    Path("src/execution_ladder/repository.py"),
    Path("src/execution_ladder/run_ladder_profile_preview_v1.py"),
])
def test_no_eval_exec_compile(source_path: Path) -> None:
    _ast_check_no_dangerous_calls(source_path, ["eval", "exec", "compile"])


# ---------------------------------------------------------------------------
# Safety: runner source contains required safety markers
# ---------------------------------------------------------------------------

RUNNER_SOURCE = Path("src/execution_ladder/run_ladder_profile_preview_v1.py").read_text(
    encoding="utf-8"
)


def test_runner_has_broker_private_calls_marker() -> None:
    assert "broker_private_calls=0" in RUNNER_SOURCE


def test_runner_has_broker_writes_marker() -> None:
    assert "broker_writes=0" in RUNNER_SOURCE


def test_runner_has_order_submission_marker() -> None:
    assert "order_submission=0" in RUNNER_SOURCE


def test_runner_has_live_orders_marker() -> None:
    assert "live_orders=0" in RUNNER_SOURCE


def test_runner_has_decision_gate_none_marker() -> None:
    assert "decision_gate=none" in RUNNER_SOURCE


def test_runner_has_executor_none_marker() -> None:
    assert "executor=none" in RUNNER_SOURCE


# ---------------------------------------------------------------------------
# Safety: runner does not import executor or broker modules
# ---------------------------------------------------------------------------

def test_runner_does_not_import_executor() -> None:
    tree = ast.parse(RUNNER_SOURCE)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = ""
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            assert "executor" not in module, (
                f"runner must not import executor module, found: {module!r}"
            )
            assert "broker" not in module, (
                f"runner must not import broker module, found: {module!r}"
            )
