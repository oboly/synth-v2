from __future__ import annotations

# broker_private_calls=0  broker_writes=0  order_submission=0
# live_orders=0  decision_gate=none  executor=none

from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.execution_ladder.models import LadderLeg, LadderProfile, SizingRule, SizingVariableRef


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _req_dec(value: Any) -> Decimal:
    if value is None:
        raise ValueError("unexpected NULL for required Decimal column")
    return Decimal(str(value))


def fetch_sizing_variable_refs() -> list[SizingVariableRef]:
    sql = """
        SELECT variable_key, display_label, description, value_unit, allowed_side,
               is_active, display_order
        FROM execution_sizing_variable_ref
        ORDER BY display_order ASC, variable_key ASC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        SizingVariableRef(
            variable_key=str(r["variable_key"]),
            display_label=str(r["display_label"]),
            description=str(r["description"]),
            value_unit=str(r["value_unit"]),
            allowed_side=str(r["allowed_side"]),
            is_active=bool(r["is_active"]),
            display_order=int(r["display_order"]),
        )
        for r in rows
    ]


def fetch_profile(
    trading_account_id: int,
    profile_code: str,
) -> LadderProfile | None:
    sql = """
        SELECT ladder_profile_id, trading_account_id, profile_code, display_label,
               description, side, anchor_type, default_sizing_rule_id,
               is_enabled, current_version
        FROM execution_ladder_profile
        WHERE trading_account_id = %s
          AND profile_code = %s
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [trading_account_id, profile_code])
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    return LadderProfile(
        ladder_profile_id=int(row["ladder_profile_id"]),
        trading_account_id=int(row["trading_account_id"]),
        profile_code=str(row["profile_code"]),
        display_label=str(row["display_label"]),
        description=str(row["description"]),
        side=str(row["side"]),
        anchor_type=str(row["anchor_type"]),
        default_sizing_rule_id=(
            int(row["default_sizing_rule_id"]) if row["default_sizing_rule_id"] is not None else None
        ),
        is_enabled=bool(row["is_enabled"]),
        current_version=int(row["current_version"]),
    )


def fetch_active_legs(
    ladder_profile_id: int,
    profile_version: int,
) -> list[LadderLeg]:
    sql = """
        SELECT ladder_leg_id, ladder_profile_id, profile_version, leg_number,
               price_offset_bps, allocation_bps, order_type, time_in_force, is_enabled
        FROM execution_ladder_leg
        WHERE ladder_profile_id = %s
          AND profile_version = %s
          AND is_enabled = 1
        ORDER BY leg_number ASC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [ladder_profile_id, profile_version])
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        LadderLeg(
            ladder_leg_id=int(r["ladder_leg_id"]),
            ladder_profile_id=int(r["ladder_profile_id"]),
            profile_version=int(r["profile_version"]),
            leg_number=int(r["leg_number"]),
            price_offset_bps=int(r["price_offset_bps"]),
            allocation_bps=int(r["allocation_bps"]),
            order_type=str(r["order_type"]),
            time_in_force=str(r["time_in_force"]),
            is_enabled=bool(r["is_enabled"]),
        )
        for r in rows
    ]


def fetch_sizing_rule(sizing_rule_id: int) -> SizingRule | None:
    sql = """
        SELECT sizing_rule_id, trading_account_id, rule_code, display_label,
               description, rule_type, source_variable_key, multiplier_bps,
               fixed_quote_amount, floor_quote_amount, cap_quote_amount,
               is_enabled, version
        FROM execution_sizing_rule
        WHERE sizing_rule_id = %s
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [sizing_rule_id])
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    return SizingRule(
        sizing_rule_id=int(row["sizing_rule_id"]),
        trading_account_id=int(row["trading_account_id"]),
        rule_code=str(row["rule_code"]),
        display_label=str(row["display_label"]),
        description=str(row["description"]),
        rule_type=str(row["rule_type"]),
        source_variable_key=(
            str(row["source_variable_key"]) if row["source_variable_key"] is not None else None
        ),
        multiplier_bps=(
            int(row["multiplier_bps"]) if row["multiplier_bps"] is not None else None
        ),
        fixed_quote_amount=_dec(row["fixed_quote_amount"]),
        floor_quote_amount=_dec(row["floor_quote_amount"]),
        cap_quote_amount=_dec(row["cap_quote_amount"]),
        is_enabled=bool(row["is_enabled"]),
        version=int(row["version"]),
    )
