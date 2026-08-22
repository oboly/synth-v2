"""Canonical source-owned writer for immutable automatic BUY runtime inputs.

This module owns the only supported creation path for
``automatic_buy_runtime_input_v1`` snapshots.  It writes market/source and
account-observation evidence only; it has no candidate, decision, planner,
executor, credential, or broker dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from pymysql.err import IntegrityError

from src.entry_policy.automatic_buy_runtime_contract_v1 import (
    AutomaticBuyRuntimeContractError,
    AutomaticBuyRuntimeInputV1,
    validate_runtime_input_v1,
)
from src.entry_policy.automatic_buy_runtime_repository_v1 import _row_to_input


class AutomaticBuyRuntimeInputWriteError(RuntimeError):
    pass


@dataclass(frozen=True)
class AutomaticBuyRuntimeInputSourceV1:
    """Fully bound source snapshot accepted by the canonical input writer."""

    source_snapshot_key: str
    input_contract_version: str
    evaluation_ts_utc: datetime
    trading_account_id: int
    venue: str
    asset_id: int
    market: str
    strategy_bucket_id: str
    strategy_id: str
    strategy_version: str
    setup_id: str
    setup_ready: bool
    current_price: Decimal
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    re_entry_zone_low: Decimal | None
    re_entry_zone_high: Decimal | None
    setup_evidence_id: str
    setup_observed_ts_utc: datetime
    account_observed_ts_utc: datetime
    account_enabled: bool
    account_mode: str
    automatic_buy_execution_enabled: bool
    free_quote_balance_eur: Decimal
    free_quote_balance_observed_ts_utc: datetime
    blocking_conflict: bool
    proposed_position_amount_eur: Decimal
    current_bucket_amount_eur: Decimal
    current_open_positions: int
    current_asset_exposure_pct: Decimal
    max_automatic_buy_notional_eur: Decimal | None
    source_provenance: str
    live_trading_enabled: bool = False

    def as_runtime_input(self, *, automatic_buy_runtime_input_id: int) -> AutomaticBuyRuntimeInputV1:
        return AutomaticBuyRuntimeInputV1(
            automatic_buy_runtime_input_id=automatic_buy_runtime_input_id,
            **self.__dict__,
        )


@dataclass(frozen=True)
class AutomaticBuyRuntimeInputWriteResultV1:
    runtime_input: AutomaticBuyRuntimeInputV1
    outcome: str


_INPUT_COLUMNS = (
    "source_snapshot_key", "input_contract_version", "evaluation_ts_utc",
    "trading_account_id", "venue", "asset_id", "market", "strategy_bucket_id",
    "strategy_id", "strategy_version", "setup_id", "setup_ready", "current_price",
    "entry_zone_low", "entry_zone_high", "re_entry_zone_low", "re_entry_zone_high",
    "setup_evidence_id", "setup_observed_ts_utc", "account_observed_ts_utc",
    "account_enabled", "account_mode", "automatic_buy_execution_enabled",
    "live_trading_enabled", "free_quote_balance_eur", "free_quote_balance_observed_ts_utc",
    "blocking_conflict", "proposed_position_amount_eur", "current_bucket_amount_eur",
    "current_open_positions", "current_asset_exposure_pct", "max_automatic_buy_notional_eur",
    "source_provenance",
)
_SELECT_COLUMNS = "automatic_buy_runtime_input_id, " + ", ".join(_INPUT_COLUMNS)
_INSERT_SQL = (
    "INSERT INTO automatic_buy_runtime_input_v1 (" + ", ".join(_INPUT_COLUMNS) + ") VALUES ("
    + ", ".join("%s" for _ in _INPUT_COLUMNS) + ")"
)


def _values(source: AutomaticBuyRuntimeInputSourceV1) -> tuple[Any, ...]:
    return tuple(getattr(source, column) for column in _INPUT_COLUMNS)


def _load_by_source_snapshot_key(conn: Any, *, source_snapshot_key: str) -> AutomaticBuyRuntimeInputV1 | None:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_SELECT_COLUMNS} FROM automatic_buy_runtime_input_v1 "
            "WHERE source_snapshot_key = %s LIMIT 1",
            (source_snapshot_key,),
        )
        row = cur.fetchone()
    return None if row is None else _row_to_input(dict(row))


def _require_same_source(existing: AutomaticBuyRuntimeInputV1, source: AutomaticBuyRuntimeInputSourceV1) -> None:
    if existing != source.as_runtime_input(automatic_buy_runtime_input_id=existing.automatic_buy_runtime_input_id):
        raise AutomaticBuyRuntimeInputWriteError("AUTOMATIC_BUY_RUNTIME_INPUT_IDENTITY_CONFLICT")


def write_automatic_buy_runtime_input_v1(
    conn: Any,
    *,
    source: AutomaticBuyRuntimeInputSourceV1,
) -> AutomaticBuyRuntimeInputWriteResultV1:
    """Persist exactly one immutable source snapshot or reuse its exact replay."""
    try:
        validate_runtime_input_v1(source.as_runtime_input(automatic_buy_runtime_input_id=1))
    except AutomaticBuyRuntimeContractError as exc:
        raise AutomaticBuyRuntimeInputWriteError(exc.args[0]) from exc

    existing = _load_by_source_snapshot_key(conn, source_snapshot_key=source.source_snapshot_key)
    if existing is not None:
        _require_same_source(existing, source)
        return AutomaticBuyRuntimeInputWriteResultV1(existing, "idempotent_existing")

    try:
        with conn.cursor() as cur:
            cur.execute(_INSERT_SQL, _values(source))
            runtime_input_id = int(cur.lastrowid)
    except IntegrityError:
        existing = _load_by_source_snapshot_key(conn, source_snapshot_key=source.source_snapshot_key)
        if existing is None:
            raise
        _require_same_source(existing, source)
        return AutomaticBuyRuntimeInputWriteResultV1(existing, "idempotent_existing")
    return AutomaticBuyRuntimeInputWriteResultV1(
        source.as_runtime_input(automatic_buy_runtime_input_id=runtime_input_id),
        "inserted",
    )
