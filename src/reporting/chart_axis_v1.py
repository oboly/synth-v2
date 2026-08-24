from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class NiceAxis:
    """A deterministic human-readable y-axis domain and tick set.

    ``domain_min``/``domain_max`` always contain every value the caller
    passed in via ``raw_min``/``raw_max`` -- this only rounds the domain
    outward to nice boundaries, it never narrows it. ``ticks`` is sorted
    ascending and always includes 0 whenever the domain spans zero.
    """

    domain_min: float
    domain_max: float
    ticks: tuple[float, ...]
    step: float


def _nice_number(value: float, round_result: bool) -> float:
    """Standard "nice numbers" step: 1, 2, 5, or 10 times a power of ten."""
    if value <= 0:
        return 0.0
    exponent = math.floor(math.log10(value))
    fraction = value / (10.0 ** exponent)
    if round_result:
        if fraction < 1.5:
            nice_fraction = 1.0
        elif fraction < 3.0:
            nice_fraction = 2.0
        elif fraction < 7.0:
            nice_fraction = 5.0
        else:
            nice_fraction = 10.0
    else:
        if fraction <= 1.0:
            nice_fraction = 1.0
        elif fraction <= 2.0:
            nice_fraction = 2.0
        elif fraction <= 5.0:
            nice_fraction = 5.0
        else:
            nice_fraction = 10.0
    return nice_fraction * (10.0 ** exponent)


def nice_domain_and_ticks(
    raw_min: float, raw_max: float, *, target_ticks: int = 5
) -> NiceAxis:
    """Derive a deterministic, human-readable domain and tick set.

    ``raw_min``/``raw_max`` describe the span that must be visible (the
    caller is responsible for folding in a zero reference beforehand if
    zero must be represented). The result always contains
    [raw_min, raw_max], rounds outward to "nice" boundaries, and produces
    identical output for identical input -- no wall-clock or random state
    is involved.
    """
    if raw_min > raw_max:
        raw_min, raw_max = raw_max, raw_min
    span = raw_max - raw_min
    if span <= 0.0:
        # Degenerate: a single point, or every visible value is identical.
        magnitude = max(abs(raw_min), abs(raw_max), 1.0)
        pad = magnitude * 0.1
        raw_min -= pad
        raw_max += pad
        span = raw_max - raw_min
    nice_span = _nice_number(span, False)
    step = _nice_number(nice_span / max(target_ticks - 1, 1), True)
    if step <= 0.0:
        step = 1.0
    domain_min = math.floor(raw_min / step) * step
    domain_max = math.ceil(raw_max / step) * step
    tick_count = round((domain_max - domain_min) / step)
    ticks = tuple(round(domain_min + index * step, 10) for index in range(tick_count + 1))
    return NiceAxis(domain_min=domain_min, domain_max=domain_max, ticks=ticks, step=step)


def decimal_places_for_step(step: float) -> int:
    """Decimal digits needed to render a "nice" step (1/2/5/10 * 10^n)
    without collapsing distinct ticks onto the same label. Exact for every
    step ``nice_domain_and_ticks`` can produce, since each is of that form."""
    if step <= 0 or step >= 1.0:
        return 0
    return max(0, -math.floor(math.log10(step)))


def format_tick_label(value: float, *, decimals: int | None = None) -> str:
    """Deterministic tick label. ``decimals`` should be
    ``decimal_places_for_step(axis.step)`` so ticks spaced closer than 0.01
    (e.g. a sub-cent-wide visible window) still render as distinct values
    instead of all collapsing to the same rounded text. Without ``decimals``,
    falls back to whole numbers / trimmed-to-2-decimals for standalone use."""
    value = 0.0 if abs(value) < 1e-9 else value
    if value == 0.0:
        return "0"
    if decimals is not None:
        return f"{value:+.{decimals}f}" if decimals > 0 else f"{value:+.0f}"
    text = f"{value:+.2f}"
    if text.endswith("00"):
        text = text[:-3]
    elif text.endswith("0"):
        text = text[:-1]
    return text
