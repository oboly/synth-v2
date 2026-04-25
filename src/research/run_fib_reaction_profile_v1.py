from __future__ import annotations

"""
ENGINE: run_fib_reaction_profile_v1
MODE: historical

INPUT:
- fib_observation
- obs_market_candle
- asset

OUTPUT:
- synth_bt.fib_reaction_profile

CLI:
python -m src.research.run_fib_reaction_profile_v1 \
  --venue bitvavo \
  --interval-codes 4h \
  --from-ts "2026-03-01 00:00:00" \
  --to-ts "2026-04-22 00:00:00" \
  --write-db

HISTORICAL:
- supported

NOTES:
- research module, not execution logic
- reads compat view fib_observation
- asset universe is selected first, then all matching fib rows are fetched
- no misleading global fib-row LIMIT
"""

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from src.common.db import get_connection


SOURCE_DB = "synth"
RESULT_DB = "synth_bt"

DEFAULT_INTERVAL_CODES = ["1h", "4h", "1d"]
DEFAULT_FIB_LEVELS = ["0.500000", "0.618000", "0.786000"]


@dataclass(frozen=True)
class AssetRow:
    asset_id: int
    symbol: str


@dataclass(frozen=True)
class FibRow:
    asset_id: int
    symbol: str
    venue: str
    interval_code: str
    anchor_start_ts_utc: datetime
    anchor_end_ts_utc: datetime
    swing_direction: str
    fib_level: Decimal
    fib_price: Decimal
    is_retracement: bool
    is_extension: bool
    confluence_score: Decimal


@dataclass(frozen=True)
class CandleRow:
    asset_id: int
    symbol: str
    venue: str
    interval_code: str
    open_ts_utc: datetime
    close_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass
class ReactionSample:
    asset_id: int
    symbol: str
    venue: str
    interval_code: str
    regime_label: str
    fib_level: Decimal
    opportunity_count: int = 0
    touch_count: int = 0
    reaction_count: int = 0
    failure_count: int = 0
    sum_reaction_return: Decimal = Decimal("0")
    sum_continuation_return: Decimal = Decimal("0")
    continuation_count: int = 0


INTERVAL_TO_MINUTES = {
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build fib reaction profile by asset / TF / regime / fib level.")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval-codes", nargs="+", default=DEFAULT_INTERVAL_CODES)
    parser.add_argument("--fib-levels", nargs="+", default=DEFAULT_FIB_LEVELS)
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--max-assets", type=int, default=500)

    parser.add_argument("--atr-period", type=int, default=14)
    parser.add_argument("--reaction-horizon-candles", type=int, default=5)
    parser.add_argument("--continuation-horizon-candles", type=int, default=12)
    parser.add_argument("--zone-atr-mult", default="0.25")
    parser.add_argument("--min-zone-bps", default="20")
    parser.add_argument("--reaction-atr-mult", default="0.75")
    parser.add_argument("--min-reaction-bps", default="80")
    parser.add_argument("--trend-anchor-atr-mult", default="3.0")

    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _q8(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _q10(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _signed_return(start_price: Decimal, end_price: Decimal, direction: str) -> Decimal:
    if start_price == 0:
        return Decimal("0")
    raw = (end_price - start_price) / start_price
    if direction == "DOWN":
        raw = -raw
    return _q8(raw)


def _interval_delta(interval_code: str, candles: int) -> timedelta:
    minutes = INTERVAL_TO_MINUTES[interval_code] * candles
    return timedelta(minutes=minutes)


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def ensure_result_table() -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS fib_reaction_profile (
        fib_reaction_profile_id BIGINT NOT NULL AUTO_INCREMENT,
        asset_id INT NOT NULL,
        symbol VARCHAR(32) NOT NULL,
        venue VARCHAR(32) NOT NULL,
        interval_code VARCHAR(16) NOT NULL,
        regime_label VARCHAR(32) NOT NULL,
        fib_level DECIMAL(10,6) NOT NULL,
        opportunity_count INT NOT NULL DEFAULT 0,
        touch_count INT NOT NULL DEFAULT 0,
        reaction_count INT NOT NULL DEFAULT 0,
        failure_count INT NOT NULL DEFAULT 0,
        avg_reaction_return DECIMAL(18,8) DEFAULT NULL,
        avg_continuation_return DECIMAL(18,8) DEFAULT NULL,
        hit_rate DECIMAL(18,8) DEFAULT NULL,
        touch_rate DECIMAL(18,8) DEFAULT NULL,
        sample_size INT NOT NULL DEFAULT 0,
        from_ts_utc DATETIME(6) NOT NULL,
        to_ts_utc DATETIME(6) NOT NULL,
        created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        updated_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
        PRIMARY KEY (fib_reaction_profile_id),
        UNIQUE KEY uq_fib_reaction_profile (
            asset_id,
            venue,
            interval_code,
            regime_label,
            fib_level,
            from_ts_utc,
            to_ts_utc
        ),
        KEY ix_fib_reaction_profile_lookup (
            asset_id,
            venue,
            interval_code,
            regime_label,
            fib_level
        )
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    conn = get_connection(database=RESULT_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_asset_universe(
    *,
    asset_id: int | None,
    max_assets: int,
) -> list[AssetRow]:
    params: list[Any] = []
    asset_filter_sql = ""
    if asset_id is not None:
        asset_filter_sql = "AND asset_id = %s"
        params.append(asset_id)

    params.append(max_assets)

    sql = f"""
    SELECT
        asset_id,
        symbol
    FROM asset
    WHERE is_enabled = 1
      AND is_tradeable = 1
      {asset_filter_sql}
    ORDER BY asset_id
    LIMIT %s
    """
    conn = get_connection(database=SOURCE_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
    finally:
        conn.close()

    return [
        AssetRow(
            asset_id=int(row["asset_id"]),
            symbol=str(row["symbol"]),
        )
        for row in rows
    ]


def fetch_fib_rows(
    *,
    venue: str,
    interval_codes: list[str],
    fib_levels: list[Decimal],
    from_ts: datetime,
    to_ts: datetime,
    assets: list[AssetRow],
) -> list[FibRow]:
    if not assets:
        return []

    interval_placeholders = ",".join(["%s"] * len(interval_codes))
    fib_placeholders = ",".join(["%s"] * len(fib_levels))
    asset_placeholders = ",".join(["%s"] * len(assets))

    asset_ids = [asset.asset_id for asset in assets]
    symbol_by_asset = {asset.asset_id: asset.symbol for asset in assets}

    params: list[Any] = [
        venue,
        from_ts,
        to_ts,
        *interval_codes,
        *fib_levels,
        *asset_ids,
    ]

    sql = f"""
    SELECT
        fo.asset_id,
        %s AS venue,
        fo.interval_code,
        fo.anchor_start_ts_utc,
        fo.anchor_end_ts_utc,
        fo.swing_direction,
        fo.fib_level,
        fo.fib_price,
        fo.is_retracement,
        fo.is_extension,
        fo.confluence_score
    FROM fib_observation fo
    WHERE fo.is_active = 1
      AND fo.anchor_end_ts_utc >= %s
      AND fo.anchor_end_ts_utc < %s
      AND fo.interval_code IN ({interval_placeholders})
      AND fo.fib_level IN ({fib_placeholders})
      AND fo.asset_id IN ({asset_placeholders})
    ORDER BY fo.asset_id, fo.interval_code, fo.anchor_end_ts_utc, fo.fib_level
    """
    conn = get_connection(database=SOURCE_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
    finally:
        conn.close()

    out: list[FibRow] = []
    for row in rows:
        asset_id = int(row["asset_id"])
        out.append(
            FibRow(
                asset_id=asset_id,
                symbol=symbol_by_asset.get(asset_id, str(asset_id)),
                venue=str(row["venue"]),
                interval_code=str(row["interval_code"]),
                anchor_start_ts_utc=row["anchor_start_ts_utc"],
                anchor_end_ts_utc=row["anchor_end_ts_utc"],
                swing_direction=str(row["swing_direction"]).upper(),
                fib_level=_to_decimal(row["fib_level"]),
                fib_price=_to_decimal(row["fib_price"]),
                is_retracement=bool(row["is_retracement"]),
                is_extension=bool(row["is_extension"]),
                confluence_score=_to_decimal(row["confluence_score"]),
            )
        )
    return out


def fetch_candles_for_group(
    *,
    asset_id: int,
    symbol: str,
    venue: str,
    interval_code: str,
    from_ts: datetime,
    to_ts: datetime,
) -> list[CandleRow]:
    sql = """
    SELECT
        asset_id,
        venue,
        interval_code,
        open_ts_utc,
        close_ts_utc,
        open_price,
        high_price,
        low_price,
        close_price
    FROM obs_market_candle
    WHERE asset_id = %s
      AND venue = %s
      AND interval_code = %s
      AND open_ts_utc >= %s
      AND open_ts_utc < %s
    ORDER BY open_ts_utc
    """
    conn = get_connection(database=SOURCE_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [asset_id, venue, interval_code, from_ts, to_ts])
            rows = cur.fetchall() or []
    finally:
        conn.close()

    return [
        CandleRow(
            asset_id=int(row["asset_id"]),
            symbol=symbol,
            venue=str(row["venue"]),
            interval_code=str(row["interval_code"]),
            open_ts_utc=row["open_ts_utc"],
            close_ts_utc=row["close_ts_utc"],
            open_price=_to_decimal(row["open_price"]),
            high_price=_to_decimal(row["high_price"]),
            low_price=_to_decimal(row["low_price"]),
            close_price=_to_decimal(row["close_price"]),
        )
        for row in rows
    ]


def compute_atr(candles: list[CandleRow], period: int) -> list[Decimal | None]:
    if not candles:
        return []

    trs: list[Decimal] = []
    prev_close: Decimal | None = None
    for candle in candles:
        if prev_close is None:
            tr = candle.high_price - candle.low_price
        else:
            tr = max(
                candle.high_price - candle.low_price,
                abs(candle.high_price - prev_close),
                abs(candle.low_price - prev_close),
            )
        trs.append(tr)
        prev_close = candle.close_price

    atrs: list[Decimal | None] = [None] * len(candles)
    running = Decimal("0")
    for i, tr in enumerate(trs):
        running += tr
        if i >= period:
            running -= trs[i - period]
        if i >= period - 1:
            atrs[i] = _q10(running / Decimal(period))
    return atrs


def classify_regime(
    *,
    swing_direction: str,
    anchor_start_price: Decimal,
    anchor_end_price: Decimal,
    anchor_end_atr: Decimal | None,
    trend_anchor_atr_mult: Decimal,
) -> str:
    if anchor_end_atr is None or anchor_end_atr == 0:
        return "RANGE"

    move = abs(anchor_end_price - anchor_start_price)
    move_in_atr = move / anchor_end_atr

    if move_in_atr >= trend_anchor_atr_mult:
        return "TREND_UP" if swing_direction == "UP" else "TREND_DOWN"
    return "RANGE"


def evaluate_fib_row(
    *,
    fib: FibRow,
    candles: list[CandleRow],
    atrs: list[Decimal | None],
    ts_to_index: dict[datetime, int],
    zone_atr_mult: Decimal,
    min_zone_bps: Decimal,
    reaction_atr_mult: Decimal,
    min_reaction_bps: Decimal,
    reaction_horizon_candles: int,
    continuation_horizon_candles: int,
    trend_anchor_atr_mult: Decimal,
) -> tuple[str, bool, bool, Decimal, Decimal | None]:
    if fib.anchor_start_ts_utc not in ts_to_index or fib.anchor_end_ts_utc not in ts_to_index:
        return ("RANGE", False, False, Decimal("0"), None)

    start_idx = ts_to_index[fib.anchor_start_ts_utc]
    end_idx = ts_to_index[fib.anchor_end_ts_utc]

    anchor_end_atr = atrs[end_idx]
    regime_label = classify_regime(
        swing_direction=fib.swing_direction,
        anchor_start_price=candles[start_idx].open_price,
        anchor_end_price=fib.fib_price if fib.is_extension else candles[end_idx].close_price,
        anchor_end_atr=anchor_end_atr,
        trend_anchor_atr_mult=trend_anchor_atr_mult,
    )

    touch_idx: int | None = None
    touch_price: Decimal | None = None

    for i in range(end_idx + 1, len(candles)):
        candle = candles[i]
        atr_here = atrs[i] or anchor_end_atr or Decimal("0")
        zone_half_width = max(
            fib.fib_price * (min_zone_bps / Decimal("10000")),
            atr_here * zone_atr_mult,
        )
        zone_low = fib.fib_price - zone_half_width
        zone_high = fib.fib_price + zone_half_width

        touched = candle.low_price <= zone_high and candle.high_price >= zone_low
        if touched:
            touch_idx = i
            touch_price = fib.fib_price
            break

    if touch_idx is None or touch_price is None:
        return (regime_label, False, False, Decimal("0"), None)

    favorable_best = Decimal("0")
    forward_close_return: Decimal | None = None

    horizon_end = min(len(candles) - 1, touch_idx + reaction_horizon_candles)
    cont_end = min(len(candles) - 1, touch_idx + continuation_horizon_candles)

    atr_touch = atrs[touch_idx] or anchor_end_atr or Decimal("0")
    reaction_threshold_return = max(
        (atr_touch * reaction_atr_mult) / touch_price if touch_price != 0 else Decimal("0"),
        min_reaction_bps / Decimal("10000"),
    )

    for i in range(touch_idx + 1, horizon_end + 1):
        candle = candles[i]
        favorable_price = candle.high_price if fib.swing_direction == "UP" else candle.low_price
        favorable_return = _signed_return(touch_price, favorable_price, fib.swing_direction)
        if favorable_return > favorable_best:
            favorable_best = favorable_return

    reaction_hit = favorable_best >= reaction_threshold_return

    if cont_end > touch_idx:
        forward_close_return = _signed_return(
            touch_price,
            candles[cont_end].close_price,
            fib.swing_direction,
        )

    return (regime_label, True, reaction_hit, favorable_best, forward_close_return)


def aggregate_samples(
    *,
    fib_rows: list[FibRow],
    candles_by_group: dict[tuple[int, str], list[CandleRow]],
    atr_period: int,
    zone_atr_mult: Decimal,
    min_zone_bps: Decimal,
    reaction_atr_mult: Decimal,
    min_reaction_bps: Decimal,
    reaction_horizon_candles: int,
    continuation_horizon_candles: int,
    trend_anchor_atr_mult: Decimal,
) -> dict[tuple[int, str, str, str, Decimal], ReactionSample]:
    samples: dict[tuple[int, str, str, str, Decimal], ReactionSample] = {}
    cached_atr: dict[tuple[int, str], list[Decimal | None]] = {}
    cached_index: dict[tuple[int, str], dict[datetime, int]] = {}

    for fib in fib_rows:
        group_key = (fib.asset_id, fib.interval_code)
        candles = candles_by_group.get(group_key, [])
        if not candles:
            continue

        if group_key not in cached_atr:
            cached_atr[group_key] = compute_atr(candles, atr_period)
            cached_index[group_key] = {c.open_ts_utc: i for i, c in enumerate(candles)}

        regime_label, touched, reaction_hit, reaction_return, continuation_return = evaluate_fib_row(
            fib=fib,
            candles=candles,
            atrs=cached_atr[group_key],
            ts_to_index=cached_index[group_key],
            zone_atr_mult=zone_atr_mult,
            min_zone_bps=min_zone_bps,
            reaction_atr_mult=reaction_atr_mult,
            min_reaction_bps=min_reaction_bps,
            reaction_horizon_candles=reaction_horizon_candles,
            continuation_horizon_candles=continuation_horizon_candles,
            trend_anchor_atr_mult=trend_anchor_atr_mult,
        )

        key = (fib.asset_id, fib.venue, fib.interval_code, regime_label, fib.fib_level)
        if key not in samples:
            samples[key] = ReactionSample(
                asset_id=fib.asset_id,
                symbol=fib.symbol,
                venue=fib.venue,
                interval_code=fib.interval_code,
                regime_label=regime_label,
                fib_level=fib.fib_level,
            )

        sample = samples[key]
        sample.opportunity_count += 1

        if touched:
            sample.touch_count += 1
            if reaction_hit:
                sample.reaction_count += 1
                sample.sum_reaction_return += reaction_return
            else:
                sample.failure_count += 1

            if continuation_return is not None:
                sample.sum_continuation_return += continuation_return
                sample.continuation_count += 1

    return samples


def upsert_profiles(
    *,
    samples: dict[tuple[int, str, str, str, Decimal], ReactionSample],
    from_ts: datetime,
    to_ts: datetime,
) -> int:
    if not samples:
        return 0

    sql = """
    INSERT INTO fib_reaction_profile (
        asset_id,
        symbol,
        venue,
        interval_code,
        regime_label,
        fib_level,
        opportunity_count,
        touch_count,
        reaction_count,
        failure_count,
        avg_reaction_return,
        avg_continuation_return,
        hit_rate,
        touch_rate,
        sample_size,
        from_ts_utc,
        to_ts_utc
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    ON DUPLICATE KEY UPDATE
        symbol = VALUES(symbol),
        opportunity_count = VALUES(opportunity_count),
        touch_count = VALUES(touch_count),
        reaction_count = VALUES(reaction_count),
        failure_count = VALUES(failure_count),
        avg_reaction_return = VALUES(avg_reaction_return),
        avg_continuation_return = VALUES(avg_continuation_return),
        hit_rate = VALUES(hit_rate),
        touch_rate = VALUES(touch_rate),
        sample_size = VALUES(sample_size),
        updated_ts_utc = CURRENT_TIMESTAMP(6)
    """

    params: list[list[Any]] = []
    for sample in samples.values():
        avg_reaction_return = None
        if sample.reaction_count > 0:
            avg_reaction_return = _q8(sample.sum_reaction_return / Decimal(sample.reaction_count))

        avg_continuation_return = None
        if sample.continuation_count > 0:
            avg_continuation_return = _q8(sample.sum_continuation_return / Decimal(sample.continuation_count))

        hit_rate = None
        if sample.touch_count > 0:
            hit_rate = _q8(Decimal(sample.reaction_count) / Decimal(sample.touch_count))

        touch_rate = None
        if sample.opportunity_count > 0:
            touch_rate = _q8(Decimal(sample.touch_count) / Decimal(sample.opportunity_count))

        params.append(
            [
                sample.asset_id,
                sample.symbol,
                sample.venue,
                sample.interval_code,
                sample.regime_label,
                sample.fib_level,
                sample.opportunity_count,
                sample.touch_count,
                sample.reaction_count,
                sample.failure_count,
                avg_reaction_return,
                avg_continuation_return,
                hit_rate,
                touch_rate,
                sample.touch_count,
                from_ts,
                to_ts,
            ]
        )

    conn = get_connection(database=RESULT_DB)
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, params)
        conn.commit()
        return len(params)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def printable_rows(samples: dict[tuple[int, str, str, str, Decimal], ReactionSample]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sample in sorted(
        samples.values(),
        key=lambda s: (s.asset_id, s.interval_code, s.regime_label, s.fib_level),
    ):
        avg_reaction_return = ""
        if sample.reaction_count > 0:
            avg_reaction_return = str(_q8(sample.sum_reaction_return / Decimal(sample.reaction_count)))

        avg_continuation_return = ""
        if sample.continuation_count > 0:
            avg_continuation_return = str(_q8(sample.sum_continuation_return / Decimal(sample.continuation_count)))

        hit_rate = ""
        if sample.touch_count > 0:
            hit_rate = str(_q8(Decimal(sample.reaction_count) / Decimal(sample.touch_count)))

        touch_rate = ""
        if sample.opportunity_count > 0:
            touch_rate = str(_q8(Decimal(sample.touch_count) / Decimal(sample.opportunity_count)))

        out.append(
            {
                "asset_id": sample.asset_id,
                "symbol": sample.symbol,
                "venue": sample.venue,
                "interval_code": sample.interval_code,
                "regime_label": sample.regime_label,
                "fib_level": str(sample.fib_level),
                "opportunity_count": str(sample.opportunity_count),
                "touch_count": str(sample.touch_count),
                "reaction_count": str(sample.reaction_count),
                "failure_count": str(sample.failure_count),
                "avg_reaction_return": avg_reaction_return,
                "avg_continuation_return": avg_continuation_return,
                "hit_rate": hit_rate,
                "touch_rate": touch_rate,
            }
        )
    return out


def print_table(rows: list[dict[str, Any]]) -> None:
    headers = [
        "asset_id",
        "symbol",
        "interval_code",
        "regime_label",
        "fib_level",
        "opportunity_count",
        "touch_count",
        "reaction_count",
        "failure_count",
        "avg_reaction_return",
        "avg_continuation_return",
        "hit_rate",
        "touch_rate",
    ]
    printable = [[str(row.get(h, "")) for h in headers] for row in rows]

    widths = [len(h) for h in headers]
    for row in printable:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(value))

    def fmt(values: list[str]) -> str:
        return " | ".join(v.ljust(widths[i]) for i, v in enumerate(values))

    print(fmt(headers))
    print("-+-".join("-" * w for w in widths))
    for row in printable:
        print(fmt(row))


def main() -> int:
    args = parse_args()

    from_ts = _parse_ts(args.from_ts)
    to_ts = _parse_ts(args.to_ts)

    fib_levels = [_to_decimal(v) for v in args.fib_levels]
    zone_atr_mult = _to_decimal(args.zone_atr_mult)
    min_zone_bps = _to_decimal(args.min_zone_bps)
    reaction_atr_mult = _to_decimal(args.reaction_atr_mult)
    min_reaction_bps = _to_decimal(args.min_reaction_bps)
    trend_anchor_atr_mult = _to_decimal(args.trend_anchor_atr_mult)

    assets = fetch_asset_universe(
        asset_id=args.asset_id,
        max_assets=args.max_assets,
    )

    fib_rows = fetch_fib_rows(
        venue=args.venue,
        interval_codes=args.interval_codes,
        fib_levels=fib_levels,
        from_ts=from_ts,
        to_ts=to_ts,
        assets=assets,
    )

    grouped_fibs: dict[tuple[int, str], list[FibRow]] = defaultdict(list)
    for fib in fib_rows:
        grouped_fibs[(fib.asset_id, fib.interval_code)].append(fib)

    candles_by_group: dict[tuple[int, str], list[CandleRow]] = {}
    for (asset_id, interval_code), group_rows in grouped_fibs.items():
        symbol = group_rows[0].symbol
        group_from = min(r.anchor_start_ts_utc for r in group_rows) - _interval_delta(interval_code, args.atr_period + 5)
        group_to = max(r.anchor_end_ts_utc for r in group_rows) + _interval_delta(interval_code, args.continuation_horizon_candles + 5)

        candles = fetch_candles_for_group(
            asset_id=asset_id,
            symbol=symbol,
            venue=args.venue,
            interval_code=interval_code,
            from_ts=group_from,
            to_ts=group_to,
        )
        candles_by_group[(asset_id, interval_code)] = candles

    samples = aggregate_samples(
        fib_rows=fib_rows,
        candles_by_group=candles_by_group,
        atr_period=args.atr_period,
        zone_atr_mult=zone_atr_mult,
        min_zone_bps=min_zone_bps,
        reaction_atr_mult=reaction_atr_mult,
        min_reaction_bps=min_reaction_bps,
        reaction_horizon_candles=args.reaction_horizon_candles,
        continuation_horizon_candles=args.continuation_horizon_candles,
        trend_anchor_atr_mult=trend_anchor_atr_mult,
    )

    if args.write_db:
        ensure_result_table()
        rows_written = upsert_profiles(
            samples=samples,
            from_ts=from_ts,
            to_ts=to_ts,
        )
    else:
        rows_written = 0

    rows = printable_rows(samples)

    if args.output == "json":
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        print_table(rows)

    print(
        f"assets={len(assets)} "
        f"fib_rows={len(fib_rows)} "
        f"profile_rows={len(rows)} "
        f"rows_written={rows_written} "
        f"write_db={args.write_db}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
