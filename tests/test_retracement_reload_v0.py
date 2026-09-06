from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.market_data.fib_navigation_map_v1 import FibNavLevel, FibNavigationMap
from src.market_models.retracement_reload_v0 import (
    RetracementReloadV0Error,
    STATE_NORMAL,
    STATE_STRONG,
    STATE_STRUCTURE_BROKEN,
    STATE_VERY_STRONG,
    STATE_WEAKENING,
    build_retracement_reload_v0,
)


def _nav() -> FibNavigationMap:
    labels = (("r_0236", "0.236", "17.640"), ("r_0382", "0.382", "16.180"),
              ("r_0500", "0.500", "15.000"), ("r_0618", "0.618", "13.820"),
              ("r_0786", "0.786", "12.140"))
    return FibNavigationMap(
        anchor_low=Decimal("10"), anchor_high=Decimal("20"), direction="BULLISH",
        leg_size=Decimal("10"), current_price=Decimal("18"),
        retracement_levels=tuple(FibNavLevel(a, Decimal(b), Decimal(c), True) for a, b, c in labels),
        extension_levels=(), map_state="FRESH", rebuild_trigger="NONE", confidence="HIGH",
        anchor_candle_count=20, computed_at_utc=datetime(2026, 9, 6, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (STATE_VERY_STRONG, ("r_0236", "r_0382")),
        (STATE_STRONG, ("r_0382", "r_0500")),
        (STATE_NORMAL, ("r_0500", "r_0618")),
        (STATE_WEAKENING, ("r_0618", "r_0786")),
    ],
)
def test_strength_selects_deterministic_reload_pair(state: str, expected: tuple[str, str]) -> None:
    result = build_retracement_reload_v0(
        source_map_id="map-1", nav=_nav(), continuation_strength_state=state,
        invalidation_price=Decimal("9.5"),
    )
    assert (result.preferred_reload_1_level, result.preferred_reload_2_level) == expected
    assert result.reason_codes == (f"HEURISTIC_V0_{state}",)


def test_structure_broken_emits_no_reload_opportunity() -> None:
    result = build_retracement_reload_v0(
        source_map_id="map-1", nav=_nav(), continuation_strength_state=STATE_STRUCTURE_BROKEN,
        invalidation_price=Decimal("9.5"),
    )
    assert result.reload_quality_state == "NONE"
    assert result.preferred_reload_1_level is None
    assert result.preferred_reload_2_level is None
    assert result.reason_codes == ("STRUCTURE_BROKEN_NO_RELOAD",)


def test_missing_required_canonical_level_fails_closed() -> None:
    nav = _nav()
    broken = FibNavigationMap(**{**nav.__dict__, "retracement_levels": nav.retracement_levels[1:]})
    with pytest.raises(RetracementReloadV0Error, match="REQUIRED_RETRACEMENT_LEVEL_MISSING"):
        build_retracement_reload_v0(
            source_map_id="map-1", nav=broken, continuation_strength_state=STATE_VERY_STRONG,
            invalidation_price=Decimal("9.5"),
        )
