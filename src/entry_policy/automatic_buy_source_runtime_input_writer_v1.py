"""Issue #471: canonical source-owned automatic BUY runtime-input writer.

Accepts caller-controlled market/setup evidence and identity only, and
persists an ``automatic_buy_runtime_input_v1`` snapshot row. It never accepts,
derives, or writes account-owned decision-gate evidence (enablement, mode,
LIVE flag, execution permission, balances, exposure, protection, conflict).
Those columns are written as safe fail-closed placeholders that
``automatic_buy_runtime_repository_v1.build_runtime_item_v1`` unconditionally
overwrites with canonical Issue #474 evidence before any candidate/gate/
planner logic ever runs -- this writer cannot influence that outcome no
matter what placeholder values it stores.

Identity (``trading_account_id``, ``venue``, ``asset_id``, ``market``,
``strategy_bucket_id``) is caller-controlled only to select *which* account's
canonical evidence to load; it never expresses that account's permission
state.

No executor, broker, credential, or order import. No DB writes outside the
single append-only ``automatic_buy_runtime_input_v1`` table.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Final

from pymysql.err import IntegrityError as _MySQLIntegrityError

from src.entry_policy.automatic_buy_runtime_audit_writer_v1 import canonical_json
from src.entry_policy.automatic_buy_candidate_v1 import (
    AutomaticBuySetupContextV1,
    STATE_CANDIDATE,
    evaluate_automatic_buy_candidate_v1,
)
from src.entry_policy.automatic_buy_runtime_contract_v1 import (
    DEFAULT_MAX_RUNTIME_INPUT_AGE_SECONDS,
    RUNTIME_INPUT_LIVE_CONTRACT_VERSION,
    AutomaticBuyRuntimeInputV1,
)

_DUPLICATE_KEY_ERRORS: Final[tuple[type[Exception], ...]] = (_MySQLIntegrityError, sqlite3.IntegrityError)

# Fail-closed placeholders for the account-owned columns. These are never
# read by any decision: build_runtime_item_v1 replaces every one of them with
# canonical Issue #474 evidence before the candidate/gate/planner path runs.
_PLACEHOLDER_ACCOUNT_ENABLED: Final[bool] = False
_PLACEHOLDER_ACCOUNT_MODE: Final[str] = "paper"
_PLACEHOLDER_AUTOMATIC_BUY_EXECUTION_ENABLED: Final[bool] = False
_PLACEHOLDER_LIVE_TRADING_ENABLED: Final[bool] = False
_PLACEHOLDER_FREE_QUOTE_BALANCE_EUR: Final[Decimal] = Decimal("0")
_PLACEHOLDER_BLOCKING_CONFLICT: Final[bool] = True
_PLACEHOLDER_PROPOSED_POSITION_AMOUNT_EUR: Final[Decimal] = Decimal("0.00000001")
_PLACEHOLDER_CURRENT_BUCKET_AMOUNT_EUR: Final[Decimal] = Decimal("0")
_PLACEHOLDER_CURRENT_OPEN_POSITIONS: Final[int] = 0
_PLACEHOLDER_CURRENT_ASSET_EXPOSURE_PCT: Final[Decimal] = Decimal("0")
_PLACEHOLDER_MAX_AUTOMATIC_BUY_NOTIONAL_EUR: Final[Decimal | None] = None
CANONICAL_BUY_GEOMETRY_INTERVAL: Final[str] = "4h"
QUOTE_CURRENCY_EUR: Final[str] = "EUR"


class AutomaticBuySourceRuntimeInputWriterError(RuntimeError):
    pass


class AutomaticBuySourceRuntimeInputConflictError(AutomaticBuySourceRuntimeInputWriterError):
    """A persisted row exists under the same content-derived snapshot key but
    its stored source-owned evidence does not match this request. Fails
    closed rather than silently reusing mismatched evidence."""


@dataclass(frozen=True)
class AutomaticBuyFreshSourceCandidateRequestV1:
    """Source/setup identity for one current canonical market observation.

    Price, observation time, and evidence identity are deliberately absent:
    ``resolve_fresh_source_runtime_input_request_v1`` obtains all three from
    the latest canonical public ``market_price_snapshot`` row. This prevents
    a DRY_RUN producer from accepting operator-supplied timestamps or prices.
    """

    trading_account_id: int
    venue: str
    asset_id: int
    market: str
    strategy_bucket_id: str
    strategy_id: str
    strategy_version: str
    setup_id: str
    setup_ready: bool
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    re_entry_zone_low: Decimal | None
    re_entry_zone_high: Decimal | None


@dataclass(frozen=True)
class AutomaticBuyCanonicalZoneSourceRequestV1:
    """Identity only for a canonical 4h-zone/current-price BUY setup.

    The source resolver owns all geometry, evidence, and freshness facts. The
    caller can select a market/strategy identity, but cannot supply a price,
    zone, timestamp, or provenance assertion.
    """

    trading_account_id: int
    venue: str
    asset_id: int
    market: str
    strategy_bucket_id: str
    strategy_id: str
    strategy_version: str


@dataclass(frozen=True)
class AutomaticBuyCanonicalZoneUniverseSourceRequestV1:
    """Identity for deterministic resolution within the canonical BUY universe.

    Asset, market, price, geometry, timestamps, and provenance remain source-
    owned; callers can neither nominate nor edit a setup. ``trading_account_id``
    is carried into resolved runtime input only; it never filters the market
    universe.
    """

    trading_account_id: int
    venue: str
    strategy_bucket_id: str
    strategy_id: str
    strategy_version: str


@dataclass(frozen=True)
class AutomaticBuySourceRuntimeInputRequestV1:
    """Caller-controlled market/setup evidence and identity only.

    No field here may express account permission, balance, exposure,
    protection, or conflict state. There is deliberately no field for
    ``account_enabled``, ``account_mode``, ``live_trading_enabled``,
    ``automatic_buy_execution_enabled``, or any balance/exposure/protection
    fact -- those are decision-gate-owned and are always sourced from
    canonical Issue #474 evidence, never from this contract.
    """

    evaluation_ts_utc: datetime
    trading_account_id: int
    venue: str
    asset_id: int
    market: str
    strategy_bucket_id: str
    strategy_id: str
    strategy_version: str
    setup_id: str
    setup_ready: bool
    current_price: Decimal
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    re_entry_zone_low: Decimal | None
    re_entry_zone_high: Decimal | None
    setup_evidence_id: str
    setup_observed_ts_utc: datetime
    source_provenance: str


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _valid_zone(low: Decimal | None, high: Decimal | None) -> bool:
    if low is not None and low <= 0:
        return False
    if high is not None and high <= 0:
        return False
    if low is not None and high is not None and high < low:
        return False
    return True


def _validate_fresh_source_candidate_request(request: AutomaticBuyFreshSourceCandidateRequestV1) -> None:
    if (
        not _positive_int(request.trading_account_id)
        or not _positive_int(request.asset_id)
        or not all(_nonempty(item) for item in (
            request.venue,
            request.market,
            request.strategy_bucket_id,
            request.strategy_id,
            request.strategy_version,
            request.setup_id,
        ))
        or type(request.setup_ready) is not bool
        or not _valid_zone(request.entry_zone_low, request.entry_zone_high)
        or not _valid_zone(request.re_entry_zone_low, request.re_entry_zone_high)
    ):
        raise AutomaticBuySourceRuntimeInputWriterError("INVALID_FRESH_SOURCE_CANDIDATE_REQUEST")


def _validate_canonical_zone_source_request(request: AutomaticBuyCanonicalZoneSourceRequestV1) -> None:
    if (
        not _positive_int(request.trading_account_id)
        or not _positive_int(request.asset_id)
        or not all(_nonempty(item) for item in (
            request.venue,
            request.market,
            request.strategy_bucket_id,
            request.strategy_id,
            request.strategy_version,
        ))
    ):
        raise AutomaticBuySourceRuntimeInputWriterError("INVALID_CANONICAL_ZONE_SOURCE_REQUEST")


def _validate_canonical_zone_universe_source_request(
    request: AutomaticBuyCanonicalZoneUniverseSourceRequestV1,
) -> None:
    if (
        not _positive_int(request.trading_account_id)
        or not all(_nonempty(item) for item in (
            request.venue,
            request.strategy_bucket_id,
            request.strategy_id,
            request.strategy_version,
        ))
    ):
        raise AutomaticBuySourceRuntimeInputWriterError("INVALID_CANONICAL_ZONE_UNIVERSE_SOURCE_REQUEST")


def _load_fresh_market_price_row(
    conn: Any, *, venue: str, market: str, now_utc: datetime, max_age_seconds: int,
) -> dict[str, Any]:
    sql = """
    SELECT market_price_snapshot_id, venue, market, price, observed_ts_utc
    FROM market_price_snapshot
    WHERE venue = %s AND market = %s
    ORDER BY observed_ts_utc DESC, market_price_snapshot_id DESC
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, market))
        row = cur.fetchone()
    if row is None:
        raise AutomaticBuySourceRuntimeInputWriterError("MARKET_PRICE_SNAPSHOT_MISSING")
    source = dict(row)
    if str(source["venue"]) != venue or str(source["market"]).upper() != market.upper():
        raise AutomaticBuySourceRuntimeInputWriterError("MARKET_PRICE_IDENTITY_MISMATCH")
    observed_ts_utc = _aware_row_ts(source["observed_ts_utc"])
    age = now_utc.astimezone(timezone.utc) - observed_ts_utc
    if age < timedelta(0) or age > timedelta(seconds=max_age_seconds):
        raise AutomaticBuySourceRuntimeInputWriterError("MARKET_PRICE_SNAPSHOT_STALE")
    source["observed_ts_utc"] = observed_ts_utc
    source["price"] = Decimal(str(source["price"]))
    if source["price"] <= 0:
        raise AutomaticBuySourceRuntimeInputWriterError("INVALID_MARKET_PRICE")
    return source


def resolve_fresh_source_runtime_input_request_v1(
    conn: Any,
    *,
    candidate: AutomaticBuyFreshSourceCandidateRequestV1,
    now_utc: datetime,
    max_age_seconds: int = DEFAULT_MAX_RUNTIME_INPUT_AGE_SECONDS,
) -> AutomaticBuySourceRuntimeInputRequestV1:
    """Build one idempotent source input from a fresh canonical price row.

    The public price observation is the source evidence, so its immutable row
    id and observed timestamp become the evidence id and evaluation timestamp.
    Re-resolving the same row yields the exact same source input; no caller
    can manufacture a newer timestamp or price.
    """
    _validate_fresh_source_candidate_request(candidate)
    if not _aware(now_utc) or max_age_seconds < 0:
        raise AutomaticBuySourceRuntimeInputWriterError("INVALID_EVALUATION_TIMESTAMP")

    source = _load_fresh_market_price_row(
        conn, venue=candidate.venue, market=candidate.market,
        now_utc=now_utc, max_age_seconds=max_age_seconds,
    )
    observed_ts_utc = source["observed_ts_utc"]

    return AutomaticBuySourceRuntimeInputRequestV1(
        evaluation_ts_utc=observed_ts_utc,
        trading_account_id=candidate.trading_account_id,
        venue=candidate.venue,
        asset_id=candidate.asset_id,
        market=candidate.market,
        strategy_bucket_id=candidate.strategy_bucket_id,
        strategy_id=candidate.strategy_id,
        strategy_version=candidate.strategy_version,
        setup_id=candidate.setup_id,
        setup_ready=candidate.setup_ready,
        current_price=source["price"],
        entry_zone_low=candidate.entry_zone_low,
        entry_zone_high=candidate.entry_zone_high,
        re_entry_zone_low=candidate.re_entry_zone_low,
        re_entry_zone_high=candidate.re_entry_zone_high,
        setup_evidence_id=f"market_price_snapshot:{int(source['market_price_snapshot_id'])}",
        setup_observed_ts_utc=observed_ts_utc,
        source_provenance="market_price_snapshot_v1",
    )


def resolve_canonical_zone_source_runtime_input_request_v1(
    conn: Any,
    *,
    candidate: AutomaticBuyCanonicalZoneSourceRequestV1,
    now_utc: datetime,
    max_price_age_seconds: int = DEFAULT_MAX_RUNTIME_INPUT_AGE_SECONDS,
) -> AutomaticBuySourceRuntimeInputRequestV1:
    """Compose a current price with the latest completed canonical 4h map.

    The 4h geometry is fresh only when its ``asof_ts_utc`` matches the latest
    completed canonical 4h candle for the same asset/venue. Price freshness
    remains independently bounded at the normal runtime-input threshold.
    """
    _validate_canonical_zone_source_request(candidate)
    if not _aware(now_utc) or max_price_age_seconds < 0:
        raise AutomaticBuySourceRuntimeInputWriterError("INVALID_EVALUATION_TIMESTAMP")
    price = _load_fresh_market_price_row(
        conn, venue=candidate.venue, market=candidate.market,
        now_utc=now_utc, max_age_seconds=max_price_age_seconds,
    )
    zone_sql = """
    SELECT asof_ts_utc, expected_entry_zone_low, expected_entry_zone_high
    FROM execution_zone_context
    WHERE asset_id = %s AND venue = %s AND interval_code = %s
    ORDER BY asof_ts_utc DESC
    LIMIT 1
    """
    candle_sql = """
    SELECT MAX(close_ts_utc) AS asof_ts_utc
    FROM obs_market_candle
    WHERE asset_id = %s AND venue = %s AND interval_code = %s
    """
    with conn.cursor() as cur:
        cur.execute(zone_sql, (candidate.asset_id, candidate.venue, CANONICAL_BUY_GEOMETRY_INTERVAL))
        zone_row = cur.fetchone()
        cur.execute(candle_sql, (candidate.asset_id, candidate.venue, CANONICAL_BUY_GEOMETRY_INTERVAL))
        candle_row = cur.fetchone()
    if zone_row is None:
        raise AutomaticBuySourceRuntimeInputWriterError("CANONICAL_BUY_GEOMETRY_MISSING")
    if candle_row is None or candle_row["asof_ts_utc"] is None:
        raise AutomaticBuySourceRuntimeInputWriterError("CANONICAL_BUY_GEOMETRY_CANDLE_MISSING")
    zone = dict(zone_row)
    zone_asof_ts_utc = _aware_row_ts(zone["asof_ts_utc"])
    candle_asof_ts_utc = _aware_row_ts(candle_row["asof_ts_utc"])
    if zone_asof_ts_utc != candle_asof_ts_utc:
        raise AutomaticBuySourceRuntimeInputWriterError("CANONICAL_BUY_GEOMETRY_NOT_CURRENT")
    entry_zone_low = _decimal_or_none(zone["expected_entry_zone_low"])
    entry_zone_high = _decimal_or_none(zone["expected_entry_zone_high"])
    if not _valid_zone(entry_zone_low, entry_zone_high) or entry_zone_low is None or entry_zone_high is None:
        raise AutomaticBuySourceRuntimeInputWriterError("CANONICAL_BUY_GEOMETRY_INVALID")

    price_observed_ts_utc = price["observed_ts_utc"]
    zone_identity = (
        f"execution_zone_context:{candidate.asset_id}:{candidate.venue}:"
        f"{CANONICAL_BUY_GEOMETRY_INTERVAL}:{zone_asof_ts_utc.isoformat()}"
    )
    return AutomaticBuySourceRuntimeInputRequestV1(
        evaluation_ts_utc=price_observed_ts_utc,
        trading_account_id=candidate.trading_account_id,
        venue=candidate.venue,
        asset_id=candidate.asset_id,
        market=candidate.market,
        strategy_bucket_id=candidate.strategy_bucket_id,
        strategy_id=candidate.strategy_id,
        strategy_version=candidate.strategy_version,
        setup_id=zone_identity,
        setup_ready=True,
        current_price=price["price"],
        entry_zone_low=entry_zone_low,
        entry_zone_high=entry_zone_high,
        re_entry_zone_low=None,
        re_entry_zone_high=None,
        setup_evidence_id=f"{zone_identity}|market_price_snapshot:{int(price['market_price_snapshot_id'])}",
        setup_observed_ts_utc=price_observed_ts_utc,
        source_provenance="execution_zone_context_v1+market_price_snapshot_v1",
    )


def resolve_actionable_canonical_zone_source_runtime_input_requests_v1(
    conn: Any,
    *,
    universe: AutomaticBuyCanonicalZoneUniverseSourceRequestV1,
    now_utc: datetime,
    max_price_age_seconds: int = DEFAULT_MAX_RUNTIME_INPUT_AGE_SECONDS,
) -> tuple[AutomaticBuySourceRuntimeInputRequestV1, ...]:
    """Resolve actionable setups from the canonical market-only BUY universe.

    Enumeration is deterministic by canonical market identity. Each market is
    independently resolved through the existing 4h geometry/current-price
    source and then evaluated by the unchanged candidate contract; no ranking
    or setup geometry is introduced here. Account identity is only propagated
    into each returned runtime input for the downstream decision gate.
    """
    _validate_canonical_zone_universe_source_request(universe)
    if not _aware(now_utc) or max_price_age_seconds < 0:
        raise AutomaticBuySourceRuntimeInputWriterError("INVALID_EVALUATION_TIMESTAMP")
    sql = """
    SELECT vm.base_asset_id AS asset_id, vm.market
    FROM venue_market vm
    WHERE vm.venue = %s
      AND vm.quote_currency = %s
      AND vm.is_tradeable = 1
      AND EXISTS (
          SELECT 1
          FROM execution_zone_context ezc
          WHERE ezc.asset_id = vm.base_asset_id
            AND ezc.venue COLLATE utf8mb4_unicode_ci = vm.venue COLLATE utf8mb4_unicode_ci
            AND ezc.interval_code = %s
      )
    ORDER BY vm.market, vm.base_asset_id, vm.venue_market_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (universe.venue, QUOTE_CURRENCY_EUR, CANONICAL_BUY_GEOMETRY_INTERVAL))
        rows = [dict(row) for row in cur.fetchall()]

    actionable: list[AutomaticBuySourceRuntimeInputRequestV1] = []
    for row in rows:
        try:
            request = resolve_canonical_zone_source_runtime_input_request_v1(
                conn,
                candidate=AutomaticBuyCanonicalZoneSourceRequestV1(
                    trading_account_id=universe.trading_account_id,
                    venue=universe.venue,
                    asset_id=int(row["asset_id"]),
                    market=str(row["market"]),
                    strategy_bucket_id=universe.strategy_bucket_id,
                    strategy_id=universe.strategy_id,
                    strategy_version=universe.strategy_version,
                ),
                now_utc=now_utc,
                max_price_age_seconds=max_price_age_seconds,
            )
        except AutomaticBuySourceRuntimeInputWriterError:
            continue
        evaluation = evaluate_automatic_buy_candidate_v1(
            setup_context=AutomaticBuySetupContextV1(
                venue=request.venue,
                asset_id=request.asset_id,
                market=request.market,
                strategy_id=request.strategy_id,
                strategy_version=request.strategy_version,
                setup_id=request.setup_id,
                setup_ready=request.setup_ready,
                current_price=request.current_price,
                entry_zone_low=request.entry_zone_low,
                entry_zone_high=request.entry_zone_high,
                re_entry_zone_low=request.re_entry_zone_low,
                re_entry_zone_high=request.re_entry_zone_high,
                evidence_id=request.setup_evidence_id,
                observed_ts_utc=request.setup_observed_ts_utc,
            ),
            evaluation_ts_utc=request.evaluation_ts_utc,
        )
        if evaluation.state == STATE_CANDIDATE:
            actionable.append(request)
    if actionable:
        return tuple(actionable)
    raise AutomaticBuySourceRuntimeInputWriterError("CANONICAL_BUY_ACTIONABLE_CANDIDATE_MISSING")


def resolve_first_actionable_canonical_zone_source_runtime_input_request_v1(
    conn: Any,
    *,
    universe: AutomaticBuyCanonicalZoneUniverseSourceRequestV1,
    now_utc: datetime,
    max_price_age_seconds: int = DEFAULT_MAX_RUNTIME_INPUT_AGE_SECONDS,
) -> AutomaticBuySourceRuntimeInputRequestV1:
    """Return the deterministic first actionable canonical market setup."""
    return resolve_actionable_canonical_zone_source_runtime_input_requests_v1(
        conn,
        universe=universe,
        now_utc=now_utc,
        max_price_age_seconds=max_price_age_seconds,
    )[0]


def validate_source_runtime_input_request_v1(
    request: AutomaticBuySourceRuntimeInputRequestV1,
    *,
    max_age_seconds: int = DEFAULT_MAX_RUNTIME_INPUT_AGE_SECONDS,
) -> None:
    if not _aware(request.evaluation_ts_utc) or max_age_seconds < 0:
        raise AutomaticBuySourceRuntimeInputWriterError("INVALID_EVALUATION_TIMESTAMP")
    if (
        not _positive_int(request.trading_account_id)
        or not _positive_int(request.asset_id)
        or not all(_nonempty(item) for item in (
            request.venue,
            request.market,
            request.strategy_bucket_id,
            request.strategy_id,
            request.strategy_version,
            request.setup_id,
            request.setup_evidence_id,
            request.source_provenance,
        ))
        or type(request.setup_ready) is not bool
        or not isinstance(request.current_price, Decimal)
        or request.current_price <= 0
        or not _valid_zone(request.entry_zone_low, request.entry_zone_high)
        or not _valid_zone(request.re_entry_zone_low, request.re_entry_zone_high)
    ):
        raise AutomaticBuySourceRuntimeInputWriterError("INVALID_SOURCE_RUNTIME_INPUT_REQUEST")

    if not _aware(request.setup_observed_ts_utc):
        raise AutomaticBuySourceRuntimeInputWriterError("INVALID_SOURCE_RUNTIME_INPUT_TIMESTAMP")

    age = request.evaluation_ts_utc - request.setup_observed_ts_utc
    if age < timedelta(0) or age > timedelta(seconds=max_age_seconds):
        raise AutomaticBuySourceRuntimeInputWriterError("STALE_OR_FUTURE_SOURCE_RUNTIME_INPUT")


def _source_identity_payload(request: AutomaticBuySourceRuntimeInputRequestV1) -> dict[str, Any]:
    return {
        "contract": "automatic_buy_source_runtime_input_v1",
        "input_contract_version": RUNTIME_INPUT_LIVE_CONTRACT_VERSION,
        "evaluation_ts_utc": request.evaluation_ts_utc,
        "trading_account_id": request.trading_account_id,
        "venue": request.venue,
        "asset_id": request.asset_id,
        "market": request.market,
        "strategy_bucket_id": request.strategy_bucket_id,
        "strategy_id": request.strategy_id,
        "strategy_version": request.strategy_version,
        "setup_id": request.setup_id,
        "setup_ready": request.setup_ready,
        "current_price": request.current_price,
        "entry_zone_low": request.entry_zone_low,
        "entry_zone_high": request.entry_zone_high,
        "re_entry_zone_low": request.re_entry_zone_low,
        "re_entry_zone_high": request.re_entry_zone_high,
        "setup_evidence_id": request.setup_evidence_id,
        "setup_observed_ts_utc": request.setup_observed_ts_utc,
        "source_provenance": request.source_provenance,
    }


def derive_source_snapshot_key_v1(request: AutomaticBuySourceRuntimeInputRequestV1) -> str:
    return hashlib.sha256(canonical_json(_source_identity_payload(request)).encode("utf-8")).hexdigest()


def _row_to_placeholder_input(
    row: dict[str, Any], *, request: AutomaticBuySourceRuntimeInputRequestV1,
) -> AutomaticBuyRuntimeInputV1:
    return AutomaticBuyRuntimeInputV1(
        automatic_buy_runtime_input_id=int(row["automatic_buy_runtime_input_id"]),
        source_snapshot_key=str(row["source_snapshot_key"]),
        input_contract_version=RUNTIME_INPUT_LIVE_CONTRACT_VERSION,
        evaluation_ts_utc=request.evaluation_ts_utc,
        trading_account_id=request.trading_account_id,
        venue=request.venue,
        asset_id=request.asset_id,
        market=request.market,
        strategy_bucket_id=request.strategy_bucket_id,
        strategy_id=request.strategy_id,
        strategy_version=request.strategy_version,
        setup_id=request.setup_id,
        setup_ready=request.setup_ready,
        current_price=request.current_price,
        entry_zone_low=request.entry_zone_low,
        entry_zone_high=request.entry_zone_high,
        re_entry_zone_low=request.re_entry_zone_low,
        re_entry_zone_high=request.re_entry_zone_high,
        setup_evidence_id=request.setup_evidence_id,
        setup_observed_ts_utc=request.setup_observed_ts_utc,
        account_observed_ts_utc=request.evaluation_ts_utc,
        account_enabled=_PLACEHOLDER_ACCOUNT_ENABLED,
        account_mode=_PLACEHOLDER_ACCOUNT_MODE,
        automatic_buy_execution_enabled=_PLACEHOLDER_AUTOMATIC_BUY_EXECUTION_ENABLED,
        free_quote_balance_eur=_PLACEHOLDER_FREE_QUOTE_BALANCE_EUR,
        free_quote_balance_observed_ts_utc=request.evaluation_ts_utc,
        blocking_conflict=_PLACEHOLDER_BLOCKING_CONFLICT,
        proposed_position_amount_eur=_PLACEHOLDER_PROPOSED_POSITION_AMOUNT_EUR,
        current_bucket_amount_eur=_PLACEHOLDER_CURRENT_BUCKET_AMOUNT_EUR,
        current_open_positions=_PLACEHOLDER_CURRENT_OPEN_POSITIONS,
        current_asset_exposure_pct=_PLACEHOLDER_CURRENT_ASSET_EXPOSURE_PCT,
        max_automatic_buy_notional_eur=_PLACEHOLDER_MAX_AUTOMATIC_BUY_NOTIONAL_EUR,
        source_provenance=request.source_provenance,
        live_trading_enabled=_PLACEHOLDER_LIVE_TRADING_ENABLED,
    )


def _aware_row_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    raise AutomaticBuySourceRuntimeInputWriterError("INVALID_PERSISTED_TIMESTAMP")


def _load_existing_row(conn: Any, snapshot_key: str) -> dict[str, Any] | None:
    sql = """
    SELECT automatic_buy_runtime_input_id, source_snapshot_key, input_contract_version,
           evaluation_ts_utc, trading_account_id, venue, asset_id, market, strategy_bucket_id,
           strategy_id, strategy_version, setup_id, setup_ready, current_price,
           entry_zone_low, entry_zone_high, re_entry_zone_low, re_entry_zone_high,
           setup_evidence_id, setup_observed_ts_utc, source_provenance
    FROM automatic_buy_runtime_input_v1
    WHERE source_snapshot_key = %s
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (snapshot_key,))
        row = cur.fetchone()
    return None if row is None else dict(row)


def _decimal_or_none(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _row_matches_request(row: dict[str, Any], request: AutomaticBuySourceRuntimeInputRequestV1) -> bool:
    try:
        return (
            str(row["input_contract_version"]) == RUNTIME_INPUT_LIVE_CONTRACT_VERSION
            and _aware_row_ts(row["evaluation_ts_utc"]) == request.evaluation_ts_utc
            and int(row["trading_account_id"]) == request.trading_account_id
            and str(row["venue"]) == request.venue
            and int(row["asset_id"]) == request.asset_id
            and str(row["market"]) == request.market
            and str(row["strategy_bucket_id"]) == request.strategy_bucket_id
            and str(row["strategy_id"]) == request.strategy_id
            and str(row["strategy_version"]) == request.strategy_version
            and str(row["setup_id"]) == request.setup_id
            and bool(row["setup_ready"]) == request.setup_ready
            and Decimal(str(row["current_price"])) == request.current_price
            and _decimal_or_none(row["entry_zone_low"]) == request.entry_zone_low
            and _decimal_or_none(row["entry_zone_high"]) == request.entry_zone_high
            and _decimal_or_none(row["re_entry_zone_low"]) == request.re_entry_zone_low
            and _decimal_or_none(row["re_entry_zone_high"]) == request.re_entry_zone_high
            and str(row["setup_evidence_id"]) == request.setup_evidence_id
            and _aware_row_ts(row["setup_observed_ts_utc"]) == request.setup_observed_ts_utc
            and str(row["source_provenance"]) == request.source_provenance
        )
    except (KeyError, TypeError, ValueError):
        return False


def write_automatic_buy_source_runtime_input_v1(
    conn: Any,
    *,
    request: AutomaticBuySourceRuntimeInputRequestV1,
    max_age_seconds: int = DEFAULT_MAX_RUNTIME_INPUT_AGE_SECONDS,
) -> AutomaticBuyRuntimeInputV1:
    """Persist one immutable source-owned runtime-input snapshot.

    Idempotent: the same logical source snapshot (identical caller-controlled
    fields) always derives the same ``source_snapshot_key`` and reuses the
    same persisted row. A persisted row found under that key whose stored
    evidence does not match this request fails closed with
    ``AutomaticBuySourceRuntimeInputConflictError`` rather than silently
    reusing mismatched evidence.
    """
    validate_source_runtime_input_request_v1(request, max_age_seconds=max_age_seconds)
    snapshot_key = derive_source_snapshot_key_v1(request)

    existing = _load_existing_row(conn, snapshot_key)
    if existing is not None:
        if not _row_matches_request(existing, request):
            raise AutomaticBuySourceRuntimeInputConflictError(snapshot_key)
        return _row_to_placeholder_input(existing, request=request)

    insert_sql = """
    INSERT INTO automatic_buy_runtime_input_v1 (
        source_snapshot_key, input_contract_version, evaluation_ts_utc,
        trading_account_id, venue, asset_id, market, strategy_bucket_id,
        strategy_id, strategy_version, setup_id, setup_ready, current_price,
        entry_zone_low, entry_zone_high, re_entry_zone_low, re_entry_zone_high,
        setup_evidence_id, setup_observed_ts_utc, account_observed_ts_utc,
        account_enabled, account_mode, automatic_buy_execution_enabled,
        live_trading_enabled, free_quote_balance_eur, free_quote_balance_observed_ts_utc,
        blocking_conflict, proposed_position_amount_eur, current_bucket_amount_eur,
        current_open_positions, current_asset_exposure_pct, max_automatic_buy_notional_eur,
        source_provenance
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s
    )
    """
    params = (
        snapshot_key, RUNTIME_INPUT_LIVE_CONTRACT_VERSION, request.evaluation_ts_utc,
        request.trading_account_id, request.venue, request.asset_id, request.market,
        request.strategy_bucket_id, request.strategy_id, request.strategy_version,
        request.setup_id, request.setup_ready, request.current_price,
        request.entry_zone_low, request.entry_zone_high, request.re_entry_zone_low,
        request.re_entry_zone_high, request.setup_evidence_id, request.setup_observed_ts_utc,
        request.evaluation_ts_utc,
        _PLACEHOLDER_ACCOUNT_ENABLED, _PLACEHOLDER_ACCOUNT_MODE,
        _PLACEHOLDER_AUTOMATIC_BUY_EXECUTION_ENABLED, _PLACEHOLDER_LIVE_TRADING_ENABLED,
        _PLACEHOLDER_FREE_QUOTE_BALANCE_EUR, request.evaluation_ts_utc,
        _PLACEHOLDER_BLOCKING_CONFLICT, _PLACEHOLDER_PROPOSED_POSITION_AMOUNT_EUR,
        _PLACEHOLDER_CURRENT_BUCKET_AMOUNT_EUR, _PLACEHOLDER_CURRENT_OPEN_POSITIONS,
        _PLACEHOLDER_CURRENT_ASSET_EXPOSURE_PCT, _PLACEHOLDER_MAX_AUTOMATIC_BUY_NOTIONAL_EUR,
        request.source_provenance,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(insert_sql, params)
            new_id = int(cur.lastrowid)
    except _DUPLICATE_KEY_ERRORS:
        existing = _load_existing_row(conn, snapshot_key)
        if existing is None:
            raise
        if not _row_matches_request(existing, request):
            raise AutomaticBuySourceRuntimeInputConflictError(snapshot_key) from None
        return _row_to_placeholder_input(existing, request=request)

    return AutomaticBuyRuntimeInputV1(
        automatic_buy_runtime_input_id=new_id,
        source_snapshot_key=snapshot_key,
        input_contract_version=RUNTIME_INPUT_LIVE_CONTRACT_VERSION,
        evaluation_ts_utc=request.evaluation_ts_utc,
        trading_account_id=request.trading_account_id,
        venue=request.venue,
        asset_id=request.asset_id,
        market=request.market,
        strategy_bucket_id=request.strategy_bucket_id,
        strategy_id=request.strategy_id,
        strategy_version=request.strategy_version,
        setup_id=request.setup_id,
        setup_ready=request.setup_ready,
        current_price=request.current_price,
        entry_zone_low=request.entry_zone_low,
        entry_zone_high=request.entry_zone_high,
        re_entry_zone_low=request.re_entry_zone_low,
        re_entry_zone_high=request.re_entry_zone_high,
        setup_evidence_id=request.setup_evidence_id,
        setup_observed_ts_utc=request.setup_observed_ts_utc,
        account_observed_ts_utc=request.evaluation_ts_utc,
        account_enabled=_PLACEHOLDER_ACCOUNT_ENABLED,
        account_mode=_PLACEHOLDER_ACCOUNT_MODE,
        automatic_buy_execution_enabled=_PLACEHOLDER_AUTOMATIC_BUY_EXECUTION_ENABLED,
        free_quote_balance_eur=_PLACEHOLDER_FREE_QUOTE_BALANCE_EUR,
        free_quote_balance_observed_ts_utc=request.evaluation_ts_utc,
        blocking_conflict=_PLACEHOLDER_BLOCKING_CONFLICT,
        proposed_position_amount_eur=_PLACEHOLDER_PROPOSED_POSITION_AMOUNT_EUR,
        current_bucket_amount_eur=_PLACEHOLDER_CURRENT_BUCKET_AMOUNT_EUR,
        current_open_positions=_PLACEHOLDER_CURRENT_OPEN_POSITIONS,
        current_asset_exposure_pct=_PLACEHOLDER_CURRENT_ASSET_EXPOSURE_PCT,
        max_automatic_buy_notional_eur=_PLACEHOLDER_MAX_AUTOMATIC_BUY_NOTIONAL_EUR,
        source_provenance=request.source_provenance,
        live_trading_enabled=_PLACEHOLDER_LIVE_TRADING_ENABLED,
    )
