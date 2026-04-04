"""
SYNTH v2
Module: synth_sleeves.transition_logger
Purpose:
    Derive and persist daily transition counts from current targets vs open lots.
Boundary:
    - Stateless derivation
    - Aggregated daily upsert only
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from src.synth_sleeves.models import ApprovedTarget, DecisionAction, OpenLot, SleeveCode


def _target_state_name(action: DecisionAction) -> str:
    if action == DecisionAction.PREPARE:
        return "PREPARE"
    if action == DecisionAction.ENTER_LONG:
        return "ENTER_LONG"
    if action == DecisionAction.SCALP_ONLY:
        return "SCALP_ONLY"
    if action == DecisionAction.WATCH:
        return "WATCH"
    if action in {DecisionAction.AVOID, DecisionAction.BLOCK}:
        return "BLOCK"
    if action == DecisionAction.EXIT:
        return "EXIT"
    if action == DecisionAction.REDUCE:
        return "REDUCE"
    if action == DecisionAction.HOLD:
        return "HOLD"
    return action.value


def build_transition_rows(
    *,
    run_ts_utc: datetime,
    targets: list[ApprovedTarget],
    open_lots: list[OpenLot],
) -> list[dict]:
    metric_date_utc = run_ts_utc.date()

    current_state_by_key: dict[tuple[int, SleeveCode], str] = {}
    for lot in open_lots:
        key = (lot.asset_id, lot.sleeve_code)
        current_state = lot.entry_state.value if hasattr(lot.entry_state, "value") else str(lot.entry_state)
        current_state_by_key[key] = current_state

    grouped: dict[tuple[str, str, str, str], int] = defaultdict(int)

    for target in targets:
        key = (target.asset_id, target.sleeve_code)
        from_state = current_state_by_key.get(key, "WATCH")
        to_state = _target_state_name(target.desired_action)

        if from_state == to_state:
            continue

        grouped[(target.sleeve_code.value, target.strategy_name, from_state, to_state)] += 1

    rows: list[dict] = []
    for (sleeve_code, strategy_name, from_state, to_state), transition_count in grouped.items():
        rows.append(
            {
                "metric_date_utc": metric_date_utc,
                "sleeve_code": sleeve_code,
                "strategy_name": strategy_name,
                "from_state": from_state,
                "to_state": to_state,
                "transition_count": transition_count,
                "avg_forward_return_24h_pct": 0,
                "avg_forward_return_72h_pct": 0,
            }
        )

    return rows
