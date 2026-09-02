"""Canonical persisted market-only MA breadth snapshot, version 1.

This module owns only the aggregate MA50 participation measurement.  It reads
canonical persisted candles and reuses ``candle_feat_builder`` for the per-series
SMA50 primitive; it contains no account, broker, decision, planning, or
reporting coupling.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Iterable

import pandas as pd

from src.features.candle_feat_builder import CandleFeatureConfig, build_candle_features
from src.market_data.publication_cohort_contract_v1 import fetch_publication_cohort_contract


MODEL_ID = "ma_breadth_snapshot"
MODEL_VERSION = "1.0"
INPUT_INTERVAL = "4h"
LOOKBACK_HORIZON = "50 bars @ 4h"
EFFECTIVE_HORIZON = "UNKNOWN"
FRESHNESS_STATUS = "UNKNOWN"
UNIVERSE_ID = "publication_cohort_enabled_tradeable_venue_market"
UNIVERSE_VERSION = "asset_publication_cohort_unambiguous_candle_identity_v1"
DATA_STATUS_AVAILABLE = "AVAILABLE"
DATA_STATUS_INSUFFICIENT = "INSUFFICIENT_DATA"


class MABreadthInputError(ValueError):
    """Raised when the required canonical input shape is unavailable."""


@dataclass(frozen=True)
class UniverseMember:
    asset_id: int
    market: str
    symbol: str


@dataclass(frozen=True)
class MABreadthSnapshot:
    asof_ts_utc: datetime
    venue: str
    universe_id: str
    universe_version: str
    universe_hash: str
    input_interval: str
    lookback_horizon: str
    effective_horizon: str
    freshness_status: str
    model_id: str
    model_version: str
    data_status: str
    eligible_count: int
    evaluated_count: int
    insufficient_history_count: int
    stale_constituent_count: int
    coverage_pct: Decimal
    universe_above_sma50_count: int
    universe_above_sma50_pct: Decimal | None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def universe_identity(members: Iterable[UniverseMember]) -> str:
    payload = [
        {"asset_id": member.asset_id, "market": member.market, "symbol": member.symbol}
        for member in sorted(members, key=lambda item: (item.asset_id, item.market, item.symbol))
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _market_by_asset(members: Iterable[UniverseMember]) -> dict[int, str]:
    """Return the only market that may be attributed to each candle asset.

    ``obs_market_candle`` is keyed by asset/venue/interval/open timestamp and
    has no market-level identity. A caller that supplies two markets for one
    asset would therefore make attribution unprovable; reject that input.
    """
    result: dict[int, str] = {}
    for member in members:
        existing = result.get(member.asset_id)
        if existing is not None:
            raise MABreadthInputError(
                "ambiguous candle market identity for "
                f"asset_id={member.asset_id}: {existing!r} and {member.market!r}"
            )
        result[member.asset_id] = member.market
    return result


def build_snapshot(
    *, members: Iterable[UniverseMember], candles: pd.DataFrame, asof_ts_utc: datetime,
    venue: str, interval_code: str,
) -> MABreadthSnapshot:
    """Build a point-in-time snapshot without any latest-row fallback.

    Percentage denominator is ``evaluated_count``: only constituents with an
    exact-asof candle and a valid 50-bar SMA are evaluated.  ``eligible_count``
    is retained unchanged, so insufficient history never becomes "below MA".
    A stale constituent has candle history but no exact-asof candle.
    """
    if interval_code != INPUT_INTERVAL:
        raise MABreadthInputError(f"unsupported input interval: {interval_code}")
    asof = _utc(asof_ts_utc)
    universe = tuple(sorted(members, key=lambda item: (item.asset_id, item.market)))
    _market_by_asset(universe)
    if candles.empty:
        candles = pd.DataFrame(columns=["venue", "asset_id", "market", "interval_code", "close_ts_utc", "open_price", "high_price", "low_price", "close_price", "volume_base"])
    required = {"venue", "asset_id", "market", "interval_code", "close_ts_utc", "open_price", "high_price", "low_price", "close_price", "volume_base"}
    missing = required.difference(candles.columns)
    if missing:
        raise MABreadthInputError(f"candle input missing columns: {sorted(missing)}")
    source = candles.copy()
    source["close_ts_utc"] = pd.to_datetime(source["close_ts_utc"], utc=True, errors="raise")
    if not source.empty and set(source["interval_code"].astype(str)) != {INPUT_INTERVAL}:
        raise MABreadthInputError("candle input contains wrong interval")
    source = source[source["close_ts_utc"] <= pd.Timestamp(asof)].copy()
    source = source[source["venue"].astype(str) == venue].copy()
    member_keys = {(member.asset_id, member.market) for member in universe}
    source = source[source.apply(lambda row: (int(row["asset_id"]), str(row["market"])) in member_keys, axis=1)].copy()
    if source.empty:
        featured = source
    else:
        featured = build_candle_features(pd.DataFrame({
            "venue": source["venue"], "market": source["market"], "interval": source["interval_code"],
            "start_ts": source["close_ts_utc"], "end_ts": source["close_ts_utc"] + pd.Timedelta(hours=4),
            "open": source["open_price"], "high": source["high_price"], "low": source["low_price"],
            "close": source["close_price"], "volume": source["volume_base"], "is_final": True,
            "asset_id": source["asset_id"], "close_ts_utc": source["close_ts_utc"],
        }), CandleFeatureConfig(group_cols=("venue", "asset_id", "market", "interval"), sma_windows=(20, 50)))
    evaluated = above = insufficient = stale = 0
    exact_asof = pd.Timestamp(asof)
    for member in universe:
        rows = featured[
            (featured["venue"].astype(str) == venue)
            & (featured["asset_id"] == member.asset_id)
            & (featured["market"].astype(str) == member.market)
        ] if not featured.empty else featured
        if rows.empty:
            insufficient += 1
            continue
        exact_rows = rows.loc[rows["close_ts_utc"] == exact_asof]
        if exact_rows.empty:
            stale += 1
            continue
        if len(exact_rows) != 1:
            raise MABreadthInputError(
                "duplicate exact-asof candle rows for "
                f"venue={venue} asset_id={member.asset_id} market={member.market} "
                f"interval={INPUT_INTERVAL} asof={asof.isoformat()}"
            )
        row = exact_rows.iloc[0]
        if pd.isna(row["sma_50"]):
            insufficient += 1
            continue
        evaluated += 1
        above += int(bool(row["close_above_sma50"]))
    eligible = len(universe)
    coverage = Decimal("0") if eligible == 0 else Decimal(evaluated * 100) / Decimal(eligible)
    pct = None if evaluated == 0 else Decimal(above * 100) / Decimal(evaluated)
    return MABreadthSnapshot(
        asof_ts_utc=asof, venue=venue, universe_id=UNIVERSE_ID, universe_version=UNIVERSE_VERSION,
        universe_hash=universe_identity(universe), input_interval=INPUT_INTERVAL,
        lookback_horizon=LOOKBACK_HORIZON, effective_horizon=EFFECTIVE_HORIZON,
        freshness_status=FRESHNESS_STATUS, model_id=MODEL_ID, model_version=MODEL_VERSION,
        data_status=DATA_STATUS_AVAILABLE if evaluated else DATA_STATUS_INSUFFICIENT,
        eligible_count=eligible, evaluated_count=evaluated, insufficient_history_count=insufficient,
        stale_constituent_count=stale, coverage_pct=coverage,
        universe_above_sma50_count=above, universe_above_sma50_pct=pct,
    )


def fetch_universe_members(conn: Any, *, venue: str) -> list[UniverseMember]:
    contract = fetch_publication_cohort_contract(conn)
    sql = f"""
    SELECT a.asset_id, vm.market, a.symbol
    FROM venue_market vm JOIN asset a ON a.asset_id = vm.base_asset_id
    WHERE vm.venue=%s AND vm.is_tradeable=1 AND a.is_enabled=1
      AND COALESCE(a.is_tradeable, 0)=1 AND {contract.predicate('a')}
      AND 1 = (
          SELECT COUNT(*)
          FROM venue_market candidate_vm
          WHERE candidate_vm.venue = vm.venue
            AND candidate_vm.base_asset_id = vm.base_asset_id
            AND candidate_vm.is_tradeable = 1
      )
    ORDER BY a.asset_id, vm.market
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue,))
        return [UniverseMember(int(row["asset_id"]), str(row["market"]), str(row["symbol"]).upper()) for row in cur.fetchall()]


def fetch_candles_at_or_before(conn: Any, *, members: Iterable[UniverseMember], venue: str, asof_ts_utc: datetime) -> pd.DataFrame:
    member_list = tuple(members)
    if not member_list:
        return pd.DataFrame()
    market_by_asset = _market_by_asset(member_list)
    placeholders = ",".join(["%s"] * len(member_list))
    sql = f"""
    SELECT c.venue, c.asset_id, c.interval_code, c.close_ts_utc, c.open_price, c.high_price,
           c.low_price, c.close_price, c.volume_base
    FROM obs_market_candle c
    WHERE c.venue=%s AND c.interval_code=%s AND c.close_ts_utc<=%s
      AND c.asset_id IN ({placeholders})
    ORDER BY c.asset_id, c.close_ts_utc
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, INPUT_INTERVAL, _utc(asof_ts_utc).replace(tzinfo=None), *[member.asset_id for member in member_list]))
        rows = cur.fetchall()
    candles = pd.DataFrame(rows)
    if not candles.empty:
        candles["market"] = candles["asset_id"].map(market_by_asset)
    return candles


def persist_snapshot(conn: Any, snapshot: MABreadthSnapshot, *, authorization: Any) -> str:
    from src.operations.writer_capability_authorization_v1 import require_writer_mutation_authorization
    require_writer_mutation_authorization(authorization, "ma_breadth_snapshot")
    sql = """
    INSERT INTO ma_breadth_snapshot_v1 (
      asof_ts_utc,venue,universe_id,universe_version,universe_hash,input_interval,lookback_horizon,
      effective_horizon,freshness_status,model_id,model_version,data_status,eligible_count,evaluated_count,
      insufficient_history_count,stale_constituent_count,coverage_pct,universe_above_sma50_count,universe_above_sma50_pct
    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE created_at=created_at
    """
    values = (snapshot.asof_ts_utc.replace(tzinfo=None), snapshot.venue, snapshot.universe_id, snapshot.universe_version,
              snapshot.universe_hash, snapshot.input_interval, snapshot.lookback_horizon, snapshot.effective_horizon,
              snapshot.freshness_status, snapshot.model_id, snapshot.model_version, snapshot.data_status,
              snapshot.eligible_count, snapshot.evaluated_count, snapshot.insufficient_history_count,
              snapshot.stale_constituent_count, str(snapshot.coverage_pct), snapshot.universe_above_sma50_count,
              None if snapshot.universe_above_sma50_pct is None else str(snapshot.universe_above_sma50_pct))
    with conn.cursor() as cur:
        created = int(cur.execute(sql, values)) > 0
    conn.commit()
    return "CREATED" if created else "NOOP_ALREADY_EXISTS"
