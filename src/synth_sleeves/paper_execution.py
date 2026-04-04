"""
SYNTH v2
Module: synth_sleeves.paper_execution
Purpose:
    Apply OPEN / ADD / REDUCE / CLOSE intents to position_lot and trade_lot tables.
Policy:
    - OPEN creates a new lot
    - ADD creates a new lot
    - REDUCE reduces oldest open lots first (FIFO)
    - CLOSE closes all open lots for sleeve/asset pair
    - If target fraction matches but target state changes, harmonize open lot state without trading
Boundary:
    - DB orchestration allowed through repository hooks
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from src.synth_sleeves.models import ApprovedTarget, OpenLot, SleeveCode
from src.synth_sleeves.paper_pnl import (
    build_fill_intents,
    mark_to_market,
    open_new_lot,
    reduce_lot_fraction,
    target_to_entry_state,
)


DECIMAL_ZERO = Decimal("0")


def _build_asset_snapshots(open_lots_by_key):
    by_asset = defaultdict(list)

    for (asset_id, _sleeve_code), lots in open_lots_by_key.items():
        for lot in lots:
            if lot.current_fraction > DECIMAL_ZERO and lot.quantity_units > DECIMAL_ZERO:
                by_asset[asset_id].append(lot)

    snapshots = []

    for asset_id, lots in by_asset.items():
        total_quantity = sum((lot.quantity_units for lot in lots), start=DECIMAL_ZERO)
        total_entry_notional = sum((lot.entry_notional_eur for lot in lots), start=DECIMAL_ZERO)
        total_market_value = sum((lot.quantity_units * lot.latest_price_eur for lot in lots), start=DECIMAL_ZERO)
        total_unrealized = sum((lot.unrealized_pnl_eur for lot in lots), start=DECIMAL_ZERO)

        avg_entry_price = None
        if total_quantity > DECIMAL_ZERO:
            avg_entry_price = total_entry_notional / total_quantity

        snapshots.append(
            {
                "asset_id": asset_id,
                "quantity": total_quantity,
                "avg_entry_price_eur": avg_entry_price,
                "market_value_eur": total_market_value,
                "unrealized_pnl_eur": total_unrealized,
            }
        )

    return snapshots


class PaperExecutionApplier:
    def __init__(self, repository) -> None:
        self.repository = repository

    def apply(
        self,
        *,
        run_ts_utc: datetime,
        targets: list[ApprovedTarget],
        open_lots: list[OpenLot],
        wallet_equity_eur: Decimal,
        min_trade_fraction: Decimal,
        snapshot_every_loop: bool = True,
    ) -> dict[str, int]:
        intents = build_fill_intents(
            targets=targets,
            open_lots=open_lots,
            min_trade_fraction=min_trade_fraction,
        )

        latest_target_by_key: dict[tuple[int, SleeveCode], ApprovedTarget] = {
            (t.asset_id, t.sleeve_code): t for t in targets
        }

        open_lots_by_key: dict[tuple[int, SleeveCode], list[OpenLot]] = defaultdict(list)
        for lot in sorted(open_lots, key=lambda x: (x.open_ts_utc, x.position_lot_id)):
            open_lots_by_key[(lot.asset_id, lot.sleeve_code)].append(lot)

        created = 0
        reduced = 0
        closed = 0
        snapped = 0
        harmonized = 0

        # First harmonize state when exposure already matches closely.
        for key, lots in open_lots_by_key.items():
            target = latest_target_by_key.get(key)
            if target is None:
                continue

            target_state = target_to_entry_state(target.desired_action)
            current_fraction_total = sum((lot.current_fraction for lot in lots), start=DECIMAL_ZERO)

            fraction_gap = abs(target.target_fraction - current_fraction_total)
            if fraction_gap >= min_trade_fraction:
                continue

            for i, lot in enumerate(lots):
                if lot.current_fraction <= DECIMAL_ZERO:
                    continue
                if lot.entry_state == target_state:
                    continue

                updated_lot = OpenLot(
                    position_lot_id=lot.position_lot_id,
                    asset_id=lot.asset_id,
                    sleeve_code=lot.sleeve_code,
                    strategy_name=lot.strategy_name,
                    entry_state=target_state,
                    open_ts_utc=lot.open_ts_utc,
                    entry_price_eur=lot.entry_price_eur,
                    latest_price_eur=lot.latest_price_eur,
                    current_fraction=lot.current_fraction,
                    entry_notional_eur=lot.entry_notional_eur,
                    current_notional_eur=lot.current_notional_eur,
                    quantity_units=lot.quantity_units,
                    realized_pnl_eur=lot.realized_pnl_eur,
                    unrealized_pnl_eur=lot.unrealized_pnl_eur,
                    entry_reason=lot.entry_reason,
                    last_transition_state=target_state.value,
                )
                self.repository.upsert_open_lot(updated_lot)
                lots[i] = updated_lot
                harmonized += 1

        # Then apply actual trade intents.
        for intent in intents:
            key = (intent.asset_id, intent.sleeve_code)
            target = latest_target_by_key.get(key)

            if intent.action in {"OPEN", "ADD"}:
                if target is None:
                    continue

                if intent.price_eur is None or intent.price_eur <= DECIMAL_ZERO:
                    continue

                next_id = self.repository.get_next_position_lot_id()
                new_lot = open_new_lot(
                    next_position_lot_id=next_id,
                    run_ts_utc=run_ts_utc,
                    asset_id=intent.asset_id,
                    sleeve_code=intent.sleeve_code,
                    strategy_name=intent.strategy_name,
                    entry_state=target_to_entry_state(target.desired_action),
                    price_eur=intent.price_eur,
                    target_fraction=abs(intent.delta_fraction),
                    wallet_equity_eur=wallet_equity_eur,
                    entry_reason=intent.reasoning,
                )
                self.repository.upsert_open_lot(new_lot)
                open_lots_by_key[key].append(new_lot)
                created += 1
                continue

            if intent.action in {"REDUCE", "CLOSE"}:
                remaining_to_reduce = abs(intent.delta_fraction)

                lots = open_lots_by_key.get(key, [])
                new_open_list: list[OpenLot] = []

                for lot in lots:
                    if remaining_to_reduce <= DECIMAL_ZERO:
                        new_open_list.append(lot)
                        continue

                    current_lot = mark_to_market(lot, intent.price_eur, wallet_equity_eur)

                    if current_lot.current_fraction <= DECIMAL_ZERO:
                        continue

                    slice_reduce = min(current_lot.current_fraction, remaining_to_reduce)
                    updated_lot, _realized = reduce_lot_fraction(current_lot, slice_reduce, intent.price_eur)
                    remaining_to_reduce -= slice_reduce
                    reduced += 1

                    if updated_lot.current_fraction <= DECIMAL_ZERO:
                        updated_lot.last_transition_state = "EXIT" if intent.action == "CLOSE" else "REDUCE"
                        self.repository.upsert_open_lot(updated_lot)
                        self.repository.close_lot(
                            updated_lot,
                            close_ts_utc=run_ts_utc,
                            exit_price_eur=intent.price_eur,
                            exit_reason=intent.reasoning,
                            exit_state=updated_lot.last_transition_state or "EXIT",
                        )
                        closed += 1
                    else:
                        updated_lot.last_transition_state = "REDUCE"
                        self.repository.upsert_open_lot(updated_lot)
                        new_open_list.append(updated_lot)

                open_lots_by_key[key] = new_open_list

        if snapshot_every_loop:
            for key, lots in open_lots_by_key.items():
                for i, lot in enumerate(lots):
                    target = latest_target_by_key.get((lot.asset_id, lot.sleeve_code))
                    latest_price = target.latest_price_eur if target is not None else lot.latest_price_eur

                    marked = mark_to_market(lot, latest_price, wallet_equity_eur)
                    self.repository.upsert_open_lot(marked)
                    lots[i] = marked

            asset_snapshots = _build_asset_snapshots(open_lots_by_key)

            for snap in asset_snapshots:
                self.repository.insert_position_snapshot_asset_level(
                    snapshot_ts_utc=run_ts_utc,
                    asset_id=snap["asset_id"],
                    quantity=snap["quantity"],
                    avg_entry_price_eur=snap["avg_entry_price_eur"],
                    market_value_eur=snap["market_value_eur"],
                    unrealized_pnl_eur=snap["unrealized_pnl_eur"],
                )
                snapped += 1

        return {
            "fill_intents": len(intents),
            "lots_created": created,
            "lots_reduced": reduced,
            "lots_closed": closed,
            "lots_harmonized": harmonized,
            "snapshots_written": snapped,
        }
