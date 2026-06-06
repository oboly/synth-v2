"""
Tests for long_reserve_policy_v1.

No DB access. All inputs are supplied directly.

Coverage:
- Default fallback when no profile configured (DEFAULT_ASSUMED)
- Account default when no asset override (ACCOUNT_DEFAULT)
- Asset-level override applied (ASSET_OVERRIDE)
- max_short_swing_sell_pct = 100 - active_reserve
- max_sell_pct_allowed by tp_scope:
    CHILD_SHORT_SWING → max_short_swing_sell_pct
    PARENT_TF_PARTIAL → max_short_swing_sell_pct
    PARENT_TF_FULL + allow=False → max_short_swing_sell_pct
    PARENT_TF_FULL + allow=True  → 100
- Invalid reserve_pct rejected at profile construction
- Invalid tp_scope rejected at resolve time
- Determinism
- Task example: CHIP=80, NEAR=50, HYPE=30
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.account.long_reserve_policy_v1 import (
    RESERVE_SOURCE_ACCOUNT_DEFAULT,
    RESERVE_SOURCE_ASSET_OVERRIDE,
    RESERVE_SOURCE_DEFAULT_ASSUMED,
    TP_SCOPE_CHILD_SHORT_SWING,
    TP_SCOPE_PARENT_TF_FULL,
    TP_SCOPE_PARENT_TF_PARTIAL,
    AccountLongReserveProfile,
    LongReservePolicyInput,
    resolve_from_parts,
    resolve_long_reserve_policy,
)


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------

def _profile(
    account_profile_id: str = "test",
    default_reserve: str = "50",
    allow_parent_tf_full_exit: bool = False,
    overrides: dict[str, str] | None = None,
) -> AccountLongReserveProfile:
    return AccountLongReserveProfile(
        account_profile_id=account_profile_id,
        default_long_reserve_pct=Decimal(default_reserve),
        allow_parent_tf_full_exit=allow_parent_tf_full_exit,
        asset_overrides={k: Decimal(v) for k, v in (overrides or {}).items()},
    )


def _resolve(
    account_profile_id: str,
    symbol: str,
    tp_scope: str = TP_SCOPE_CHILD_SHORT_SWING,
    profiles: dict | None = None,
):
    return resolve_from_parts(
        account_profile_id=account_profile_id,
        symbol=symbol,
        tp_scope=tp_scope,
        profiles=profiles,
    )


# ---------------------------------------------------------------------------
# DEFAULT_ASSUMED fallback
# ---------------------------------------------------------------------------

def test_no_profile_uses_default_assumed() -> None:
    result = _resolve("unknown_profile", "NEAR", profiles={})
    assert result.reserve_source == RESERVE_SOURCE_DEFAULT_ASSUMED
    assert result.active_long_reserve_pct == Decimal("50")
    assert result.default_long_reserve_pct == Decimal("50")
    assert result.asset_long_reserve_pct is None


def test_default_assumed_max_short_swing_sell_pct() -> None:
    result = _resolve("unknown_profile", "NEAR", profiles={})
    assert result.max_short_swing_sell_pct == Decimal("50")


def test_default_assumed_does_not_allow_parent_tf_full_exit() -> None:
    result = _resolve(
        "unknown_profile", "NEAR",
        tp_scope=TP_SCOPE_PARENT_TF_FULL,
        profiles={},
    )
    assert result.allow_parent_tf_full_exit is False
    assert result.max_sell_pct_allowed == Decimal("50")


# ---------------------------------------------------------------------------
# ACCOUNT_DEFAULT
# ---------------------------------------------------------------------------

def test_account_default_used_when_no_asset_override() -> None:
    profiles = {"p": _profile(account_profile_id="p", default_reserve="60")}
    result = _resolve("p", "XRP", profiles=profiles)
    assert result.reserve_source == RESERVE_SOURCE_ACCOUNT_DEFAULT
    assert result.active_long_reserve_pct == Decimal("60")
    assert result.asset_long_reserve_pct is None
    assert result.max_short_swing_sell_pct == Decimal("40")


def test_account_default_70_reserve() -> None:
    profiles = {"p": _profile(default_reserve="70")}
    result = _resolve("p", "SOL", profiles=profiles)
    assert result.max_short_swing_sell_pct == Decimal("30")
    assert result.max_sell_pct_allowed == Decimal("30")


# ---------------------------------------------------------------------------
# ASSET_OVERRIDE
# ---------------------------------------------------------------------------

def test_asset_override_applied() -> None:
    profiles = {
        "p": _profile(default_reserve="50", overrides={"NEAR": "50", "HYPE": "30"})
    }
    # NEAR has an explicit override even though it equals the default
    result = _resolve("p", "NEAR", profiles=profiles)
    assert result.reserve_source == RESERVE_SOURCE_ASSET_OVERRIDE
    assert result.asset_long_reserve_pct == Decimal("50")
    assert result.active_long_reserve_pct == Decimal("50")


def test_asset_override_hype_30() -> None:
    profiles = {
        "p": _profile(default_reserve="50", overrides={"HYPE": "30"})
    }
    result = _resolve("p", "HYPE", profiles=profiles)
    assert result.reserve_source == RESERVE_SOURCE_ASSET_OVERRIDE
    assert result.active_long_reserve_pct == Decimal("30")
    assert result.max_short_swing_sell_pct == Decimal("70")
    assert result.max_sell_pct_allowed == Decimal("70")


def test_asset_override_chip_80() -> None:
    profiles = {
        "p": _profile(default_reserve="50", overrides={"CHIP": "80"})
    }
    result = _resolve("p", "CHIP", profiles=profiles)
    assert result.reserve_source == RESERVE_SOURCE_ASSET_OVERRIDE
    assert result.active_long_reserve_pct == Decimal("80")
    assert result.max_short_swing_sell_pct == Decimal("20")


def test_non_overridden_symbol_uses_account_default() -> None:
    profiles = {
        "p": _profile(default_reserve="50", overrides={"CHIP": "80"})
    }
    result = _resolve("p", "XLM", profiles=profiles)
    assert result.reserve_source == RESERVE_SOURCE_ACCOUNT_DEFAULT
    assert result.active_long_reserve_pct == Decimal("50")


# ---------------------------------------------------------------------------
# max_sell_pct_allowed by tp_scope
# ---------------------------------------------------------------------------

def test_child_short_swing_capped_at_max_short_swing() -> None:
    profiles = {"p": _profile(default_reserve="50", allow_parent_tf_full_exit=True)}
    result = _resolve("p", "SOL", tp_scope=TP_SCOPE_CHILD_SHORT_SWING, profiles=profiles)
    assert result.max_sell_pct_allowed == Decimal("50")


def test_parent_tf_partial_capped_at_max_short_swing() -> None:
    profiles = {"p": _profile(default_reserve="40", allow_parent_tf_full_exit=True)}
    result = _resolve("p", "SOL", tp_scope=TP_SCOPE_PARENT_TF_PARTIAL, profiles=profiles)
    assert result.max_sell_pct_allowed == Decimal("60")


def test_parent_tf_full_blocked_when_not_allowed() -> None:
    profiles = {"p": _profile(default_reserve="50", allow_parent_tf_full_exit=False)}
    result = _resolve("p", "SOL", tp_scope=TP_SCOPE_PARENT_TF_FULL, profiles=profiles)
    assert result.allow_parent_tf_full_exit is False
    assert result.max_sell_pct_allowed == Decimal("50")


def test_parent_tf_full_allowed_when_enabled() -> None:
    profiles = {"p": _profile(default_reserve="50", allow_parent_tf_full_exit=True)}
    result = _resolve("p", "SOL", tp_scope=TP_SCOPE_PARENT_TF_FULL, profiles=profiles)
    assert result.allow_parent_tf_full_exit is True
    assert result.max_sell_pct_allowed == Decimal("100")


def test_parent_tf_full_allowed_ignores_reserve_for_max_sell() -> None:
    # Even with 80% reserve, if parent TF full exit is allowed → 100%
    profiles = {"p": _profile(default_reserve="80", allow_parent_tf_full_exit=True)}
    result = _resolve("p", "CHIP", tp_scope=TP_SCOPE_PARENT_TF_FULL, profiles=profiles)
    assert result.max_sell_pct_allowed == Decimal("100")
    assert result.max_short_swing_sell_pct == Decimal("20")


# ---------------------------------------------------------------------------
# Task example: CHIP=80, NEAR=50, HYPE=30 with account default=50
# ---------------------------------------------------------------------------

def test_task_example_chip() -> None:
    from src.account.long_reserve_policy_v1 import RESEARCH_PROFILES
    result = _resolve("joost", "CHIP",
                      tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
                      profiles=RESEARCH_PROFILES)
    assert result.reserve_source == RESERVE_SOURCE_ASSET_OVERRIDE
    assert result.active_long_reserve_pct == Decimal("80")
    assert result.max_short_swing_sell_pct == Decimal("20")
    assert result.max_sell_pct_allowed == Decimal("20")


def test_task_example_near() -> None:
    from src.account.long_reserve_policy_v1 import RESEARCH_PROFILES
    result = _resolve("joost", "NEAR",
                      tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
                      profiles=RESEARCH_PROFILES)
    assert result.reserve_source == RESERVE_SOURCE_ASSET_OVERRIDE
    assert result.active_long_reserve_pct == Decimal("50")
    assert result.max_short_swing_sell_pct == Decimal("50")
    assert result.max_sell_pct_allowed == Decimal("50")


def test_task_example_hype() -> None:
    from src.account.long_reserve_policy_v1 import RESEARCH_PROFILES
    result = _resolve("joost", "HYPE",
                      tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
                      profiles=RESEARCH_PROFILES)
    assert result.reserve_source == RESERVE_SOURCE_ASSET_OVERRIDE
    assert result.active_long_reserve_pct == Decimal("30")
    assert result.max_short_swing_sell_pct == Decimal("70")
    assert result.max_sell_pct_allowed == Decimal("70")


def test_task_example_unknown_symbol_uses_default() -> None:
    from src.account.long_reserve_policy_v1 import RESEARCH_PROFILES
    result = _resolve("joost", "XLM",
                      tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
                      profiles=RESEARCH_PROFILES)
    assert result.reserve_source == RESERVE_SOURCE_ACCOUNT_DEFAULT
    assert result.active_long_reserve_pct == Decimal("50")
    assert result.default_long_reserve_pct == Decimal("50")


def test_task_example_joost_no_parent_tf_full_exit() -> None:
    from src.account.long_reserve_policy_v1 import RESEARCH_PROFILES
    result = _resolve("joost", "NEAR",
                      tp_scope=TP_SCOPE_PARENT_TF_FULL,
                      profiles=RESEARCH_PROFILES)
    assert result.allow_parent_tf_full_exit is False
    assert result.max_sell_pct_allowed == Decimal("50")


# ---------------------------------------------------------------------------
# Result fields completeness
# ---------------------------------------------------------------------------

def test_result_has_all_required_fields() -> None:
    result = _resolve("unknown", "NEAR", profiles={})
    required = [
        "account_profile_id", "default_long_reserve_pct",
        "asset_long_reserve_pct", "active_long_reserve_pct",
        "reserve_source", "max_short_swing_sell_pct",
        "allow_parent_tf_full_exit", "tp_scope", "max_sell_pct_allowed",
    ]
    for f in required:
        assert hasattr(result, f), f"Missing field: {f}"


def test_result_policy_name_and_version_present() -> None:
    result = _resolve("unknown", "NEAR", profiles={})
    assert result.policy_name == "long_reserve_policy_v1"
    assert result.policy_version


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

def test_profile_rejects_reserve_above_100() -> None:
    with pytest.raises(ValueError, match="must be in"):
        _profile(default_reserve="101")


def test_profile_rejects_negative_reserve() -> None:
    with pytest.raises(ValueError, match="must be in"):
        _profile(default_reserve="-1")


def test_profile_rejects_override_above_100() -> None:
    with pytest.raises(ValueError, match="must be in"):
        _profile(overrides={"SOL": "105"})


def test_resolve_rejects_invalid_tp_scope() -> None:
    with pytest.raises(ValueError, match="Invalid tp_scope"):
        _resolve("joost", "NEAR", tp_scope="INVALID_SCOPE", profiles={})


def test_resolve_rejects_empty_tp_scope() -> None:
    with pytest.raises(ValueError, match="Invalid tp_scope"):
        _resolve("joost", "NEAR", tp_scope="", profiles={})


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_zero_reserve_pct_allowed() -> None:
    profiles = {"p": _profile(default_reserve="0")}
    result = _resolve("p", "SOL", profiles=profiles)
    assert result.active_long_reserve_pct == Decimal("0")
    assert result.max_short_swing_sell_pct == Decimal("100")
    assert result.max_sell_pct_allowed == Decimal("100")


def test_100_reserve_pct_allowed() -> None:
    profiles = {"p": _profile(default_reserve="100")}
    result = _resolve("p", "SOL", profiles=profiles)
    assert result.active_long_reserve_pct == Decimal("100")
    assert result.max_short_swing_sell_pct == Decimal("0")
    assert result.max_sell_pct_allowed == Decimal("0")


def test_policy_input_dataclass_used_directly() -> None:
    inp = LongReservePolicyInput(
        account_profile_id="joost",
        symbol="NEAR",
        tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
    )
    result = resolve_long_reserve_policy(inp, profiles={})
    assert result.account_profile_id == "joost"
    assert result.symbol == "NEAR"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_resolve_is_deterministic() -> None:
    from src.account.long_reserve_policy_v1 import RESEARCH_PROFILES
    r1 = _resolve("joost", "CHIP", tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
                  profiles=RESEARCH_PROFILES)
    r2 = _resolve("joost", "CHIP", tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
                  profiles=RESEARCH_PROFILES)
    assert r1 == r2
