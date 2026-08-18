"""Phase 4B persisted-evidence repository for the automatic-exit runtime.

DB-local reads only. No broker calls, no credential resolution, no broker
writes. Consumes persisted COMPLETE account-state evidence and canonical
market/profile/permission/venue facts and assembles one typed
``RuntimeItemV1`` per positive held position. Contains no strategy, gate, or
planner mechanics: it loads evidence and resolves it through the existing
Phase 1/2/3/4A contracts only.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Final

from src.decision_gate.automatic_exit_live_permission_contract_v1 import (
    resolve_automatic_exit_live_decision_gate_permission_v1,
)
from src.decision_gate.automatic_exit_live_permission_repository_v1 import (
    load_automatic_exit_live_permission_history_v1,
)
from src.decision_gate.free_base_quantity_v1 import (
    STATUS_OK,
    WalletAvailableSnapshot,
    resolve_free_base_quantity_core_v1,
)
from src.decision_gate.sell_reservation_v1 import SellReservationRepository
from src.exit_policy.automatic_exit_runtime_contract_v1 import (
    AutomaticExitPlanningPermissionV1,
    AutomaticExitProfileV1,
    resolve_automatic_exit_planning_enabled,
    resolve_automatic_exit_profile,
)
from src.market_rules.venue_execution_constraints_v1 import (
    VenueExecutionConstraints,
    load_constraints_from_db,
    resolve_venue_execution_constraints,
)


COMPLETE_STATE: Final[str] = "COMPLETE"

DEFAULT_MAX_ACCOUNT_STATE_AGE_SECONDS: Final[int] = 15 * 60
DEFAULT_MAX_MARKET_PRICE_AGE_SECONDS: Final[int] = 15 * 60

REASON_MISSING_AUTOMATIC_EXIT_PERMISSION: Final[str] = "MISSING_AUTOMATIC_EXIT_PERMISSION"
REASON_MISSING_VENUE_CONSTRAINT: Final[str] = "MISSING_VENUE_CONSTRAINT"
REASON_FREE_BASE_QUANTITY_BLOCKED: Final[str] = "FREE_BASE_QUANTITY_BLOCKED"

class AutomaticExitRuntimeRepositoryError(RuntimeError):
    """Fail-closed evidence-loading error. ``args[0]`` is the reason code."""


def _reject(condition: bool, reason_code: str) -> None:
    if condition:
        raise AutomaticExitRuntimeRepositoryError(reason_code)


def _aware(value: Any) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _fetch_one(cur: Any) -> dict[str, Any] | None:
    row = cur.fetchone()
    return None if row is None else dict(row)


def _fetch_all(cur: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in cur.fetchall()]


def _stale(observed_ts_utc: datetime, now: datetime, max_age_seconds: int) -> bool:
    age = now - observed_ts_utc
    return age < timedelta(0) or age > timedelta(seconds=max_age_seconds)


@dataclass(frozen=True)
class EligibleAccountV1:
    trading_account_id: int
    account_code: str
    venue: str
    account_mode: str
    enabled: bool
    live_trading_enabled: bool


@dataclass(frozen=True)
class AccountStateBundleV1:
    account_state_snapshot_run_id: int
    trading_account_id: int
    venue: str
    snapshot_ts_utc: datetime
    position_source_name: str
    position_snapshot_count: int
    balance_source_name: str
    balance_snapshot_count: int
    account_open_order_snapshot_run_id: int
    open_order_count: int


@dataclass(frozen=True)
class PositionEvidenceV1:
    account_position_snapshot_id: int
    asset_id: int
    symbol: str
    quantity_base: Decimal
    available_quantity_base: Decimal


@dataclass(frozen=True)
class BalanceEvidenceV1:
    trading_account_balance_snapshot_id: int
    currency_code: str
    available_amount: Decimal


@dataclass(frozen=True)
class MarketPriceEvidenceV1:
    market_price_snapshot_id: int
    venue: str
    symbol: str
    market: str
    price: Decimal
    observed_ts_utc: datetime


@dataclass(frozen=True)
class PositionMarketIdentityV1:
    """Canonical account-bound executable market for one held position."""

    venue_market_id: int
    venue: str
    market: str
    base_asset_id: int
    asset_symbol: str


@dataclass(frozen=True)
class RuntimeItemV1:
    """One independent evaluable unit: one positive held position."""

    trading_account_id: int
    account_code: str
    position_reference: str
    venue: str
    asset_id: int
    market: str
    symbol: str
    held_quantity_base: Decimal
    free_quantity_base: Decimal
    current_price: Decimal
    account_enabled: bool
    account_mode: str
    live_trading_enabled: bool
    automatic_exit_execution_enabled: bool
    automatic_exit_live_permission_enabled: bool
    blocking_conflict: bool
    account_state_observed_ts_utc: datetime
    market_price_observed_ts_utc: datetime
    exit_profile: AutomaticExitProfileV1
    venue_constraints: VenueExecutionConstraints
    account_state_snapshot_run_id: int
    position_snapshot_id: int
    balance_snapshot_id: int
    open_order_snapshot_run_id: int
    market_price_snapshot_id: int
    automatic_exit_permission_id: int
    venue_constraint_id: int


def load_eligible_trading_accounts(conn: Any, *, venue: str) -> list[EligibleAccountV1]:
    """Enabled, paper-mode trading accounts for the given venue.

    Automatic-exit planning permission is a separate account-permission fact
    (see PHASE I): this enumerates structural account eligibility only.
    """
    sql = """
    SELECT trading_account_id, account_code, venue, account_mode, enabled, live_trading_enabled
    FROM trading_account
    WHERE enabled = %s AND venue = %s
    ORDER BY trading_account_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (1, venue))
        rows = _fetch_all(cur)
    return [
        EligibleAccountV1(
            trading_account_id=int(row["trading_account_id"]),
            account_code=str(row["account_code"]),
            venue=str(row["venue"]),
            account_mode=str(row["account_mode"]),
            enabled=bool(row["enabled"]),
            live_trading_enabled=bool(row["live_trading_enabled"]),
        )
        for row in rows
    ]


def load_latest_complete_account_state_bundle(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    now: datetime,
    max_age_seconds: int = DEFAULT_MAX_ACCOUNT_STATE_AGE_SECONDS,
) -> AccountStateBundleV1:
    """Load the latest fresh COMPLETE aligned account-state bundle or fail closed."""
    _reject(not _aware(now), "INVALID_EVALUATION_TIMESTAMP")
    sql = """
    SELECT
        state_run.account_state_snapshot_run_id, state_run.trading_account_id,
        state_run.venue, state_run.snapshot_ts_utc,
        state_run.position_source_name, state_run.position_snapshot_count,
        state_run.balance_source_name, state_run.balance_snapshot_count,
        state_run.account_open_order_snapshot_run_id,
        order_run.snapshot_state AS order_run_state,
        order_run.open_order_count
    FROM account_state_snapshot_run_v1 state_run
    JOIN account_open_order_snapshot_run_v1 order_run
      ON order_run.account_open_order_snapshot_run_id
       = state_run.account_open_order_snapshot_run_id
    WHERE state_run.trading_account_id = %s
      AND state_run.venue = %s
      AND state_run.run_state = %s
    ORDER BY state_run.snapshot_ts_utc DESC, state_run.account_state_snapshot_run_id DESC
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue, COMPLETE_STATE))
        row = _fetch_one(cur)
    _reject(row is None, "ACCOUNT_STATE_BUNDLE_MISSING")
    assert row is not None
    _reject(row["order_run_state"] != COMPLETE_STATE, "OPEN_ORDER_HEADER_NOT_COMPLETE")
    snapshot_ts_utc = _ensure_aware(row["snapshot_ts_utc"])
    _reject(_stale(snapshot_ts_utc, now, max_age_seconds), "ACCOUNT_STATE_BUNDLE_STALE")
    return AccountStateBundleV1(
        account_state_snapshot_run_id=int(row["account_state_snapshot_run_id"]),
        trading_account_id=int(row["trading_account_id"]),
        venue=str(row["venue"]),
        snapshot_ts_utc=snapshot_ts_utc,
        position_source_name=str(row["position_source_name"]),
        position_snapshot_count=int(row["position_snapshot_count"]),
        balance_source_name=str(row["balance_source_name"]),
        balance_snapshot_count=int(row["balance_snapshot_count"]),
        account_open_order_snapshot_run_id=int(row["account_open_order_snapshot_run_id"]),
        open_order_count=int(row["open_order_count"]),
    )


def load_positive_positions(conn: Any, *, bundle: AccountStateBundleV1) -> list[PositionEvidenceV1]:
    """Positive held positions tied exactly to the COMPLETE bundle's provenance."""
    count_sql = """
    SELECT COUNT(*) AS rows_total FROM account_position_snapshot
    WHERE trading_account_id = %s AND venue = %s AND source_name = %s AND snapshot_ts_utc = %s
    """
    select_sql = """
    SELECT account_position_snapshot_id, asset_id, symbol, quantity_base, available_quantity_base
    FROM account_position_snapshot
    WHERE trading_account_id = %s AND venue = %s AND source_name = %s AND snapshot_ts_utc = %s
      AND quantity_base > 0
    ORDER BY account_position_snapshot_id
    """
    params = (
        bundle.trading_account_id, bundle.venue, bundle.position_source_name, bundle.snapshot_ts_utc,
    )
    with conn.cursor() as cur:
        cur.execute(count_sql, params)
        count_row = _fetch_one(cur)
        cur.execute(select_sql, params)
        rows = _fetch_all(cur)
    _reject(count_row is None or int(count_row["rows_total"]) != bundle.position_snapshot_count, "POSITION_SNAPSHOT_COUNT_MISMATCH")
    return [
        PositionEvidenceV1(
            account_position_snapshot_id=int(row["account_position_snapshot_id"]),
            asset_id=int(row["asset_id"]),
            symbol=str(row["symbol"]),
            quantity_base=Decimal(str(row["quantity_base"])),
            available_quantity_base=Decimal(str(row["available_quantity_base"])),
        )
        for row in rows
    ]


def load_balance_evidence(
    conn: Any, *, bundle: AccountStateBundleV1, currency_code: str,
) -> BalanceEvidenceV1:
    """Exact free-quantity balance row for one asset tied to the COMPLETE bundle."""
    sql = """
    SELECT trading_account_balance_snapshot_id, currency_code, available_amount
    FROM trading_account_balance_snapshot
    WHERE trading_account_id = %s AND venue = %s AND source_name = %s AND snapshot_ts_utc = %s
      AND currency_code = %s
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (bundle.trading_account_id, bundle.venue, bundle.balance_source_name, bundle.snapshot_ts_utc, currency_code),
        )
        rows = _fetch_all(cur)
    _reject(len(rows) == 0, "BALANCE_ROW_MISSING")
    _reject(len(rows) > 1, "BALANCE_ROW_CONFLICT")
    row = rows[0]
    available = Decimal(str(row["available_amount"]))
    _reject(available < 0, "NEGATIVE_FREE_QUANTITY")
    return BalanceEvidenceV1(
        trading_account_balance_snapshot_id=int(row["trading_account_balance_snapshot_id"]),
        currency_code=str(row["currency_code"]),
        available_amount=available,
    )


def load_blocking_conflict(conn: Any, *, bundle: AccountStateBundleV1, market: str) -> bool:
    """Resolve blocking_conflict for one market from the authoritative open-order header.

    A zero ``open_order_count`` header is authoritative no-conflict evidence.
    A nonzero header requires the exact order rows tied to the same
    trading_account_id/venue/snapshot_ts_utc; any row in this exact market is
    a blocking conflict for the proposed SELL.
    """
    if bundle.open_order_count == 0:
        return False
    total_sql = """
    SELECT COUNT(*) AS rows_total FROM account_open_order_snapshot
    WHERE trading_account_id = %s AND venue = %s AND snapshot_ts_utc = %s
    """
    market_sql = """
    SELECT COUNT(*) AS rows_total FROM account_open_order_snapshot
    WHERE trading_account_id = %s AND venue = %s AND snapshot_ts_utc = %s AND market = %s
    """
    with conn.cursor() as cur:
        cur.execute(total_sql, (bundle.trading_account_id, bundle.venue, bundle.snapshot_ts_utc))
        total_row = _fetch_one(cur)
        cur.execute(market_sql, (bundle.trading_account_id, bundle.venue, bundle.snapshot_ts_utc, market))
        market_row = _fetch_one(cur)
    _reject(total_row is None or int(total_row["rows_total"]) != bundle.open_order_count, "OPEN_ORDER_SNAPSHOT_COUNT_MISMATCH")
    assert market_row is not None
    return int(market_row["rows_total"]) > 0


def resolve_position_market_v1(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    asset_id: int,
    symbol: str,
) -> PositionMarketIdentityV1:
    """Resolve one held position through its account-bound ``venue_market`` identity.

    ``account_asset`` is read only as an account-aware market-identity binding.
    Its strategy and presentation flags never participate in this query.
    """
    sql = """
    SELECT vm.venue_market_id, vm.venue, vm.market, vm.base_asset_id, a.symbol AS asset_symbol
    FROM account_asset aa
    JOIN venue_market vm ON vm.venue_market_id = aa.venue_market_id
    JOIN asset a ON a.asset_id = vm.base_asset_id
    WHERE aa.trading_account_id = %s
      AND vm.venue = %s
      AND vm.base_asset_id = %s
    ORDER BY vm.venue_market_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue, asset_id))
        rows = _fetch_all(cur)
    _reject(len(rows) == 0, "POSITION_MARKET_IDENTITY_MISSING")
    _reject(len(rows) > 1, "POSITION_MARKET_IDENTITY_AMBIGUOUS")
    row = rows[0]
    canonical_venue = str(row["venue"] or "")
    market = str(row["market"] or "").strip().upper()
    canonical_symbol = str(row["asset_symbol"] or "").strip().upper()
    expected_symbol = str(symbol or "").strip().upper()
    _reject(not market, "POSITION_MARKET_IDENTITY_INVALID")
    _reject(canonical_venue != venue, "POSITION_MARKET_VENUE_MISMATCH")
    _reject(int(row["base_asset_id"]) != asset_id, "POSITION_MARKET_ASSET_MISMATCH")
    _reject(not canonical_symbol or canonical_symbol != expected_symbol, "POSITION_MARKET_SYMBOL_MISMATCH")
    return PositionMarketIdentityV1(
        venue_market_id=int(row["venue_market_id"]),
        venue=canonical_venue,
        market=market,
        base_asset_id=int(row["base_asset_id"]),
        asset_symbol=canonical_symbol,
    )


def load_latest_market_price(
    conn: Any,
    *,
    venue: str,
    market: str,
    now: datetime,
    max_age_seconds: int = DEFAULT_MAX_MARKET_PRICE_AGE_SECONDS,
) -> MarketPriceEvidenceV1:
    """Freshest market_price_snapshot row for one canonical market, including its row id.

    Not routed through market_price_snapshot_v1.fetch_latest_prices_by_symbol:
    that helper does not select market_price_snapshot_id, which idempotency
    evidence requires.
    """
    _reject(not _aware(now), "INVALID_EVALUATION_TIMESTAMP")
    sql = """
    SELECT market_price_snapshot_id, venue, symbol, market, price, observed_ts_utc
    FROM market_price_snapshot
    WHERE venue = %s AND market = %s
    ORDER BY observed_ts_utc DESC, market_price_snapshot_id DESC
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, market))
        row = _fetch_one(cur)
    _reject(row is None, "MARKET_PRICE_SNAPSHOT_MISSING")
    assert row is not None
    _reject(str(row["venue"]) != venue or str(row["market"]).upper() != market.upper(), "MARKET_PRICE_IDENTITY_MISMATCH")
    observed_ts_utc = _ensure_aware(row["observed_ts_utc"])
    _reject(_stale(observed_ts_utc, now, max_age_seconds), "MARKET_PRICE_SNAPSHOT_STALE")
    price = Decimal(str(row["price"]))
    _reject(price <= 0, "INVALID_MARKET_PRICE")
    return MarketPriceEvidenceV1(
        market_price_snapshot_id=int(row["market_price_snapshot_id"]),
        venue=str(row["venue"]),
        symbol=str(row["symbol"]),
        market=str(row["market"]),
        price=price,
        observed_ts_utc=observed_ts_utc,
    )


def load_exit_profiles(
    conn: Any, *, venue: str, asset_id: int, market: str,
) -> list[AutomaticExitProfileV1]:
    """Applicable automatic_exit_profile_v1 rows; resolution stays in resolve_automatic_exit_profile()."""
    sql = """
    SELECT profile_id, profile_version, venue, asset_id, market,
           active_target_price, invalidation_price, evidence_id, evidence_provenance,
           observed_ts_utc, effective_from_ts_utc, effective_until_ts_utc
    FROM automatic_exit_profile_v1
    WHERE venue = %s AND asset_id = %s AND market = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, asset_id, market))
        rows = _fetch_all(cur)
    return [
        AutomaticExitProfileV1(
            profile_id=str(row["profile_id"]),
            profile_version=str(row["profile_version"]),
            venue=str(row["venue"]),
            asset_id=int(row["asset_id"]),
            market=str(row["market"]),
            active_target_price=(Decimal(str(row["active_target_price"])) if row["active_target_price"] is not None else None),
            invalidation_price=(Decimal(str(row["invalidation_price"])) if row["invalidation_price"] is not None else None),
            evidence_id=str(row["evidence_id"]),
            evidence_provenance=str(row["evidence_provenance"]),
            observed_ts_utc=_ensure_aware(row["observed_ts_utc"]),
            effective_from_ts_utc=_ensure_aware(row["effective_from_ts_utc"]),
            effective_until_ts_utc=(_ensure_aware(row["effective_until_ts_utc"]) if row["effective_until_ts_utc"] is not None else None),
        )
        for row in rows
    ]


def load_permission_history(conn: Any, *, trading_account_id: int) -> list[AutomaticExitPlanningPermissionV1]:
    """Full permission history; resolution stays in resolve_automatic_exit_planning_enabled()."""
    sql = """
    SELECT automatic_exit_account_permission_id, trading_account_id, planning_enabled,
           effective_from_ts_utc, effective_until_ts_utc, permission_version, source_provenance
    FROM automatic_exit_account_permission_v1
    WHERE trading_account_id = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id,))
        rows = _fetch_all(cur)
    return [
        AutomaticExitPlanningPermissionV1(
            permission_id=int(row["automatic_exit_account_permission_id"]),
            trading_account_id=int(row["trading_account_id"]),
            planning_enabled=bool(row["planning_enabled"]),
            effective_from_ts_utc=_ensure_aware(row["effective_from_ts_utc"]),
            effective_until_ts_utc=(_ensure_aware(row["effective_until_ts_utc"]) if row["effective_until_ts_utc"] is not None else None),
            permission_version=str(row["permission_version"]),
            source_provenance=str(row["source_provenance"]),
        )
        for row in rows
    ]


def _active_permission_id(
    permissions: list[AutomaticExitPlanningPermissionV1], *, trading_account_id: int, at: datetime,
) -> int:
    """Identity of the single active permission row; absence fails closed.

    Only called after resolve_automatic_exit_planning_enabled() has already
    proven at most one active row exists; this does not re-decide enablement.
    """
    matches = [
        row for row in permissions
        if row.trading_account_id == trading_account_id
        and row.effective_from_ts_utc <= at
        and (row.effective_until_ts_utc is None or at < row.effective_until_ts_utc)
    ]
    if not matches:
        raise AutomaticExitRuntimeRepositoryError(REASON_MISSING_AUTOMATIC_EXIT_PERMISSION)
    return matches[0].permission_id


def load_venue_constraint_id(conn: Any, *, venue: str, market: str) -> int:
    """Row id for venue_execution_constraint; absence fails closed.

    load_constraints_from_db() does not select the row id (it is not part of
    the shared VenueExecutionConstraints contract), so it is fetched here
    separately for idempotency evidence only.
    """
    sql = "SELECT venue_execution_constraint_id FROM venue_execution_constraint WHERE venue = %s AND market = %s"
    with conn.cursor() as cur:
        cur.execute(sql, (venue, market))
        row = _fetch_one(cur)
    if row is None:
        raise AutomaticExitRuntimeRepositoryError(REASON_MISSING_VENUE_CONSTRAINT)
    return int(row["venue_execution_constraint_id"])


def build_runtime_item_v1(
    conn: Any,
    *,
    account: EligibleAccountV1,
    bundle: AccountStateBundleV1,
    position: PositionEvidenceV1,
    now: datetime,
    max_market_price_age_seconds: int = DEFAULT_MAX_MARKET_PRICE_AGE_SECONDS,
    max_profile_age_seconds: int | None = None,
) -> RuntimeItemV1:
    """Assemble one complete, independently-idempotent runtime item.

    Every persisted-evidence reference required by
    automatic_exit_idempotency_key_v1() is resolved here, before any
    candidate/gate/planner call, so identical evidence always yields an
    identical idempotency key regardless of the eventual outcome.
    """
    balance = load_balance_evidence(conn, bundle=bundle, currency_code=position.symbol)
    reservation_repository = SellReservationRepository()
    with conn.cursor() as cur:
        approved_not_submitted = reservation_repository.sum_approved_not_submitted(
            trading_account_id=account.trading_account_id,
            venue=bundle.venue,
            asset_id=position.asset_id,
            cursor=cur,
        )
        reconciliation_pending = reservation_repository.count_reconciliation_pending(
            trading_account_id=account.trading_account_id,
            venue=bundle.venue,
            asset_id=position.asset_id,
            cursor=cur,
        )
    free_quantity_result = resolve_free_base_quantity_core_v1(
        wallet_snapshot=WalletAvailableSnapshot(
            trading_account_id=account.trading_account_id,
            venue=bundle.venue,
            asset_id=position.asset_id,
            symbol=position.symbol,
            available_base_quantity=position.available_quantity_base,
            total_base_quantity=position.quantity_base,
            source_name=bundle.position_source_name,
            snapshot_ts_utc=bundle.snapshot_ts_utc,
            snapshot_id=position.account_position_snapshot_id,
        ),
        approved_not_submitted_reservation_base=approved_not_submitted,
        reconciliation_pending_reservation_count=reconciliation_pending,
        evaluation_ts_utc=now,
        expected_trading_account_id=account.trading_account_id,
        expected_venue=bundle.venue,
        expected_asset_id=position.asset_id,
    )
    if free_quantity_result.status != STATUS_OK:
        raise AutomaticExitRuntimeRepositoryError(
            REASON_FREE_BASE_QUANTITY_BLOCKED + ":" + ",".join(free_quantity_result.blocking_reasons)
        )
    assert free_quantity_result.free_base_quantity is not None
    market_identity = resolve_position_market_v1(
        conn,
        trading_account_id=account.trading_account_id,
        venue=bundle.venue,
        asset_id=position.asset_id,
        symbol=position.symbol,
    )
    market = market_identity.market
    blocking_conflict = load_blocking_conflict(conn, bundle=bundle, market=market)
    price_evidence = load_latest_market_price(
        conn, venue=bundle.venue, market=market, now=now, max_age_seconds=max_market_price_age_seconds,
    )
    profiles = load_exit_profiles(conn, venue=bundle.venue, asset_id=position.asset_id, market=market)
    profile_kwargs: dict[str, Any] = {}
    if max_profile_age_seconds is not None:
        profile_kwargs["max_profile_age_seconds"] = max_profile_age_seconds
    profile = resolve_automatic_exit_profile(
        profiles, venue=bundle.venue, asset_id=position.asset_id, market=market, at=now, **profile_kwargs,
    )

    permissions = load_permission_history(conn, trading_account_id=account.trading_account_id)
    execution_enabled = resolve_automatic_exit_planning_enabled(
        permissions, trading_account_id=account.trading_account_id, at=now,
    )
    permission_id = _active_permission_id(permissions, trading_account_id=account.trading_account_id, at=now)

    # Issue #392 Phase 6 blocker B: resolved for every account regardless of
    # mode, matching automatic_exit_execution_enabled's own precedent. It is
    # decision-gate LIVE permission evidence only and is not consulted by the
    # gate for paper-mode accounts.
    live_permissions = load_automatic_exit_live_permission_history_v1(conn, trading_account_id=account.trading_account_id)
    live_execution_permission_enabled = resolve_automatic_exit_live_decision_gate_permission_v1(
        live_permissions, trading_account_id=account.trading_account_id, at=now,
    )

    venue_constraint_rows = load_constraints_from_db(conn, venue=bundle.venue, markets=[market])
    venue_constraints = resolve_venue_execution_constraints(
        venue=bundle.venue, market=market, db_rows=venue_constraint_rows, now=now,
    )
    venue_constraint_id = load_venue_constraint_id(conn, venue=bundle.venue, market=market)

    return RuntimeItemV1(
        trading_account_id=account.trading_account_id,
        account_code=account.account_code,
        position_reference=f"account_position_snapshot:{position.account_position_snapshot_id}",
        venue=bundle.venue,
        asset_id=position.asset_id,
        market=market,
        symbol=position.symbol,
        held_quantity_base=position.quantity_base,
        free_quantity_base=free_quantity_result.free_base_quantity,
        current_price=price_evidence.price,
        account_enabled=account.enabled,
        account_mode=account.account_mode,
        live_trading_enabled=account.live_trading_enabled,
        automatic_exit_execution_enabled=execution_enabled,
        automatic_exit_live_permission_enabled=live_execution_permission_enabled,
        blocking_conflict=blocking_conflict,
        account_state_observed_ts_utc=bundle.snapshot_ts_utc,
        market_price_observed_ts_utc=price_evidence.observed_ts_utc,
        exit_profile=profile,
        venue_constraints=venue_constraints,
        account_state_snapshot_run_id=bundle.account_state_snapshot_run_id,
        position_snapshot_id=position.account_position_snapshot_id,
        balance_snapshot_id=balance.trading_account_balance_snapshot_id,
        open_order_snapshot_run_id=bundle.account_open_order_snapshot_run_id,
        market_price_snapshot_id=price_evidence.market_price_snapshot_id,
        automatic_exit_permission_id=permission_id,
        venue_constraint_id=venue_constraint_id,
    )
