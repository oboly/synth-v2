from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


EXTENSION_LEVELS: tuple[tuple[str, Decimal], ...] = (
    ("ext_1_272", Decimal("1.272")),
    ("ext_1_618", Decimal("1.618")),
    ("ext_2_000", Decimal("2.000")),
)

DEFAULT_ROUND_STEP: Decimal = Decimal("1")
DEFAULT_ROUND_THRESHOLD_FRAC: Decimal = Decimal("0.02")
DEFAULT_RESISTANCE_PROXIMITY_PCT: Decimal = Decimal("2")
DEFAULT_GATE_RETEST_PROXIMITY_PCT: Decimal = Decimal("2")


@dataclass(frozen=True)
class HtfSwingInput:
    symbol: str
    interval_code: str
    swing_low: Decimal
    swing_high: Decimal   # previous structural peak; serves as breakout_gate
    current_price: Decimal
    prior_high_price: Decimal | None = None  # structural resistance / prior HTF high


@dataclass(frozen=True)
class FibExtensionTarget:
    label: str             # "ext_1_272" | "ext_1_618" | "ext_2_000"
    fib_level: Decimal
    price: Decimal
    pct_above_swing_high: Decimal    # % above the breakout gate
    distance_to_current_pct: Decimal # % distance from current price (positive = above)
    round_number_confluence: bool
    prior_high_confluence: bool      # price lands within resistance_proximity_pct of prior_high


@dataclass(frozen=True)
class HtfExtensionConfluenceMap:
    symbol: str
    interval_code: str
    swing_low: Decimal
    swing_high: Decimal
    breakout_gate: Decimal           # == swing_high; exposed separately for readability
    leg_size: Decimal
    current_price: Decimal
    targets: tuple[FibExtensionTarget, ...]
    price_band: str                  # descriptive band label for current price position
    ext_1_272_touched_and_rejected: bool
    retesting_breakout_gate: bool    # near breakout_gate after prior extension touch


def _quant_price(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0000000001"))


def _quant_pct(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"))


def _extension_price(swing_low: Decimal, swing_high: Decimal, fib_level: Decimal) -> Decimal:
    leg = swing_high - swing_low
    return _quant_price(swing_low + leg * fib_level)


def _pct_above(price: Decimal, reference: Decimal) -> Decimal:
    if reference == 0:
        return Decimal("0")
    return _quant_pct((price - reference) / reference * Decimal("100"))


def _distance_to_current_pct(target_price: Decimal, current_price: Decimal) -> Decimal:
    if current_price == 0:
        return Decimal("0")
    return _quant_pct((target_price - current_price) / current_price * Decimal("100"))


def _is_round_number(
    price: Decimal,
    round_step: Decimal,
    threshold_frac: Decimal,
) -> bool:
    if round_step <= 0:
        return False
    remainder = price % round_step
    fraction = remainder / round_step
    return fraction <= threshold_frac or fraction >= (Decimal("1") - threshold_frac)


def _is_near_resistance(
    price: Decimal,
    resistance: Decimal | None,
    proximity_pct: Decimal,
) -> bool:
    if resistance is None or resistance <= 0:
        return False
    dist_pct = abs(price - resistance) / resistance * Decimal("100")
    return dist_pct <= proximity_pct


def _price_band(
    current_price: Decimal,
    swing_high: Decimal,
    targets: tuple[FibExtensionTarget, ...],
) -> str:
    by_level: dict[str, Decimal] = {t.label: t.price for t in targets}
    ext_1_272 = by_level.get("ext_1_272")
    ext_1_618 = by_level.get("ext_1_618")
    ext_2_000 = by_level.get("ext_2_000")

    if current_price < swing_high:
        return "BELOW_BREAKOUT_GATE"
    if ext_1_272 is not None and current_price < ext_1_272:
        return "ABOVE_GATE_APPROACHING_1272"
    if ext_1_618 is not None and current_price < ext_1_618:
        return "BETWEEN_1272_1618"
    if ext_2_000 is not None and current_price < ext_2_000:
        return "BETWEEN_1618_2000"
    return "ABOVE_2000"


def build_htf_extension_map(
    anchor: HtfSwingInput,
    *,
    round_step: Decimal = DEFAULT_ROUND_STEP,
    round_threshold_frac: Decimal = DEFAULT_ROUND_THRESHOLD_FRAC,
    resistance_proximity_pct: Decimal = DEFAULT_RESISTANCE_PROXIMITY_PCT,
    gate_retest_proximity_pct: Decimal = DEFAULT_GATE_RETEST_PROXIMITY_PCT,
) -> HtfExtensionConfluenceMap:
    if anchor.swing_low >= anchor.swing_high:
        raise ValueError(
            f"swing_low ({anchor.swing_low}) must be less than swing_high ({anchor.swing_high})"
        )
    if anchor.current_price <= 0:
        raise ValueError(f"current_price must be positive, got {anchor.current_price}")
    if anchor.swing_low <= 0:
        raise ValueError(f"swing_low must be positive, got {anchor.swing_low}")

    leg = _quant_price(anchor.swing_high - anchor.swing_low)
    targets_list: list[FibExtensionTarget] = []
    ext_1_272_price: Decimal | None = None

    for label, fib_level in EXTENSION_LEVELS:
        ext_price = _extension_price(anchor.swing_low, anchor.swing_high, fib_level)
        if label == "ext_1_272":
            ext_1_272_price = ext_price
        targets_list.append(
            FibExtensionTarget(
                label=label,
                fib_level=fib_level,
                price=ext_price,
                pct_above_swing_high=_pct_above(ext_price, anchor.swing_high),
                distance_to_current_pct=_distance_to_current_pct(ext_price, anchor.current_price),
                round_number_confluence=_is_round_number(ext_price, round_step, round_threshold_frac),
                prior_high_confluence=_is_near_resistance(
                    ext_price, anchor.prior_high_price, resistance_proximity_pct
                ),
            )
        )

    targets = tuple(targets_list)

    ext_1_272_touched_and_rejected = bool(
        ext_1_272_price is not None
        and anchor.prior_high_price is not None
        and anchor.prior_high_price >= ext_1_272_price
        and anchor.current_price < ext_1_272_price
    )

    gate_dist_pct = (
        abs(anchor.current_price - anchor.swing_high) / anchor.swing_high * Decimal("100")
    )
    retesting_breakout_gate = bool(
        gate_dist_pct <= gate_retest_proximity_pct
        and ext_1_272_price is not None
        and anchor.prior_high_price is not None
        and anchor.prior_high_price >= ext_1_272_price
    )

    return HtfExtensionConfluenceMap(
        symbol=anchor.symbol,
        interval_code=anchor.interval_code,
        swing_low=anchor.swing_low,
        swing_high=anchor.swing_high,
        breakout_gate=anchor.swing_high,
        leg_size=leg,
        current_price=anchor.current_price,
        targets=targets,
        price_band=_price_band(anchor.current_price, anchor.swing_high, targets),
        ext_1_272_touched_and_rejected=ext_1_272_touched_and_rejected,
        retesting_breakout_gate=retesting_breakout_gate,
    )
