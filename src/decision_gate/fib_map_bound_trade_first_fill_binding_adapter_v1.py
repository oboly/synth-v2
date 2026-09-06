"""Issue #753 B7: decision_gate-owned adapter that constructs and persists one
immutable ``FibMapBoundTradeV1`` (B1, ``src/decision_gate/fib_map_bound_trade_v1.py``)
at the first strategy-owned BUY fill, from B4/B5 ownership/fill lineage
(``StrategyOwnedInventoryEventV1``, #752/#753) plus caller-supplied canonical
Fib map evidence, persisted through the existing B6 repository
(``src/decision_gate/fib_map_bound_trade_repository_v1.py``).

Smallest explicit input contract: one real ``StrategyOwnedInventoryEventV1``
(the BUY fill establishing lineage/ownership -- trading_account_id, venue,
market, strategy_bucket_id, strategy_id, strategy_version, trade_id,
source_execution_plan_id, source_fill_id, occurred_ts_utc, all copied
verbatim, never re-derived) and one caller-supplied ``CanonicalFibMapEvidenceV1``
(the already-selected canonical ShortTF Fib map's identity/geometry/full
target ladder). This module never selects, recomputes, or re-derives a map,
never infers ownership from wallet balance, and never creates execution
intent -- ``execution_planner``/``executor`` remain untouched.

``bound_ts_utc`` is always the fill's own ``occurred_ts_utc`` -- never wall
clock -- so binding construction stays a pure, deterministic function of its
inputs and "no future data relative to first fill" has one unambiguous
reference point.

Target-ladder immutability: the full ``map_evidence.target_levels`` ladder is
frozen into the binding verbatim. This adapter never filters to
"currently active" or "not yet reached" targets -- that is exit-decision
progression state (B2, ``fib_map_bound_exit_decision_v1.py``), owned by the
caller of that layer, and must never leak into what gets bound at B7 time.

First-fill / no-rebind semantics are enforced by the B6 repository's existing
unique keys (lineage, source fill, binding_id), not re-implemented here:
replaying the identical fill+map evidence is idempotent
(``record_fib_map_bound_trade_v1`` returns the existing row); a later fill or
different map evidence reusing the same lineage or source fill fails closed
via ``FibMapBoundTradeConflictError``.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=extended (new construct+persist adapter, reuses B6 persistence)
execution_planner=none
executor=none
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Final

from src.decision_gate.fib_map_bound_trade_repository_v1 import (
    FibMapBoundTradeRepositoryV1,
)
from src.decision_gate.fib_map_bound_trade_v1 import (
    FibMapBoundTradeV1,
    validate_fib_map_bound_trade_v1,
)
from src.decision_gate.strategy_owned_inventory_v1 import (
    StrategyOwnedInventoryError,
    StrategyOwnedInventoryEventV1,
    validate_strategy_owned_inventory_event_v1,
)
from src.market_data.native_short_fib_context_v1 import DEFAULT_PRIMARY_STALE_HOURS

BINDING_ID_PREFIX: Final[str] = "fib_map_bound_trade_v1"

# The canonical ShortTF map's primary authority (4h candles) is only
# considered fresh up to this age (see
# ``native_short_fib_context_v1.DEFAULT_PRIMARY_STALE_HOURS``). Reusing the
# same named constant here instead of a new magic threshold keeps the
# freshness bar for "map evidence used to bind a trade" no looser than the
# bar market_data already applies to the same primary authority.
DEFAULT_MAX_MAP_EVIDENCE_AGE_SECONDS: Final[int] = DEFAULT_PRIMARY_STALE_HOURS * 3600

SOURCE_FILL_SIDE_BUY: Final[str] = "BUY"


class FibMapBoundTradeBindingAdapterError(ValueError):
    """Fail-closed adapter error. ``args[0]`` is the reason code."""


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class CanonicalFibMapEvidenceV1:
    """Caller-supplied canonical ShortTF Fib map evidence for one bind call.

    Every field mirrors an existing canonical native-map field name/unit
    (see ``src/market_data/native_short_fib_context_v1.py`` and
    ``native_short_fib_context_snapshot_v1.py``'s ``PROVENANCE_FIELDS``) --
    this is a narrow data carrier for already-selected map truth, not a
    parallel geometry definition. ``venue``/``market`` are included only so
    this adapter can validate the evidence names the same market as the
    fill lineage; they are not re-derived or guessed.

    ``target_levels`` must be the full ladder for this map (e.g. the
    complete ``active_target_levels`` extension set), never a subset
    filtered by current price or prior progression.
    """

    venue: str
    market: str
    native_map_id: str
    map_cycle_id: str
    map_structure_hash: str
    map_source_name: str
    map_source_version: str
    map_asof_ts_utc: datetime
    map_published_at_utc: datetime
    anchor_start_ts_utc: datetime
    anchor_end_ts_utc: datetime
    anchor_low_price: Decimal
    anchor_high_price: Decimal
    breakout_gate_price: Decimal
    invalidation_price: Decimal
    target_levels: tuple[Decimal, ...]
    target_ladder_semantics_version: str


def derive_fib_map_bound_trade_binding_id_v1(
    *,
    fill_event: StrategyOwnedInventoryEventV1,
    map_evidence: CanonicalFibMapEvidenceV1,
) -> str:
    """Deterministic ``binding_id``: same fill + same map evidence always
    derives the same id; any change to lineage, source fill, or map
    identity changes it."""
    payload = "\x1f".join(
        str(part)
        for part in (
            fill_event.trading_account_id, fill_event.venue, fill_event.market,
            fill_event.strategy_bucket_id, fill_event.strategy_id,
            fill_event.strategy_version, fill_event.trade_id,
            fill_event.source_execution_plan_id, fill_event.source_fill_id,
            map_evidence.native_map_id, map_evidence.map_cycle_id,
            map_evidence.map_structure_hash,
        )
    )
    return f"{BINDING_ID_PREFIX}:{sha256(payload.encode('utf-8')).hexdigest()}"


def _validate_fill_event_for_binding(fill_event: StrategyOwnedInventoryEventV1) -> None:
    if not isinstance(fill_event, StrategyOwnedInventoryEventV1):
        raise FibMapBoundTradeBindingAdapterError("INVALID_FIRST_FILL_EVENT")
    try:
        validate_strategy_owned_inventory_event_v1(fill_event)
    except StrategyOwnedInventoryError as exc:
        raise FibMapBoundTradeBindingAdapterError("INVALID_FIRST_FILL_EVENT") from exc
    if fill_event.side != SOURCE_FILL_SIDE_BUY:
        raise FibMapBoundTradeBindingAdapterError("SOURCE_FILL_NOT_BUY_SIDE")


def _validate_identity_consistency(
    *, fill_event: StrategyOwnedInventoryEventV1, map_evidence: CanonicalFibMapEvidenceV1,
) -> None:
    if not isinstance(map_evidence, CanonicalFibMapEvidenceV1):
        raise FibMapBoundTradeBindingAdapterError("INVALID_CANONICAL_FIB_MAP_EVIDENCE")
    if fill_event.venue != map_evidence.venue or fill_event.market != map_evidence.market:
        raise FibMapBoundTradeBindingAdapterError("FIB_MAP_EVIDENCE_IDENTITY_MISMATCH")


def _validate_map_evidence_freshness(
    *,
    map_evidence: CanonicalFibMapEvidenceV1,
    bound_ts_utc: datetime,
) -> None:
    for value in (
        map_evidence.map_asof_ts_utc, map_evidence.map_published_at_utc,
        map_evidence.anchor_start_ts_utc, map_evidence.anchor_end_ts_utc,
    ):
        if not _aware(value):
            raise FibMapBoundTradeBindingAdapterError("INVALID_FIB_MAP_EVIDENCE_TIMESTAMP")
        if value > bound_ts_utc:
            raise FibMapBoundTradeBindingAdapterError("FIB_MAP_EVIDENCE_FROM_THE_FUTURE")
    age = bound_ts_utc - map_evidence.map_asof_ts_utc
    if age < timedelta(0) or age > timedelta(seconds=DEFAULT_MAX_MAP_EVIDENCE_AGE_SECONDS):
        raise FibMapBoundTradeBindingAdapterError("FIB_MAP_EVIDENCE_STALE")


def build_fib_map_bound_trade_v1_from_first_fill(
    *,
    fill_event: StrategyOwnedInventoryEventV1,
    map_evidence: CanonicalFibMapEvidenceV1,
) -> FibMapBoundTradeV1:
    """Pure construction: no I/O, no repository, no execution intent.

    Raises ``FibMapBoundTradeBindingAdapterError`` for lineage/identity/
    freshness problems this adapter owns, and
    ``src.decision_gate.fib_map_bound_trade_v1.FibMapBoundTradeError`` for
    structural geometry/identity problems already owned by B1's validator
    (anchor ordering, non-finite/non-positive prices, empty target ladder,
    etc.) -- this function never re-implements that validation.
    """
    _validate_fill_event_for_binding(fill_event)
    _validate_identity_consistency(fill_event=fill_event, map_evidence=map_evidence)
    bound_ts_utc = fill_event.occurred_ts_utc
    _validate_map_evidence_freshness(
        map_evidence=map_evidence,
        bound_ts_utc=bound_ts_utc,
    )

    binding = FibMapBoundTradeV1(
        binding_id=derive_fib_map_bound_trade_binding_id_v1(
            fill_event=fill_event, map_evidence=map_evidence,
        ),
        trading_account_id=fill_event.trading_account_id,
        venue=fill_event.venue,
        market=fill_event.market,
        strategy_bucket_id=fill_event.strategy_bucket_id,
        strategy_id=fill_event.strategy_id,
        strategy_version=fill_event.strategy_version,
        trade_id=fill_event.trade_id,
        source_execution_plan_id=fill_event.source_execution_plan_id,
        source_buy_fill_id=fill_event.source_fill_id,
        native_map_id=map_evidence.native_map_id,
        map_cycle_id=map_evidence.map_cycle_id,
        map_structure_hash=map_evidence.map_structure_hash,
        map_source_name=map_evidence.map_source_name,
        map_source_version=map_evidence.map_source_version,
        map_asof_ts_utc=map_evidence.map_asof_ts_utc,
        map_published_at_utc=map_evidence.map_published_at_utc,
        anchor_start_ts_utc=map_evidence.anchor_start_ts_utc,
        anchor_end_ts_utc=map_evidence.anchor_end_ts_utc,
        anchor_low_price=map_evidence.anchor_low_price,
        anchor_high_price=map_evidence.anchor_high_price,
        breakout_gate_price=map_evidence.breakout_gate_price,
        invalidation_price=map_evidence.invalidation_price,
        target_levels=map_evidence.target_levels,
        target_ladder_semantics_version=map_evidence.target_ladder_semantics_version,
        bound_ts_utc=bound_ts_utc,
    )
    validate_fib_map_bound_trade_v1(binding)
    return binding


def bind_fib_map_bound_trade_on_first_fill_v1(
    *,
    fill_event: StrategyOwnedInventoryEventV1,
    map_evidence: CanonicalFibMapEvidenceV1,
    repository: FibMapBoundTradeRepositoryV1,
) -> FibMapBoundTradeV1:
    """Construct the immutable binding, then persist it through B6.

    Idempotent replay and fail-closed conflicting-rebind behavior are both
    provided by ``repository.record_fib_map_bound_trade_v1`` (B6) against its
    existing unique keys; this function adds no additional persistence logic.
    """
    binding = build_fib_map_bound_trade_v1_from_first_fill(
        fill_event=fill_event,
        map_evidence=map_evidence,
    )
    return repository.record_fib_map_bound_trade_v1(binding=binding)
