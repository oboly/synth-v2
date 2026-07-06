from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

RETRACE_LEVELS: tuple[tuple[str, Decimal, str], ...] = (
    ("retrace_0_382", Decimal("0.382"), "FIRST_TOUCH"),
    ("retrace_0_500", Decimal("0.500"), "MAIN_REBUY"),
    ("retrace_0_618", Decimal("0.618"), "DEEP_REBUY"),
    ("retrace_0_786", Decimal("0.786"), "PANIC_RESET"),
)


@dataclass(frozen=True)
class HtfReentryInput:
    symbol: str
    interval_code: str
    swing_low: Decimal
    swing_high: Decimal
    current_price: Decimal
    recent_low_price: Decimal | None = None
    prior_support_price: Decimal | None = None
    prior_breakout_price: Decimal | None = None


@dataclass(frozen=True)
class RetraceLevelRow:
    label: str
    fib_level: Decimal
    price: Decimal
    role: str
    distance_to_current_pct: Decimal | None
    distance_to_recent_low_pct: Decimal | None
    recently_touched: bool


@dataclass(frozen=True)
class FibRetraceLadder:
    symbol: str
    interval_code: str
    swing_low: Decimal
    swing_high: Decimal
    leg_size: Decimal
    current_price: Decimal
    levels: tuple[RetraceLevelRow, ...]
    deepest_touched_label: str | None
    missed_main_rebuy_by_pct: Decimal | None


def build_fib_retrace_ladder(inp: HtfReentryInput) -> FibRetraceLadder:
    if inp.swing_high <= inp.swing_low:
        raise ValueError(
            f"swing_high must be greater than swing_low: {inp.swing_high} <= {inp.swing_low}"
        )
    if inp.current_price <= Decimal("0"):
        raise ValueError(f"current_price must be positive: {inp.current_price}")

    leg = inp.swing_high - inp.swing_low
    rows: list[RetraceLevelRow] = []

    for label, fib_level, role in RETRACE_LEVELS:
        price = inp.swing_high - leg * fib_level

        distance_to_current_pct: Decimal | None = None
        if inp.current_price > Decimal("0"):
            distance_to_current_pct = (
                (price - inp.current_price) / inp.current_price * Decimal("100")
            )

        distance_to_recent_low_pct: Decimal | None = None
        if inp.recent_low_price is not None and inp.recent_low_price > Decimal("0"):
            distance_to_recent_low_pct = (
                (price - inp.recent_low_price) / inp.recent_low_price * Decimal("100")
            )

        recently_touched = (
            inp.recent_low_price is not None and inp.recent_low_price <= price
        )

        rows.append(
            RetraceLevelRow(
                label=label,
                fib_level=fib_level,
                price=price,
                role=role,
                distance_to_current_pct=distance_to_current_pct,
                distance_to_recent_low_pct=distance_to_recent_low_pct,
                recently_touched=recently_touched,
            )
        )

    # deepest_touched_label: the lowest-price level (deepest retrace) where recently_touched is True
    deepest_touched_label: str | None = None
    for row in reversed(rows):
        if row.recently_touched:
            deepest_touched_label = row.label
            break

    # missed_main_rebuy_by_pct: how far above r500 did price stop? Only when recent_low > r500.
    missed_main_rebuy_by_pct: Decimal | None = None
    if inp.recent_low_price is not None:
        r500_price = next(r.price for r in rows if r.label == "retrace_0_500")
        if r500_price > Decimal("0") and inp.recent_low_price > r500_price:
            missed_main_rebuy_by_pct = (
                (inp.recent_low_price - r500_price) / r500_price * Decimal("100")
            )

    return FibRetraceLadder(
        symbol=inp.symbol,
        interval_code=inp.interval_code,
        swing_low=inp.swing_low,
        swing_high=inp.swing_high,
        leg_size=leg,
        current_price=inp.current_price,
        levels=tuple(rows),
        deepest_touched_label=deepest_touched_label,
        missed_main_rebuy_by_pct=missed_main_rebuy_by_pct,
    )
