"""Issue #753 B6: persistence boundary for the immutable V1 trade -> canonical
ShortTF Fib map binding defined in ``src/decision_gate/fib_map_bound_trade_v1.py``
and stored by ``db/migrations/20260906_fib_map_bound_trade_v1.sql``.

Ownership: this module is decision_gate-owned persistence only. It does not
select maps, resolve fill ownership, or create execution intent -- it only
records and reloads the one immutable binding decision the caller already
made, keyed at the exact strategy/trade lineage
(``uq_fib_map_bound_trade_lineage``) and the exact source fill
(``uq_fib_map_bound_trade_source_fill``).

Insert-at-first-fill semantics: ``record_fib_map_bound_trade_v1`` is the only
write path. Replaying the identical binding (same ``binding_id`` and
identical immutable content) is idempotent and returns the already-persisted
binding -- no second row, no re-evaluation. Reusing the same lineage, the
same source fill, or the same ``binding_id`` for materially different
content fails closed with an explicit repository error instead of silently
overwriting or guessing.

No broker calls, no order creation, no execution intent.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=persistence-only
execution_planner=none
executor=none
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from pymysql.err import IntegrityError

from src.decision_gate.fib_map_bound_trade_v1 import (
    FibMapBoundTradeError,
    FibMapBoundTradeV1,
    validate_fib_map_bound_trade_v1,
)

_INSERT_SQL = """
INSERT INTO fib_map_bound_trade_v1 (
    binding_id, trading_account_id, venue, market, strategy_bucket_id,
    strategy_id, strategy_version, trade_id, source_execution_plan_id,
    source_buy_fill_id, native_map_id, map_cycle_id, map_structure_hash,
    map_source_name, map_source_version, map_asof_ts_utc, map_published_at_utc,
    anchor_start_ts_utc, anchor_end_ts_utc, anchor_low_price, anchor_high_price,
    breakout_gate_price, invalidation_price, target_levels_json,
    target_ladder_semantics_version, bound_ts_utc
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s
)
"""

_SELECT_COLUMNS = """
    binding_id, trading_account_id, venue, market, strategy_bucket_id,
    strategy_id, strategy_version, trade_id, source_execution_plan_id,
    source_buy_fill_id, native_map_id, map_cycle_id, map_structure_hash,
    map_source_name, map_source_version, map_asof_ts_utc, map_published_at_utc,
    anchor_start_ts_utc, anchor_end_ts_utc, anchor_low_price, anchor_high_price,
    breakout_gate_price, invalidation_price, target_levels_json,
    target_ladder_semantics_version, bound_ts_utc
"""

_SELECT_BY_BINDING_ID_SQL = f"""
SELECT {_SELECT_COLUMNS} FROM fib_map_bound_trade_v1 WHERE binding_id = %s
"""

_SELECT_BY_LINEAGE_SQL = f"""
SELECT {_SELECT_COLUMNS} FROM fib_map_bound_trade_v1
WHERE trading_account_id = %s AND venue = %s AND market = %s
  AND strategy_bucket_id = %s AND strategy_id = %s AND strategy_version = %s
  AND trade_id = %s
"""

_SELECT_BY_SOURCE_FILL_SQL = f"""
SELECT {_SELECT_COLUMNS} FROM fib_map_bound_trade_v1
WHERE trading_account_id = %s AND venue = %s AND source_buy_fill_id = %s
"""


class FibMapBoundTradeRepositoryError(RuntimeError):
    """Fail-closed repository error. ``args[0]`` is the reason code."""


class FibMapBoundTradeConflictError(FibMapBoundTradeRepositoryError):
    """A lineage, source-fill, or binding_id identity is reused with
    materially different immutable content."""


def _legacy_db_cursor(*, commit: bool = False, database: str | None = None):
    from src.common.db import db_cursor
    return db_cursor(commit=commit, database=database)


def _cursor(value: Any) -> Any:
    return value[1] if isinstance(value, tuple) else value


def _aware_utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("expected datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _naive_utc_for_db(value: Any) -> datetime:
    return _aware_utc(value).replace(tzinfo=None)


def _decimal_36_18_for_db(value: Any) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise FibMapBoundTradeRepositoryError("FIB_MAP_BOUND_TRADE_PRICE_OUT_OF_RANGE")
    digits = list(value.as_tuple().digits)
    exponent = value.as_tuple().exponent
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    if not digits:
        return value
    scale = max(-exponent, 0)
    integer_digits = max(len(digits) + exponent, 0)
    if scale > 18 or integer_digits > 18:
        raise FibMapBoundTradeRepositoryError("FIB_MAP_BOUND_TRADE_PRICE_OUT_OF_RANGE")
    return value


def _encode_target_levels(target_levels: tuple[Decimal, ...]) -> str:
    return json.dumps([str(level) for level in target_levels])


def _required_nonempty_string(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError("expected nonempty string")
    return value


def _decode_target_levels(raw: Any) -> tuple[Decimal, ...]:
    parsed = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    if (
        not isinstance(parsed, list)
        or not parsed
        or not all(isinstance(item, str) for item in parsed)
    ):
        raise ValueError("FIB_MAP_TARGET_LEVELS_JSON_NOT_A_NONEMPTY_STRING_LIST")
    return tuple(Decimal(item) for item in parsed)


def _row_to_binding(row: Any) -> FibMapBoundTradeV1:
    try:
        binding = FibMapBoundTradeV1(
            binding_id=_required_nonempty_string(row["binding_id"]),
            trading_account_id=int(row["trading_account_id"]),
            venue=_required_nonempty_string(row["venue"]),
            market=_required_nonempty_string(row["market"]),
            strategy_bucket_id=_required_nonempty_string(row["strategy_bucket_id"]),
            strategy_id=_required_nonempty_string(row["strategy_id"]),
            strategy_version=_required_nonempty_string(row["strategy_version"]),
            trade_id=_required_nonempty_string(row["trade_id"]),
            source_execution_plan_id=_required_nonempty_string(row["source_execution_plan_id"]),
            source_buy_fill_id=_required_nonempty_string(row["source_buy_fill_id"]),
            native_map_id=_required_nonempty_string(row["native_map_id"]),
            map_cycle_id=_required_nonempty_string(row["map_cycle_id"]),
            map_structure_hash=_required_nonempty_string(row["map_structure_hash"]),
            map_source_name=_required_nonempty_string(row["map_source_name"]),
            map_source_version=_required_nonempty_string(row["map_source_version"]),
            map_asof_ts_utc=_aware_utc(row["map_asof_ts_utc"]),
            map_published_at_utc=_aware_utc(row["map_published_at_utc"]),
            anchor_start_ts_utc=_aware_utc(row["anchor_start_ts_utc"]),
            anchor_end_ts_utc=_aware_utc(row["anchor_end_ts_utc"]),
            anchor_low_price=Decimal(str(row["anchor_low_price"])),
            anchor_high_price=Decimal(str(row["anchor_high_price"])),
            breakout_gate_price=Decimal(str(row["breakout_gate_price"])),
            invalidation_price=Decimal(str(row["invalidation_price"])),
            target_levels=_decode_target_levels(row["target_levels_json"]),
            target_ladder_semantics_version=_required_nonempty_string(
                row["target_ladder_semantics_version"]
            ),
            bound_ts_utc=_aware_utc(row["bound_ts_utc"]),
        )
    except (KeyError, TypeError, ValueError, InvalidOperation, json.JSONDecodeError) as exc:
        raise FibMapBoundTradeRepositoryError("INVALID_PERSISTED_FIB_MAP_BOUND_TRADE") from exc
    try:
        validate_fib_map_bound_trade_v1(binding)
    except FibMapBoundTradeError as exc:
        raise FibMapBoundTradeRepositoryError("INVALID_PERSISTED_FIB_MAP_BOUND_TRADE") from exc
    return binding


@dataclass
class FibMapBoundTradeRepositoryV1:
    """One immutable row per binding. No update, no delete.
    ``record_fib_map_bound_trade_v1`` is the only write path."""

    cursor_factory: Callable[..., Any] = field(default=_legacy_db_cursor, repr=False)

    def record_fib_map_bound_trade_v1(self, *, binding: FibMapBoundTradeV1) -> FibMapBoundTradeV1:
        validate_fib_map_bound_trade_v1(binding)
        persisted_prices = tuple(
            _decimal_36_18_for_db(value)
            for value in (
                binding.anchor_low_price,
                binding.anchor_high_price,
                binding.breakout_gate_price,
                binding.invalidation_price,
            )
        )
        params = (
            binding.binding_id, binding.trading_account_id, binding.venue, binding.market,
            binding.strategy_bucket_id, binding.strategy_id, binding.strategy_version,
            binding.trade_id, binding.source_execution_plan_id, binding.source_buy_fill_id,
            binding.native_map_id, binding.map_cycle_id, binding.map_structure_hash,
            binding.map_source_name, binding.map_source_version,
            _naive_utc_for_db(binding.map_asof_ts_utc),
            _naive_utc_for_db(binding.map_published_at_utc),
            _naive_utc_for_db(binding.anchor_start_ts_utc),
            _naive_utc_for_db(binding.anchor_end_ts_utc),
            *persisted_prices,
            _encode_target_levels(binding.target_levels),
            binding.target_ladder_semantics_version,
            _naive_utc_for_db(binding.bound_ts_utc),
        )
        try:
            with self.cursor_factory(commit=True) as db_obj:
                cursor = _cursor(db_obj)
                cursor.execute(_INSERT_SQL, params)
            return binding
        except IntegrityError:
            return self._resolve_insert_conflict(binding)

    def _resolve_insert_conflict(self, binding: FibMapBoundTradeV1) -> FibMapBoundTradeV1:
        by_binding_id = self.load_by_binding_id(binding_id=binding.binding_id)
        if by_binding_id is not None:
            if by_binding_id == binding:
                return by_binding_id
            raise FibMapBoundTradeConflictError("FIB_MAP_BOUND_TRADE_BINDING_ID_CONFLICT")

        by_lineage = self.load_by_lineage(
            trading_account_id=binding.trading_account_id, venue=binding.venue,
            market=binding.market, strategy_bucket_id=binding.strategy_bucket_id,
            strategy_id=binding.strategy_id, strategy_version=binding.strategy_version,
            trade_id=binding.trade_id,
        )
        if by_lineage is not None:
            if by_lineage == binding:
                return by_lineage
            raise FibMapBoundTradeConflictError("FIB_MAP_BOUND_TRADE_LINEAGE_CONFLICT")

        by_source_fill = self.load_by_source_fill(
            trading_account_id=binding.trading_account_id, venue=binding.venue,
            source_buy_fill_id=binding.source_buy_fill_id,
        )
        if by_source_fill is not None:
            if by_source_fill == binding:
                return by_source_fill
            raise FibMapBoundTradeConflictError("FIB_MAP_BOUND_TRADE_SOURCE_FILL_CONFLICT")

        raise FibMapBoundTradeRepositoryError("FIB_MAP_BOUND_TRADE_INSERT_CONFLICT_UNRESOLVED")

    def load_by_binding_id(self, *, binding_id: str) -> FibMapBoundTradeV1 | None:
        if not isinstance(binding_id, str) or not binding_id.strip():
            raise FibMapBoundTradeRepositoryError("INVALID_FIB_MAP_BOUND_TRADE_LOOKUP")
        with self.cursor_factory() as db_obj:
            cursor = _cursor(db_obj)
            cursor.execute(_SELECT_BY_BINDING_ID_SQL, (binding_id,))
            row = cursor.fetchone()
        return None if row is None else _row_to_binding(row)

    def load_by_lineage(
        self,
        *,
        trading_account_id: int,
        venue: str,
        market: str,
        strategy_bucket_id: str,
        strategy_id: str,
        strategy_version: str,
        trade_id: str,
    ) -> FibMapBoundTradeV1 | None:
        if (
            trading_account_id <= 0
            or not venue.strip() or not market.strip() or not strategy_bucket_id.strip()
            or not strategy_id.strip() or not strategy_version.strip() or not trade_id.strip()
        ):
            raise FibMapBoundTradeRepositoryError("INVALID_FIB_MAP_BOUND_TRADE_LOOKUP")
        with self.cursor_factory() as db_obj:
            cursor = _cursor(db_obj)
            cursor.execute(
                _SELECT_BY_LINEAGE_SQL,
                (
                    trading_account_id, venue, market, strategy_bucket_id,
                    strategy_id, strategy_version, trade_id,
                ),
            )
            row = cursor.fetchone()
        return None if row is None else _row_to_binding(row)

    def load_by_source_fill(
        self, *, trading_account_id: int, venue: str, source_buy_fill_id: str,
    ) -> FibMapBoundTradeV1 | None:
        if trading_account_id <= 0 or not venue.strip() or not source_buy_fill_id.strip():
            raise FibMapBoundTradeRepositoryError("INVALID_FIB_MAP_BOUND_TRADE_LOOKUP")
        with self.cursor_factory() as db_obj:
            cursor = _cursor(db_obj)
            cursor.execute(
                _SELECT_BY_SOURCE_FILL_SQL,
                (trading_account_id, venue, source_buy_fill_id),
            )
            row = cursor.fetchone()
        return None if row is None else _row_to_binding(row)


FibMapBoundTradeRepository = FibMapBoundTradeRepositoryV1
