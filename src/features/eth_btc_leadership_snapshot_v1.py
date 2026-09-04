"""Canonical persisted market-only ETH/BTC leadership snapshot, version 1.

Issue #721 (implementation only). Issue #305 remains the semantic/architecture
owner of ETH/BTC leadership; this module produces raw, market-only evidence
for #305's future classifier and for #617's downstream
`RegimeEvidenceEnvelopeV1` to consume. It does not compute or invent a
leadership state/band -- only exact return/ratio arithmetic between the
canonical BTC and ETH candle series.

Per `docs/architecture/regime_evidence_matrix_audit_v1.md` 3.7/3.8, no
canonical ETH/BTC leadership producer existed before this module, and no
native ETH/BTC market exists at the venue (Bitvavo is EUR-quote only). The
ratio/return pair is therefore derived from the separately persisted
`BTC-EUR`/`ETH-EUR` candle series in `obs_market_candle` (keyed by
`asset_id`+`venue`+`interval_code`, per issue #310's audit -- that table
carries no market/pair identity of its own), never read as a native
venue market pair.

Per #243 3.3, `effective_horizon` is never inferred from `input_interval`.
No #305 owner decision has declared an `effective_horizon` for ETH/BTC
leadership yet, so this module leaves it `UNKNOWN` and always adds
`UNMAPPED_HORIZON` to `reason_codes`, mirroring the same fail-closed pattern
already used by `relative_strength_evidence_contract_v1.py` for the same
unresolved-ownership situation -- this is a documented blocker, not an
invented value.

Freshness reuses the existing canonical persisted-candle freshness authority
(`src.operations.persisted_market_candle_freshness_v1`, issue #606) rather
than inventing a new staleness rule: for each of the four required exact
candle boundaries (BTC/ETH, at-asof/at-lookback) this module asks that
canonical classifier whether the exact expected close is persisted, stale,
missing, malformed, or future-dated, and folds the four results into one
overall `freshness`/`data_status`. This is a per-asset extension of that
canonical classifier (which itself is venue+interval scoped, not
asset-scoped): `fetch_asset_boundary` below issues its own asset_id-filtered
query, then hands the result to the unmodified, already-reviewed
`classify_persisted_candle_boundary` function.

No `selection_engine`, `decision_gate`, `execution_planner`, `executor`, or
account-aware logic is read or written by this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from src.operations.persisted_market_candle_freshness_v1 import (
    FUTURE as _CANDLE_FUTURE,
    MALFORMED as _CANDLE_MALFORMED,
    MISSING as _CANDLE_MISSING,
    STALE as _CANDLE_STALE,
    classify_persisted_candle_boundary,
)

MODEL_ID = "eth_btc_leadership_snapshot"
MODEL_VERSION = "1.0"
VENUE = "bitvavo"
BTC_SYMBOL = "BTC"
ETH_SYMBOL = "ETH"

# Canonical market identity (#305/#721 audit): Bitvavo is EUR-quote only, and
# these are the exact, reviewed venue_market strings this producer is allowed
# to read. A non-canonical venue or a non-EUR/mismatched-quote market (e.g.
# BTC-USD, ETH-USDT) must never silently substitute for these -- fail closed
# instead of accepting any tradeable market for the symbol.
BTC_MARKET = "BTC-EUR"
ETH_MARKET = "ETH-EUR"
CANONICAL_MARKETS: dict[str, str] = {BTC_SYMBOL: BTC_MARKET, ETH_SYMBOL: ETH_MARKET}

# Deterministic producer-owned facts, not guesses: the only persisted candle
# series usable for this comparison today is the daily series, and one
# interval back is exactly the smallest, least-ambiguous lookback for a
# leadership return comparison. A longer/multi-horizon lane is an explicit
# future extension, not invented here.
INPUT_INTERVAL = "1d"
LOOKBACK_HORIZON = "24h"
# The exact timedelta a persisted `lookback_horizon="24h"` claim represents.
# `build_snapshot` enforces `lookback_ts_utc == asof_ts_utc - LOOKBACK_DELTA`
# exactly so the persisted `lookback_horizon` label can never silently
# describe a caller-supplied `lookback_ts_utc` that does not actually match.
LOOKBACK_DELTA = timedelta(hours=24)

# #305 has not made a reviewed `effective_horizon` declaration for ETH/BTC
# leadership. Per #243 3.3 this must never be inferred from `input_interval`,
# so it stays UNKNOWN (see module docstring) until #305 records one.
EFFECTIVE_HORIZON = "UNKNOWN"

FRESHNESS_FRESH = "FRESH"
FRESHNESS_STALE = "STALE"
FRESHNESS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

DATA_STATUS_AVAILABLE = "AVAILABLE"
DATA_STATUS_INSUFFICIENT = "INSUFFICIENT_DATA"


class ReasonCode:
    MISSING_BTC_CANDLE = "MISSING_BTC_CANDLE"
    MISSING_ETH_CANDLE = "MISSING_ETH_CANDLE"
    MISSING_BTC_LOOKBACK_CANDLE = "MISSING_BTC_LOOKBACK_CANDLE"
    MISSING_ETH_LOOKBACK_CANDLE = "MISSING_ETH_LOOKBACK_CANDLE"
    STALE_BTC_CANDLE = "STALE_BTC_CANDLE"
    STALE_ETH_CANDLE = "STALE_ETH_CANDLE"
    STALE_BTC_LOOKBACK_CANDLE = "STALE_BTC_LOOKBACK_CANDLE"
    STALE_ETH_LOOKBACK_CANDLE = "STALE_ETH_LOOKBACK_CANDLE"
    MALFORMED_CANDLE_BOUNDARY = "MALFORMED_CANDLE_BOUNDARY"
    FUTURE_CANDLE_BOUNDARY = "FUTURE_CANDLE_BOUNDARY"
    ASOF_AFTER_EVALUATION_TS = "ASOF_AFTER_EVALUATION_TS"
    LOOKBACK_HORIZON_MISALIGNED = "LOOKBACK_HORIZON_MISALIGNED"
    NONPOSITIVE_CANDLE_PRICE = "NONPOSITIVE_CANDLE_PRICE"
    UNMAPPED_HORIZON = "UNMAPPED_HORIZON"


class EthBtcLeadershipInputError(ValueError):
    """Raised when the required canonical input shape is unavailable."""


@dataclass(frozen=True, slots=True)
class EthBtcLeadershipSnapshot:
    asof_ts_utc: datetime
    venue: str
    btc_market: str
    eth_market: str
    input_interval: str
    lookback_horizon: str
    effective_horizon: str
    model_id: str
    model_version: str
    freshness: str
    data_status: str
    btc_return_pct: Decimal | None
    eth_return_pct: Decimal | None
    eth_minus_btc_return_pct: Decimal | None
    eth_btc_ratio_start: Decimal | None
    eth_btc_ratio_end: Decimal | None
    eth_btc_ratio_change_pct: Decimal | None
    reason_codes: tuple[str, ...]
    provenance: dict[str, Any]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: Any) -> str | None:
    return _utc(value).isoformat() if isinstance(value, datetime) else None


class _MalformedPrice:
    """Sentinel: a candle price was present but not a finite decimal number
    (non-numeric, NaN, or +/-Infinity). Distinct from `None` (absent)."""

    __slots__ = ()


_MALFORMED_PRICE = _MalformedPrice()


def _price(value: Any) -> Decimal | None | _MalformedPrice:
    """Parse a candle price defensively; never raises.

    Returns `None` if `value` is absent, `_MALFORMED_PRICE` if `value` is
    present but not a finite decimal number (non-numeric, NaN, or
    +/-Infinity), otherwise the parsed `Decimal`.
    """
    if value is None:
        return None
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return _MALFORMED_PRICE
    if not price.is_finite():
        return _MALFORMED_PRICE
    return price


def _boundary_summary(row: Mapping[str, Any] | None, expected_close_ts_utc: datetime) -> dict[str, Any]:
    classification = classify_persisted_candle_boundary(row, expected_close_ts_utc=expected_close_ts_utc)
    return {
        "expected_close_ts_utc": classification.expected_close_ts_utc.isoformat(),
        "latest_close_ts_utc": _iso(classification.latest_close_ts_utc),
        "freshness_classification": classification.freshness_classification,
        "expected_close_row_count": classification.expected_close_row_count,
    }


def build_snapshot(
    *,
    btc_asof_row: Mapping[str, Any] | None,
    eth_asof_row: Mapping[str, Any] | None,
    btc_lookback_row: Mapping[str, Any] | None,
    eth_lookback_row: Mapping[str, Any] | None,
    asof_ts_utc: datetime,
    lookback_ts_utc: datetime,
    evaluated_at: datetime,
    venue: str,
    interval_code: str,
    btc_market: str,
    eth_market: str,
) -> EthBtcLeadershipSnapshot:
    """Build a point-in-time ETH/BTC leadership snapshot without any
    latest-row fallback.

    Every candle row must be the exact historical (or current) row for the
    exact expected boundary being evaluated -- this function performs no
    lookup of its own, so a replay caller can never receive a "latest" row
    for a historical asof. `evaluated_at` is a required keyword argument with
    no default, so this function never reads the wall clock.
    """
    if interval_code != INPUT_INTERVAL:
        raise EthBtcLeadershipInputError(f"unsupported input interval: {interval_code}")

    asof = _utc(asof_ts_utc)
    lookback = _utc(lookback_ts_utc)
    evaluated = _utc(evaluated_at)

    # The persisted `lookback_horizon` label is the fixed constant "24h", so
    # the caller-supplied `lookback_ts_utc` must exactly equal
    # `asof - LOOKBACK_DELTA`. A mismatched lookback would let the persisted
    # label silently misdescribe the actual comparison window -- fail closed
    # deterministically rather than accepting an arbitrary lookback.
    if lookback != asof - LOOKBACK_DELTA:
        return EthBtcLeadershipSnapshot(
            asof_ts_utc=asof,
            venue=venue,
            btc_market=btc_market,
            eth_market=eth_market,
            input_interval=INPUT_INTERVAL,
            lookback_horizon=LOOKBACK_HORIZON,
            effective_horizon=EFFECTIVE_HORIZON,
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
            freshness=FRESHNESS_INSUFFICIENT_DATA,
            data_status=DATA_STATUS_INSUFFICIENT,
            btc_return_pct=None,
            eth_return_pct=None,
            eth_minus_btc_return_pct=None,
            eth_btc_ratio_start=None,
            eth_btc_ratio_end=None,
            eth_btc_ratio_change_pct=None,
            reason_codes=(ReasonCode.LOOKBACK_HORIZON_MISALIGNED, ReasonCode.UNMAPPED_HORIZON),
            provenance={
                "asof_ts_utc": asof.isoformat(),
                "lookback_ts_utc": lookback.isoformat(),
                "expected_lookback_ts_utc": (asof - LOOKBACK_DELTA).isoformat(),
            },
        )

    def _blocked(freshness: str, reason_codes: list[str]) -> EthBtcLeadershipSnapshot:
        provenance = {
            "btc_asset_asof_boundary": _boundary_summary(btc_asof_row, asof),
            "eth_asset_asof_boundary": _boundary_summary(eth_asof_row, asof),
            "btc_asset_lookback_boundary": _boundary_summary(btc_lookback_row, lookback),
            "eth_asset_lookback_boundary": _boundary_summary(eth_lookback_row, lookback),
        }
        return EthBtcLeadershipSnapshot(
            asof_ts_utc=asof,
            venue=venue,
            btc_market=btc_market,
            eth_market=eth_market,
            input_interval=INPUT_INTERVAL,
            lookback_horizon=LOOKBACK_HORIZON,
            effective_horizon=EFFECTIVE_HORIZON,
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
            freshness=freshness,
            data_status=DATA_STATUS_INSUFFICIENT,
            btc_return_pct=None,
            eth_return_pct=None,
            eth_minus_btc_return_pct=None,
            eth_btc_ratio_start=None,
            eth_btc_ratio_end=None,
            eth_btc_ratio_change_pct=None,
            reason_codes=tuple(dict.fromkeys(reason_codes + [ReasonCode.UNMAPPED_HORIZON])),
            provenance=provenance,
        )

    # Future as-of is a data-integrity contradiction, not a staleness
    # judgement -- fail closed before any candle boundary is even consulted.
    if asof > evaluated or lookback > evaluated:
        return _blocked(FRESHNESS_INSUFFICIENT_DATA, [ReasonCode.ASOF_AFTER_EVALUATION_TS])

    btc_asof = classify_persisted_candle_boundary(btc_asof_row, expected_close_ts_utc=asof)
    eth_asof = classify_persisted_candle_boundary(eth_asof_row, expected_close_ts_utc=asof)
    btc_lb = classify_persisted_candle_boundary(btc_lookback_row, expected_close_ts_utc=lookback)
    eth_lb = classify_persisted_candle_boundary(eth_lookback_row, expected_close_ts_utc=lookback)

    legs = (
        (btc_asof, ReasonCode.MISSING_BTC_CANDLE, ReasonCode.STALE_BTC_CANDLE),
        (eth_asof, ReasonCode.MISSING_ETH_CANDLE, ReasonCode.STALE_ETH_CANDLE),
        (btc_lb, ReasonCode.MISSING_BTC_LOOKBACK_CANDLE, ReasonCode.STALE_BTC_LOOKBACK_CANDLE),
        (eth_lb, ReasonCode.MISSING_ETH_LOOKBACK_CANDLE, ReasonCode.STALE_ETH_LOOKBACK_CANDLE),
    )

    reason_codes: list[str] = []
    hard_fail = False
    stale_present = False
    for classification, missing_code, stale_code in legs:
        state = classification.freshness_classification
        if state == _CANDLE_MISSING:
            reason_codes.append(missing_code)
            hard_fail = True
        elif state == _CANDLE_MALFORMED:
            reason_codes.append(ReasonCode.MALFORMED_CANDLE_BOUNDARY)
            hard_fail = True
        elif state == _CANDLE_FUTURE:
            reason_codes.append(ReasonCode.FUTURE_CANDLE_BOUNDARY)
            hard_fail = True
        elif state == _CANDLE_STALE:
            reason_codes.append(stale_code)
            stale_present = True

    if hard_fail:
        return _blocked(FRESHNESS_INSUFFICIENT_DATA, reason_codes)
    if stale_present:
        return _blocked(FRESHNESS_STALE, reason_codes)

    # All four boundaries are exactly persisted (FRESH) -- proceed with exact
    # numeric computation only.
    btc_close_asof = _price((btc_asof_row or {}).get("expected_close_price"))
    eth_close_asof = _price((eth_asof_row or {}).get("expected_close_price"))
    btc_close_lb = _price((btc_lookback_row or {}).get("expected_close_price"))
    eth_close_lb = _price((eth_lookback_row or {}).get("expected_close_price"))

    prices = (btc_close_asof, eth_close_asof, btc_close_lb, eth_close_lb)

    if any(price is None for price in prices):
        return _blocked(FRESHNESS_INSUFFICIENT_DATA, [ReasonCode.MALFORMED_CANDLE_BOUNDARY])
    if any(price is _MALFORMED_PRICE for price in prices):
        return _blocked(FRESHNESS_INSUFFICIENT_DATA, [ReasonCode.MALFORMED_CANDLE_BOUNDARY])

    # All four prices are now confirmed to be finite Decimal values (never
    # NaN/Infinity/non-numeric). They must also be strictly positive before
    # any division: a zero/negative price is a data-integrity contradiction
    # (never a real traded price), so this fails closed explicitly rather
    # than letting a zero denominator raise
    # `DivisionByZero`/`InvalidOperation` uncaught.
    if btc_close_lb <= 0 or btc_close_asof <= 0 or eth_close_lb <= 0 or eth_close_asof <= 0:
        return _blocked(FRESHNESS_INSUFFICIENT_DATA, [ReasonCode.NONPOSITIVE_CANDLE_PRICE])

    try:
        btc_return_pct = ((btc_close_asof / btc_close_lb) - Decimal("1")) * Decimal("100")
        eth_return_pct = ((eth_close_asof / eth_close_lb) - Decimal("1")) * Decimal("100")
        eth_minus_btc_return_pct = eth_return_pct - btc_return_pct
        eth_btc_ratio_start = eth_close_lb / btc_close_lb
        eth_btc_ratio_end = eth_close_asof / btc_close_asof
        eth_btc_ratio_change_pct = ((eth_btc_ratio_end / eth_btc_ratio_start) - Decimal("1")) * Decimal("100")
    except (InvalidOperation, ArithmeticError):
        # Defense in depth: the checks above already rule out every known
        # cause of a Decimal arithmetic exception here, so this should be
        # unreachable, but arithmetic must never leak an exception past this
        # boundary -- fail closed instead.
        return _blocked(FRESHNESS_INSUFFICIENT_DATA, [ReasonCode.MALFORMED_CANDLE_BOUNDARY])

    return EthBtcLeadershipSnapshot(
        asof_ts_utc=asof,
        venue=venue,
        btc_market=btc_market,
        eth_market=eth_market,
        input_interval=INPUT_INTERVAL,
        lookback_horizon=LOOKBACK_HORIZON,
        effective_horizon=EFFECTIVE_HORIZON,
        model_id=MODEL_ID,
        model_version=MODEL_VERSION,
        freshness=FRESHNESS_FRESH,
        data_status=DATA_STATUS_AVAILABLE,
        btc_return_pct=btc_return_pct,
        eth_return_pct=eth_return_pct,
        eth_minus_btc_return_pct=eth_minus_btc_return_pct,
        eth_btc_ratio_start=eth_btc_ratio_start,
        eth_btc_ratio_end=eth_btc_ratio_end,
        eth_btc_ratio_change_pct=eth_btc_ratio_change_pct,
        reason_codes=(ReasonCode.UNMAPPED_HORIZON,),
        provenance={
            "btc_asset_asof_close_ts_utc": _iso(btc_asof.latest_close_ts_utc),
            "eth_asset_asof_close_ts_utc": _iso(eth_asof.latest_close_ts_utc),
            "btc_asset_lookback_close_ts_utc": _iso(btc_lb.latest_close_ts_utc),
            "eth_asset_lookback_close_ts_utc": _iso(eth_lb.latest_close_ts_utc),
            "btc_close_asof": str(btc_close_asof),
            "eth_close_asof": str(eth_close_asof),
            "btc_close_lookback": str(btc_close_lb),
            "eth_close_lookback": str(eth_close_lb),
        },
    )


def resolve_unique_symbol_markets(
    rows: list[Mapping[str, Any]],
    *,
    canonical_markets: Mapping[str, str] = CANONICAL_MARKETS,
    venue: str,
) -> dict[str, dict[str, Any]]:
    """Fold raw `(symbol, asset_id, market)` rows into exactly one eligible
    canonical venue_market per required symbol.

    A row is eligible only when its `market` exactly matches the reviewed
    `canonical_markets[symbol]` string (e.g. `"BTC-EUR"`) -- any other
    tradeable market for the same symbol (a different quote currency, a
    mismatched pair, a stray duplicate listing) is not eligible and is
    silently excluded from consideration, never picked as a fallback.

    `obs_market_candle` carries no market/pair identity of its own (per
    #310's audit), so an ambiguous BTC/ETH venue_market -- zero canonical
    eligible rows, or more than one -- can never be resolved by picking an
    arbitrary first/last row: doing so could silently attribute candles to
    the wrong market. Both cases fail closed deterministically instead.
    """
    if venue != VENUE:
        raise EthBtcLeadershipInputError(
            f"unsupported venue: {venue!r} (only {VENUE!r} is canonical)"
        )

    symbols = tuple(canonical_markets)
    by_symbol: dict[str, list[Mapping[str, Any]]] = {symbol: [] for symbol in symbols}
    for row in rows:
        symbol = str(row["symbol"]).upper()
        if symbol not in by_symbol:
            continue
        if str(row["market"]) != canonical_markets[symbol]:
            continue
        by_symbol[symbol].append(row)

    zero = [symbol for symbol in symbols if len(by_symbol[symbol]) == 0]
    if zero:
        raise EthBtcLeadershipInputError(
            f"missing canonical tradeable venue_market for venue={venue!r} "
            f"symbols={ {symbol: canonical_markets[symbol] for symbol in zero} }"
        )
    ambiguous = {symbol: len(by_symbol[symbol]) for symbol in symbols if len(by_symbol[symbol]) > 1}
    if ambiguous:
        raise EthBtcLeadershipInputError(
            f"ambiguous canonical tradeable venue_market for venue={venue!r} "
            f"(more than one eligible row for the exact canonical market): {ambiguous}"
        )
    return {symbol: dict(by_symbol[symbol][0]) for symbol in symbols}


def fetch_btc_eth_markets(conn: Any, *, venue: str) -> dict[str, dict[str, Any]]:
    """Resolve the canonical BTC-EUR/ETH-EUR `(asset_id, market)` identity
    for `venue` via the `venue_market`/`asset` join (same join used by
    `ma_breadth_snapshot_v1.fetch_universe_members`), never a hardcoded
    asset_id, never a non-canonical market, and never an arbitrary pick
    among multiple eligible rows."""
    if venue != VENUE:
        raise EthBtcLeadershipInputError(
            f"unsupported venue: {venue!r} (only {VENUE!r} is canonical)"
        )
    sql = """
        SELECT a.symbol AS symbol, a.asset_id AS asset_id, vm.market AS market
        FROM venue_market vm JOIN asset a ON a.asset_id = vm.base_asset_id
        WHERE vm.venue=%s AND vm.is_tradeable=1 AND a.is_enabled=1
          AND COALESCE(a.is_tradeable, 0)=1 AND a.symbol IN (%s, %s)
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, BTC_SYMBOL, ETH_SYMBOL))
        rows = cur.fetchall()
    return resolve_unique_symbol_markets(rows, venue=venue)


def fetch_asset_boundary(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    asset_id: int,
    expected_close_ts_utc: datetime,
) -> Mapping[str, Any]:
    """Per-asset extension of the canonical (venue, interval)-scoped
    persisted-candle boundary query, filtered to one `asset_id`, returning
    the exact expected close price alongside the boundary aggregates
    consumed by `classify_persisted_candle_boundary`."""
    expected_naive = _utc(expected_close_ts_utc).replace(tzinfo=None)
    sql = """
        SELECT
            MAX(close_ts_utc) AS latest_close_ts_utc,
            COALESCE(SUM(CASE WHEN close_ts_utc = %s THEN 1 ELSE 0 END), 0) AS expected_close_row_count,
            MAX(CASE WHEN close_ts_utc = %s THEN close_price END) AS expected_close_price
        FROM obs_market_candle
        WHERE venue = %s AND interval_code = %s AND asset_id = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (expected_naive, expected_naive, venue.lower(), interval_code, asset_id))
        return cur.fetchone()


def persist_snapshot(conn: Any, snapshot: EthBtcLeadershipSnapshot, *, authorization: Any) -> str:
    from src.operations.writer_capability_authorization_v1 import require_writer_mutation_authorization

    require_writer_mutation_authorization(authorization, "eth_btc_leadership_snapshot")
    sql = """
    INSERT INTO eth_btc_leadership_snapshot_v1 (
      asof_ts_utc,venue,btc_market,eth_market,input_interval,lookback_horizon,effective_horizon,
      model_id,model_version,freshness,data_status,btc_return_pct,eth_return_pct,
      eth_minus_btc_return_pct,eth_btc_ratio_start,eth_btc_ratio_end,eth_btc_ratio_change_pct,
      reason_codes,provenance
    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE created_at=created_at
    """
    values = (
        snapshot.asof_ts_utc.replace(tzinfo=None),
        snapshot.venue,
        snapshot.btc_market,
        snapshot.eth_market,
        snapshot.input_interval,
        snapshot.lookback_horizon,
        snapshot.effective_horizon,
        snapshot.model_id,
        snapshot.model_version,
        snapshot.freshness,
        snapshot.data_status,
        None if snapshot.btc_return_pct is None else str(snapshot.btc_return_pct),
        None if snapshot.eth_return_pct is None else str(snapshot.eth_return_pct),
        None if snapshot.eth_minus_btc_return_pct is None else str(snapshot.eth_minus_btc_return_pct),
        None if snapshot.eth_btc_ratio_start is None else str(snapshot.eth_btc_ratio_start),
        None if snapshot.eth_btc_ratio_end is None else str(snapshot.eth_btc_ratio_end),
        None if snapshot.eth_btc_ratio_change_pct is None else str(snapshot.eth_btc_ratio_change_pct),
        json.dumps(list(snapshot.reason_codes)),
        json.dumps(snapshot.provenance, sort_keys=True),
    )
    with conn.cursor() as cur:
        created = int(cur.execute(sql, values)) > 0
    conn.commit()
    return "CREATED" if created else "NOOP_ALREADY_EXISTS"
