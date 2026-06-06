"""
Synth v2.6 — Long Reserve Policy v1.

Layer: account-aware policy.

Boundary:
  - Pure computation — no DB access, no broker calls, no orders.
  - Account-aware: reads profile and asset-level settings only.
  - Research/backtest use only. Not wired to live execution.
  - Do not place in selection_engine.
  - Do not create orders.
  - No broker writes.

Purpose:
  Resolve the active long reserve percentage for a given account profile and symbol.
  Derive max_short_swing_sell_pct and max_sell_pct_allowed based on tp_scope and
  allow_parent_tf_full_exit.

Semantics:
  - default_long_reserve_pct is set at the account profile level.
  - asset_long_reserve_pct is an optional per-symbol override.
  - active_long_reserve_pct = asset override if present, else account default.
  - max_short_swing_sell_pct = 100 - active_long_reserve_pct.
  - Child-only short swing TPs may not sell more than max_short_swing_sell_pct.
  - Long reserve must remain open unless parent TF target/completion is reached.
  - Parent TF full exit is only allowed when allow_parent_tf_full_exit=True.
  - If no profile exists for a given account_profile_id, defaults to 50% reserve
    and marks reserve_source=DEFAULT_ASSUMED (research tests only).

Safety markers:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POLICY_NAME = "long_reserve_policy_v1"
POLICY_VERSION = "1.0.0"

RESERVE_SOURCE_ASSET_OVERRIDE = "ASSET_OVERRIDE"
RESERVE_SOURCE_ACCOUNT_DEFAULT = "ACCOUNT_DEFAULT"
RESERVE_SOURCE_DEFAULT_ASSUMED = "DEFAULT_ASSUMED"

TP_SCOPE_CHILD_SHORT_SWING = "CHILD_SHORT_SWING"
TP_SCOPE_PARENT_TF_PARTIAL = "PARENT_TF_PARTIAL"
TP_SCOPE_PARENT_TF_FULL = "PARENT_TF_FULL"

VALID_TP_SCOPES: frozenset[str] = frozenset({
    TP_SCOPE_CHILD_SHORT_SWING,
    TP_SCOPE_PARENT_TF_PARTIAL,
    TP_SCOPE_PARENT_TF_FULL,
})

RESEARCH_DEFAULT_LONG_RESERVE_PCT = Decimal("50")
_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


# ---------------------------------------------------------------------------
# Validation helpers (must precede dataclass definitions)
# ---------------------------------------------------------------------------

def _validate_pct(name: str, value: Decimal) -> None:
    if not (_ZERO <= value <= _HUNDRED):
        raise ValueError(f"{name} must be in [0, 100], got {value}")


def _validate_tp_scope(tp_scope: str) -> None:
    if tp_scope not in VALID_TP_SCOPES:
        raise ValueError(
            f"Invalid tp_scope '{tp_scope}'. Valid: {sorted(VALID_TP_SCOPES)}"
        )


# ---------------------------------------------------------------------------
# Profile dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AccountLongReserveProfile:
    """
    Account-level reserve policy configuration.

    asset_overrides: symbol → override long_reserve_pct.
    Overrides are applied per-symbol; all other symbols use default_long_reserve_pct.
    """
    account_profile_id: str
    default_long_reserve_pct: Decimal
    allow_parent_tf_full_exit: bool
    asset_overrides: dict[str, Decimal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_pct("default_long_reserve_pct", self.default_long_reserve_pct)
        for sym, pct in self.asset_overrides.items():
            _validate_pct(f"asset_override[{sym}]", pct)


@dataclass(frozen=True)
class LongReservePolicyInput:
    account_profile_id: str
    symbol: str
    tp_scope: str


@dataclass(frozen=True)
class LongReservePolicyResult:
    policy_name: str
    policy_version: str
    account_profile_id: str
    symbol: str
    tp_scope: str
    default_long_reserve_pct: Decimal
    asset_long_reserve_pct: Optional[Decimal]
    active_long_reserve_pct: Decimal
    reserve_source: str
    max_short_swing_sell_pct: Decimal
    allow_parent_tf_full_exit: bool
    max_sell_pct_allowed: Decimal


# ---------------------------------------------------------------------------
# Pre-configured research profiles
# ---------------------------------------------------------------------------

RESEARCH_PROFILES: dict[str, AccountLongReserveProfile] = {
    "joost": AccountLongReserveProfile(
        account_profile_id="joost",
        default_long_reserve_pct=Decimal("50"),
        allow_parent_tf_full_exit=False,
        asset_overrides={
            "CHIP": Decimal("80"),
            "NEAR": Decimal("50"),
            "HYPE": Decimal("30"),
        },
    ),
}


# ---------------------------------------------------------------------------
# Core resolver
# ---------------------------------------------------------------------------

def resolve_long_reserve_policy(
    policy_input: LongReservePolicyInput,
    *,
    profiles: Optional[dict[str, AccountLongReserveProfile]] = None,
) -> LongReservePolicyResult:
    """
    Resolve active long reserve policy for a given account profile and symbol.

    Priority:
      1. Asset-level override in profile (reserve_source=ASSET_OVERRIDE)
      2. Account default in profile (reserve_source=ACCOUNT_DEFAULT)
      3. Research fallback of 50% (reserve_source=DEFAULT_ASSUMED)

    tp_scope drives max_sell_pct_allowed:
      CHILD_SHORT_SWING   → max_short_swing_sell_pct (reserve always applies)
      PARENT_TF_PARTIAL   → max_short_swing_sell_pct (reserve always applies)
      PARENT_TF_FULL      → 100 if allow_parent_tf_full_exit else max_short_swing_sell_pct
    """
    _validate_tp_scope(policy_input.tp_scope)

    profile_registry = profiles if profiles is not None else RESEARCH_PROFILES
    profile = profile_registry.get(policy_input.account_profile_id)

    if profile is None:
        # Research-only fallback — no live profile configured
        default_reserve = RESEARCH_DEFAULT_LONG_RESERVE_PCT
        asset_override: Optional[Decimal] = None
        active_reserve = default_reserve
        reserve_source = RESERVE_SOURCE_DEFAULT_ASSUMED
        allow_parent_tf_full_exit = False
    else:
        default_reserve = profile.default_long_reserve_pct
        asset_override = profile.asset_overrides.get(policy_input.symbol)
        allow_parent_tf_full_exit = profile.allow_parent_tf_full_exit

        if asset_override is not None:
            active_reserve = asset_override
            reserve_source = RESERVE_SOURCE_ASSET_OVERRIDE
        else:
            active_reserve = default_reserve
            reserve_source = RESERVE_SOURCE_ACCOUNT_DEFAULT

    max_short_swing_sell_pct = _HUNDRED - active_reserve

    if (
        policy_input.tp_scope == TP_SCOPE_PARENT_TF_FULL
        and allow_parent_tf_full_exit
    ):
        max_sell_pct_allowed = _HUNDRED
    else:
        max_sell_pct_allowed = max_short_swing_sell_pct

    return LongReservePolicyResult(
        policy_name=POLICY_NAME,
        policy_version=POLICY_VERSION,
        account_profile_id=policy_input.account_profile_id,
        symbol=policy_input.symbol,
        tp_scope=policy_input.tp_scope,
        default_long_reserve_pct=default_reserve,
        asset_long_reserve_pct=asset_override,
        active_long_reserve_pct=active_reserve,
        reserve_source=reserve_source,
        max_short_swing_sell_pct=max_short_swing_sell_pct,
        allow_parent_tf_full_exit=allow_parent_tf_full_exit,
        max_sell_pct_allowed=max_sell_pct_allowed,
    )


def resolve_from_parts(
    *,
    account_profile_id: str,
    symbol: str,
    tp_scope: str,
    profiles: Optional[dict[str, AccountLongReserveProfile]] = None,
) -> LongReservePolicyResult:
    """Convenience wrapper — constructs LongReservePolicyInput and resolves."""
    return resolve_long_reserve_policy(
        LongReservePolicyInput(
            account_profile_id=account_profile_id,
            symbol=symbol,
            tp_scope=tp_scope,
        ),
        profiles=profiles,
    )
