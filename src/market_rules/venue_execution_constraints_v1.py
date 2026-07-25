"""
venue_execution_constraints_v1 — canonical venue/market execution metadata contract.

Layer: public market metadata. Account-agnostic. No broker private calls.

Extends the venue metadata contract beyond price-tick size alone
(src.market_rules.price_tick_normalization_v1) to cover the full set required
before any execution-plan leg can be validated:

  tick_size, qty_step_size, min_base_quantity, min_quote_notional,
  supported_order_types, supported_time_in_force, source_provenance,
  metadata_synced_ts_utc

Fail-closed: resolve_venue_execution_constraints() returns a MISSING or
STALE result rather than guessing; callers must treat both as blocking, the
same discipline price_tick_normalization_v1 already uses for MISSING_TICK_RULE.

No asset-specific values are hardcoded here, in decision_gate, or in
execution_planner — this module and its DB-backed source
(venue_execution_constraint table) are the only path. Per-venue resolution
(e.g. Bitvavo) is isolated in src.market_rules.bitvavo_venue_adapter_v1.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Final


STATUS_FRESH: Final[str] = "FRESH"
STATUS_STALE: Final[str] = "STALE"
STATUS_MISSING: Final[str] = "MISSING"

DEFAULT_MAX_METADATA_AGE_SECONDS: Final[int] = 7 * 24 * 3600  # 7 days

SOURCE_BITVAVO_PUBLIC_MARKETS_API_V2: Final[str] = "BITVAVO_PUBLIC_MARKETS_API_V2"
SOURCE_MISSING: Final[str] = "MISSING"


@dataclass(frozen=True)
class VenueExecutionConstraints:
    venue: str
    market: str
    tick_size: Decimal
    qty_step_size: Decimal
    min_base_quantity: Decimal
    min_quote_notional: Decimal
    supported_order_types: tuple[str, ...]
    supported_time_in_force: tuple[str, ...]
    source_provenance: str
    metadata_synced_ts_utc: datetime
    status: str  # FRESH | STALE | MISSING


def _missing(venue: str, market: str) -> VenueExecutionConstraints:
    return VenueExecutionConstraints(
        venue=venue,
        market=market,
        tick_size=Decimal("0"),
        qty_step_size=Decimal("0"),
        min_base_quantity=Decimal("0"),
        min_quote_notional=Decimal("0"),
        supported_order_types=(),
        supported_time_in_force=(),
        source_provenance=SOURCE_MISSING,
        metadata_synced_ts_utc=datetime.min.replace(tzinfo=timezone.utc),
        status=STATUS_MISSING,
    )


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def load_constraints_from_db(
    conn: Any,
    *,
    venue: str,
    markets: list[str],
) -> dict[str, VenueExecutionConstraints]:
    """Load rows from venue_execution_constraint for the given markets.

    Returns only markets with a matching row; callers must resolve the rest
    through resolve_venue_execution_constraints, which returns MISSING for
    anything absent here rather than guessing.
    """
    if not markets:
        return {}
    placeholders = ", ".join(["%s"] * len(markets))
    sql = (
        "SELECT market, tick_size, qty_step_size, min_base_quantity, "
        "min_quote_notional, supported_order_types, supported_time_in_force, "
        "source_provenance, metadata_synced_ts_utc "
        "FROM venue_execution_constraint "
        f"WHERE venue = %s AND market IN ({placeholders})"
    )
    params: tuple[Any, ...] = (venue, *markets)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    except Exception:
        return {}

    result: dict[str, VenueExecutionConstraints] = {}
    for row in rows:
        market = str(row["market"])
        result[market] = VenueExecutionConstraints(
            venue=venue,
            market=market,
            tick_size=Decimal(str(row["tick_size"])),
            qty_step_size=Decimal(str(row["qty_step_size"])),
            min_base_quantity=Decimal(str(row["min_base_quantity"])),
            min_quote_notional=Decimal(str(row["min_quote_notional"])),
            supported_order_types=tuple(str(row["supported_order_types"]).split(",")),
            supported_time_in_force=tuple(str(row["supported_time_in_force"]).split(",")),
            source_provenance=str(row["source_provenance"]),
            metadata_synced_ts_utc=_ensure_aware(row["metadata_synced_ts_utc"]),
            status=STATUS_FRESH,  # staleness is computed relative to "now" by the caller below
        )
    return result


def resolve_venue_execution_constraints(
    *,
    venue: str,
    market: str,
    db_rows: dict[str, VenueExecutionConstraints] | None,
    now: datetime,
    max_age_seconds: int = DEFAULT_MAX_METADATA_AGE_SECONDS,
) -> VenueExecutionConstraints:
    """Resolve constraints for one market: DB-first, fail closed otherwise.

    Never falls back to a hardcoded per-asset table. Returns status=MISSING
    when no row exists and status=STALE when the row is older than
    max_age_seconds; both must be treated as blocking by callers.
    """
    row = (db_rows or {}).get(market)
    if row is None:
        return _missing(venue, market)

    now_aware = _ensure_aware(now)
    age = now_aware - row.metadata_synced_ts_utc
    if age > timedelta(seconds=max_age_seconds) or age < timedelta(0):
        return VenueExecutionConstraints(
            venue=row.venue,
            market=row.market,
            tick_size=row.tick_size,
            qty_step_size=row.qty_step_size,
            min_base_quantity=row.min_base_quantity,
            min_quote_notional=row.min_quote_notional,
            supported_order_types=row.supported_order_types,
            supported_time_in_force=row.supported_time_in_force,
            source_provenance=row.source_provenance,
            metadata_synced_ts_utc=row.metadata_synced_ts_utc,
            status=STATUS_STALE,
        )

    return row


def is_usable(constraints: VenueExecutionConstraints) -> bool:
    return constraints.status == STATUS_FRESH
