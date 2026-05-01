from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from math import log, sqrt
from statistics import median, pstdev
from typing import Any

from src.asset_profile.models import AssetProfileSnapshot

PROFILE_VERSION = "asset_profile_engine_v1"


def quant(value: Decimal | None, places: str = "0.00000001") -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def safe_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


def percentile_rank(sorted_values: list[Decimal], value: Decimal) -> Decimal:
    if not sorted_values:
        return Decimal("0")
    count = sum(1 for item in sorted_values if item <= value)
    return Decimal(count) / Decimal(len(sorted_values))


def liquidity_class_from_rank(rank: Decimal) -> str:
    if rank >= Decimal("0.90"):
        return "MAJOR"
    if rank >= Decimal("0.65"):
        return "LARGE_ALT"
    if rank >= Decimal("0.35"):
        return "MID_ALT"
    if rank >= Decimal("0.15"):
        return "SMALL_ALT"
    return "MICRO_ALT"


def beta_profile_from_values(beta: Decimal | None, daily_vol: Decimal | None) -> str | None:
    if beta is None and daily_vol is None:
        return None

    beta_value = abs(beta or Decimal("0"))
    vol_value = daily_vol or Decimal("0")

    if beta_value >= Decimal("2.0") or vol_value >= Decimal("0.12"):
        return "EXTREME_BETA"
    if beta_value >= Decimal("1.25") or vol_value >= Decimal("0.075"):
        return "HIGH_BETA"
    if beta_value <= Decimal("0.75") and vol_value <= Decimal("0.045"):
        return "LOW_BETA"
    return "NORMAL_BETA"


def pct_return(previous: Decimal, current: Decimal) -> Decimal | None:
    if previous <= 0:
        return None
    return (current / previous) - Decimal("1")


def covariance(xs: list[Decimal], ys: list[Decimal]) -> Decimal | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None

    mean_x = sum(xs) / Decimal(len(xs))
    mean_y = sum(ys) / Decimal(len(ys))
    total = Decimal("0")

    for x, y in zip(xs, ys):
        total += (x - mean_x) * (y - mean_y)

    return total / Decimal(len(xs))


def variance(xs: list[Decimal]) -> Decimal | None:
    if len(xs) < 2:
        return None

    mean_x = sum(xs) / Decimal(len(xs))
    total = Decimal("0")

    for x in xs:
        total += (x - mean_x) * (x - mean_x)

    return total / Decimal(len(xs))


def expected_candles_for_interval(interval_code: str, lookback_days: int) -> int:
    if interval_code == "1h":
        return max(1, lookback_days * 24)
    if interval_code == "4h":
        return max(1, lookback_days * 6)
    if interval_code == "1d":
        return max(1, lookback_days)
    return max(1, lookback_days)


def volatility_normalizer(interval_code: str) -> Decimal:
    if interval_code == "1h":
        return Decimal(str(sqrt(24)))
    if interval_code == "4h":
        return Decimal(str(sqrt(6)))
    return Decimal("1")


def build_asset_profiles(
    *,
    market_rows: list[dict[str, Any]],
    venue: str,
    interval_code: str,
    asof_ts_utc: datetime,
    lookback_days: int,
    benchmark_symbols: list[str],
) -> list[AssetProfileSnapshot]:
    by_asset: dict[int, list[dict[str, Any]]] = defaultdict(list)
    symbol_by_asset: dict[int, str] = {}

    for row in market_rows:
        asset_id = int(row["asset_id"])
        symbol = str(row["symbol"]).upper()
        by_asset[asset_id].append(row)
        symbol_by_asset[asset_id] = symbol

    expected_candles = expected_candles_for_interval(interval_code, lookback_days)

    asset_liquidity: dict[int, Decimal] = {}
    asset_returns: dict[int, dict[datetime, Decimal]] = {}
    asset_volatility: dict[int, Decimal | None] = {}

    for asset_id, rows in by_asset.items():
        sorted_rows = sorted(rows, key=lambda item: item["close_ts_utc"])

        volumes = [safe_decimal(row.get("volume_quote_eur")) for row in sorted_rows]
        trades = [safe_decimal(row.get("trade_count")) for row in sorted_rows]

        median_volume = median(volumes) if volumes else Decimal("0")
        median_trades = median(trades) if trades else Decimal("0")
        coverage_ratio = Decimal(len(sorted_rows)) / Decimal(expected_candles)

        liquidity_score = (
            Decimal(str(log(float(median_volume + Decimal("1")))))
            + Decimal("0.15") * Decimal(str(log(float(median_trades + Decimal("1")))))
            + min(coverage_ratio, Decimal("1"))
        )

        asset_liquidity[asset_id] = liquidity_score

        returns: dict[datetime, Decimal] = {}
        previous_close: Decimal | None = None
        return_values: list[Decimal] = []

        for row in sorted_rows:
            close_price = safe_decimal(row.get("close_price"))
            ts = row["close_ts_utc"]

            if previous_close is not None:
                ret = pct_return(previous_close, close_price)
                if ret is not None:
                    returns[ts] = ret
                    return_values.append(ret)

            previous_close = close_price

        asset_returns[asset_id] = returns

        if len(return_values) >= 2:
            raw_vol = Decimal(str(pstdev([float(item) for item in return_values])))
            asset_volatility[asset_id] = raw_vol * volatility_normalizer(interval_code)
        else:
            asset_volatility[asset_id] = None

    benchmark_symbol_set = {symbol.upper() for symbol in benchmark_symbols}
    benchmark_asset_ids = [
        asset_id
        for asset_id, symbol in symbol_by_asset.items()
        if symbol in benchmark_symbol_set
    ]

    benchmark_returns_by_ts: dict[datetime, Decimal] = {}
    benchmark_ts = set()

    for asset_id in benchmark_asset_ids:
        benchmark_ts.update(asset_returns.get(asset_id, {}).keys())

    for ts in sorted(benchmark_ts):
        values = [
            asset_returns[asset_id][ts]
            for asset_id in benchmark_asset_ids
            if ts in asset_returns.get(asset_id, {})
        ]
        if values:
            benchmark_returns_by_ts[ts] = sum(values) / Decimal(len(values))

    sorted_liquidity_scores = sorted(asset_liquidity.values())
    out: list[AssetProfileSnapshot] = []

    for asset_id, rows in sorted(by_asset.items(), key=lambda item: symbol_by_asset[item[0]]):
        symbol = symbol_by_asset[asset_id]
        sorted_rows = sorted(rows, key=lambda item: item["close_ts_utc"])
        candles_observed = len(sorted_rows)
        coverage_ratio = Decimal(candles_observed) / Decimal(expected_candles)

        liquidity_score = asset_liquidity.get(asset_id)
        liquidity_rank = percentile_rank(sorted_liquidity_scores, liquidity_score or Decimal("0"))
        liquidity_class = liquidity_class_from_rank(liquidity_rank)

        asset_ret_by_ts = asset_returns.get(asset_id, {})
        paired_asset_returns: list[Decimal] = []
        paired_market_returns: list[Decimal] = []

        for ts, asset_ret in asset_ret_by_ts.items():
            market_ret = benchmark_returns_by_ts.get(ts)
            if market_ret is None:
                continue
            paired_asset_returns.append(asset_ret)
            paired_market_returns.append(market_ret)

        beta: Decimal | None = None
        market_var = variance(paired_market_returns)

        if market_var is not None and market_var != 0:
            cov = covariance(paired_asset_returns, paired_market_returns)
            if cov is not None:
                beta = cov / market_var

        realized_volatility = asset_volatility.get(asset_id)
        beta_profile = beta_profile_from_values(beta, realized_volatility)

        out.append(
            AssetProfileSnapshot(
                asset_id=asset_id,
                symbol=symbol,
                venue=venue,
                interval_code=interval_code,
                asof_ts_utc=asof_ts_utc,
                lookback_days=lookback_days,
                profile_version=PROFILE_VERSION,
                liquidity_score=quant(liquidity_score),
                liquidity_class=liquidity_class,
                beta_to_market=quant(beta),
                beta_profile=beta_profile,
                realized_volatility=quant(realized_volatility),
                sector_group_code=None,
                sector_confidence=Decimal("0"),
                candles_observed=candles_observed,
                coverage_ratio=quant(coverage_ratio),
                benchmark_symbols=",".join(benchmark_symbols),
                notes="sector_group_code intentionally null in v1; clustering comes later",
            )
        )

    return out


def from_ts_for_lookback(asof_ts_utc: datetime, lookback_days: int) -> datetime:
    return asof_ts_utc - timedelta(days=lookback_days)
