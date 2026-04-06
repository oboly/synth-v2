from __future__ import annotations

from datetime import datetime, UTC
from decimal import Decimal

from src.market_structure.models import ExecutionPlan


def choose_execution_mode(sleeve_code: str) -> str:
    if sleeve_code == "CORE":
        return "SPREAD_CAPTURE_PASSIVE"
    if sleeve_code == "SWING":
        return "PASSIVE_SMART_REPRICE"
    if sleeve_code == "TACTICAL":
        return "URGENT_LIMIT"
    return "CONFIGURABLE"


def build_execution_plan(
    asset_id: int,
    sleeve_code: str,
    desired_action: str,
    target_fraction: Decimal,
    reference_price_eur: Decimal | None,
) -> ExecutionPlan:
    passive_price = reference_price_eur
    urgent_price = reference_price_eur

    return ExecutionPlan(
        asset_id=asset_id,
        sleeve_code=sleeve_code,
        desired_action=desired_action,
        plan_ts_utc=datetime.now(UTC).replace(tzinfo=None),
        execution_mode=choose_execution_mode(sleeve_code),
        target_fraction=target_fraction,
        reference_price_eur=reference_price_eur,
        passive_price_eur=passive_price,
        urgent_limit_price_eur=urgent_price,
        max_reprices=25 if sleeve_code == "CORE" else 12,
        max_wait_seconds=3600 if sleeve_code == "CORE" else 900,
        max_chase_bps=Decimal("10"),
        min_spread_bps_for_capture=Decimal("3"),
        escalation_to_urgent_limit=True,
        abort_if_signal_invalidates=True,
        plan_state="IDLE",
        notes="Skeleton execution plan",
    )
