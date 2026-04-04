"""
SYNTH v2
Module: synth_sleeves.allocator
Purpose:
    Convert proposals into approved sleeve targets with overlap and priority policy.
Boundary:
    - No DB I/O
    - No exchange I/O
    - Deterministic ranking and capping
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_DOWN

from src.synth_sleeves.models import ApprovedTarget, AgentProposal, DecisionAction, SleeveCode, SleeveConfig


DECIMAL_ZERO = Decimal("0")
Q8 = Decimal("0.00000001")

SLEEVE_PRIORITY = {
    SleeveCode.CORE: 1,
    SleeveCode.SWING: 2,
    SleeveCode.TACTICAL: 3,
    SleeveCode.EXPERIMENTAL: 4,
}

MAX_SLEEVES_PER_ASSET = 2
STRUCTURAL_SLEEVES = {SleeveCode.CORE, SleeveCode.SWING}


def _q(value: Decimal) -> Decimal:
    return value.quantize(Q8, rounding=ROUND_DOWN)


def _strength_from_action(action: DecisionAction) -> str:
    if action == DecisionAction.PREPARE:
        return "MEDIUM"
    if action in {DecisionAction.ENTER_LONG, DecisionAction.SCALP_ONLY}:
        return "HIGH"
    if action in {DecisionAction.REDUCE, DecisionAction.EXIT, DecisionAction.BLOCK}:
        return "HIGH"
    return "LOW"


def _proposal_sort_key(item: AgentProposal) -> tuple:
    action_rank = {
        DecisionAction.ENTER_LONG: 1,
        DecisionAction.PREPARE: 2,
        DecisionAction.SCALP_ONLY: 3,
        DecisionAction.HOLD: 4,
        DecisionAction.WATCH: 5,
    }.get(item.desired_action, 99)

    sleeve_rank = SLEEVE_PRIORITY[item.sleeve_code]
    return (action_rank, sleeve_rank, -item.score, item.asset_id)


def allocate_targets(
    proposals: list[AgentProposal],
    sleeve_config: dict[SleeveCode, SleeveConfig],
) -> list[ApprovedTarget]:
    approved: list[ApprovedTarget] = []

    used_budget_by_sleeve: dict[SleeveCode, Decimal] = defaultdict(lambda: DECIMAL_ZERO)
    used_positions_by_sleeve: dict[SleeveCode, int] = defaultdict(int)
    used_prepare_positions_by_sleeve: dict[SleeveCode, int] = defaultdict(int)

    approved_sleeves_by_asset: dict[int, list[SleeveCode]] = defaultdict(list)

    ranked = sorted(proposals, key=_proposal_sort_key)

    for item in ranked:
        cfg = sleeve_config[item.sleeve_code]

        if item.desired_action not in cfg.allowed_actions:
            continue

        if used_positions_by_sleeve[item.sleeve_code] >= cfg.max_positions:
            continue

        existing_sleeves = approved_sleeves_by_asset[item.asset_id]

        # No duplicate sleeve on same asset.
        if item.sleeve_code in existing_sleeves:
            continue

        # Cap sleeves per asset.
        if len(existing_sleeves) >= MAX_SLEEVES_PER_ASSET:
            continue

        # Experimental may not piggyback on existing structural exposure.
        if item.sleeve_code == SleeveCode.EXPERIMENTAL:
            if any(s in STRUCTURAL_SLEEVES for s in existing_sleeves):
                continue

        # Tactical should not overlap with existing structural exposure on same asset.
        if item.sleeve_code == SleeveCode.TACTICAL:
            if any(s in STRUCTURAL_SLEEVES for s in existing_sleeves):
                continue

        raw_target = min(item.requested_fraction, cfg.per_position_cap)

        if item.desired_action == DecisionAction.PREPARE:
            if not cfg.prepare_enabled:
                continue
            if used_prepare_positions_by_sleeve[item.sleeve_code] >= cfg.prepare_max_positions:
                continue
            raw_target = min(raw_target, cfg.prepare_cap)

        remaining_budget = cfg.wallet_share - used_budget_by_sleeve[item.sleeve_code]
        if remaining_budget <= DECIMAL_ZERO:
            continue

        target_fraction = _q(min(raw_target, remaining_budget))
        if target_fraction <= DECIMAL_ZERO:
            continue

        approved.append(
            ApprovedTarget(
                run_ts_utc=item.run_ts_utc,
                asset_id=item.asset_id,
                symbol=item.symbol,
                sleeve_code=item.sleeve_code,
                strategy_name=item.strategy_name,
                desired_action=item.desired_action,
                target_fraction=target_fraction,
                decision_strength=_strength_from_action(item.desired_action),
                source_state=item.source_state,
                reasoning=item.reasoning,
                latest_price_eur=item.latest_price_eur,
            )
        )

        used_budget_by_sleeve[item.sleeve_code] += target_fraction
        used_positions_by_sleeve[item.sleeve_code] += 1
        if item.desired_action == DecisionAction.PREPARE:
            used_prepare_positions_by_sleeve[item.sleeve_code] += 1

        approved_sleeves_by_asset[item.asset_id].append(item.sleeve_code)

    return approved
