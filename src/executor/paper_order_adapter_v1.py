"""Issue #753 B5.5: truthful PAPER order-placement adapter for the shared
executor handoff path (``src/executor/execution_submission_orchestrator_v1.py``).

This is not a synthetic TEST fallback and does not weaken or replace the
existing ``PAPER_ADAPTER_NOT_CONFIGURED`` guard in
``src/executor/shared_execution_runtime_v1.py`` -- that guard protects the
fully decoupled, side-neutral shared-executor runtime, which has no per-plan
strategy identity to reconcile ownership with. This adapter is a separate,
narrowly-scoped composition for callers (see
``src/entry_policy/automatic_buy_paper_fill_execution_v1.py``) that already
hold that identity and submit synchronously.

V1 fill semantics, deliberately minimal and deterministic:

- Every leg this adapter ever receives is a post-only limit order: every
  execution planner in this repository (``automatic_buy_planner_v1``,
  ``automatic_exit_planner_v1``, ``fib_map_bound_exit_planner_v1``,
  ``contract_preview_v1``) hardcodes ``post_only=True`` and no planner ever
  sets it to ``False``. The shared, side-neutral ``OrderPlacementAdapter``
  protocol (``execution_submission_orchestrator_v1.py``) does not carry a
  ``post_only`` flag through to ``place_order`` at all, so this adapter does
  not need one plumbed in: it truthfully models *every* order it is asked to
  place as post-only, matching the only orders that ever reach it.
- A real post-only order can never fill at placement: an exchange rejects a
  post-only order outright if it would immediately cross the book (that is
  what "post-only" means), it never fills it synchronously. So when the
  caller-supplied, repository-backed best-bid/best-ask market quote for the leg's market
  (``PaperMarketQuoteProviderV1``) shows the order would cross on arrival --
  a BUY leg whose limit price is at or above the quote, or a SELL leg whose
  limit price is at or below it -- ``place_order`` returns ``REJECTED``, not
  a synthetic ``FILLED``. This adapter never invents a fill; ``FILLED`` is
  never returned by ``place_order``.
- A quote that would not cross is a legitimate business outcome (a passive
  limit order simply rests on the book), not a failure: the leg stays
  ``ACTIVE``. This is a submission-time-only snapshot decision: this V1
  adapter does not later re-poll or re-evaluate a resting ``ACTIVE`` PAPER
  leg against fresh market evidence to transition it to ``FILLED`` -- exactly
  like the existing shared executor has no automatic later re-reconciliation
  of an ``ACTIVE`` leg for TEST/LIVE either (only ``SUBMISSION_UNCERTAIN``/
  ``RECONCILIATION_REQUIRED`` legs are ever re-resolved, by
  ``execution_order_reconciliation_v1.py``). Any later ladder/reprice/
  fill-on-touch behavior for a resting PAPER order is out of scope for B5.5
  and belongs to a later phase (B6/B7/B8).
- Missing, mismatched, future-dated, or stale (older than
  ``max_quote_age_seconds``) evidence fails closed: ``place_order`` raises
  rather than guessing, which the shared submission orchestrator already
  turns into ``SUBMISSION_UNCERTAIN`` -> (since no broker order was ever
  really placed) ``RECONCILIATION_REQUIRED`` on the next attempt -- the same
  reviewed terminal safety state used for a real ambiguous broker failure,
  not a new bespoke state.
- Every ``ACTIVE``/``REJECTED`` acknowledgement is durably recorded by
  ``placement_repository`` (``src/executor/paper_order_placement_repository_v1.py``)
  *before* ``place_order`` returns it, keyed by the already-globally-unique,
  deterministic ``client_order_id``. ``find_order_by_client_order_id`` reads
  that same record. This closes the #753 B5.5 PR #776 review finding: a
  crash between this adapter's ``ACTIVE`` acknowledgement and
  ``executor_execution_leg`` persistence used to be unrecoverable --
  ``find_order_by_client_order_id`` always reported no order, dead-lettering
  an acknowledged order to ``RECONCILIATION_REQUIRED``. A retry now recovers
  the exact recorded acknowledgement instead.

``paper_broker_cumulative_fill_evidence_from_leg_v1`` remains a pure
FILLED-leg -> fill-evidence converter, preserved for forward compatibility
with any later phase that persists a real FILLED PAPER leg (e.g. B6/B7
ladder/reprice fill-on-touch); this V1 adapter itself never produces one.

No network, credential, or broker call is made anywhere in this module.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Callable, Protocol

from src.executor.broker_ack_classification_v1 import BrokerAckStateV1, OrderAckV1
from src.executor.execution_leg_v1 import FILLED, ExecutionLegV1

SIDE_BUY = "BUY"
SIDE_SELL = "SELL"

PAPER_RAW_STATUS_ACTIVE = "PAPER_ACTIVE_SUBMISSION_TIME_ONLY_NOT_CROSSED"
PAPER_RAW_STATUS_REJECTED_POST_ONLY_WOULD_CROSS = "PAPER_REJECTED_POST_ONLY_WOULD_CROSS"


class PaperMarketEvidenceUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class PaperMarketQuoteV1:
    """One caller-supplied/repository-backed best-bid/best-ask snapshot."""

    market: str
    best_bid: Decimal
    best_ask: Decimal
    observed_ts_utc: datetime


class PaperMarketQuoteProviderV1(Protocol):
    def latest_quote(self, *, market: str) -> PaperMarketQuoteV1 | None: ...


class PaperOrderPlacementRepository(Protocol):
    """Durable, replay-safe store for this adapter's own ACTIVE/REJECTED
    placement decisions. See ``paper_order_placement_repository_v1.py`` for
    the concrete, executor-owned implementation."""

    def record_placement(
        self,
        *,
        market: str,
        client_order_id: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        ack: OrderAckV1,
    ) -> OrderAckV1: ...

    def find_order_by_client_order_id(
        self, *, market: str, client_order_id: str
    ) -> OrderAckV1 | None: ...


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


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


def _would_cross(*, side: str, order_price: Decimal, quote: PaperMarketQuoteV1) -> bool:
    """Evaluate post-only crossing against the correct side of the spread."""
    if side == SIDE_BUY:
        return order_price >= quote.best_ask
    if side == SIDE_SELL:
        return order_price <= quote.best_bid
    raise ValueError("side must be BUY or SELL")


@dataclass(frozen=True)
class PaperOrderPlacementAdapterV1:
    """Deterministic, evidence-gated PAPER adapter for one shared-executor
    submission call. ``place_order`` durably records every ``ACTIVE``/
    ``REJECTED`` acknowledgement it makes into ``placement_repository``
    before returning it; ``find_order_by_client_order_id`` reads that same
    record. When ``place_order`` fails closed on bad evidence, no
    acknowledgement is ever recorded, so a later lookup truthfully reports no
    order -- but an acknowledged order is always recoverable.
    """

    quote_provider: PaperMarketQuoteProviderV1
    max_quote_age_seconds: int
    now_fn: Callable[[], datetime]
    placement_repository: PaperOrderPlacementRepository

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_quote_age_seconds, bool)
            or not isinstance(self.max_quote_age_seconds, int)
            or self.max_quote_age_seconds <= 0
        ):
            raise ValueError("max_quote_age_seconds must be a positive integer")

    def place_order(
        self,
        *,
        market: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        client_order_id: str,
        operator_id: int,
    ) -> OrderAckV1:
        del operator_id
        if side not in (SIDE_BUY, SIDE_SELL):
            raise ValueError("side must be BUY or SELL")
        quote = self.quote_provider.latest_quote(market=market)
        if quote is None:
            raise PaperMarketEvidenceUnavailableError("PAPER_MARKET_EVIDENCE_MISSING")
        if not _valid_quote_shape(quote):
            raise PaperMarketEvidenceUnavailableError("PAPER_MARKET_EVIDENCE_MALFORMED")
        if quote.market != market:
            raise PaperMarketEvidenceUnavailableError("PAPER_MARKET_EVIDENCE_MARKET_MISMATCH")
        now = self.now_fn()
        if not _aware(now):
            raise PaperMarketEvidenceUnavailableError("PAPER_ADAPTER_CLOCK_NOT_AWARE")
        age_seconds = (now - quote.observed_ts_utc).total_seconds()
        if age_seconds < 0:
            raise PaperMarketEvidenceUnavailableError("PAPER_MARKET_EVIDENCE_FUTURE_TIMESTAMP")
        if age_seconds > self.max_quote_age_seconds:
            raise PaperMarketEvidenceUnavailableError("PAPER_MARKET_EVIDENCE_STALE")
        if _would_cross(side=side, order_price=price, quote=quote):
            # A real exchange rejects a crossing post-only order outright; it
            # never fills it synchronously. No broker order was ever really
            # placed, so there is no broker_order_id to report.
            ack = OrderAckV1(
                broker_order_id=None,
                state=BrokerAckStateV1.REJECTED,
                broker_raw_status=PAPER_RAW_STATUS_REJECTED_POST_ONLY_WOULD_CROSS,
            )
        else:
            ack = OrderAckV1(
                broker_order_id=f"paper-{client_order_id}",
                state=BrokerAckStateV1.ACTIVE,
                broker_raw_status=PAPER_RAW_STATUS_ACTIVE,
            )
        # Recorded before returning so a crash after this acknowledgement but
        # before executor_execution_leg persistence is still recoverable by
        # find_order_by_client_order_id below (#753 B5.5 PR #776 review fix).
        return self.placement_repository.record_placement(
            market=market,
            client_order_id=client_order_id,
            side=side,
            price=price,
            quantity=quantity,
            ack=ack,
        )

    def find_order_by_client_order_id(
        self, *, market: str, client_order_id: str
    ) -> OrderAckV1 | None:
        return self.placement_repository.find_order_by_client_order_id(
            market=market, client_order_id=client_order_id,
        )


def paper_broker_cumulative_fill_evidence_from_leg_v1(
    leg: ExecutionLegV1, *, observed_ts_utc: datetime,
) -> "BrokerCumulativeFillEvidenceV1":
    """Build canonical #752 fill evidence from one persisted, FILLED PAPER leg.

    ``executor_execution_leg`` is the repository-backed PAPER fill-quantity
    read authority this phase closes: a FILLED leg's immutable ``quantity``
    is, by this adapter's own V1 semantics, the full cumulative filled amount
    -- there is no partial-fill state to read instead. ``source_snapshot_id``
    is a stable hash of the leg's own persisted identity/state/quantity, so
    replaying the same persisted leg always yields the same snapshot id and
    the same cumulative quantity, which is what #752's reconciliation needs
    for idempotent replay.
    """
    from src.decision_gate.strategy_owned_fill_reconciliation_v1 import (
        BrokerCumulativeFillEvidenceV1,
    )

    if leg.state != FILLED:
        raise ValueError("PAPER_FILL_EVIDENCE_REQUIRES_FILLED_LEG")
    if not isinstance(leg.broker_order_id, str) or not leg.broker_order_id.strip():
        raise ValueError("PAPER_FILL_EVIDENCE_REQUIRES_BROKER_ORDER_ID")
    if not _aware(observed_ts_utc):
        raise ValueError("PAPER_FILL_EVIDENCE_REQUIRES_AWARE_TIMESTAMP")
    payload = "\x1f".join(
        str(part) for part in (
            leg.execution_leg_id, leg.handoff_id, leg.leg_index, leg.broker_order_id,
            leg.state, leg.quantity,
        )
    )
    snapshot_id = f"paper_fill_snapshot_{sha256(payload.encode('utf-8')).hexdigest()}"
    return BrokerCumulativeFillEvidenceV1(
        source_snapshot_id=snapshot_id,
        cumulative_filled_base_quantity=leg.quantity,
        observed_ts_utc=observed_ts_utc,
    )
