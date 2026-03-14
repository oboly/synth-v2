from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True)
class PredictionFactorSeed:
    factor_type: str
    factor_name: str
    factor_value_text: str | None = None
    factor_value_num: Decimal | None = None
    factor_score: Decimal | None = None
    factor_weight: Decimal | None = None
    notes: str | None = None


def map_aplus_signal_to_prediction_factors(
    *,
    phase_label: str | None,
    direction_label: str | None,
    confidence_score: Decimal | None,
    target_price: Decimal | None,
    target_currency: str | None,
) -> list[PredictionFactorSeed]:
    out: list[PredictionFactorSeed] = []

    if phase_label:
        out.append(
            PredictionFactorSeed(
                factor_type="a_plus",
                factor_name="breathline_phase",
                factor_value_text=phase_label,
                factor_score=confidence_score,
            )
        )

    if direction_label:
        out.append(
            PredictionFactorSeed(
                factor_type="a_plus",
                factor_name="breathline_direction",
                factor_value_text=direction_label,
                factor_score=confidence_score,
            )
        )

    if target_price is not None:
        out.append(
            PredictionFactorSeed(
                factor_type="a_plus",
                factor_name="symbolic_target_price",
                factor_value_num=target_price,
                notes=f"Original A+ target currency={target_currency or 'unknown'}",
            )
        )

    return out
