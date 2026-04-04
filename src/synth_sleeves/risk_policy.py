"""
SYNTH v2
Module: synth_sleeves.risk_policy
Purpose:
    Apply v1 state/risk clamping for PREPARE and sleeve actions.
Boundary:
    - No DB I/O
    - Stateless
"""

from __future__ import annotations

from decimal import Decimal

from src.synth_sleeves.models import ApprovedTarget, DecisionAction, SleeveCode, SleeveConfig


DECIMAL_ZERO = Decimal("0")


def apply_risk_policy(
    targets: list[ApprovedTarget],
    sleeve_config: dict[SleeveCode, SleeveConfig],
) -> list[ApprovedTarget]:
    result: list[ApprovedTarget] = []

    for target in targets:
        cfg = sleeve_config[target.sleeve_code]
        clamped = target.target_fraction

        if target.desired_action == DecisionAction.PREPARE:
            clamped = min(clamped, cfg.prepare_cap)

        if target.desired_action == DecisionAction.SCALP_ONLY:
            clamped = min(clamped, cfg.per_position_cap)

        if clamped <= DECIMAL_ZERO:
            continue

        result.append(
            ApprovedTarget(
                run_ts_utc=target.run_ts_utc,
                asset_id=target.asset_id,
                symbol=target.symbol,
                sleeve_code=target.sleeve_code,
                strategy_name=target.strategy_name,
                desired_action=target.desired_action,
                target_fraction=clamped,
                decision_strength=target.decision_strength,
                source_state=target.source_state,
                reasoning=target.reasoning,
                latest_price_eur=target.latest_price_eur,
            )
        )

    return result
