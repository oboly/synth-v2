"""
Integration test tying together the P0 safety remediation modules using a
paper/fake broker snapshot — no real DB, no network, no broker calls.

Flow exercised:
  1. A fake wallet snapshot (as if read from a paper/fake broker balance
     read) reports an available BTC quantity.
  2. FREE_BASE_QUANTITY is resolved from it with zero local reservations.
  3. A SELL reservation is approved (idempotently) against that free
     quantity, for one ladder leg.
  4. The canonical rounding service rounds that leg's price/quantity
     against venue execution constraints.
  5. Recomputing FREE_BASE_QUANTITY *before* the reservation reaches the
     broker correctly subtracts it (not yet broker-reflected).
  6. Reconciliation moves the reservation to SUBMITTED_AWAITING_RECONCILIATION
     (ambiguous) then OPEN (now broker-reflected); recomputing free quantity
     with an updated fake wallet snapshot (available now excludes the open
     order) must not double-subtract the same reservation again.
  7. A retried "approve" call with the same idempotency key does not create
     a second reservation (idempotent retry / double-reservation guard).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.decision_gate.free_base_quantity_v1 import (
    STATUS_BLOCKED,
    STATUS_OK,
    WalletAvailableSnapshot,
    resolve_free_base_quantity,
)
from src.decision_gate.sell_reservation_v1 import (
    STATE_OPEN,
    STATE_SUBMITTED_AWAITING_RECONCILIATION,
    SellReservationRepository,
)
from src.execution_planner.canonical_rounding_v1 import round_leg_for_side
from src.market_rules.venue_execution_constraints_v1 import (
    STATUS_FRESH,
    VenueExecutionConstraints,
)


NOW = datetime(2026, 7, 25, 20, 0, 0, tzinfo=timezone.utc)


class _FakeCursor:
    def __init__(self, table: list[dict]) -> None:
        self._table = table
        self._result: list[dict] | None = None
        self.lastrowid: int | None = None
        self.rowcount = 0

    def execute(self, sql: str, params: list) -> None:
        sql_norm = " ".join(sql.split())
        if sql_norm.startswith("SELECT * FROM execution_sell_reservation WHERE idempotency_key"):
            (key,) = params
            self._result = [dict(r) for r in self._table if r["idempotency_key"] == key]
        elif sql_norm.startswith("INSERT INTO execution_sell_reservation"):
            (
                trading_account_id, venue, asset_id, symbol, idempotency_key,
                quantity_base, reservation_state, manual_execution_request_id,
                execution_plan_id, leg_number, notes,
            ) = params
            new_id = len(self._table) + 1
            row = {
                "reservation_id": new_id, "trading_account_id": trading_account_id,
                "venue": venue, "asset_id": asset_id, "symbol": symbol,
                "idempotency_key": idempotency_key, "quantity_base": quantity_base,
                "reservation_state": reservation_state,
                "manual_execution_request_id": manual_execution_request_id,
                "execution_plan_id": execution_plan_id, "leg_number": leg_number,
                "broker_order_id": None, "notes": notes,
                "created_ts_utc": NOW, "updated_ts_utc": NOW, "terminal_ts_utc": None,
            }
            self._table.append(row)
            self.lastrowid = new_id
        elif sql_norm.startswith("SELECT * FROM execution_sell_reservation WHERE reservation_id"):
            (reservation_id,) = params
            self._result = [dict(r) for r in self._table if r["reservation_id"] == reservation_id]
        elif sql_norm.startswith("SELECT COALESCE(SUM(quantity_base)"):
            trading_account_id, venue, asset_id, state = params
            total = sum(
                (r["quantity_base"] for r in self._table
                 if r["trading_account_id"] == trading_account_id and r["venue"] == venue
                 and r["asset_id"] == asset_id and r["reservation_state"] == state),
                Decimal("0"),
            )
            self._result = [{"total": total}]
        elif sql_norm.startswith("SELECT COUNT(*) AS n"):
            trading_account_id, venue, asset_id, state = params
            n = sum(
                1 for r in self._table
                if r["trading_account_id"] == trading_account_id and r["venue"] == venue
                and r["asset_id"] == asset_id and r["reservation_state"] == state
            )
            self._result = [{"n": n}]
        elif sql_norm.startswith("UPDATE execution_sell_reservation"):
            new_state, broker_order_id, reservation_id = params
            is_terminal_update = "terminal_ts_utc = UTC_TIMESTAMP()" in sql_norm
            self.rowcount = 0
            for r in self._table:
                if r["reservation_id"] == reservation_id:
                    r["reservation_state"] = new_state
                    if broker_order_id is not None:
                        r["broker_order_id"] = broker_order_id
                    if is_terminal_update:
                        r["terminal_ts_utc"] = datetime.now(timezone.utc)
                    self.rowcount = 1
        else:
            raise AssertionError(f"unhandled fake SQL: {sql_norm}")

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result or []


class _FakeDbContext:
    def __init__(self, table: list[dict]) -> None:
        self._cursor = _FakeCursor(table)

    def __enter__(self):
        return self._cursor

    def __exit__(self, *exc_info) -> bool:
        return False


def _make_repo() -> SellReservationRepository:
    table: list[dict] = []

    def factory(*, commit: bool = False, database: str | None = None):
        return _FakeDbContext(table)

    return SellReservationRepository(cursor_factory=factory)


def _btc_constraints() -> VenueExecutionConstraints:
    return VenueExecutionConstraints(
        venue="bitvavo",
        market="BTC-EUR",
        tick_size=Decimal("1.00"),
        qty_step_size=Decimal("0.00000001"),
        min_base_quantity=Decimal("0.00008817"),
        min_quote_notional=Decimal("5.00"),
        supported_order_types=("limit",),
        supported_time_in_force=("GTC", "IOC", "FOK"),
        source_provenance="BITVAVO_PUBLIC_MARKETS_API_V2",
        metadata_synced_ts_utc=NOW - timedelta(hours=1),
        status=STATUS_FRESH,
    )


def test_full_paper_flow_no_double_subtraction_idempotent_and_ambiguity_safe() -> None:
    repo = _make_repo()

    # 1-2. Fake wallet snapshot: 1.0 BTC available, no local reservations yet.
    wallet_before = WalletAvailableSnapshot(
        trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
        available_base_quantity=Decimal("1.0"), total_base_quantity=Decimal("1.0"),
        source_name="paper_fake_balance_snapshot", snapshot_ts_utc=NOW - timedelta(minutes=1),
    )
    result_before = resolve_free_base_quantity(
        wallet_snapshot=wallet_before,
        approved_not_submitted_reservation_base=repo.sum_approved_not_submitted(
            trading_account_id=3, venue="bitvavo", asset_id=101
        ),
        reconciliation_pending_reservation_count=repo.count_reconciliation_pending(
            trading_account_id=3, venue="bitvavo", asset_id=101
        ),
        now=NOW,
    )
    assert result_before.status == STATUS_OK
    assert result_before.free_base_quantity == Decimal("1.0")

    # 3. Approve a reservation for 70% of free quantity, one ladder leg.
    leg_quantity = result_before.free_base_quantity * Decimal("0.70")
    reservation = repo.create_reservation_idempotent(
        trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
        idempotency_key="req-42-leg-1", quantity_base=leg_quantity,
    )

    # 4. Round the leg against venue constraints.
    rounded = round_leg_for_side(
        side="SELL", raw_price=Decimal("100.111"), raw_quantity_base=leg_quantity,
        constraints=_btc_constraints(),
    )
    assert rounded.is_valid
    assert rounded.rounded_price == Decimal("101.00")  # SELL rounds up to the 1.00 tick

    # 5. Recompute free quantity before submission: must reflect the new
    # local reservation (not yet broker-known).
    result_after_approve = resolve_free_base_quantity(
        wallet_snapshot=wallet_before,  # broker balance unchanged, nothing submitted yet
        approved_not_submitted_reservation_base=repo.sum_approved_not_submitted(
            trading_account_id=3, venue="bitvavo", asset_id=101
        ),
        reconciliation_pending_reservation_count=repo.count_reconciliation_pending(
            trading_account_id=3, venue="bitvavo", asset_id=101
        ),
        now=NOW,
    )
    assert result_after_approve.status == STATUS_OK
    assert result_after_approve.free_base_quantity == Decimal("0.3")

    # 6a. Mark submitted (ambiguous window): free-quantity resolution must
    # fail closed rather than guess.
    repo.reconcile_reservation_state(
        reservation_id=reservation.reservation_id,
        new_state=STATE_SUBMITTED_AWAITING_RECONCILIATION,
        broker_order_id=None,
        matching_broker_rows=1,
    )
    result_pending = resolve_free_base_quantity(
        wallet_snapshot=wallet_before,
        approved_not_submitted_reservation_base=repo.sum_approved_not_submitted(
            trading_account_id=3, venue="bitvavo", asset_id=101
        ),
        reconciliation_pending_reservation_count=repo.count_reconciliation_pending(
            trading_account_id=3, venue="bitvavo", asset_id=101
        ),
        now=NOW,
    )
    assert result_pending.status == STATUS_BLOCKED

    # 6b. Broker confirms the order is OPEN; the fake broker balance now
    # reflects it directly in `available` (this is what a real Bitvavo
    # balance read would show once the order is live).
    repo.reconcile_reservation_state(
        reservation_id=reservation.reservation_id,
        new_state=STATE_OPEN,
        broker_order_id="paper-order-1",
        matching_broker_rows=1,
    )
    wallet_after_open = WalletAvailableSnapshot(
        trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
        available_base_quantity=Decimal("0.3"),  # broker already excludes the open order
        total_base_quantity=Decimal("1.0"),
        source_name="paper_fake_balance_snapshot", snapshot_ts_utc=NOW,
    )
    result_after_open = resolve_free_base_quantity(
        wallet_snapshot=wallet_after_open,
        # OPEN is no longer APPROVED_NOT_SUBMITTED, so it must not be
        # subtracted a second time on top of the broker's own figure.
        approved_not_submitted_reservation_base=repo.sum_approved_not_submitted(
            trading_account_id=3, venue="bitvavo", asset_id=101
        ),
        reconciliation_pending_reservation_count=repo.count_reconciliation_pending(
            trading_account_id=3, venue="bitvavo", asset_id=101
        ),
        now=NOW,
    )
    assert result_after_open.status == STATUS_OK
    assert result_after_open.free_base_quantity == Decimal("0.3")  # not 0.0 — no double subtraction

    # 7. Idempotent retry: re-approving the same leg with the same key must
    # not create a second reservation.
    retried = repo.create_reservation_idempotent(
        trading_account_id=3, venue="bitvavo", asset_id=101, symbol="BTC",
        idempotency_key="req-42-leg-1", quantity_base=leg_quantity,
    )
    assert retried.reservation_id == reservation.reservation_id
    assert repo.sum_approved_not_submitted(
        trading_account_id=3, venue="bitvavo", asset_id=101
    ) == Decimal("0")  # the only reservation is OPEN, not APPROVED_NOT_SUBMITTED
