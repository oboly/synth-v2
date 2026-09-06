"""Issue #753 B8: PAPER resting-order ``ACTIVE -> FILLED`` reconciliation.

``src/executor/paper_order_adapter_v1.py`` (Issue #753 B5.5) is explicitly
submission-time-only: a non-crossing PAPER order rests ``ACTIVE`` forever and
that adapter never later re-evaluates it. This module is the deliberately
deferred later phase that closes exactly that gap, and only that gap.

V1 reconciliation contract, deliberately the smallest deterministic rule that
is honest about what PAPER mode can know:

- **Fill-on-through only, never fill-on-touch.** A resting BUY leg fills only
  when the current best ask is strictly below its limit price; a resting
  SELL leg fills only when the current best bid is strictly above its limit
  price. Equality leaves the leg ``ACTIVE`` unchanged, because this V1 has no
  queue-priority model: a real resting order at the touch price may or may
  not be next in the book, and this is a conservative deterministic PAPER
  simulation, not broker truth.
- **Full-fill-only, matching the existing V1 adapter.** ``ExecutionLegV1``
  has no partial-filled-quantity field; this module does not invent one.
- **Evidence health is not lifecycle state.** Per
  ``docs/ops/state_model_discipline_v1.md``: missing, malformed, mismatched,
  future-dated, or stale quote evidence -- or a quote no later than the
  leg's own persisted resting-since time (``executor_paper_order_placement``
  .created_ts_utc, reused unchanged, no new schema) -- fails closed by
  raising ``PaperMarketEvidenceUnavailableError``. Callers must leave the
  leg's persisted ``ACTIVE`` state untouched on that raise; this module never
  converts a temporary evidence-health problem into a lifecycle transition.
- **The only lifecycle mutation is the executor-owned, PAPER-specific CAS**
  ``ExecutionLegRepositoryV1.resolve_paper_resting_fill_v1`` -- idempotent
  replay-safe, conflicts on incompatible current state/identity, preserves
  ``broker_order_id``.

No network, credential, or broker call is made anywhere in this module.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.executor.execution_leg_v1 import ACTIVE, ExecutionLegRepositoryV1, ExecutionLegV1
from src.executor.paper_order_adapter_v1 import (
    PaperMarketEvidenceUnavailableError,
    PaperMarketQuoteProviderV1,
    PaperMarketQuoteV1,
)

SIDE_BUY = "BUY"
SIDE_SELL = "SELL"

PAPER_RESTING_FILL_RAW_STATUS = "PAPER_RESTING_ORDER_FILLED_ON_THROUGH"


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _aware_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _valid_quote_shape(quote: PaperMarketQuoteV1) -> bool:
    return (
        isinstance(quote.market, str)
        and bool(quote.market.strip())
        and isinstance(quote.best_bid, Decimal)
        and quote.best_bid.is_finite()
        and quote.best_bid > 0
        and isinstance(quote.best_ask, Decimal)
        and quote.best_ask.is_finite()
        and quote.best_ask > 0
        and quote.best_bid <= quote.best_ask
        and _aware(quote.observed_ts_utc)
    )


def paper_resting_order_would_fill_through_v1(
    *, side: str, limit_price: Decimal, quote: PaperMarketQuoteV1,
) -> bool:
    """Fill-on-through only: equality leaves the resting order ``ACTIVE``
    because real queue priority ahead of it is unknown. Conservative
    deterministic PAPER simulation, not broker truth."""
    if side == SIDE_BUY:
        return quote.best_ask < limit_price
    if side == SIDE_SELL:
        return quote.best_bid > limit_price
    raise ValueError("side must be BUY or SELL")


def evaluate_paper_resting_order_evidence_v1(
    *,
    market: str,
    placement_created_ts_utc: datetime,
    quote: PaperMarketQuoteV1 | None,
    now: datetime,
    max_quote_age_seconds: int,
) -> PaperMarketQuoteV1:
    """Validate resting-fill evidence and return the usable quote, or raise
    ``PaperMarketEvidenceUnavailableError`` with a typed reason. Never
    mutates lifecycle state -- callers must leave the leg's persisted
    ``ACTIVE`` state unchanged on any raise here."""
    if quote is None:
        raise PaperMarketEvidenceUnavailableError("PAPER_RESTING_FILL_EVIDENCE_MISSING")
    if not _valid_quote_shape(quote):
        raise PaperMarketEvidenceUnavailableError("PAPER_RESTING_FILL_EVIDENCE_MALFORMED")
    if quote.market != market:
        raise PaperMarketEvidenceUnavailableError("PAPER_RESTING_FILL_EVIDENCE_MARKET_MISMATCH")
    if not _aware(now):
        raise PaperMarketEvidenceUnavailableError("PAPER_RESTING_FILL_CLOCK_NOT_AWARE")
    age_seconds = (now - quote.observed_ts_utc).total_seconds()
    if age_seconds < 0:
        raise PaperMarketEvidenceUnavailableError("PAPER_RESTING_FILL_EVIDENCE_FUTURE_TIMESTAMP")
    if age_seconds > max_quote_age_seconds:
        raise PaperMarketEvidenceUnavailableError("PAPER_RESTING_FILL_EVIDENCE_STALE")
    if quote.observed_ts_utc <= _aware_utc(placement_created_ts_utc):
        raise PaperMarketEvidenceUnavailableError(
            "PAPER_RESTING_FILL_EVIDENCE_NOT_LATER_THAN_PLACEMENT"
        )
    return quote


def reconcile_paper_resting_order_fill_v1(
    *,
    leg: ExecutionLegV1,
    placement_created_ts_utc: datetime,
    quote_provider: PaperMarketQuoteProviderV1,
    max_quote_age_seconds: int,
    now: datetime,
    leg_repository: ExecutionLegRepositoryV1,
) -> ExecutionLegV1:
    """Attempt one PAPER resting-order ``ACTIVE -> FILLED`` reconciliation
    for one already-``ACTIVE`` leg. Raises
    ``PaperMarketEvidenceUnavailableError`` (leaving the leg's persisted
    ``ACTIVE`` state untouched) on bad evidence. Returns the leg unchanged
    (still ``ACTIVE``) when the quote does not cross through the limit price.
    Only transitions to ``FILLED`` via the executor-owned, PAPER-specific CAS
    ``ExecutionLegRepositoryV1.resolve_paper_resting_fill_v1``, which is
    itself idempotent and conflict-safe.
    """
    if leg.state != ACTIVE:
        raise ValueError("PAPER_RESTING_FILL_REQUIRES_ACTIVE_LEG")
    if not isinstance(leg.broker_order_id, str) or not leg.broker_order_id.strip():
        raise ValueError("PAPER_RESTING_FILL_REQUIRES_BROKER_ORDER_ID")
    if leg.execution_leg_id is None:
        raise ValueError("PAPER_RESTING_FILL_REQUIRES_PERSISTED_LEG_ID")
    quote = quote_provider.latest_quote(market=leg.market)
    validated_quote = evaluate_paper_resting_order_evidence_v1(
        market=leg.market,
        placement_created_ts_utc=placement_created_ts_utc,
        quote=quote,
        now=now,
        max_quote_age_seconds=max_quote_age_seconds,
    )
    if not paper_resting_order_would_fill_through_v1(
        side=leg.side, limit_price=leg.price, quote=validated_quote,
    ):
        return leg
    return leg_repository.resolve_paper_resting_fill_v1(
        leg.execution_leg_id,
        broker_order_id=leg.broker_order_id,
        broker_raw_status=PAPER_RESTING_FILL_RAW_STATUS,
    )
