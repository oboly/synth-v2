"""
SYNTH v2
Module: synth_sleeves.paper_pnl
Purpose:
    Lot-based paper accounting engine.
Boundary:
    - No strategy logic here
    - Applies target deltas to lots
    - Uses EUR wallet equity + latest EUR prices
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from src.synth_sleeves.models import (
    ApprovedTarget,
    DecisionAction,
    EntryState,
    OpenLot,
    PaperFillIntent,
    SleeveCode,
)


DECIMAL_ZERO = Decimal("0")
Q8 = Decimal("0.00000001")
Q10 = Decimal("0.0000000001")
Q18 = Decimal("0.000000000000000001")


def q8(value: Decimal) -> Decimal:
    return value.quantize(Q8, rounding=ROUND_HALF_UP)


def q10(value: Decimal) -> Decimal:
    return value.quantize(Q10, rounding=ROUND_HALF_UP)


def q18(value: Decimal) -> Decimal:
    return value.quantize(Q18, rounding=ROUND_HALF_UP)


@dataclass(slots=True)
class TargetDelta:
    target: ApprovedTarget
    current_fraction: Decimal
    delta_fraction: Decimal


def build_fill_intents(
    targets: list[ApprovedTarget],
    open_lots: Iterable[OpenLot],
    min_trade_fraction: Decimal,
) -> list[PaperFillIntent]:
    current_by_key: dict[tuple[int, SleeveCode], Decimal] = {}
    for lot in open_lots:
        key = (lot.asset_id, lot.sleeve_code)
        current_by_key[key] = current_by_key.get(key, DECIMAL_ZERO) + lot.current_fraction

    intents: list[PaperFillIntent] = []
    seen_keys: set[tuple[int, SleeveCode]] = set()

    for target in targets:
        key = (target.asset_id, target.sleeve_code)
        seen_keys.add(key)
        current_fraction = current_by_key.get(key, DECIMAL_ZERO)
        delta = q8(target.target_fraction - current_fraction)

        if abs(delta) < min_trade_fraction:
            continue

        if delta > DECIMAL_ZERO:
            action = "OPEN" if current_fraction <= DECIMAL_ZERO else "ADD"
        else:
            action = "CLOSE" if target.target_fraction <= DECIMAL_ZERO else "REDUCE"

        intents.append(
            PaperFillIntent(
                run_ts_utc=target.run_ts_utc,
                asset_id=target.asset_id,
                symbol=target.symbol,
                sleeve_code=target.sleeve_code,
                strategy_name=target.strategy_name,
                action=action,
                delta_fraction=delta,
                price_eur=target.latest_price_eur,
                reasoning=target.reasoning,
            )
        )

    for lot in open_lots:
        key = (lot.asset_id, lot.sleeve_code)
        if key in seen_keys:
            continue
        if lot.current_fraction <= DECIMAL_ZERO:
            continue
        intents.append(
            PaperFillIntent(
                run_ts_utc=lot.open_ts_utc,
                asset_id=lot.asset_id,
                symbol=f"asset_{lot.asset_id}",
                sleeve_code=lot.sleeve_code,
                strategy_name=lot.strategy_name,
                action="CLOSE",
                delta_fraction=q8(-lot.current_fraction),
                price_eur=lot.latest_price_eur,
                reasoning="No remaining target for sleeve/asset pair.",
            )
        )

    return intents


def open_new_lot(
    *,
    next_position_lot_id: int,
    run_ts_utc: datetime,
    asset_id: int,
    sleeve_code: SleeveCode,
    strategy_name: str,
    entry_state: EntryState,
    price_eur: Decimal,
    target_fraction: Decimal,
    wallet_equity_eur: Decimal,
    entry_reason: str,
) -> OpenLot:
    entry_notional = q10(wallet_equity_eur * target_fraction)
    quantity = q18(entry_notional / price_eur) if price_eur > DECIMAL_ZERO else DECIMAL_ZERO
    return OpenLot(
        position_lot_id=next_position_lot_id,
        asset_id=asset_id,
        sleeve_code=sleeve_code,
        strategy_name=strategy_name,
        entry_state=entry_state,
        open_ts_utc=run_ts_utc,
        entry_price_eur=q10(price_eur),
        latest_price_eur=q10(price_eur),
        current_fraction=q8(target_fraction),
        entry_notional_eur=entry_notional,
        current_notional_eur=entry_notional,
        quantity_units=quantity,
        entry_reason=entry_reason,
    )


def mark_to_market(lot: OpenLot, latest_price_eur: Decimal, wallet_equity_eur: Decimal) -> OpenLot:
    current_notional = q10(wallet_equity_eur * lot.current_fraction)
    quantity = lot.quantity_units
    market_value = q10(quantity * latest_price_eur)
    unrealized = q10(market_value - lot.entry_notional_eur)
    return OpenLot(
        position_lot_id=lot.position_lot_id,
        asset_id=lot.asset_id,
        sleeve_code=lot.sleeve_code,
        strategy_name=lot.strategy_name,
        entry_state=lot.entry_state,
        open_ts_utc=lot.open_ts_utc,
        entry_price_eur=lot.entry_price_eur,
        latest_price_eur=q10(latest_price_eur),
        current_fraction=lot.current_fraction,
        entry_notional_eur=lot.entry_notional_eur,
        current_notional_eur=current_notional,
        quantity_units=quantity,
        realized_pnl_eur=lot.realized_pnl_eur,
        unrealized_pnl_eur=unrealized,
        entry_reason=lot.entry_reason,
        last_transition_state=lot.last_transition_state,
    )


def reduce_lot_fraction(lot: OpenLot, reduce_fraction: Decimal, price_eur: Decimal) -> tuple[OpenLot, Decimal]:
    if reduce_fraction <= DECIMAL_ZERO:
        return lot, DECIMAL_ZERO
    if reduce_fraction > lot.current_fraction:
        reduce_fraction = lot.current_fraction

    exit_ratio = reduce_fraction / lot.current_fraction if lot.current_fraction > DECIMAL_ZERO else DECIMAL_ZERO
    exited_units = q18(lot.quantity_units * exit_ratio)
    exit_notional = q10(exited_units * price_eur)
    cost_basis = q10(lot.entry_notional_eur * exit_ratio)
    realized = q10(exit_notional - cost_basis)

    remaining_fraction = q8(lot.current_fraction - reduce_fraction)
    remaining_units = q18(lot.quantity_units - exited_units)
    remaining_entry_notional = q10(lot.entry_notional_eur - cost_basis)

    updated = OpenLot(
        position_lot_id=lot.position_lot_id,
        asset_id=lot.asset_id,
        sleeve_code=lot.sleeve_code,
        strategy_name=lot.strategy_name,
        entry_state=lot.entry_state,
        open_ts_utc=lot.open_ts_utc,
        entry_price_eur=lot.entry_price_eur,
        latest_price_eur=q10(price_eur),
        current_fraction=remaining_fraction,
        entry_notional_eur=remaining_entry_notional,
        current_notional_eur=q10(exit_notional if remaining_fraction <= DECIMAL_ZERO else remaining_units * price_eur),
        quantity_units=remaining_units,
        realized_pnl_eur=q10(lot.realized_pnl_eur + realized),
        unrealized_pnl_eur=DECIMAL_ZERO,
        entry_reason=lot.entry_reason,
        last_transition_state=lot.last_transition_state,
    )
    return updated, realized


def target_to_entry_state(action: DecisionAction) -> EntryState:
    if action == DecisionAction.PREPARE:
        return EntryState.PREPARE
    if action == DecisionAction.SCALP_ONLY:
        return EntryState.SCALP_ONLY
    return EntryState.ENTER_LONG
