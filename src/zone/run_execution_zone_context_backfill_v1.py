from __future__ import annotations

"""
ENGINE: run_execution_zone_context_backfill_v1
MODE: historical backfill

LAYER:
- zone / measurement-context generation

INPUT:
- obs_market_candle
- asset

OUTPUT:
- fib_observation_v2
- zone_observation_v2
- execution_zone_context

BOUNDARY:
- No selection writes.
- No decision writes.
- No execution_plan writes.
- No execution_intent writes.
- No execution_event writes.
- No account/balance/position/order writes.

IMPORTANT:
- This runner intentionally does NOT apply fib_preference_profile.
- Reason: current fib_preference_profile rows are research/backtest profiles and
  fetch_latest_fib_preference_profile() is latest-style. Applying that during
  historical backfill would introduce future leakage.
- This runner appends a simple point-in-time regime marker to execution context notes:
    regime=TREND_UP / TREND_DOWN / RANGE
  derived only from the current zone engine fib leg direction.

CLI dry-run:
python -m src.zone.run_execution_zone_context_backfill_v1 \
  --venue bitvavo \
  --interval 4h \
  --sleeve-code SWING_STRUCTURAL \
  --from-ts "2026-04-01 00:00:00" \
  --to-ts "2026-04-03 00:00:00" \
  --limit-assets 2 \
  --max-snapshots-per-asset 5

CLI write:
python -m src.zone.run_execution_zone_context_backfill_v1 \
  --venue bitvavo \
  --interval 4h \
  --sleeve-code SWING_STRUCTURAL \
  --from-ts "2026-03-01 00:00:00" \
  --to-ts "2026-05-01 00:00:00" \
  --limit-assets 40 \
  --write-db
"""

import argparse
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.zone.engine_v1 import build_zone_engine_result
from src.zone.models import CandleRow, ExecutionZoneContextInput
from src.zone.repository import ZoneRepository


@dataclass(frozen=True)
class AssetRow:
    asset_id: int
    symbol: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill base execution_zone_context snapshots.")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--sleeve-code", default="SWING_STRUCTURAL")
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--limit-assets", type=int, default=40)
    parser.add_argument("--lookback-candles", type=int, default=300)
    parser.add_argument("--min-candles", type=int, default=40)
    parser.add_argument("--swing-window", type=int, default=2)
    parser.add_argument("--sr-tolerance-bps", default="60")
    parser.add_argument("--max-snapshots-per-asset", type=int, default=None)
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def parse_ts(value: str) -> datetime:
    normalized = value.strip().replace("T", " ")
    if normalized.endswith("Z"):
        normalized = normalized[:-1]
    return datetime.fromisoformat(normalized)


def interval_to_timedelta(interval_code: str, candles: int) -> timedelta:
    match = re.fullmatch(r"(\d+)(m|h|d)", interval_code.strip().lower())
    if not match:
        raise ValueError(f"Unsupported interval_code: {interval_code}")

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "m":
        return timedelta(minutes=value * candles)
    if unit == "h":
        return timedelta(hours=value * candles)
    if unit == "d":
        return timedelta(days=value * candles)

    raise ValueError(f"Unsupported interval unit: {unit}")


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def fetch_assets(*, asset_id: int | None, limit: int) -> list[AssetRow]:
    params: list[Any] = []
    asset_filter_sql = ""

    if asset_id is not None:
        asset_filter_sql = "AND asset_id = %s"
        params.append(asset_id)

    params.append(limit)

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

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
    finally:
        conn.close()

    return [AssetRow(asset_id=int(row["asset_id"]), symbol=str(row["symbol"])) for row in rows]


def fetch_candles(
    *,
    asset_id: int,
    symbol: str,
    venue: str,
    interval_code: str,
    warmup_from_ts: datetime,
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
    ORDER BY open_ts_utc ASC
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [asset_id, venue, interval_code, warmup_from_ts, to_ts])
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


def infer_base_regime_label(leg_direction: str | None) -> str:
    normalized = (leg_direction or "").strip().upper()
    if normalized == "UP":
        return "TREND_UP"
    if normalized == "DOWN":
        return "TREND_DOWN"
    return "RANGE"


def append_base_regime_note(
    context: ExecutionZoneContextInput,
    *,
    regime_label: str,
    leg_direction: str | None,
) -> ExecutionZoneContextInput:
    existing_notes = context.notes or ""

    additions = [
        f"regime={regime_label}",
        f"leg_direction={leg_direction or ''}",
        "fib_pref_overlay=disabled",
        "backfill_runner=run_execution_zone_context_backfill_v1",
    ]

    merged_notes = existing_notes.strip()
    for addition in additions:
        if addition not in merged_notes:
            merged_notes = (merged_notes + " " + addition).strip()

    return replace(context, notes=merged_notes)


def write_result(repo: ZoneRepository, result: Any, context: ExecutionZoneContextInput) -> int:
    writes = 0

    repo.upsert_fib_observation(result.fib_observation)
    writes += 1

    for zone in result.zones:
        repo.upsert_zone_observation(zone)
        writes += 1

    repo.upsert_execution_zone_context(context)
    writes += 1

    return writes


def main() -> int:
    args = parse_args()

    from_ts = parse_ts(args.from_ts)
    to_ts = parse_ts(args.to_ts)
    if to_ts <= from_ts:
        raise ValueError("--to-ts must be after --from-ts")

    if args.lookback_candles <= 0:
        raise ValueError("--lookback-candles must be > 0")
    if args.min_candles <= 0:
        raise ValueError("--min-candles must be > 0")
    if args.min_candles > args.lookback_candles:
        raise ValueError("--min-candles must be <= --lookback-candles")

    warmup_from_ts = from_ts - interval_to_timedelta(args.interval, args.lookback_candles)

    repo = ZoneRepository()
    assets = fetch_assets(asset_id=args.asset_id, limit=args.limit_assets)
    sr_tolerance_bps = Decimal(str(args.sr_tolerance_bps))

    total_assets = len(assets)
    total_snapshots = 0
    total_results = 0
    total_written_rows = 0

    if args.write_db:
        raise RuntimeError(
            "Operational writes are disabled for this runner. "
            "Historical zone context backfills must target synth_bt replay tables, "
            "not synth.execution_zone_context."
        )

    mode = "DRY_RUN"
    print(
        f"mode={mode} venue={args.venue} interval={args.interval} "
        f"from_ts={from_ts} to_ts={to_ts} warmup_from_ts={warmup_from_ts} "
        f"assets={total_assets}"
    )

    for asset_idx, asset in enumerate(assets, start=1):
        candles = fetch_candles(
            asset_id=asset.asset_id,
            symbol=asset.symbol,
            venue=args.venue,
            interval_code=args.interval,
            warmup_from_ts=warmup_from_ts,
            to_ts=to_ts,
        )

        if len(candles) < args.min_candles:
            print(
                f"asset_progress={asset_idx}/{total_assets} "
                f"asset_id={asset.asset_id} symbol={asset.symbol} "
                f"candles={len(candles)} snapshots=0 results=0 written_rows=0 "
                f"skipped=not_enough_candles"
            )
            continue

        asset_snapshots = 0
        asset_results = 0
        asset_written_rows = 0

        for end_idx in range(args.min_candles, len(candles) + 1):
            snapshot_candle = candles[end_idx - 1]
            snapshot_asof = snapshot_candle.open_ts_utc

            if snapshot_asof < from_ts:
                continue
            if snapshot_asof >= to_ts:
                continue

            if (
                args.max_snapshots_per_asset is not None
                and asset_snapshots >= args.max_snapshots_per_asset
            ):
                break

            start_idx = max(0, end_idx - args.lookback_candles)
            subset = candles[start_idx:end_idx]

            asset_snapshots += 1
            total_snapshots += 1

            result = build_zone_engine_result(
                repo=repo,
                candles=subset,
                swing_window=args.swing_window,
                sr_tolerance_bps=sr_tolerance_bps,
                sleeve_code=args.sleeve_code,
            )

            if result is None:
                continue

            leg_direction = getattr(result, "leg_direction", None)
            if leg_direction is None and getattr(result, "fib_observation", None) is not None:
                leg_direction = getattr(result.fib_observation, "leg_direction", None)

            regime_label = infer_base_regime_label(leg_direction)
            context = append_base_regime_note(
                result.execution_context,
                regime_label=regime_label,
                leg_direction=leg_direction,
            )

            asset_results += 1
            total_results += 1

            if args.write_db:
                written_rows = write_result(repo, result, context)
                asset_written_rows += written_rows
                total_written_rows += written_rows

            if not args.quiet:
                print(
                    f"asset_id={asset.asset_id} symbol={asset.symbol} "
                    f"asof_ts={context.asof_ts_utc} regime={regime_label} "
                    f"entry_low={context.expected_entry_zone_low} "
                    f"entry_high={context.expected_entry_zone_high} "
                    f"write_db={args.write_db}"
                )

        print(
            f"asset_progress={asset_idx}/{total_assets} "
            f"asset_id={asset.asset_id} symbol={asset.symbol} "
            f"candles={len(candles)} snapshots={asset_snapshots} "
            f"results={asset_results} written_rows={asset_written_rows}"
        )

    print(
        f"done mode={mode} assets={total_assets} snapshots={total_snapshots} "
        f"results={total_results} written_rows={total_written_rows}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
