"""Issue #474: DB-local repository assembling the canonical automatic BUY
account-allocation evidence projection.

Reads only. No broker calls, no credential resolution, no broker/executor
writes, no order authority. Composes persisted COMPLETE account-state
evidence (positions, balance, open orders), the account's own resolved
strategy-bucket risk/allocation configuration, and the decision-gate-owned
automatic-BUY execution permission into one immutable, fully-bound
:class:`AutomaticBuyAccountAllocationEvidenceV1`. Never accepts any of the
five previously-missing fields as a caller-supplied value; every field is
read or derived from an authoritative table.

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

from src.decision_gate.automatic_buy_account_allocation_evidence_contract_v1 import (
    AutomaticBuyAccountAllocationEvidenceContractError,
    AutomaticBuyAccountAllocationEvidenceV1,
    EVIDENCE_CONTRACT_VERSION,
    validate_automatic_buy_account_allocation_evidence_v1,
)
from src.decision_gate.automatic_buy_account_permission_contract_v1 import (
    AutomaticBuyAccountPermissionContractError,
    resolve_automatic_buy_account_permission_v1,
)
from src.decision_gate.automatic_buy_account_permission_repository_v1 import (
    AutomaticBuyAccountPermissionRepositoryError,
    load_automatic_buy_account_permission_history_v1,
    load_automatic_buy_account_permission_revocation_history_v1,
)
from src.decision_gate.strategy_bucket_account_config_contract_v1 import StrategyBucketAccountConfigV1

COMPLETE_STATE: Final[str] = "COMPLETE"
QUOTE_CURRENCY_EUR: Final[str] = "EUR"

DEFAULT_MAX_ACCOUNT_STATE_AGE_SECONDS: Final[int] = 15 * 60
DEFAULT_MAX_MARKET_PRICE_AGE_SECONDS: Final[int] = 15 * 60


class AutomaticBuyAccountAllocationEvidenceRepositoryError(RuntimeError):
    """Fail-closed evidence-loading error. ``args[0]`` is the reason code."""


def _reject(condition: bool, reason_code: str) -> None:
    if condition:
        raise AutomaticBuyAccountAllocationEvidenceRepositoryError(reason_code)


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
class _TradingAccountRecord:
    trading_account_id: int
    venue: str
    account_mode: str
    enabled: bool
    live_trading_enabled: bool


@dataclass(frozen=True)
class _AccountStateBundle:
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
class _PositionRow:
    asset_id: int
    quantity_base: Decimal


@dataclass(frozen=True)
class _AssetMarketBinding:
    market: str
    quote_currency: str


def _load_trading_account(conn: Any, *, trading_account_id: int) -> _TradingAccountRecord:
    sql = """
    SELECT trading_account_id, venue, account_mode, enabled, live_trading_enabled
    FROM trading_account
    WHERE trading_account_id = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id,))
        row = _fetch_one(cur)
    _reject(row is None, "TRADING_ACCOUNT_NOT_FOUND")
    assert row is not None
    return _TradingAccountRecord(
        trading_account_id=int(row["trading_account_id"]),
        venue=str(row["venue"]),
        account_mode=str(row["account_mode"]),
        enabled=bool(row["enabled"]),
        live_trading_enabled=bool(row["live_trading_enabled"]),
    )


def _load_complete_account_state_bundle(
    conn: Any, *, trading_account_id: int, venue: str, now: datetime, max_age_seconds: int,
) -> _AccountStateBundle:
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
    return _AccountStateBundle(
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


def _load_positive_positions(conn: Any, *, bundle: _AccountStateBundle) -> list[_PositionRow]:
    count_sql = """
    SELECT COUNT(*) AS rows_total FROM account_position_snapshot
    WHERE trading_account_id = %s AND venue = %s AND source_name = %s AND snapshot_ts_utc = %s
    """
    select_sql = """
    SELECT asset_id, quantity_base
    FROM account_position_snapshot
    WHERE trading_account_id = %s AND venue = %s AND source_name = %s AND snapshot_ts_utc = %s
      AND quantity_base > 0
    ORDER BY asset_id
    """
    params = (bundle.trading_account_id, bundle.venue, bundle.position_source_name, bundle.snapshot_ts_utc)
    with conn.cursor() as cur:
        cur.execute(count_sql, params)
        count_row = _fetch_one(cur)
        cur.execute(select_sql, params)
        rows = _fetch_all(cur)
    _reject(
        count_row is None or int(count_row["rows_total"]) != bundle.position_snapshot_count,
        "POSITION_SNAPSHOT_COUNT_MISMATCH",
    )
    return [
        _PositionRow(asset_id=int(row["asset_id"]), quantity_base=Decimal(str(row["quantity_base"])))
        for row in rows
    ]


def _load_free_quote_balance(conn: Any, *, bundle: _AccountStateBundle) -> tuple[Decimal, int]:
    sql = """
    SELECT trading_account_balance_snapshot_id, available_amount
    FROM trading_account_balance_snapshot
    WHERE trading_account_id = %s AND venue = %s AND source_name = %s AND snapshot_ts_utc = %s
      AND currency_code = %s
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (bundle.trading_account_id, bundle.venue, bundle.balance_source_name, bundle.snapshot_ts_utc, QUOTE_CURRENCY_EUR),
        )
        rows = _fetch_all(cur)
    _reject(len(rows) == 0, "FREE_QUOTE_BALANCE_ROW_MISSING")
    _reject(len(rows) > 1, "FREE_QUOTE_BALANCE_ROW_CONFLICT")
    row = rows[0]
    available = Decimal(str(row["available_amount"]))
    _reject(available < 0, "NEGATIVE_FREE_QUOTE_BALANCE")
    return available, int(row["trading_account_balance_snapshot_id"])


def _load_blocking_conflict(conn: Any, *, bundle: _AccountStateBundle, market: str) -> bool:
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
    _reject(
        total_row is None or int(total_row["rows_total"]) != bundle.open_order_count,
        "OPEN_ORDER_SNAPSHOT_COUNT_MISMATCH",
    )
    assert market_row is not None
    return int(market_row["rows_total"]) > 0


def _resolve_account_asset_market(
    conn: Any, *, trading_account_id: int, venue: str, asset_id: int,
) -> _AssetMarketBinding:
    """Resolve one account-bound executable market for one asset, or fail closed.

    Does not require a held position: a BUY candidate asset need not already
    be held. Fails closed on zero or ambiguous (multi-quote-currency) bindings.
    """
    sql = """
    SELECT vm.market, vm.quote_currency
    FROM account_asset aa
    JOIN venue_market vm ON vm.venue_market_id = aa.venue_market_id
    WHERE aa.trading_account_id = %s AND vm.venue = %s AND vm.base_asset_id = %s
    ORDER BY vm.venue_market_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue, asset_id))
        rows = _fetch_all(cur)
    _reject(len(rows) == 0, "ASSET_MARKET_BINDING_MISSING")
    _reject(len(rows) > 1, "ASSET_MARKET_BINDING_AMBIGUOUS")
    row = rows[0]
    return _AssetMarketBinding(market=str(row["market"]).strip().upper(), quote_currency=str(row["quote_currency"]).strip().upper())


def _load_latest_market_price(
    conn: Any, *, venue: str, market: str, now: datetime, max_age_seconds: int,
) -> Decimal:
    sql = """
    SELECT price, observed_ts_utc
    FROM market_price_snapshot
    WHERE venue = %s AND market = %s
    ORDER BY observed_ts_utc DESC, market_price_snapshot_id DESC
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, market))
        row = _fetch_one(cur)
    _reject(row is None, "POSITION_MARKET_PRICE_MISSING")
    assert row is not None
    observed_ts_utc = _ensure_aware(row["observed_ts_utc"])
    _reject(_stale(observed_ts_utc, now, max_age_seconds), "POSITION_MARKET_PRICE_STALE")
    price = Decimal(str(row["price"]))
    _reject(price <= 0, "INVALID_POSITION_MARKET_PRICE")
    return price


def _value_positions_in_eur(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    positions: list[_PositionRow],
    now: datetime,
    max_market_price_age_seconds: int,
) -> dict[int, Decimal]:
    """EUR value of every positive held position, keyed by asset_id.

    Every held asset must resolve to exactly one EUR-quoted, freshly-priced
    market; any held asset that does not fails the whole evidence load
    closed rather than silently omitting it from exposure/bucket totals.
    """
    values: dict[int, Decimal] = {}
    for position in positions:
        binding = _resolve_account_asset_market(
            conn, trading_account_id=trading_account_id, venue=venue, asset_id=position.asset_id,
        )
        _reject(binding.quote_currency != QUOTE_CURRENCY_EUR, "UNSUPPORTED_POSITION_QUOTE_CURRENCY")
        price = _load_latest_market_price(
            conn, venue=venue, market=binding.market, now=now, max_age_seconds=max_market_price_age_seconds,
        )
        values[position.asset_id] = values.get(position.asset_id, Decimal("0")) + position.quantity_base * price
    return values


def load_automatic_buy_account_allocation_evidence_v1(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    asset_id: int,
    market: str,
    strategy_bucket_id: str,
    resolved_bucket_config: StrategyBucketAccountConfigV1 | None,
    evaluation_ts_utc: datetime,
    max_account_state_age_seconds: int = DEFAULT_MAX_ACCOUNT_STATE_AGE_SECONDS,
    max_market_price_age_seconds: int = DEFAULT_MAX_MARKET_PRICE_AGE_SECONDS,
) -> AutomaticBuyAccountAllocationEvidenceV1:
    """Assemble the canonical automatic BUY account-allocation evidence.

    ``resolved_bucket_config`` must already be the caller's own
    ``resolve_strategy_bucket_account_config_v1`` result (or ``None`` when
    unresolved); this function never re-derives bucket enablement/ceiling
    policy, it only reads ``max_position_amount_eur`` off the already-
    resolved row to bind ``proposed_position_amount_eur``. Fails closed
    (raises :class:`AutomaticBuyAccountAllocationEvidenceRepositoryError`)
    on any missing, ambiguous, stale, or inconsistent evidence.
    """
    _reject(
        trading_account_id <= 0
        or asset_id <= 0
        or not venue
        or not market
        or not strategy_bucket_id
        or not _aware(evaluation_ts_utc)
        or max_account_state_age_seconds < 0
        or max_market_price_age_seconds < 0,
        "INVALID_ACCOUNT_ALLOCATION_EVIDENCE_LOOKUP",
    )

    account = _load_trading_account(conn, trading_account_id=trading_account_id)
    _reject(account.venue != venue, "TRADING_ACCOUNT_VENUE_MISMATCH")

    candidate_binding = _resolve_account_asset_market(
        conn, trading_account_id=trading_account_id, venue=venue, asset_id=asset_id,
    )
    _reject(candidate_binding.market != market.strip().upper(), "CANDIDATE_MARKET_IDENTITY_MISMATCH")

    bundle = _load_complete_account_state_bundle(
        conn,
        trading_account_id=trading_account_id,
        venue=venue,
        now=evaluation_ts_utc,
        max_age_seconds=max_account_state_age_seconds,
    )
    positions = _load_positive_positions(conn, bundle=bundle)
    free_quote_balance_eur, balance_snapshot_id = _load_free_quote_balance(conn, bundle=bundle)
    blocking_conflict = _load_blocking_conflict(conn, bundle=bundle, market=market)

    position_values_eur = _value_positions_in_eur(
        conn,
        trading_account_id=trading_account_id,
        venue=venue,
        positions=positions,
        now=evaluation_ts_utc,
        max_market_price_age_seconds=max_market_price_age_seconds,
    )
    total_position_value_eur = sum(position_values_eur.values(), Decimal("0"))
    candidate_asset_value_eur = position_values_eur.get(asset_id, Decimal("0"))
    nav_eur = total_position_value_eur + free_quote_balance_eur
    current_asset_exposure_pct = (
        Decimal("0") if nav_eur == 0 else min(Decimal("100"), (candidate_asset_value_eur * 100) / nav_eur)
    )

    permissions = load_automatic_buy_account_permission_history_v1(conn, trading_account_id=trading_account_id)
    revocations = load_automatic_buy_account_permission_revocation_history_v1(conn, trading_account_id=trading_account_id)
    try:
        resolved_permission = resolve_automatic_buy_account_permission_v1(
            permissions, revocations, trading_account_id=trading_account_id, at=evaluation_ts_utc,
        )
    except AutomaticBuyAccountPermissionContractError as exc:
        raise AutomaticBuyAccountAllocationEvidenceRepositoryError(
            exc.args[0] if exc.args else "AUTOMATIC_BUY_ACCOUNT_PERMISSION_UNRESOLVED"
        ) from exc
    automatic_buy_execution_enabled = resolved_permission is not None and resolved_permission.execution_enabled

    proposed_position_amount_eur = (
        resolved_bucket_config.max_position_amount_eur
        if resolved_bucket_config is not None and resolved_bucket_config.max_position_amount_eur is not None
        else Decimal("0")
    )

    evidence = AutomaticBuyAccountAllocationEvidenceV1(
        evidence_contract_version=EVIDENCE_CONTRACT_VERSION,
        trading_account_id=trading_account_id,
        venue=venue,
        asset_id=asset_id,
        market=market,
        strategy_bucket_id=strategy_bucket_id,
        evaluation_ts_utc=evaluation_ts_utc,
        account_observed_ts_utc=bundle.snapshot_ts_utc,
        account_enabled=account.enabled,
        account_mode=account.account_mode,
        live_trading_enabled=account.live_trading_enabled,
        automatic_buy_execution_enabled=automatic_buy_execution_enabled,
        free_quote_balance_eur=free_quote_balance_eur,
        free_quote_balance_observed_ts_utc=bundle.snapshot_ts_utc,
        blocking_conflict=blocking_conflict,
        proposed_position_amount_eur=proposed_position_amount_eur,
        current_bucket_amount_eur=total_position_value_eur,
        current_open_positions=len(positions),
        current_asset_exposure_pct=current_asset_exposure_pct,
        account_state_snapshot_run_id=bundle.account_state_snapshot_run_id,
        trading_account_balance_snapshot_id=balance_snapshot_id,
    )
    try:
        validate_automatic_buy_account_allocation_evidence_v1(evidence, max_age_seconds=max_account_state_age_seconds)
    except AutomaticBuyAccountAllocationEvidenceContractError as exc:
        raise AutomaticBuyAccountAllocationEvidenceRepositoryError(
            exc.args[0] if exc.args else "INVALID_ACCOUNT_ALLOCATION_EVIDENCE"
        ) from exc
    return evidence
