"""Issue #753 B7.5: executor-owned ``ACTIVE`` -> ``FILLED`` reconciliation for
one resting PAPER leg, given fresh market evidence.

``src/executor/paper_order_adapter_v1.py`` (B5.5) is explicitly and
deliberately submission-time-only: a non-crossing post-only order rests
``ACTIVE`` and that adapter never later re-polls it. This module is the
narrowly-scoped follow-on that closes exactly that documented gap -- nothing
else. It does not touch placement: ``executor_paper_order_placement`` is
immutable placement-ack history and this module never reads or writes it.

Fill semantics are deliberately minimal and deterministic, matching a resting
limit order actually touched by the market, not a broker fill report:

- BUY fills when the fresh best ask has moved to or through the resting
  limit price (``best_ask <= price``).
- SELL fills when the fresh best bid has moved to or through the resting
  limit price (``best_bid >= price``).
- No partial fill is ever simulated and no queue-position claim is made: a
  touch is a full fill of the leg's own persisted ``quantity``, exactly like
  B5.5's placement-time fill-or-rest decision.
- A quote that does not touch the resting price leaves the leg ``ACTIVE``
  unchanged -- this is a legitimate business outcome, not a failure.
- Missing, malformed, market-mismatched, future-dated, or stale (older than
  ``max_quote_age_seconds``) evidence fails closed by raising
  ``PaperMarketEvidenceUnavailableError`` -- the same fail-closed contract
  B5.5's placement adapter already uses, reusing its own validation so the
  two paths can never silently diverge on what counts as valid evidence.
- Replaying an already-``FILLED`` leg is idempotent: this function reads the
  leg's *current* persisted state first and returns it unchanged without ever
  requiring a fresh quote for a leg that is already resolved.

This module only ever transitions a leg it is directly handed; it does not
scan or list legs itself. Composing callers (e.g.
``src/entry_policy/automatic_buy_paper_fill_execution_v1.py``) decide which
persisted legs to reconcile and in what order.

No network, credential, or broker call is made anywhere in this module.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=unchanged
execution_planner=unchanged
executor=extended (new resting-order reconciliation only; existing state
machine/table triggers unchanged)
"""
from __future__ import annotations

from typing import Callable
from datetime import datetime

from src.executor.execution_leg_v1 import ACTIVE, FILLED, ExecutionLegRepositoryV1, ExecutionLegV1
from src.executor.paper_order_adapter_v1 import (
    PaperMarketEvidenceUnavailableError,
    PaperMarketQuoteProviderV1,
    PaperMarketQuoteV1,
    _aware,
    _valid_quote_shape,
)

SIDE_BUY = "BUY"
SIDE_SELL = "SELL"

PAPER_RAW_STATUS_FILLED_ON_TOUCH = "PAPER_FILLED_ON_TOUCH_RESTING_RECONCILIATION"


class PaperRestingLegNotReconcilableError(ValueError):
    """Leg is not in a state this reconciliation function may act on."""


def _touched(*, side: str, resting_price: object, quote: PaperMarketQuoteV1) -> bool:
    if side == SIDE_BUY:
        return quote.best_ask <= resting_price
    if side == SIDE_SELL:
        return quote.best_bid >= resting_price
    raise ValueError("side must be BUY or SELL")


def reconcile_paper_resting_leg_v1(
    leg: ExecutionLegV1,
    *,
    quote_provider: PaperMarketQuoteProviderV1,
    max_quote_age_seconds: int,
    now_fn: Callable[[], datetime],
    leg_repository: ExecutionLegRepositoryV1,
) -> ExecutionLegV1:
    """Reconcile one persisted resting PAPER leg against fresh market
    evidence. ``leg`` must be the caller's own current read of the leg
    (typically ``leg_repository.find`` / ``find_by_handoff_and_index``); this
    function does not re-read it before deciding replay-vs-evaluate.
    """
    if leg.state == FILLED:
        return leg
    if leg.state != ACTIVE:
        raise PaperRestingLegNotReconcilableError(
            "PAPER_RESTING_RECONCILIATION_REQUIRES_ACTIVE_OR_FILLED_LEG"
        )
    if leg.side not in (SIDE_BUY, SIDE_SELL):
        raise ValueError("side must be BUY or SELL")

    quote = quote_provider.latest_quote(market=leg.market)
    if quote is None:
        raise PaperMarketEvidenceUnavailableError("PAPER_MARKET_EVIDENCE_MISSING")
    if not _valid_quote_shape(quote):
        raise PaperMarketEvidenceUnavailableError("PAPER_MARKET_EVIDENCE_MALFORMED")
    if quote.market != leg.market:
        raise PaperMarketEvidenceUnavailableError("PAPER_MARKET_EVIDENCE_MARKET_MISMATCH")
    now = now_fn()
    if not _aware(now):
        raise PaperMarketEvidenceUnavailableError("PAPER_ADAPTER_CLOCK_NOT_AWARE")
    age_seconds = (now - quote.observed_ts_utc).total_seconds()
    if age_seconds < 0:
        raise PaperMarketEvidenceUnavailableError("PAPER_MARKET_EVIDENCE_FUTURE_TIMESTAMP")
    if age_seconds > max_quote_age_seconds:
        raise PaperMarketEvidenceUnavailableError("PAPER_MARKET_EVIDENCE_STALE")

    if not _touched(side=leg.side, resting_price=leg.price, quote=quote):
        return leg

    if leg.execution_leg_id is None:
        raise ValueError("PAPER_RESTING_RECONCILIATION_REQUIRES_PERSISTED_LEG_ID")
    return leg_repository.mark_active_filled_on_touch(
        leg.execution_leg_id, broker_raw_status=PAPER_RAW_STATUS_FILLED_ON_TOUCH,
    )
