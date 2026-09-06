"""Issue #753 B7.5: executor-owned ``ACTIVE`` -> ``FILLED`` reconciliation for
one resting PAPER leg, given fresh market evidence that strictly priced
through the resting limit.

``src/executor/paper_order_adapter_v1.py`` (B5.5) is explicitly and
deliberately submission-time-only: a non-crossing post-only order rests
``ACTIVE`` and that adapter never later re-polls it. This module is the
narrowly-scoped follow-on that closes exactly that documented gap -- nothing
else. It never writes to ``executor_paper_order_placement``: that table is
immutable placement-ack history, read here only to prove resting-since
evidence and exact order identity (see below).

Fill semantics are deliberately minimal, deterministic, and strict:

- **Price-through only, not touch.** BUY fills only when the fresh best ask
  has moved *strictly below* the resting limit price
  (``best_ask < price``); SELL fills only when the fresh best bid has moved
  *strictly above* it (``best_bid > price``). Exact equality leaves the leg
  ``ACTIVE`` unchanged: this adapter has no queue-position evidence, so it
  cannot claim a resting order at the front of the book actually traded at a
  price the market merely reached once.
- No partial fill is ever simulated and no queue-position claim is made: a
  strict price-through is a full fill of the leg's own persisted
  ``quantity``, exactly like B5.5's placement-time fill-or-rest decision.
- A quote that does not price through the resting limit leaves the leg
  ``ACTIVE`` unchanged -- this is a legitimate business outcome, not a
  failure.
- **The fresh quote must be proven to postdate this leg's own PAPER
  placement.** ``executor_paper_order_placement.created_ts_utc`` (the
  durable record B5.5's adapter wrote before this leg could ever rest) is
  the authoritative resting-since evidence. A quote observed at or before
  that timestamp cannot possibly reflect market movement since the order was
  placed, so it must not be trusted to fill it. The placement record's exact
  identity (market, client_order_id, side, price, quantity, broker_order_id,
  and ``ACTIVE`` placement state) must also match the leg being reconciled;
  a missing or conflicting placement record fails closed and leaves the leg
  ``ACTIVE``.
- **PAPER-only.** The caller-supplied ``ExecutionHandoffV1`` must be exactly
  the PAPER handoff this leg belongs to (``executor_mode`` and
  handoff/account/venue/market/side identity all match the leg). A
  LIVE/DRY_RUN handoff, or any identity mismatch, fails closed without
  reading market evidence or mutating anything.
- Missing, malformed, market-mismatched, future-dated, or stale (older than
  ``max_quote_age_seconds``) quote evidence fails closed by raising
  ``PaperMarketEvidenceUnavailableError`` -- the same fail-closed contract
  B5.5's placement adapter already uses, reusing its own validation so the
  two paths can never silently diverge on what counts as valid evidence.
  Missing/conflicting placement evidence, a non-``ACTIVE`` placement, or a
  quote that does not postdate placement raises
  ``PaperRestingPlacementEvidenceError`` instead -- a distinct, typed reason
  so callers and logs never conflate "no market evidence" with "no proof
  this quote postdates placement". Neither error is a new lifecycle state:
  both leave the leg's persisted state untouched (still ``ACTIVE``).
- Replaying an already-``FILLED`` leg is idempotent: this function reads the
  leg's *current* persisted state first and returns it unchanged without ever
  requiring a fresh quote for a leg that is already resolved.
- The guarded ``ACTIVE -> FILLED`` write is an explicit compare-and-swap on
  both ``state`` and the leg's own already-persisted ``broker_order_id``
  (``ExecutionLegRepositoryV1.mark_active_filled_price_through_v1``): replay
  of the identical ``FILLED`` state with the identical ``broker_order_id`` is
  idempotent; any other current state, or a ``broker_order_id`` mismatch, is
  a conflict.

This module only ever transitions a leg it is directly handed; it does not
scan or list legs itself. Composing callers (e.g.
``src/entry_policy/automatic_buy_paper_fill_execution_v1.py``) decide which
persisted legs to reconcile and in what order, and must never hand this
function a leg that was itself just placed in the same invocation (this
module has no way to know that on its own; see the composing caller's own
pre-submit-state contract).

No network, credential, or broker call is made anywhere in this module.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=unchanged
execution_planner=unchanged
executor=extended (new resting-order reconciliation only; existing state
machine/table triggers unchanged; executor_paper_order_placement read-only)
"""
from __future__ import annotations

from typing import Callable
from datetime import datetime

from src.executor.broker_ack_classification_v1 import BrokerAckStateV1
from src.executor.execution_handoff_v1 import RUNTIME_MODE_PAPER, ExecutionHandoffRepositoryV1, ExecutionHandoffV1
from src.executor.execution_leg_v1 import ACTIVE, FILLED, ExecutionLegRepositoryV1, ExecutionLegV1
from src.executor.paper_order_adapter_v1 import (
    PaperMarketEvidenceUnavailableError,
    PaperMarketQuoteProviderV1,
    PaperMarketQuoteV1,
    PaperOrderPlacementRepository,
    _aware,
    _valid_quote_shape,
)

SIDE_BUY = "BUY"
SIDE_SELL = "SELL"

PAPER_RAW_STATUS_FILLED_PRICE_THROUGH = "PAPER_FILLED_PRICE_THROUGH_RESTING_RECONCILIATION"


class PaperRestingLegNotReconcilableError(ValueError):
    """Leg is not in a state this reconciliation function may act on."""


class PaperRestingHandoffMismatchError(RuntimeError):
    """Handoff is not exactly the PAPER handoff this resting leg belongs to."""


class PaperRestingPlacementEvidenceError(RuntimeError):
    """Placement identity/state/resting-since evidence is missing, conflicts
    with the leg, or does not postdate the leg's own PAPER placement."""


def _priced_through(*, side: str, resting_price: object, quote: PaperMarketQuoteV1) -> bool:
    if side == SIDE_BUY:
        return quote.best_ask < resting_price
    if side == SIDE_SELL:
        return quote.best_bid > resting_price
    raise ValueError("side must be BUY or SELL")


def _verify_paper_handoff_identity(handoff: ExecutionHandoffV1, leg: ExecutionLegV1) -> None:
    if handoff.executor_mode != RUNTIME_MODE_PAPER:
        raise PaperRestingHandoffMismatchError("PAPER_RESTING_RECONCILIATION_REQUIRES_PAPER_HANDOFF")
    if (
        handoff.handoff_id != leg.handoff_id
        or handoff.trading_account_id != leg.trading_account_id
        or handoff.venue != leg.venue
        or handoff.market != leg.market
        or handoff.side != leg.side
    ):
        raise PaperRestingHandoffMismatchError(
            "PAPER_RESTING_RECONCILIATION_HANDOFF_IDENTITY_MISMATCH"
        )


def _verify_placement_evidence(
    leg: ExecutionLegV1,
    *,
    placement_repository: PaperOrderPlacementRepository,
    quote: PaperMarketQuoteV1,
) -> None:
    placement = placement_repository.find_placement_record(
        market=leg.market, client_order_id=leg.client_order_id,
    )
    if placement is None:
        raise PaperRestingPlacementEvidenceError("PAPER_PLACEMENT_RECORD_MISSING")
    if (
        placement.market != leg.market
        or placement.client_order_id != leg.client_order_id
        or placement.side != leg.side
        or placement.price != leg.price
        or placement.quantity != leg.quantity
        or placement.ack.broker_order_id != leg.broker_order_id
    ):
        raise PaperRestingPlacementEvidenceError("PAPER_PLACEMENT_IDENTITY_MISMATCH")
    if placement.ack.state is not BrokerAckStateV1.ACTIVE:
        raise PaperRestingPlacementEvidenceError("PAPER_PLACEMENT_NOT_ACTIVE")
    if not _aware(placement.created_ts_utc):
        raise PaperRestingPlacementEvidenceError("PAPER_PLACEMENT_CREATED_TS_NOT_AWARE")
    if quote.observed_ts_utc <= placement.created_ts_utc:
        raise PaperRestingPlacementEvidenceError("PAPER_MARKET_EVIDENCE_NOT_AFTER_PLACEMENT")


def reconcile_paper_resting_leg_v1(
    leg: ExecutionLegV1,
    *,
    handoff_repository: ExecutionHandoffRepositoryV1,
    quote_provider: PaperMarketQuoteProviderV1,
    placement_repository: PaperOrderPlacementRepository,
    max_quote_age_seconds: int,
    now_fn: Callable[[], datetime],
    leg_repository: ExecutionLegRepositoryV1,
) -> ExecutionLegV1:
    """Reconcile one persisted resting PAPER leg against fresh market evidence.

    Re-read both the leg and its parent handoff from canonical executor
    repositories before any simulated fill decision. This prevents stale
    caller objects or a fabricated/non-PAPER handoff from authorizing a PAPER
    lifecycle transition.
    """
    if leg.execution_leg_id is None:
        raise ValueError("PAPER_RESTING_RECONCILIATION_REQUIRES_PERSISTED_LEG_ID")
    persisted_leg = leg_repository.find(leg.execution_leg_id)
    if persisted_leg is None:
        raise PaperRestingLegNotReconcilableError("PAPER_RESTING_EXECUTION_LEG_NOT_FOUND")
    identity_fields = (
        "execution_leg_id", "handoff_id", "leg_index", "trading_account_id",
        "venue", "market", "side", "client_order_id", "price", "quantity",
        "broker_order_id",
    )
    if any(getattr(persisted_leg, field) != getattr(leg, field) for field in identity_fields):
        raise PaperRestingLegNotReconcilableError("PAPER_RESTING_EXECUTION_LEG_IDENTITY_MISMATCH")
    leg = persisted_leg

    handoff = handoff_repository.find(leg.handoff_id)
    if handoff is None:
        raise PaperRestingHandoffMismatchError("PAPER_RESTING_RECONCILIATION_HANDOFF_NOT_FOUND")
    _verify_paper_handoff_identity(handoff, leg)

    if leg.state == FILLED:
        return leg
    if leg.state != ACTIVE:
        raise PaperRestingLegNotReconcilableError(
            "PAPER_RESTING_RECONCILIATION_REQUIRES_ACTIVE_OR_FILLED_LEG"
        )
    if leg.side not in (SIDE_BUY, SIDE_SELL):
        raise ValueError("side must be BUY or SELL")
    if not isinstance(leg.broker_order_id, str) or not leg.broker_order_id.strip():
        raise ValueError("PAPER_RESTING_RECONCILIATION_REQUIRES_BROKER_ORDER_ID")

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

    _verify_placement_evidence(leg, placement_repository=placement_repository, quote=quote)

    if not _priced_through(side=leg.side, resting_price=leg.price, quote=quote):
        return leg

    return leg_repository.mark_active_filled_price_through_v1(
        leg.execution_leg_id,
        expected_broker_order_id=leg.broker_order_id,
        broker_raw_status=PAPER_RAW_STATUS_FILLED_PRICE_THROUGH,
    )
