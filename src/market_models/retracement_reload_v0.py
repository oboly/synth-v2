"""Issue #665: market-only Retracement Reload v0 preference overlay.

Consumes canonical FibNavigationMap geometry and prepared continuation strength.
It never reads account state and never creates execution authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from src.market_data.fib_navigation_map_v1 import FibNavigationMap

VERSION: Final[str] = "retracement_reload_v0"
STATE_VERY_STRONG: Final[str] = "VERY_STRONG"
STATE_STRONG: Final[str] = "STRONG"
STATE_NORMAL: Final[str] = "NORMAL"
STATE_WEAKENING: Final[str] = "WEAKENING"
STATE_STRUCTURE_BROKEN: Final[str] = "STRUCTURE_BROKEN"
SUPPORTED_STRENGTH_STATES = frozenset({
    STATE_VERY_STRONG, STATE_STRONG, STATE_NORMAL,
    STATE_WEAKENING, STATE_STRUCTURE_BROKEN,
})

PREFERRED_LEVELS: Final[dict[str, tuple[str, str]]] = {
    STATE_VERY_STRONG: ("r_0236", "r_0382"),
    STATE_STRONG: ("r_0382", "r_0500"),
    STATE_NORMAL: ("r_0500", "r_0618"),
    STATE_WEAKENING: ("r_0618", "r_0786"),
}
QUALITY_BY_STRENGTH: Final[dict[str, str]] = {
    STATE_VERY_STRONG: "HIGH",
    STATE_STRONG: "HIGH",
    STATE_NORMAL: "MEDIUM",
    STATE_WEAKENING: "LOW",
    STATE_STRUCTURE_BROKEN: "NONE",
}


class RetracementReloadV0Error(ValueError):
    """Fail-closed market-model contract error."""


@dataclass(frozen=True)
class RetracementReloadV0:
    reload_map_version: str
    source_map_id: str
    direction: str
    swing_low: Decimal
    swing_high: Decimal
    continuation_strength_state: str
    reload_strength_score: Decimal
    reload_quality_state: str
    preferred_reload_1_level: str | None
    preferred_reload_1_price: Decimal | None
    preferred_reload_2_level: str | None
    preferred_reload_2_price: Decimal | None
    invalidation_price: Decimal | None
    reason_codes: tuple[str, ...]


def _level_price(nav: FibNavigationMap, label: str) -> Decimal:
    for level in nav.retracement_levels:
        if level.label == label:
            return level.price
    raise RetracementReloadV0Error("REQUIRED_RETRACEMENT_LEVEL_MISSING")


def _score(state: str) -> Decimal:
    return {
        STATE_VERY_STRONG: Decimal("0.90"),
        STATE_STRONG: Decimal("0.75"),
        STATE_NORMAL: Decimal("0.55"),
        STATE_WEAKENING: Decimal("0.30"),
        STATE_STRUCTURE_BROKEN: Decimal("0.00"),
    }[state]

def build_retracement_reload_v0(
    *,
    source_map_id: str,
    nav: FibNavigationMap,
    continuation_strength_state: str,
    invalidation_price: Decimal | None,
) -> RetracementReloadV0:
    if not source_map_id.strip():
        raise RetracementReloadV0Error("SOURCE_MAP_ID_REQUIRED")
    if continuation_strength_state not in SUPPORTED_STRENGTH_STATES:
        raise RetracementReloadV0Error("UNSUPPORTED_CONTINUATION_STRENGTH_STATE")
    if nav.anchor_low <= 0 or nav.anchor_high <= nav.anchor_low:
        raise RetracementReloadV0Error("INVALID_SOURCE_IMPULSE_GEOMETRY")
    if invalidation_price is not None and invalidation_price <= 0:
        raise RetracementReloadV0Error("INVALID_INVALIDATION_PRICE")

    if continuation_strength_state == STATE_STRUCTURE_BROKEN:
        return RetracementReloadV0(
            VERSION, source_map_id, nav.direction, nav.anchor_low, nav.anchor_high,
            continuation_strength_state, _score(continuation_strength_state), "NONE",
            None, None, None, None, invalidation_price,
            ("STRUCTURE_BROKEN_NO_RELOAD",),
        )

    first, second = PREFERRED_LEVELS[continuation_strength_state]
    return RetracementReloadV0(
        reload_map_version=VERSION,
        source_map_id=source_map_id,
        direction=nav.direction,
        swing_low=nav.anchor_low,
        swing_high=nav.anchor_high,
        continuation_strength_state=continuation_strength_state,
        reload_strength_score=_score(continuation_strength_state),
        reload_quality_state=QUALITY_BY_STRENGTH[continuation_strength_state],
        preferred_reload_1_level=first,
        preferred_reload_1_price=_level_price(nav, first),
        preferred_reload_2_level=second,
        preferred_reload_2_price=_level_price(nav, second),
        invalidation_price=invalidation_price,
        reason_codes=(f"HEURISTIC_V0_{continuation_strength_state}",),
    )
