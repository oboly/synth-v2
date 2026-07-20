from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import requests

from src.common.db import get_connection


RUNNER_NAME = "market_rotation_history_v1"
VERSION = "1.0"

CANDLE_INTERVAL = "1h"
CANDLE_INTERVAL_H = 1
HORIZONS_H = (24, 168)
MIN_COVERAGE_RATIO = Decimal("0.90")
MAX_STALENESS_H = 2
VENUE_DEFAULT = "bitvavo"
QUOTE_CURRENCY = "EUR"
TOP_N = 10

# Full lookback needed: baseline of 7d horizon starts at as_of_ts - 336h
_FETCH_LOOKBACK_H = 2 * max(HORIZONS_H)  # 336
FETCH_BATCH_ROWS = 1000

LOCAL_ROTATION_TABLES = (
    "market_rotation_snapshot_v1",
    "market_rotation_observation_v1",
)
GLOBAL_CONTEXT_TABLE = "market_global_snapshot_v1"
REQUIRED_TABLES = LOCAL_ROTATION_TABLES + (
    "market_global_snapshot_v1",
)

PROVIDER_NAME = "coingecko"
COINGECKO_API_KEY_ENV = "COINGECKO_API_KEY"
COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"
COINGECKO_DEMO_HEADER = "x-cg-demo-api-key"
COINGECKO_TIMEOUT_S = 10


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AssetRow:
    asset_id: int
    symbol: str
    market: str


@dataclass(frozen=True)
class CandleRecord:
    asset_id: int
    open_ts_utc: datetime
    close_ts_utc: datetime
    close_price: Decimal
    volume_quote_eur: Decimal


@dataclass(frozen=True)
class HorizonObservation:
    asset_id: int
    market: str
    horizon_h: int
    window_open_ts_utc: datetime
    window_close_ts_utc: datetime
    price_open: Decimal
    price_close: Decimal
    price_change_pct: Decimal
    quote_volume: Decimal
    baseline_quote_volume: Decimal
    relative_volume: Decimal
    candle_count: int
    expected_candle_count: int
    coverage_ratio: Decimal
    baseline_candle_count: int
    baseline_expected_candle_count: int
    baseline_coverage_ratio: Decimal
    as_of_ts_utc: datetime


@dataclass
class GlobalContextResult:
    source_status: str  # AVAILABLE | UNAVAILABLE | SKIPPED_NO_CREDENTIAL
    source_error_reason: str | None
    total_volume_24h_usd: Decimal | None
    volume_change_pct_24h: Decimal | None
    total_market_cap_usd: Decimal | None
    market_cap_change_pct_24h: Decimal | None
    btc_dominance_pct: Decimal | None
    eth_dominance_pct: Decimal | None
    provider_updated_at_utc: datetime | None
    fetched_at_utc: datetime


# ---------------------------------------------------------------------------
# Pure computation functions
# ---------------------------------------------------------------------------

def floor_to_hour(ts: datetime) -> datetime:
    return ts.replace(minute=0, second=0, microsecond=0)


def compute_price_change_pct(price_open: Decimal, price_close: Decimal) -> Decimal:
    if price_open == 0:
        raise ValueError("price_open must be non-zero")
    return (price_close - price_open) / price_open * Decimal("100")


def compute_relative_volume(quote_volume: Decimal, baseline_quote_volume: Decimal) -> Decimal:
    if baseline_quote_volume == 0:
        raise ValueError("baseline_quote_volume must be non-zero")
    return quote_volume / baseline_quote_volume


def compute_coverage_ratio(candle_count: int, expected_count: int) -> Decimal:
    if expected_count == 0:
        return Decimal("0")
    return Decimal(candle_count) / Decimal(expected_count)


def _partition_candles(
    all_candles: list[CandleRecord],
    as_of_ts: datetime,
    horizon_h: int,
) -> tuple[list[CandleRecord], list[CandleRecord]]:
    current_start = as_of_ts - timedelta(hours=horizon_h)
    baseline_start = as_of_ts - timedelta(hours=2 * horizon_h)
    current: list[CandleRecord] = []
    baseline: list[CandleRecord] = []
    for c in all_candles:
        if current_start < c.close_ts_utc <= as_of_ts:
            current.append(c)
        elif baseline_start < c.close_ts_utc <= current_start:
            baseline.append(c)
    return current, baseline


def check_eligibility(
    current_candles: list[CandleRecord],
    baseline_candles: list[CandleRecord],
    as_of_ts: datetime,
    horizon_h: int,
    *,
    min_coverage: Decimal = MIN_COVERAGE_RATIO,
    max_staleness_h: int = MAX_STALENESS_H,
) -> tuple[bool, str]:
    expected = horizon_h // CANDLE_INTERVAL_H
    if not current_candles:
        return False, "NO_CURRENT_CANDLES"
    if not baseline_candles:
        return False, "NO_BASELINE_CANDLES"
    current_cov = compute_coverage_ratio(len(current_candles), expected)
    if current_cov < min_coverage:
        return False, f"LOW_CURRENT_COVERAGE:{float(current_cov):.3f}"
    baseline_cov = compute_coverage_ratio(len(baseline_candles), expected)
    if baseline_cov < min_coverage:
        return False, f"LOW_BASELINE_COVERAGE:{float(baseline_cov):.3f}"
    latest_close = max(c.close_ts_utc for c in current_candles)
    if latest_close < as_of_ts - timedelta(hours=max_staleness_h):
        return False, f"STALE_DATA:{latest_close.isoformat()}"
    baseline_vol = sum((c.volume_quote_eur for c in baseline_candles), Decimal("0"))
    if baseline_vol <= 0:
        return False, "BASELINE_ZERO_VOLUME"
    return True, "OK"


def compute_observation(
    asset_id: int,
    market: str,
    horizon_h: int,
    current_candles: list[CandleRecord],
    baseline_candles: list[CandleRecord],
    as_of_ts: datetime,
) -> HorizonObservation:
    expected = horizon_h // CANDLE_INTERVAL_H
    last_baseline = max(baseline_candles, key=lambda c: c.close_ts_utc)
    first_current = min(current_candles, key=lambda c: c.close_ts_utc)
    last_current = max(current_candles, key=lambda c: c.close_ts_utc)
    price_open = last_baseline.close_price
    price_close = last_current.close_price
    quote_vol = sum((c.volume_quote_eur for c in current_candles), Decimal("0"))
    base_vol = sum((c.volume_quote_eur for c in baseline_candles), Decimal("0"))
    return HorizonObservation(
        asset_id=asset_id,
        market=market,
        horizon_h=horizon_h,
        window_open_ts_utc=first_current.open_ts_utc,
        window_close_ts_utc=last_current.close_ts_utc,
        price_open=price_open,
        price_close=price_close,
        price_change_pct=round(compute_price_change_pct(price_open, price_close), 6),
        quote_volume=round(quote_vol, 6),
        baseline_quote_volume=round(base_vol, 6),
        relative_volume=round(compute_relative_volume(quote_vol, base_vol), 6),
        candle_count=len(current_candles),
        expected_candle_count=expected,
        coverage_ratio=round(compute_coverage_ratio(len(current_candles), expected), 4),
        baseline_candle_count=len(baseline_candles),
        baseline_expected_candle_count=expected,
        baseline_coverage_ratio=round(compute_coverage_ratio(len(baseline_candles), expected), 4),
        as_of_ts_utc=as_of_ts,
    )


# ---------------------------------------------------------------------------
# CoinGecko global context
# ---------------------------------------------------------------------------

def _safe_decimal(val: Any) -> Decimal | None:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def _make_unavailable(reason: str, fetched_at: datetime) -> GlobalContextResult:
    return GlobalContextResult(
        source_status="UNAVAILABLE",
        source_error_reason=reason[:200],
        total_volume_24h_usd=None,
        volume_change_pct_24h=None,
        total_market_cap_usd=None,
        market_cap_change_pct_24h=None,
        btc_dominance_pct=None,
        eth_dominance_pct=None,
        provider_updated_at_utc=None,
        fetched_at_utc=fetched_at,
    )


def _require_mapping(payload: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(field_name)
    return payload


def _require_finite_decimal(raw: Any, field_name: str) -> Decimal:
    value = _safe_decimal(raw)
    if value is None or not value.is_finite():
        raise ValueError(field_name)
    return value


def _require_positive_decimal(raw: Any, field_name: str) -> Decimal:
    value = _require_finite_decimal(raw, field_name)
    if value <= 0:
        raise ValueError(field_name)
    return value


def _require_pct_decimal(raw: Any, field_name: str) -> Decimal:
    value = _require_finite_decimal(raw, field_name)
    if value < 0 or value > 100:
        raise ValueError(field_name)
    return value


def _require_updated_at(raw: Any) -> datetime:
    updated_at = _require_finite_decimal(raw, "updated_at")
    if updated_at != updated_at.to_integral_value():
        raise ValueError("updated_at")
    try:
        return datetime.fromtimestamp(int(updated_at), UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError, OSError) as exc:
        raise ValueError("updated_at") from exc


def normalize_coingecko_global(data: Any, fetched_at: datetime) -> GlobalContextResult:
    try:
        payload = _require_mapping(data, "data")
        total_volume = _require_mapping(payload.get("total_volume"), "total_volume")
        total_market_cap = _require_mapping(payload.get("total_market_cap"), "total_market_cap")
        market_cap_pct = _require_mapping(payload.get("market_cap_percentage"), "market_cap_percentage")
        return GlobalContextResult(
            source_status="AVAILABLE",
            source_error_reason=None,
            total_volume_24h_usd=_require_positive_decimal(total_volume.get("usd"), "total_volume.usd"),
            volume_change_pct_24h=_require_finite_decimal(
                payload.get("volume_change_percentage_24h_usd"),
                "volume_change_percentage_24h_usd",
            ),
            total_market_cap_usd=_require_positive_decimal(total_market_cap.get("usd"), "total_market_cap.usd"),
            market_cap_change_pct_24h=_require_finite_decimal(
                payload.get("market_cap_change_percentage_24h_usd"),
                "market_cap_change_percentage_24h_usd",
            ),
            btc_dominance_pct=_require_pct_decimal(market_cap_pct.get("btc"), "market_cap_percentage.btc"),
            eth_dominance_pct=_require_pct_decimal(market_cap_pct.get("eth"), "market_cap_percentage.eth"),
            provider_updated_at_utc=_require_updated_at(payload.get("updated_at")),
            fetched_at_utc=fetched_at,
        )
    except ValueError as exc:
        return _make_unavailable(f"INVALID_PAYLOAD:{exc}", fetched_at)


def fetch_coingecko_global(api_key: str | None) -> GlobalContextResult:
    fetched_at = datetime.now(UTC).replace(tzinfo=None)
    if not api_key:
        return GlobalContextResult(
            source_status="SKIPPED_NO_CREDENTIAL",
            source_error_reason=None,
            total_volume_24h_usd=None,
            volume_change_pct_24h=None,
            total_market_cap_usd=None,
            market_cap_change_pct_24h=None,
            btc_dominance_pct=None,
            eth_dominance_pct=None,
            provider_updated_at_utc=None,
            fetched_at_utc=fetched_at,
        )
    try:
        resp = requests.get(
            COINGECKO_GLOBAL_URL,
            headers={COINGECKO_DEMO_HEADER: api_key},
            timeout=COINGECKO_TIMEOUT_S,
        )
        resp.raise_for_status()
        try:
            payload = resp.json()
        except ValueError:
            return _make_unavailable("INVALID_PAYLOAD:JSON_DECODE", fetched_at)
        if not isinstance(payload, dict):
            return _make_unavailable("INVALID_PAYLOAD:response", fetched_at)
        return normalize_coingecko_global(payload.get("data"), fetched_at)
    except requests.Timeout:
        return _make_unavailable(f"TIMEOUT_{COINGECKO_TIMEOUT_S}s", fetched_at)
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "unknown"
        return _make_unavailable(f"HTTP_{code}", fetched_at)
    except Exception as exc:
        return _make_unavailable(type(exc).__name__, fetched_at)


# ---------------------------------------------------------------------------
# DB — schema preflight
# ---------------------------------------------------------------------------

def check_schema_ready(conn: Any) -> list[str]:
    placeholders = ", ".join(["%s"] * len(REQUIRED_TABLES))
    sql = (
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        f"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ({placeholders})"
    )
    with conn.cursor() as cur:
        cur.execute(sql, list(REQUIRED_TABLES))
        found = {r["TABLE_NAME"] for r in cur.fetchall()}
    return [t for t in REQUIRED_TABLES if t not in found]


def split_missing_tables(missing_tables: list[str]) -> tuple[list[str], list[str]]:
    local_missing = [table for table in missing_tables if table in LOCAL_ROTATION_TABLES]
    global_missing = [table for table in missing_tables if table == GLOBAL_CONTEXT_TABLE]
    return local_missing, global_missing


# ---------------------------------------------------------------------------
# DB — rotation snapshot
# ---------------------------------------------------------------------------

def fetch_eligible_assets(conn: Any, venue: str) -> list[AssetRow]:
    sql = """
    SELECT a.asset_id, a.symbol, vm.market
    FROM asset a
    JOIN venue_market vm ON vm.base_asset_id = a.asset_id
    WHERE a.is_enabled = 1
      AND COALESCE(a.is_tradeable, 0) = 1
      AND vm.venue = %s
      AND vm.quote_currency = %s
      AND vm.is_tradeable = 1
    ORDER BY a.asset_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, QUOTE_CURRENCY))
        rows = cur.fetchall()
    return [AssetRow(asset_id=int(r["asset_id"]), symbol=str(r["symbol"]), market=str(r["market"])) for r in rows]


def fetch_candles_bulk(
    conn: Any,
    asset_ids: list[int],
    venue: str,
    oldest_close_exclusive: datetime,
    newest_close_inclusive: datetime,
) -> dict[int, list[CandleRecord]]:
    if not asset_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(asset_ids))
    sql = f"""
    SELECT asset_id, open_ts_utc, close_ts_utc, close_price, volume_quote_eur
    FROM obs_market_candle
    WHERE venue = %s
      AND interval_code = %s
      AND asset_id IN ({placeholders})
      AND close_ts_utc > %s
      AND close_ts_utc <= %s
    ORDER BY asset_id, close_ts_utc
    """
    params: list[Any] = [venue, CANDLE_INTERVAL] + asset_ids + [oldest_close_exclusive, newest_close_inclusive]
    result: dict[int, list[CandleRecord]] = {}
    with conn.cursor() as cur:
        cur.execute(sql, params)
        while True:
            rows = cur.fetchmany(FETCH_BATCH_ROWS)
            if not rows:
                break
            for r in rows:
                aid = int(r["asset_id"])
                if aid not in result:
                    result[aid] = []
                result[aid].append(CandleRecord(
                    asset_id=aid,
                    open_ts_utc=r["open_ts_utc"],
                    close_ts_utc=r["close_ts_utc"],
                    close_price=Decimal(str(r["close_price"])),
                    volume_quote_eur=Decimal(str(r["volume_quote_eur"])),
                ))
    return result


def write_rotation_snapshot(
    conn: Any,
    as_of_ts: datetime,
    horizon_h: int,
    venue: str,
    eligible_count: int,
    excluded_count: int,
    observations: list[HorizonObservation],
    *,
    authorization: Any = None,
) -> tuple[str, int]:
    from src.operations.writer_capability_authorization_v1 import (
        require_writer_mutation_authorization,
    )

    require_writer_mutation_authorization(authorization, "market_rotation_pressure")
    sql_header = """
    INSERT IGNORE INTO market_rotation_snapshot_v1
      (as_of_ts_utc, horizon_h, venue, candle_interval_code,
       eligible_market_count, excluded_market_count, observation_count)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        affected = cur.execute(sql_header, (
            as_of_ts, horizon_h, venue, CANDLE_INTERVAL,
            eligible_count, excluded_count, 0,
        ))
    created = int(affected) > 0

    sql_get_id = """
    SELECT snapshot_id, eligible_market_count, excluded_market_count, observation_count
    FROM market_rotation_snapshot_v1
    WHERE as_of_ts_utc = %s AND horizon_h = %s AND venue = %s
    FOR UPDATE
    """
    with conn.cursor() as cur:
        cur.execute(sql_get_id, (as_of_ts, horizon_h, venue))
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"Snapshot header missing after INSERT IGNORE: as_of={as_of_ts} h={horizon_h}")
    snapshot_id = int(row["snapshot_id"])
    prior_eligible = int(row["eligible_market_count"])
    prior_excluded = int(row["excluded_market_count"])
    prior_observation_count = int(row["observation_count"])

    sql_obs = """
    INSERT IGNORE INTO market_rotation_observation_v1 (
      snapshot_id, asset_id, market, horizon_h,
      window_open_ts_utc, window_close_ts_utc,
      price_open, price_close, price_change_pct,
      quote_volume, baseline_quote_volume, relative_volume,
      candle_count, expected_candle_count, coverage_ratio,
      baseline_candle_count, baseline_expected_candle_count, baseline_coverage_ratio,
      as_of_ts_utc
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    obs_written = 0
    with conn.cursor() as cur:
        for obs in observations:
            n = cur.execute(sql_obs, (
                snapshot_id, obs.asset_id, obs.market, obs.horizon_h,
                obs.window_open_ts_utc, obs.window_close_ts_utc,
                str(obs.price_open), str(obs.price_close), str(obs.price_change_pct),
                str(obs.quote_volume), str(obs.baseline_quote_volume), str(obs.relative_volume),
                obs.candle_count, obs.expected_candle_count, str(obs.coverage_ratio),
                obs.baseline_candle_count, obs.baseline_expected_candle_count, str(obs.baseline_coverage_ratio),
                obs.as_of_ts_utc,
            ))
            obs_written += int(n)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS observation_count "
            "FROM market_rotation_observation_v1 WHERE snapshot_id = %s",
            (snapshot_id,),
        )
        obs_row = cur.fetchone()
    if obs_row is None:
        raise RuntimeError(f"Observation count missing for snapshot_id={snapshot_id}")
    actual_observation_count = int(obs_row["observation_count"])

    with conn.cursor() as cur:
        header_changed = int(cur.execute(
            """
            UPDATE market_rotation_snapshot_v1
            SET eligible_market_count = %s,
                excluded_market_count = %s,
                observation_count = %s
            WHERE snapshot_id = %s
              AND (
                eligible_market_count <> %s
                OR excluded_market_count <> %s
                OR observation_count <> %s
              )
            """,
            (
                eligible_count,
                excluded_count,
                actual_observation_count,
                snapshot_id,
                eligible_count,
                excluded_count,
                actual_observation_count,
            ),
        )) > 0

    if created:
        status = "CREATED"
    elif obs_written > 0 or header_changed or prior_eligible != eligible_count or prior_excluded != excluded_count or prior_observation_count != actual_observation_count:
        status = "RECONCILED"
    else:
        status = "NOOP_ALREADY_COMPLETE"
    return status, obs_written


# ---------------------------------------------------------------------------
# DB — global context (conditional write with recovery semantics)
# ---------------------------------------------------------------------------

def _determine_global_action(existing_status: str | None, new_status: str) -> str:
    if existing_status is None:
        return "INSERT"
    if existing_status == "AVAILABLE":
        return "SKIP_AVAILABLE_EXISTS"
    if new_status == "AVAILABLE":
        return "PROMOTE"
    return "SKIP_NO_IMPROVEMENT"


def _dec_str(v: Decimal | None) -> str | None:
    return str(v) if v is not None else None


def _insert_global_row(conn: Any, as_of_ts: datetime, result: GlobalContextResult) -> None:
    sql = """
    INSERT INTO market_global_snapshot_v1 (
      as_of_ts_utc, provider_name, source_status, source_error_reason,
      total_volume_24h_usd, volume_change_pct_24h,
      total_market_cap_usd, market_cap_change_pct_24h,
      btc_dominance_pct, eth_dominance_pct,
      provider_updated_at_utc, fetched_at_utc
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        cur.execute(sql, (
            as_of_ts, PROVIDER_NAME, result.source_status, result.source_error_reason,
            _dec_str(result.total_volume_24h_usd), _dec_str(result.volume_change_pct_24h),
            _dec_str(result.total_market_cap_usd), _dec_str(result.market_cap_change_pct_24h),
            _dec_str(result.btc_dominance_pct), _dec_str(result.eth_dominance_pct),
            result.provider_updated_at_utc, result.fetched_at_utc,
        ))


def _update_global_to_available(conn: Any, as_of_ts: datetime, result: GlobalContextResult) -> None:
    sql = """
    UPDATE market_global_snapshot_v1
    SET source_status = 'AVAILABLE',
        source_error_reason = NULL,
        total_volume_24h_usd = %s,
        volume_change_pct_24h = %s,
        total_market_cap_usd = %s,
        market_cap_change_pct_24h = %s,
        btc_dominance_pct = %s,
        eth_dominance_pct = %s,
        provider_updated_at_utc = %s,
        fetched_at_utc = %s
    WHERE as_of_ts_utc = %s
      AND provider_name = %s
      AND source_status != 'AVAILABLE'
    """
    with conn.cursor() as cur:
        cur.execute(sql, (
            _dec_str(result.total_volume_24h_usd), _dec_str(result.volume_change_pct_24h),
            _dec_str(result.total_market_cap_usd), _dec_str(result.market_cap_change_pct_24h),
            _dec_str(result.btc_dominance_pct), _dec_str(result.eth_dominance_pct),
            result.provider_updated_at_utc, result.fetched_at_utc,
            as_of_ts, PROVIDER_NAME,
        ))


def write_global_snapshot(
    conn: Any,
    as_of_ts: datetime,
    result: GlobalContextResult,
    *,
    dry_run: bool = False,
    authorization: Any = None,
) -> tuple[bool, str]:
    if not dry_run:
        from src.operations.writer_capability_authorization_v1 import (
            require_writer_mutation_authorization,
        )

        require_writer_mutation_authorization(authorization, "market_rotation_pressure")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_status FROM market_global_snapshot_v1 "
            "WHERE as_of_ts_utc = %s AND provider_name = %s",
            (as_of_ts, PROVIDER_NAME),
        )
        existing = cur.fetchone()
    existing_status = existing["source_status"] if existing else None
    action = _determine_global_action(existing_status, result.source_status)
    if dry_run:
        return False, action
    if action == "INSERT":
        _insert_global_row(conn, as_of_ts, result)
        return True, action
    if action == "PROMOTE":
        _update_global_to_available(conn, as_of_ts, result)
        return True, action
    return False, action


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _fmt_dec(v: Decimal | None, digits: int = 2) -> str:
    if v is None:
        return "n/a"
    return f"{float(v):,.{digits}f}"


def print_validate_config(as_of_ts: datetime, args: argparse.Namespace) -> None:
    horizons = args.horizon or list(HORIZONS_H)
    print(f"RUNNER  {RUNNER_NAME} {VERSION}  mode=validate-only")
    print(f"as_of_ts={as_of_ts.isoformat()}Z  venue={args.venue}  interval={CANDLE_INTERVAL}")
    print(f"eligibility: min_coverage_ratio={float(MIN_COVERAGE_RATIO):.2f}  max_staleness_h={MAX_STALENESS_H}")
    for h in horizons:
        cur_start = as_of_ts - timedelta(hours=h)
        base_start = as_of_ts - timedelta(hours=2 * h)
        print(
            f"HORIZON {h}h  "
            f"current=({cur_start.isoformat()}Z, {as_of_ts.isoformat()}Z]  "
            f"baseline=({base_start.isoformat()}Z, {cur_start.isoformat()}Z]  "
            f"expected_candles={h}"
        )
    api_key_set = bool(os.getenv(COINGECKO_API_KEY_ENV))
    status = "SET" if api_key_set else "NOT_SET -> SKIPPED_NO_CREDENTIAL"
    print(f"GLOBAL  provider={PROVIDER_NAME}  {COINGECKO_API_KEY_ENV}={status}")


def print_horizon_report(
    horizon_h: int,
    eligible: list[HorizonObservation],
    excluded: list[tuple[str, str]],
    write_status: str,
) -> None:
    label = "7d" if horizon_h == 168 else "24h"
    print(f"\nHORIZON {label} ({horizon_h}h)  eligible={len(eligible)}  excluded={len(excluded)}  {write_status}")
    if excluded:
        by_reason: dict[str, int] = {}
        for _, reason in excluded:
            key = reason.split(":")[0]
            by_reason[key] = by_reason.get(key, 0) + 1
        print("  excl_reasons: " + "  ".join(f"{r}={n}" for r, n in sorted(by_reason.items())))
    if not eligible:
        return
    sorted_obs = sorted(eligible, key=lambda o: o.price_change_pct, reverse=True)
    print(f"  TOP {TOP_N} POSITIVE  return_pct / quote_vol_EUR / rel_vol")
    for obs in sorted_obs[:TOP_N]:
        print(
            f"    {obs.market:<12}  {float(obs.price_change_pct):+.2f}%"
            f"  {_fmt_dec(obs.quote_volume)} EUR  {float(obs.relative_volume):.2f}x"
        )
    bottom = sorted_obs[max(0, len(sorted_obs) - TOP_N):]
    print(f"  TOP {TOP_N} NEGATIVE  return_pct / quote_vol_EUR / rel_vol")
    for obs in reversed(bottom):
        print(
            f"    {obs.market:<12}  {float(obs.price_change_pct):+.2f}%"
            f"  {_fmt_dec(obs.quote_volume)} EUR  {float(obs.relative_volume):.2f}x"
        )


def print_global_section(result: GlobalContextResult, action: str) -> None:
    print(f"\nGLOBAL CONTEXT  provider={PROVIDER_NAME}  status={result.source_status}  action={action}")
    if result.source_error_reason:
        print(f"  error: {result.source_error_reason}")
    if result.source_status == "AVAILABLE":
        print(f"  total_volume_24h:   ${_fmt_dec(result.total_volume_24h_usd)} USD")
        print(f"  vol_change_24h:     {_fmt_dec(result.volume_change_pct_24h, 2)}%")
        print(f"  total_market_cap:   ${_fmt_dec(result.total_market_cap_usd)} USD")
        print(f"  mktcap_change_24h:  {_fmt_dec(result.market_cap_change_pct_24h, 2)}%")
        print(f"  btc_dominance:      {_fmt_dec(result.btc_dominance_pct, 2)}%")
        print(f"  eth_dominance:      {_fmt_dec(result.eth_dominance_pct, 2)}%")
        if result.provider_updated_at_utc:
            print(f"  provider_updated:   {result.provider_updated_at_utc.isoformat()}Z")


def print_missing_schema(prefix: str, missing_tables: list[str]) -> None:
    if missing_tables:
        print(f"{prefix}  missing={missing_tables}")


# ---------------------------------------------------------------------------
# Arg parsing and entry point
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Market Rotation History V1. "
            "Append-only rotation/momentum-volume snapshots from Synth market candles. "
            "Research-only, market-only, account-agnostic."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true",
                      help="No DB connection. Print configuration and eligibility contract.")
    mode.add_argument("--dry-run", action="store_true",
                      help="DB read-only. Compute and report without writing.")
    mode.add_argument("--write-db", action="store_true",
                      help="Transactional append-only write.")
    parser.add_argument("--venue", default=VENUE_DEFAULT)
    parser.add_argument("--as-of-ts", dest="asof_ts", default=None,
                        help="Override snapshot timestamp (ISO8601 UTC). Default: current UTC hour.")
    parser.add_argument("--horizon", type=int, action="append", choices=list(HORIZONS_H),
                        default=None, metavar="{24|168}",
                        help="Limit to one horizon. May be repeated. Default: both.")
    return parser.parse_args(argv)


def resolve_as_of_ts(asof_arg: str | None) -> datetime:
    if asof_arg is not None:
        ts = datetime.fromisoformat(asof_arg.replace("Z", "+00:00"))
        if ts.tzinfo is not None:
            from datetime import timezone
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
        return floor_to_hour(ts)
    return floor_to_hour(datetime.now(UTC).replace(tzinfo=None))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.write_db:
        from src.operations.writer_capability_authorization_v1 import (
            require_capability_write_authorization,
        )

        # Final mandatory authorization boundary before any rotation-history
        # write. A direct invocation cannot bypass ownership authorization.
        writer_authorization = require_capability_write_authorization(
            "market_rotation_pressure",
            service="synth-market-rotation-pressure-writer.service",
        )
    else:
        writer_authorization = None
    as_of_ts = resolve_as_of_ts(args.asof_ts)
    horizons = args.horizon or list(HORIZONS_H)
    mode = "validate-only" if args.validate_only else ("dry-run" if args.dry_run else "write-db")

    print(f"STARTED {RUNNER_NAME} {VERSION}  mode={mode}  as_of_ts={as_of_ts.isoformat()}Z  venue={args.venue}")

    if args.validate_only:
        print_validate_config(as_of_ts, args)
        return 0

    conn = get_connection()
    try:
        missing_tables = check_schema_ready(conn)
        local_missing, global_missing = split_missing_tables(missing_tables)
        if local_missing and args.write_db:
            print_missing_schema("FAILED  LOCAL_ROTATION_TARGET_SCHEMA_MISSING", local_missing)
            print_missing_schema("GLOBAL_CONTEXT_TARGET_SCHEMA_MISSING", global_missing)
            return 1
        if local_missing:
            print_missing_schema("LOCAL_ROTATION_TARGET_SCHEMA_MISSING", local_missing)
        if global_missing and not args.write_db:
            print_missing_schema("GLOBAL_CONTEXT_TARGET_SCHEMA_MISSING", global_missing)

        assets = fetch_eligible_assets(conn, args.venue)
        print(f"universe: {len(assets)} eligible EUR spot markets")

        if not assets:
            print("WARNING: no eligible assets found — nothing to compute")
            return 0

        oldest_ts = as_of_ts - timedelta(hours=_FETCH_LOOKBACK_H)
        asset_ids = [a.asset_id for a in assets]
        candles_by_asset = fetch_candles_bulk(conn, asset_ids, args.venue, oldest_ts, as_of_ts)

        horizon_results: list[tuple[int, list[HorizonObservation], list[tuple[str, str]]]] = []
        for h in horizons:
            eligible: list[HorizonObservation] = []
            excluded: list[tuple[str, str]] = []
            for asset in assets:
                all_c = candles_by_asset.get(asset.asset_id, [])
                current, baseline = _partition_candles(all_c, as_of_ts, h)
                ok, reason = check_eligibility(current, baseline, as_of_ts, h)
                if not ok:
                    excluded.append((asset.market, reason))
                    continue
                obs = compute_observation(asset.asset_id, asset.market, h, current, baseline, as_of_ts)
                eligible.append(obs)
            horizon_results.append((h, eligible, excluded))

        if args.dry_run or local_missing:
            api_key = os.getenv(COINGECKO_API_KEY_ENV)
            global_result = fetch_coingecko_global(api_key)
            for h, eligible, excluded in horizon_results:
                print_horizon_report(h, eligible, excluded, f"DRY_RUN would_write={len(eligible)}")
            if global_missing:
                global_action = "DRY_RUN_TARGET_SCHEMA_MISSING"
            else:
                _, global_action = write_global_snapshot(conn, as_of_ts, global_result, dry_run=True)
            print_global_section(global_result, global_action)

        else:
            snap_results: list[tuple[int, list[HorizonObservation], list[tuple[str, str]], str, int]] = []
            try:
                for h, eligible, excluded in horizon_results:
                    write_status, obs_written = write_rotation_snapshot(
                        conn, as_of_ts, h, args.venue,
                        len(eligible), len(excluded), eligible,
                        authorization=writer_authorization,
                    )
                    snap_results.append((h, eligible, excluded, write_status, obs_written))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            for h, eligible, excluded, write_status, obs_written in snap_results:
                print_horizon_report(h, eligible, excluded, f"{write_status} obs={obs_written}")

            if global_missing:
                print_missing_schema("GLOBAL_CONTEXT_TARGET_SCHEMA_MISSING", global_missing)
                print(f"\nFINISHED {RUNNER_NAME}")
                return 1

            api_key = os.getenv(COINGECKO_API_KEY_ENV)
            global_result = fetch_coingecko_global(api_key)
            try:
                _, global_action = write_global_snapshot(
                    conn, as_of_ts, global_result, dry_run=False,
                    authorization=writer_authorization,
                )
                conn.commit()
                print_global_section(global_result, global_action)
            except Exception as exc:
                conn.rollback()
                print(
                    "GLOBAL_CONTEXT_PERSIST_FAILED  "
                    f"error_type={type(exc).__name__}  error={exc}"
                )
                print(f"\nFINISHED {RUNNER_NAME}")
                return 1

    finally:
        conn.close()

    print(f"\nFINISHED {RUNNER_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
