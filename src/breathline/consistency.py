from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from src.breathline.models import BreathlineConsistencyRow, BreathlineTokenSnapshotCreate


def _dominance_score(values: list[str]) -> float:
    """
    Returns:
    - 1.00 if all values identical
    - 0.67 if two of three values identical
    - 0.33 if all differ (or weak agreement)
    Works for N runs by returning max_count / N, rounded to 2 decimals.
    """
    if not values:
        return 0.0

    counts = Counter(values)
    max_count = max(counts.values())
    score = max_count / len(values)
    return round(score, 2)


def _classify_token(
    *,
    momentum_values: list[str],
    stability_values: list[str],
    alignment_values: list[str],
    volatility_values: list[str],
    pressure_values: list[str],
    shift_values: list[str],
) -> tuple[str | None, str | None, int, str | None]:
    """
    Initial class = first-pass dominant interpretation.
    Final class   = same for now, unless correction rules trigger.
    Correction    = set only when a deterministic override is applied.
    """
    dominant_momentum = Counter(momentum_values).most_common(1)[0][0]
    dominant_stability = Counter(stability_values).most_common(1)[0][0]
    dominant_alignment = Counter(alignment_values).most_common(1)[0][0]
    dominant_volatility = Counter(volatility_values).most_common(1)[0][0]
    dominant_pressure = Counter(pressure_values).most_common(1)[0][0]
    dominant_shift = Counter(shift_values).most_common(1)[0][0]

    initial_class: str
    final_class: str
    correction_flag = 0
    correction_reason: str | None = None

    if (
        dominant_momentum == "high"
        and dominant_alignment in {"high", "moderate"}
        and dominant_pressure == "up"
        and dominant_shift in {"strengthening", "stable"}
    ):
        initial_class = "LEADER"
    elif (
        dominant_momentum == "low"
        and dominant_alignment == "low"
        and dominant_volatility == "high"
        and dominant_pressure in {"down", "neutral"}
        and dominant_shift == "weakening"
    ):
        initial_class = "WEAK"
    elif (
        dominant_momentum in {"low", "moderate"}
        and dominant_stability == "high"
        and dominant_alignment == "high"
        and dominant_pressure == "neutral"
        and dominant_shift == "stable"
    ):
        initial_class = "ANCHOR"
    elif (
        _dominance_score(momentum_values) < 1.0
        or _dominance_score(stability_values) < 1.0
        or _dominance_score(alignment_values) < 1.0
        or _dominance_score(pressure_values) < 1.0
        or _dominance_score(shift_values) < 1.0
    ):
        initial_class = "DRIFT"
    else:
        initial_class = "MID"

    final_class = initial_class

    # deterministic correction rules
    if initial_class == "LEADER" and (
        dominant_momentum == "low"
        or dominant_alignment == "low"
        or dominant_pressure == "down"
        or dominant_shift == "weakening"
    ):
        final_class = "WEAK"
        correction_flag = 1
        correction_reason = "leader_conflicted_by_low_alignment_or_negative_pressure"

    if initial_class == "ANCHOR" and (
        dominant_volatility == "high" or dominant_shift == "weakening"
    ):
        final_class = "WEAK"
        correction_flag = 1
        correction_reason = "anchor_conflicted_by_high_volatility_or_weakening_shift"

    return initial_class, final_class, correction_flag, correction_reason


def build_consistency_rows(
    *,
    prediction_ts_utc: datetime,
    snapshots: list[BreathlineTokenSnapshotCreate],
) -> list[BreathlineConsistencyRow]:
    grouped: dict[int, list[BreathlineTokenSnapshotCreate]] = defaultdict(list)
    for snapshot in snapshots:
        grouped[snapshot.asset_id].append(snapshot)

    out: list[BreathlineConsistencyRow] = []

    for asset_id, rows in grouped.items():
        momentum_values = [row.momentum for row in rows]
        stability_values = [row.stability for row in rows]
        alignment_values = [row.alignment for row in rows]
        volatility_values = [row.volatility for row in rows]
        pressure_values = [row.pressure for row in rows]
        shift_values = [row.shift for row in rows]

        momentum_consistency = _dominance_score(momentum_values)
        stability_consistency = _dominance_score(stability_values)
        alignment_consistency = _dominance_score(alignment_values)
        volatility_consistency = _dominance_score(volatility_values)
        pressure_consistency = _dominance_score(pressure_values)
        shift_consistency = _dominance_score(shift_values)

        token_consistency_score = round(
            (
                momentum_consistency
                + stability_consistency
                + alignment_consistency
                + volatility_consistency
                + pressure_consistency
                + shift_consistency
            )
            / 6.0,
            2,
        )

        initial_class, final_class, correction_flag, correction_reason = _classify_token(
            momentum_values=momentum_values,
            stability_values=stability_values,
            alignment_values=alignment_values,
            volatility_values=volatility_values,
            pressure_values=pressure_values,
            shift_values=shift_values,
        )

        out.append(
            BreathlineConsistencyRow(
                prediction_ts_utc=prediction_ts_utc,
                asset_id=asset_id,
                run_count=len(rows),
                momentum_consistency=momentum_consistency,
                stability_consistency=stability_consistency,
                alignment_consistency=alignment_consistency,
                volatility_consistency=volatility_consistency,
                pressure_consistency=pressure_consistency,
                shift_consistency=shift_consistency,
                token_consistency_score=token_consistency_score,
                aplus_initial_class=initial_class,
                aplus_final_class=final_class,
                aplus_correction_flag=correction_flag,
                aplus_correction_reason=correction_reason,
            )
        )

    out.sort(key=lambda row: (row.asset_id,))
    return out
