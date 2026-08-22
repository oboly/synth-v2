"""Issue #471: canonical source-owned immutable automatic BUY runtime-input writer.

This module owns the only supported controlled-acceptance creation path for
``automatic_buy_runtime_input_v1`` snapshots. Its caller-controlled input
(:class:`AutomaticBuySourceEvidenceV1`) carries market/setup evidence and the
bare identity needed to later locate canonical decision-gate-owned account
evidence (``trading_account_id``, ``venue``, ``asset_id``, ``market``,
``strategy_bucket_id``). It structurally has no field for any account-owned
column: ``account_enabled``, ``account_mode``, ``live_trading_enabled``,
``automatic_buy_execution_enabled``, ``free_quote_balance_eur``,
``proposed_position_amount_eur``, ``current_bucket_amount_eur``,
``current_open_positions``, ``current_asset_exposure_pct``, or
``max_automatic_buy_notional_eur``.

A prior attempt (PR #473, reverted) let an operator-JSON dataclass carry all
of those account-owned fields directly, making the acceptance harness an
unauthorized account-permission/allocation authority. This module's shape
forecloses that: there is no keyword argument to pass any of them through.

The persisted row's account-owned columns hold neutral placeholder values
only, present solely to satisfy this append-only table's NOT NULL/CHECK
constraints. They carry no evidentiary meaning -- every reader must go
through ``build_runtime_item_v1`` (Issue #474), which unconditionally
replaces them with a freshly-loaded, decision-gate-owned
``AutomaticBuyAccountAllocationEvidenceV1`` snapshot before decision_gate
ever sees the row. This module performs no account/config DB read and makes
no permission or planning decision.

No executor, broker, credential, or order import.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from pymysql.err import IntegrityError

from src.entry_policy.automatic_buy_runtime_contract_v1 import (
    RUNTIME_INPUT_LIVE_CONTRACT_VERSION,
    AutomaticBuyRuntimeContractError,
    AutomaticBuyRuntimeInputV1,
    validate_runtime_input_v1,
)
from src.entry_policy.automatic_buy_runtime_repository_v1 import _row_to_input

# Neutral placeholder values for every account-owned column. These exist
# only so the persisted row satisfies NOT NULL/CHECK constraints;
# build_runtime_item_v1 replaces every one of them before decision_gate ever
# sees the row (Issue #474). They are never read as evidence.
_PLACEHOLDER_ACCOUNT_MODE = "paper"
_PLACEHOLDER_PROPOSED_POSITION_AMOUNT_EUR = Decimal("1")


class AutomaticBuyRuntimeInputWriteError(RuntimeError):
    pass


@dataclass(frozen=True)
class AutomaticBuySourceEvidenceV1:
    """Caller-controlled market/setup evidence and locating identity only.

    No field on this dataclass is account-owned. Adding one would reintroduce
    the exact architecture violation that got PR #473 reverted -- see module
    docstring.
    """

    source_snapshot_key: str
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
    source_provenance: str

    def as_runtime_input(self, *, automatic_buy_runtime_input_id: int) -> AutomaticBuyRuntimeInputV1:
        return AutomaticBuyRuntimeInputV1(
            automatic_buy_runtime_input_id=automatic_buy_runtime_input_id,
            source_snapshot_key=self.source_snapshot_key,
            input_contract_version=RUNTIME_INPUT_LIVE_CONTRACT_VERSION,
            evaluation_ts_utc=self.evaluation_ts_utc,
            trading_account_id=self.trading_account_id,
            venue=self.venue,
            asset_id=self.asset_id,
            market=self.market,
            strategy_bucket_id=self.strategy_bucket_id,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            setup_id=self.setup_id,
            setup_ready=self.setup_ready,
            current_price=self.current_price,
            entry_zone_low=self.entry_zone_low,
            entry_zone_high=self.entry_zone_high,
            re_entry_zone_low=self.re_entry_zone_low,
            re_entry_zone_high=self.re_entry_zone_high,
            setup_evidence_id=self.setup_evidence_id,
            setup_observed_ts_utc=self.setup_observed_ts_utc,
            account_observed_ts_utc=self.evaluation_ts_utc,
            account_enabled=True,
            account_mode=_PLACEHOLDER_ACCOUNT_MODE,
            automatic_buy_execution_enabled=True,
            free_quote_balance_eur=Decimal("0"),
            free_quote_balance_observed_ts_utc=self.evaluation_ts_utc,
            blocking_conflict=False,
            proposed_position_amount_eur=_PLACEHOLDER_PROPOSED_POSITION_AMOUNT_EUR,
            current_bucket_amount_eur=Decimal("0"),
            current_open_positions=0,
            current_asset_exposure_pct=Decimal("0"),
            max_automatic_buy_notional_eur=None,
            source_provenance=self.source_provenance,
            live_trading_enabled=False,
        )


@dataclass(frozen=True)
class AutomaticBuyRuntimeInputWriteResultV1:
    runtime_input: AutomaticBuyRuntimeInputV1
    outcome: str  # inserted | idempotent_existing


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

# Only caller-controlled fields participate in conflicting-replay identity
# comparison. Placeholder account-owned columns are deliberately excluded:
# they carry no evidence and must never be able to cause a false "conflict".
_IDENTITY_FIELDS = (
    "source_snapshot_key", "evaluation_ts_utc", "trading_account_id", "venue",
    "asset_id", "market", "strategy_bucket_id", "strategy_id", "strategy_version",
    "setup_id", "setup_ready", "current_price", "entry_zone_low", "entry_zone_high",
    "re_entry_zone_low", "re_entry_zone_high", "setup_evidence_id",
    "setup_observed_ts_utc", "source_provenance",
)


def _values(value: AutomaticBuyRuntimeInputV1) -> tuple[Any, ...]:
    return tuple(getattr(value, column) for column in _INPUT_COLUMNS)


def _load_by_source_snapshot_key(conn: Any, *, source_snapshot_key: str) -> AutomaticBuyRuntimeInputV1 | None:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_SELECT_COLUMNS} FROM automatic_buy_runtime_input_v1 "
            "WHERE source_snapshot_key = %s LIMIT 1",
            (source_snapshot_key,),
        )
        row = cur.fetchone()
    return None if row is None else _row_to_input(dict(row))


def _same_identity(existing: AutomaticBuyRuntimeInputV1, candidate: AutomaticBuyRuntimeInputV1) -> bool:
    return all(getattr(existing, field) == getattr(candidate, field) for field in _IDENTITY_FIELDS)


def write_automatic_buy_runtime_input_v1(
    conn: Any,
    *,
    source: AutomaticBuySourceEvidenceV1,
) -> AutomaticBuyRuntimeInputWriteResultV1:
    """Persist exactly one immutable source snapshot, or reuse its exact replay.

    Fails closed with :class:`AutomaticBuyRuntimeInputWriteError` if
    ``source_snapshot_key`` already exists bound to different
    caller-controlled evidence -- a conflicting replay is never silently
    accepted.
    """
    candidate = source.as_runtime_input(automatic_buy_runtime_input_id=1)
    try:
        validate_runtime_input_v1(candidate)
    except AutomaticBuyRuntimeContractError as exc:
        raise AutomaticBuyRuntimeInputWriteError(
            exc.args[0] if exc.args else "INVALID_AUTOMATIC_BUY_SOURCE_EVIDENCE"
        ) from exc

    existing = _load_by_source_snapshot_key(conn, source_snapshot_key=source.source_snapshot_key)
    if existing is not None:
        if not _same_identity(existing, candidate):
            raise AutomaticBuyRuntimeInputWriteError("AUTOMATIC_BUY_RUNTIME_INPUT_IDENTITY_CONFLICT")
        return AutomaticBuyRuntimeInputWriteResultV1(existing, "idempotent_existing")

    try:
        with conn.cursor() as cur:
            cur.execute(_INSERT_SQL, _values(candidate))
            runtime_input_id = int(cur.lastrowid)
    except IntegrityError:
        existing = _load_by_source_snapshot_key(conn, source_snapshot_key=source.source_snapshot_key)
        if existing is None:
            raise
        if not _same_identity(existing, candidate):
            raise AutomaticBuyRuntimeInputWriteError("AUTOMATIC_BUY_RUNTIME_INPUT_IDENTITY_CONFLICT") from None
        return AutomaticBuyRuntimeInputWriteResultV1(existing, "idempotent_existing")

    return AutomaticBuyRuntimeInputWriteResultV1(
        source.as_runtime_input(automatic_buy_runtime_input_id=runtime_input_id),
        "inserted",
    )
