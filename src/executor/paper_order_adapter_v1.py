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

- A leg fills fully (its whole immutable, already-approved ``quantity``) or
  not at all. There is no partial-fill simulation: ``ExecutionLegV1`` itself
  carries no partial-filled-quantity field to record one, and inventing a
  parallel field would be exactly the kind of hidden state this phase must
  avoid.
- Whether a leg fills is decided by one caller-supplied, repository-backed
  market quote per market (``PaperMarketQuoteProviderV1``), never by wallet
  balance, broker state, or hidden adapter memory. A BUY leg fills only when
  the quote price is at or below the leg's limit price (marketable); a SELL
  leg fills only when the quote price is at or above it.
- Missing, mismatched, future-dated, or stale (older than
  ``max_quote_age_seconds``) evidence fails closed: ``place_order`` raises
  rather than guessing, which the shared submission orchestrator already
  turns into ``SUBMISSION_UNCERTAIN`` -> (since no broker order was ever
  really placed) ``RECONCILIATION_REQUIRED`` on the next attempt -- the same
  reviewed terminal safety state used for a real ambiguous broker failure,
  not a new bespoke state.
- A non-marketable-but-valid quote is a legitimate business outcome (a
  passive limit order simply has not crossed yet), not a failure: the leg
  stays ``ACTIVE``.

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

PAPER_RAW_STATUS_FILLED = "PAPER_FILLED_AT_MARKET_EVIDENCE"
PAPER_RAW_STATUS_ACTIVE = "PAPER_ACTIVE_AWAITING_MARKETABLE_EVIDENCE"


class PaperMarketEvidenceUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class PaperMarketQuoteV1:
    """One caller-supplied/repository-backed current price for one market."""

    market: str
    price: Decimal
    observed_ts_utc: datetime


class PaperMarketQuoteProviderV1(Protocol):
    def latest_quote(self, *, market: str) -> PaperMarketQuoteV1 | None: ...


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _valid_quote_shape(quote: PaperMarketQuoteV1) -> bool:
    return (
        isinstance(quote.market, str)
        and bool(quote.market.strip())
        and isinstance(quote.price, Decimal)
        and quote.price.is_finite()
        and quote.price > 0
        and _aware(quote.observed_ts_utc)
    )


def _marketable(*, side: str, order_price: Decimal, quote_price: Decimal) -> bool:
    if side == SIDE_BUY:
        return quote_price <= order_price
    if side == SIDE_SELL:
        return quote_price >= order_price
    raise ValueError("side must be BUY or SELL")


@dataclass(frozen=True)
class PaperOrderPlacementAdapterV1:
    """Deterministic, evidence-gated PAPER adapter for one shared-executor
    submission call. Stateless across calls by design: ``find_order_by_client_order_id``
    always reports no order, which is truthful -- when ``place_order`` fails
    closed on bad evidence, no order was ever really placed anywhere to find.
    """

    quote_provider: PaperMarketQuoteProviderV1
    max_quote_age_seconds: int
    now_fn: Callable[[], datetime]

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
        del quantity, operator_id
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
        broker_order_id = f"paper-{client_order_id}"
        if _marketable(side=side, order_price=price, quote_price=quote.price):
            return OrderAckV1(
                broker_order_id=broker_order_id,
                state=BrokerAckStateV1.FILLED,
                broker_raw_status=PAPER_RAW_STATUS_FILLED,
            )
        return OrderAckV1(
            broker_order_id=broker_order_id,
            state=BrokerAckStateV1.ACTIVE,
            broker_raw_status=PAPER_RAW_STATUS_ACTIVE,
        )

    def find_order_by_client_order_id(
        self, *, market: str, client_order_id: str
    ) -> OrderAckV1 | None:
        del market, client_order_id
        return None


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
