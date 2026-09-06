from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.executor.execution_leg_v1 import (
    ACTIVE,
    FILLED,
    PREPARED,
    ExecutionLegConflictError,
    ExecutionLegRepositoryV1,
    ExecutionLegV1,
)
from src.executor.paper_order_adapter_v1 import PaperMarketEvidenceUnavailableError, PaperMarketQuoteV1
from src.executor.paper_resting_order_reconciliation_v1 import (
    PAPER_RESTING_FILL_RAW_STATUS,
    evaluate_paper_resting_order_evidence_v1,
    paper_resting_order_would_fill_through_v1,
    reconcile_paper_resting_order_fill_v1,
)

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
MARKET = "BTC-EUR"


# --- pure fill-on-through decision, BUY and SELL ---


def test_buy_fills_only_strictly_below_limit_price_never_on_touch() -> None:
    below = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("90"), best_ask=Decimal("99"), observed_ts_utc=NOW)
    touch = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("90"), best_ask=Decimal("100"), observed_ts_utc=NOW)
    above = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("90"), best_ask=Decimal("101"), observed_ts_utc=NOW)

    assert paper_resting_order_would_fill_through_v1(side="BUY", limit_price=Decimal("100"), quote=below) is True
    assert paper_resting_order_would_fill_through_v1(side="BUY", limit_price=Decimal("100"), quote=touch) is False
    assert paper_resting_order_would_fill_through_v1(side="BUY", limit_price=Decimal("100"), quote=above) is False


def test_sell_fills_only_strictly_above_limit_price_never_on_touch() -> None:
    below = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("99"), best_ask=Decimal("110"), observed_ts_utc=NOW)
    touch = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("100"), best_ask=Decimal("110"), observed_ts_utc=NOW)
    above = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("101"), best_ask=Decimal("110"), observed_ts_utc=NOW)

    assert paper_resting_order_would_fill_through_v1(side="SELL", limit_price=Decimal("100"), quote=below) is False
    assert paper_resting_order_would_fill_through_v1(side="SELL", limit_price=Decimal("100"), quote=touch) is False
    assert paper_resting_order_would_fill_through_v1(side="SELL", limit_price=Decimal("100"), quote=above) is True


def test_unknown_side_raises() -> None:
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("90"), best_ask=Decimal("99"), observed_ts_utc=NOW)
    with pytest.raises(ValueError):
        paper_resting_order_would_fill_through_v1(side="HOLD", limit_price=Decimal("100"), quote=quote)


# --- evidence validation, fail-closed typed reasons ---


def _evaluate(quote, *, placement_created_ts_utc=NOW - timedelta(hours=1), now=NOW, max_age=30, market=MARKET):
    return evaluate_paper_resting_order_evidence_v1(
        market=market, placement_created_ts_utc=placement_created_ts_utc,
        quote=quote, now=now, max_quote_age_seconds=max_age,
    )


def test_missing_quote_fails_closed() -> None:
    with pytest.raises(PaperMarketEvidenceUnavailableError, match="PAPER_RESTING_FILL_EVIDENCE_MISSING"):
        _evaluate(None)


def test_malformed_quote_fails_closed() -> None:
    malformed = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("110"), best_ask=Decimal("100"), observed_ts_utc=NOW)
    with pytest.raises(PaperMarketEvidenceUnavailableError, match="PAPER_RESTING_FILL_EVIDENCE_MALFORMED"):
        _evaluate(malformed)


def test_mismatched_market_fails_closed() -> None:
    quote = PaperMarketQuoteV1(market="ETH-EUR", best_bid=Decimal("90"), best_ask=Decimal("99"), observed_ts_utc=NOW)
    with pytest.raises(PaperMarketEvidenceUnavailableError, match="PAPER_RESTING_FILL_EVIDENCE_MARKET_MISMATCH"):
        _evaluate(quote)


def test_future_dated_quote_fails_closed() -> None:
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("90"), best_ask=Decimal("99"), observed_ts_utc=NOW + timedelta(seconds=1))
    with pytest.raises(PaperMarketEvidenceUnavailableError, match="PAPER_RESTING_FILL_EVIDENCE_FUTURE_TIMESTAMP"):
        _evaluate(quote)


def test_stale_quote_fails_closed() -> None:
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("90"), best_ask=Decimal("99"), observed_ts_utc=NOW - timedelta(seconds=31))
    with pytest.raises(PaperMarketEvidenceUnavailableError, match="PAPER_RESTING_FILL_EVIDENCE_STALE"):
        _evaluate(quote)


def test_quote_not_later_than_placement_fails_closed() -> None:
    placement_created_ts_utc = NOW - timedelta(seconds=5)
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("90"), best_ask=Decimal("99"), observed_ts_utc=placement_created_ts_utc)
    with pytest.raises(
        PaperMarketEvidenceUnavailableError, match="PAPER_RESTING_FILL_EVIDENCE_NOT_LATER_THAN_PLACEMENT"
    ):
        _evaluate(quote, placement_created_ts_utc=placement_created_ts_utc, now=NOW)


def test_naive_placement_timestamp_is_treated_as_utc() -> None:
    """placement_created_ts_utc read back from MariaDB DATETIME may be
    tz-naive; it must be treated as UTC, matching the repository convention
    used across this codebase (``_aware_utc``)."""
    naive_placement = datetime(2026, 9, 6, 11, 0)  # no tzinfo
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("90"), best_ask=Decimal("99"), observed_ts_utc=NOW)
    result = _evaluate(quote, placement_created_ts_utc=naive_placement)
    assert result is quote


# --- executor-owned CAS transition: idempotent, conflict-safe ---


def _fake_repository_and_leg(*, initial_state: str = ACTIVE) -> tuple[ExecutionLegRepositoryV1, int]:
    rows: dict[int, dict[str, object]] = {}
    next_id = [1]

    def cursor_factory(*, commit: bool = False, database: str | None = None):
        class _Cursor:
            def __init__(self) -> None:
                self.rowcount = 0
                self._selected: dict[str, object] | None = None

            def execute(self, sql: str, params: list[object]) -> None:
                if sql.startswith("UPDATE executor_execution_leg SET state=%s, broker_raw_status=%s"):
                    new_state, broker_raw_status, _reconciled_ts, _updated_ts, leg_id, old_state, broker_order_id = params
                    row = rows.get(leg_id)
                    if row is not None and row["state"] == old_state and row["broker_order_id"] == broker_order_id:
                        row["state"] = new_state
                        row["broker_raw_status"] = broker_raw_status
                        self.rowcount = 1
                    else:
                        self.rowcount = 0
                    return
                if sql.startswith("SELECT * FROM executor_execution_leg WHERE executor_execution_leg_id=%s"):
                    self._selected = rows.get(params[0])
                    return
                raise AssertionError(f"unexpected SQL: {sql}")

            def fetchone(self):
                return self._selected

        class _Ctx:
            def __enter__(self):
                return _Cursor()

            def __exit__(self, *_args):
                return None

        return _Ctx()

    leg_id = next_id[0]
    rows[leg_id] = {
        "executor_execution_leg_id": leg_id, "executor_execution_handoff_id": 1, "leg_index": 1,
        "trading_account_id": 7, "venue": "bitvavo", "market": MARKET, "side": "BUY",
        "client_order_id": "co-1", "operator_id": 73, "price": Decimal("100"), "quantity": Decimal("0.01"),
        "state": initial_state, "broker_order_id": "paper-co-1", "broker_raw_status": "PAPER_ACTIVE_SUBMISSION_TIME_ONLY_NOT_CROSSED",
        "restatement_reason": None, "last_reconciled_ts_utc": None,
    }
    repository = ExecutionLegRepositoryV1(cursor_factory=cursor_factory)
    return repository, leg_id


def test_resolve_paper_resting_fill_transitions_active_to_filled() -> None:
    repository, leg_id = _fake_repository_and_leg()
    leg = repository.resolve_paper_resting_fill_v1(
        leg_id, broker_order_id="paper-co-1", broker_raw_status=PAPER_RESTING_FILL_RAW_STATUS,
    )
    assert leg.state == FILLED
    assert leg.broker_order_id == "paper-co-1"
    assert leg.broker_raw_status == PAPER_RESTING_FILL_RAW_STATUS


def test_resolve_paper_resting_fill_is_idempotent_on_replay() -> None:
    repository, leg_id = _fake_repository_and_leg()
    first = repository.resolve_paper_resting_fill_v1(
        leg_id, broker_order_id="paper-co-1", broker_raw_status=PAPER_RESTING_FILL_RAW_STATUS,
    )
    second = repository.resolve_paper_resting_fill_v1(
        leg_id, broker_order_id="paper-co-1", broker_raw_status=PAPER_RESTING_FILL_RAW_STATUS,
    )
    assert first.state == second.state == FILLED


def test_resolve_paper_resting_fill_conflicts_on_wrong_broker_order_id() -> None:
    repository, leg_id = _fake_repository_and_leg()
    with pytest.raises(ExecutionLegConflictError, match="PAPER_RESTING_FILL_TRANSITION_CONFLICT"):
        repository.resolve_paper_resting_fill_v1(
            leg_id, broker_order_id="paper-someone-else", broker_raw_status=PAPER_RESTING_FILL_RAW_STATUS,
        )


def test_resolve_paper_resting_fill_conflicts_on_wrong_current_state() -> None:
    # A leg that never rested ACTIVE (e.g. still PREPARED) must never be
    # silently pulled into FILLED by this PAPER-only resting-fill path.
    repository, leg_id = _fake_repository_and_leg(initial_state=PREPARED)
    with pytest.raises(ExecutionLegConflictError, match="PAPER_RESTING_FILL_TRANSITION_CONFLICT"):
        repository.resolve_paper_resting_fill_v1(
            leg_id, broker_order_id="paper-co-1", broker_raw_status=PAPER_RESTING_FILL_RAW_STATUS,
        )


def test_resolve_paper_resting_fill_requires_nonempty_broker_order_id() -> None:
    repository, leg_id = _fake_repository_and_leg()
    with pytest.raises(ValueError):
        repository.resolve_paper_resting_fill_v1(leg_id, broker_order_id="", broker_raw_status=PAPER_RESTING_FILL_RAW_STATUS)


# --- orchestration wrapper ---


class FixedQuoteProvider:
    def __init__(self, quote: PaperMarketQuoteV1 | None) -> None:
        self.quote = quote

    def latest_quote(self, *, market: str) -> PaperMarketQuoteV1 | None:
        return self.quote


class MemoryLegRepositoryForResting:
    def __init__(self, leg: ExecutionLegV1) -> None:
        self.leg = leg
        self.resolve_calls: list[dict[str, object]] = []

    def resolve_paper_resting_fill_v1(self, leg_id: int, *, broker_order_id: str, broker_raw_status: str) -> ExecutionLegV1:
        self.resolve_calls.append(
            {"leg_id": leg_id, "broker_order_id": broker_order_id, "broker_raw_status": broker_raw_status}
        )
        self.leg = replace(self.leg, state=FILLED, broker_raw_status=broker_raw_status)
        return self.leg


def _resting_leg(**overrides: object) -> ExecutionLegV1:
    values = dict(
        execution_leg_id=1, handoff_id=1, leg_index=1, trading_account_id=7,
        venue="bitvavo", market=MARKET, side="BUY", client_order_id="co-1",
        operator_id=73, price=Decimal("100"), quantity=Decimal("0.01"),
        state=ACTIVE, broker_order_id="paper-co-1",
        broker_raw_status="PAPER_ACTIVE_SUBMISSION_TIME_ONLY_NOT_CROSSED",
    )
    values.update(overrides)
    return ExecutionLegV1(**values)  # type: ignore[arg-type]


def test_reconcile_wrapper_transitions_leg_when_quote_crosses_through() -> None:
    leg = _resting_leg()
    repository = MemoryLegRepositoryForResting(leg)
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("50"), best_ask=Decimal("99"), observed_ts_utc=NOW)
    result = reconcile_paper_resting_order_fill_v1(
        leg=leg, placement_created_ts_utc=NOW - timedelta(hours=1),
        quote_provider=FixedQuoteProvider(quote), max_quote_age_seconds=30,
        now=NOW, leg_repository=repository,
    )
    assert result.state == FILLED
    assert repository.resolve_calls == [
        {"leg_id": 1, "broker_order_id": "paper-co-1", "broker_raw_status": PAPER_RESTING_FILL_RAW_STATUS}
    ]


def test_reconcile_wrapper_leaves_leg_unchanged_when_quote_does_not_cross() -> None:
    leg = _resting_leg()
    repository = MemoryLegRepositoryForResting(leg)
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("50"), best_ask=Decimal("1000"), observed_ts_utc=NOW)
    result = reconcile_paper_resting_order_fill_v1(
        leg=leg, placement_created_ts_utc=NOW - timedelta(hours=1),
        quote_provider=FixedQuoteProvider(quote), max_quote_age_seconds=30,
        now=NOW, leg_repository=repository,
    )
    assert result is leg
    assert result.state == ACTIVE
    assert repository.resolve_calls == []


def test_reconcile_wrapper_raises_and_never_calls_cas_on_bad_evidence() -> None:
    leg = _resting_leg()
    repository = MemoryLegRepositoryForResting(leg)
    with pytest.raises(PaperMarketEvidenceUnavailableError, match="PAPER_RESTING_FILL_EVIDENCE_MISSING"):
        reconcile_paper_resting_order_fill_v1(
            leg=leg, placement_created_ts_utc=NOW - timedelta(hours=1),
            quote_provider=FixedQuoteProvider(None), max_quote_age_seconds=30,
            now=NOW, leg_repository=repository,
        )
    assert repository.resolve_calls == []


def test_reconcile_wrapper_requires_active_leg() -> None:
    leg = _resting_leg(state=FILLED)
    repository = MemoryLegRepositoryForResting(leg)
    with pytest.raises(ValueError, match="PAPER_RESTING_FILL_REQUIRES_ACTIVE_LEG"):
        reconcile_paper_resting_order_fill_v1(
            leg=leg, placement_created_ts_utc=NOW - timedelta(hours=1),
            quote_provider=FixedQuoteProvider(None), max_quote_age_seconds=30,
            now=NOW, leg_repository=repository,
        )


def test_reconcile_wrapper_requires_broker_order_id() -> None:
    leg = _resting_leg(broker_order_id=None)
    repository = MemoryLegRepositoryForResting(leg)
    with pytest.raises(ValueError, match="PAPER_RESTING_FILL_REQUIRES_BROKER_ORDER_ID"):
        reconcile_paper_resting_order_fill_v1(
            leg=leg, placement_created_ts_utc=NOW - timedelta(hours=1),
            quote_provider=FixedQuoteProvider(None), max_quote_age_seconds=30,
            now=NOW, leg_repository=repository,
        )


def test_reconcile_wrapper_supports_sell_side_at_unit_level() -> None:
    leg = _resting_leg(side="SELL", price=Decimal("100"))
    repository = MemoryLegRepositoryForResting(leg)
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("101"), best_ask=Decimal("120"), observed_ts_utc=NOW)
    result = reconcile_paper_resting_order_fill_v1(
        leg=leg, placement_created_ts_utc=NOW - timedelta(hours=1),
        quote_provider=FixedQuoteProvider(quote), max_quote_age_seconds=30,
        now=NOW, leg_repository=repository,
    )
    assert result.state == FILLED


def test_reconcile_wrapper_sell_side_remains_active_on_touch() -> None:
    leg = _resting_leg(side="SELL", price=Decimal("100"))
    repository = MemoryLegRepositoryForResting(leg)
    quote = PaperMarketQuoteV1(market=MARKET, best_bid=Decimal("100"), best_ask=Decimal("120"), observed_ts_utc=NOW)
    result = reconcile_paper_resting_order_fill_v1(
        leg=leg, placement_created_ts_utc=NOW - timedelta(hours=1),
        quote_provider=FixedQuoteProvider(quote), max_quote_age_seconds=30,
        now=NOW, leg_repository=repository,
    )
    assert result is leg
    assert repository.resolve_calls == []
