from __future__ import annotations

import argparse
import csv
import json
import signal
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_db_connection
from src.research.multi_horizon_fib_backtest_v1 import run_multi_horizon_backtest
from src.research.multi_horizon_fib_contract_v1 import (
    DEFAULT_FEE_BPS_PER_SIDE,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_OVERLAP_CANDLES,
    DEFAULT_PIVOT_SPAN,
    FIB_TRADING_HORIZONS,
    INTERVAL_TO_DELTA,
    Candle,
    ContextRow,
    FibCheckpoint,
    SAFETY_MARKERS,
    get_horizon_definition,
)
from pymysql.cursors import SSDictCursor


DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE = "EUR"
DEFAULT_WORKERS = 1
DEFAULT_FETCH_BATCH_ROWS = 5000
DEFAULT_HEARTBEAT_SECONDS = 5.0
DEFAULT_CONTEXT_PATHS = (
    Path("data/research/historical_breath_regime_context_builder_v1/historical_breath_regime_context_rows_v1.csv"),
    Path("data/research/historical_market_breath_source_recompute_v1/historical_market_breath_source_recomputed_rows_v1.csv"),
)


@dataclass(frozen=True)
class AssetRef:
    asset_id: int
    symbol: str


@dataclass
class RunControl:
    interrupted: bool = False
    interrupt_signal: str | None = None

    def request_interrupt(self, signal_name: str) -> None:
        if not self.interrupted:
            self.interrupted = True
            self.interrupt_signal = signal_name


def emit(status: str, message: str, **fields: Any) -> None:
    suffix = " ".join(f"{key}={fields[key]}" for key in sorted(fields))
    if suffix:
        print(f"{status} {message} {suffix}", flush=True)
    else:
        print(f"{status} {message}", flush=True)


@contextmanager
def phase(name: str, **fields: Any):
    started_at = time.monotonic()
    emit("PHASE_STARTED", name, **fields)
    try:
        yield
    finally:
        emit("PHASE_FINISHED", name, elapsed_seconds=f"{time.monotonic() - started_at:.2f}", **fields)


@contextmanager
def installed_signal_handlers(control: RunControl):
    previous = {
        signal.SIGINT: signal.getsignal(signal.SIGINT),
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
    }

    def _handle(signum: int, _frame: Any) -> None:
        control.request_interrupt(signal.Signals(signum).name)
        emit("INTERRUPT_REQUESTED", "signal_received", signal=signal.Signals(signum).name)

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Research-only incremental multi-horizon fib backtest foundation "
            "(market-only, account-agnostic, read-only candle inputs, no execution)."
        )
    )
    parser.add_argument("--mode", choices=("bootstrap", "incremental", "rebuild"), default="bootstrap")
    parser.add_argument("--horizons", default="SHORT,MEDIUM,LONG")
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--fee-bps-per-side", default=str(DEFAULT_FEE_BPS_PER_SIDE))
    parser.add_argument("--overlap-candles", type=int, default=DEFAULT_OVERLAP_CANDLES)
    parser.add_argument("--pivot-span", type=int, default=DEFAULT_PIVOT_SPAN)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def parse_symbols_arg(value: str | None) -> list[str] | None:
    if not value:
        return None
    return sorted({piece.strip().upper() for piece in str(value).split(",") if piece.strip()})


def parse_horizons_arg(value: str) -> list[str]:
    items = [piece.strip().upper() for piece in str(value).split(",") if piece.strip()]
    if not items:
        raise ValueError("At least one horizon is required.")
    invalid = [item for item in items if item not in FIB_TRADING_HORIZONS]
    if invalid:
        raise ValueError(f"Unsupported horizons: {', '.join(invalid)}")
    return items


def _table_columns(conn: Any, table_name: str) -> set[str]:
    started_at = time.monotonic()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = %s",
            (table_name,),
        )
        rows = cur.fetchall()
    emit(
        "QUERY_FINISHED",
        "table_columns",
        table=table_name,
        row_count=len(rows),
        elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
    )
    return {str(row["column_name"]) for row in rows}


def fetch_assets(conn: Any, *, symbols: list[str] | None, quote: str) -> list[AssetRef]:
    columns = _table_columns(conn, "asset")
    where: list[str] = []
    params: list[Any] = []
    if "is_enabled" in columns:
        where.append("is_enabled = 1")
    if symbols:
        where.append("UPPER(symbol) IN (" + ",".join(["%s"] * len(symbols)) + ")")
        params.extend(symbols)
    elif "quote_asset" in columns:
        where.append("UPPER(quote_asset) = UPPER(%s)")
        params.append(quote)
    sql = "SELECT asset_id, symbol FROM asset"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY symbol ASC"
    started_at = time.monotonic()
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall() or []
    emit(
        "QUERY_FINISHED",
        "fetch_assets",
        row_count=len(rows),
        elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
    )
    return [AssetRef(asset_id=int(row["asset_id"]), symbol=str(row["symbol"]).upper()) for row in rows]


def _checkpoint_path(output_dir: Path, symbol: str, horizon: str) -> Path:
    return output_dir / "checkpoints" / f"{symbol}_{horizon}_checkpoint_v1.json"


def load_existing_checkpoints(
    *,
    output_dir: Path,
    symbols: list[str],
    horizons: list[str],
) -> dict[tuple[str, str], FibCheckpoint]:
    checkpoints: dict[tuple[str, str], FibCheckpoint] = {}
    for symbol in symbols:
        for horizon_name in horizons:
            path = _checkpoint_path(output_dir, symbol, horizon_name)
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            checkpoints[(symbol, horizon_name)] = FibCheckpoint.from_dict(payload)
    return checkpoints


def compute_interval_start_filters(
    *,
    assets: list[AssetRef],
    horizons: list[str],
    mode: str,
    overlap_candles: int,
    checkpoint_cache: dict[tuple[str, str], FibCheckpoint],
) -> dict[tuple[str, str], datetime | None]:
    filters: dict[tuple[str, str], datetime | None] = {}
    if mode in ("bootstrap", "rebuild"):
        return filters
    for asset in assets:
        if asset.asset_id <= 0:
            continue
        for horizon_name in horizons:
            checkpoint = checkpoint_cache.get((asset.symbol, horizon_name))
            if checkpoint is None:
                continue
            horizon = get_horizon_definition(horizon_name)
            primary_ts = checkpoint.last_processed_primary_close_ts
            if primary_ts:
                start_ts = datetime.fromisoformat(primary_ts.replace("Z", "+00:00")).astimezone(UTC)
                start_ts = start_ts - INTERVAL_TO_DELTA[horizon.primary_interval] * overlap_candles
                key = (asset.symbol, horizon.primary_interval)
                filters[key] = start_ts if key not in filters else min(filters[key], start_ts)  # type: ignore[arg-type]
            support_ts = checkpoint.last_processed_support_close_ts
            if support_ts:
                support_dt = datetime.fromisoformat(support_ts.replace("Z", "+00:00")).astimezone(UTC)
                for interval in horizon.supporting_intervals:
                    start_ts = support_dt - INTERVAL_TO_DELTA[interval] * overlap_candles
                    key = (asset.symbol, interval)
                    filters[key] = start_ts if key not in filters else min(filters[key], start_ts)  # type: ignore[arg-type]
    return filters


def inspect_obs_market_candle_access_plan(
    conn: Any,
    *,
    asset_ids: list[int],
    interval_code: str,
    venue: str,
    start_ts: datetime | None,
) -> None:
    if not asset_ids:
        return
    with phase("inspect_obs_market_candle_access_plan", interval_code=interval_code):
        started_at = time.monotonic()
        with conn.cursor() as cur:
            cur.execute("SHOW INDEX FROM obs_market_candle")
            indexes = cur.fetchall() or []
        emit(
            "QUERY_FINISHED",
            "show_index_obs_market_candle",
            row_count=len(indexes),
            elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
            index_names=",".join(sorted({str(row.get('Key_name') or '') for row in indexes})),
        )
        explain_sql = """
            EXPLAIN
            SELECT c.asset_id, c.interval_code, c.close_ts_utc
            FROM obs_market_candle c
            WHERE c.venue = %s
              AND c.interval_code = %s
              AND c.asset_id IN (%s)
        """
        params: list[Any] = [venue, interval_code, asset_ids[0]]
        if start_ts is not None:
            explain_sql += " AND c.close_ts_utc >= %s"
            params.append(start_ts.replace(tzinfo=None))
        explain_sql += " ORDER BY c.close_ts_utc ASC LIMIT 1"
        started_at = time.monotonic()
        with conn.cursor() as cur:
            cur.execute(explain_sql, tuple(params))
            rows = cur.fetchall() or []
        plan_bits = []
        for row in rows:
            plan_bits.append(
                f"type={row.get('type')} key={row.get('key')} rows={row.get('rows')} extra={row.get('Extra')}"
            )
        emit(
            "QUERY_FINISHED",
            "explain_obs_market_candle",
            row_count=len(rows),
            elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
            plan=" | ".join(plan_bits) or "none",
        )


def fetch_candles(
    conn: Any,
    *,
    assets: list[AssetRef],
    venue: str,
    quote: str,
    interval_codes: list[str],
    interval_start_filters: dict[tuple[str, str], datetime | None],
    control: RunControl,
) -> dict[str, dict[str, list[Candle]]]:
    if not assets or not interval_codes:
        return {}
    grouped: dict[str, dict[str, list[Candle]]] = {
        asset.symbol: {interval: [] for interval in interval_codes} for asset in assets
    }
    interval_groups: dict[tuple[str, datetime | None], list[AssetRef]] = {}
    for interval in interval_codes:
        buckets: dict[datetime | None, list[AssetRef]] = {}
        for asset in assets:
            if asset.asset_id <= 0:
                continue
            start_ts = interval_start_filters.get((asset.symbol, interval))
            buckets.setdefault(start_ts, []).append(asset)
        for start_ts, bucket_assets in buckets.items():
            interval_groups[(interval, start_ts)] = sorted(bucket_assets, key=lambda item: item.symbol)
    inspected_plan = False
    for (interval_code, start_ts), bucket_assets in sorted(interval_groups.items(), key=lambda item: (item[0][0], item[0][1] or datetime.min.replace(tzinfo=UTC))):
        if control.interrupted:
            break
        placeholders_assets = ",".join(["%s"] * len(bucket_assets))
        sql = f"""
            SELECT c.asset_id, a.symbol, c.venue, c.interval_code, c.open_ts_utc, c.close_ts_utc,
                   c.open_price, c.high_price, c.low_price, c.close_price
            FROM obs_market_candle c
            JOIN asset a ON a.asset_id = c.asset_id
            WHERE c.venue = %s
              AND c.interval_code = %s
              AND c.asset_id IN ({placeholders_assets})
        """
        params: list[Any] = [venue, interval_code, *[asset.asset_id for asset in bucket_assets]]
        if start_ts is not None:
            sql += " AND c.close_ts_utc >= %s"
            params.append(start_ts.replace(tzinfo=None))
        sql += " ORDER BY a.symbol ASC, c.close_ts_utc ASC"
        if not inspected_plan:
            inspect_obs_market_candle_access_plan(
                conn,
                asset_ids=[asset.asset_id for asset in bucket_assets],
                interval_code=interval_code,
                venue=venue,
                start_ts=start_ts,
            )
            inspected_plan = True
        with phase(
            "fetch_candles_group",
            interval_code=interval_code,
            asset_count=len(bucket_assets),
            start_ts="full_history" if start_ts is None else start_ts.isoformat(),
        ):
            started_at = time.monotonic()
            row_count = 0
            next_heartbeat_at = started_at + DEFAULT_HEARTBEAT_SECONDS
            with conn.cursor(SSDictCursor) as cur:
                cur.execute(sql, tuple(params))
                while not control.interrupted:
                    batch = cur.fetchmany(DEFAULT_FETCH_BATCH_ROWS)
                    if not batch:
                        break
                    row_count += len(batch)
                    for row in batch:
                        symbol = str(row["symbol"]).upper()
                        open_ts = row["open_ts_utc"].replace(tzinfo=UTC) if row["open_ts_utc"].tzinfo is None else row["open_ts_utc"].astimezone(UTC)
                        close_ts = row["close_ts_utc"].replace(tzinfo=UTC) if row["close_ts_utc"].tzinfo is None else row["close_ts_utc"].astimezone(UTC)
                        grouped.setdefault(symbol, {}).setdefault(str(row["interval_code"]), []).append(
                            Candle(
                                symbol=symbol,
                                venue=str(row["venue"]),
                                quote=quote,
                                interval_code=str(row["interval_code"]),
                                open_ts_utc=open_ts,
                                close_ts_utc=close_ts,
                                open_price=Decimal(str(row["open_price"])),
                                high_price=Decimal(str(row["high_price"])),
                                low_price=Decimal(str(row["low_price"])),
                                close_price=Decimal(str(row["close_price"])),
                            )
                        )
                    if time.monotonic() >= next_heartbeat_at:
                        emit(
                            "HEARTBEAT",
                            "fetch_candles_group",
                            interval_code=interval_code,
                            row_count=row_count,
                            elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
                        )
                        next_heartbeat_at = time.monotonic() + DEFAULT_HEARTBEAT_SECONDS
            emit(
                "QUERY_FINISHED",
                "fetch_candles_group",
                interval_code=interval_code,
                row_count=row_count,
                elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
            )
    return grouped


def _parse_context_ts(text: str | None) -> datetime | None:
    if not text:
        return None
    return datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone(UTC)


def load_context_rows(symbols: list[str]) -> dict[str, list[ContextRow]]:
    grouped: dict[str, list[ContextRow]] = {symbol: [] for symbol in symbols}
    for path in DEFAULT_CONTEXT_PATHS:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                symbol = str(row.get("symbol") or "").upper()
                if symbol not in grouped:
                    continue
                ts = _parse_context_ts(
                    row.get("sample_ts_utc")
                    or row.get("close_ts_utc")
                    or row.get("asof_ts_utc")
                    or row.get("ts_utc")
                )
                if ts is None:
                    continue
                grouped[symbol].append(
                    ContextRow(
                        symbol=symbol,
                        sample_ts_utc=ts,
                        market_regime=str(row.get("market_regime") or "UNKNOWN").upper(),
                        symbol_regime=str(row.get("symbol_regime") or "UNKNOWN").upper(),
                        breath_phase=str(row.get("breath_phase") or "UNKNOWN").upper(),
                        breath_alignment=str(row.get("breath_alignment") or "UNKNOWN").upper(),
                    )
                )
    for symbol in grouped:
        grouped[symbol] = sorted(grouped[symbol], key=lambda item: item.sample_ts_utc)
    return grouped


def build_symbol_inputs(
    *,
    assets: list[AssetRef],
    candles_by_symbol: dict[str, dict[str, list[Candle]]],
    context_rows_by_symbol: dict[str, list[ContextRow]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset in assets:
        rows.append(
            {
                "symbol": asset.symbol,
                "candles_by_interval": candles_by_symbol.get(asset.symbol, {}),
                "context_rows": context_rows_by_symbol.get(asset.symbol, []),
            }
        )
    return rows


def build_summary_lines(result: dict[str, Any]) -> list[str]:
    manifest = result["manifest"]
    row_counts = manifest["row_counts"]
    return [
        f"mode={manifest['mode']} workers={manifest['workers']} fee_bps_per_side={manifest['fee_bps_per_side']}",
        f"symbols={','.join(manifest['symbols']) or 'none'} horizons={','.join(manifest['horizons'])}",
        f"swing_events={row_counts['swing_events']} active_swings={row_counts['active_swing_rows']} fib_outcomes={row_counts['fib_level_outcomes']}",
        f"profile_stats={row_counts['profile_stats']} context_profile_stats={row_counts['context_profile_stats']}",
        "broker_writes=0 order_submission=0 executor=none db_writes=0",
    ]


def estimate_scope(
    *,
    assets: list[AssetRef],
    horizons: list[str],
    interval_codes: list[str],
    workers: int,
) -> dict[str, Any]:
    return {
        "symbol_count": len(assets),
        "horizon_count": len(horizons),
        "interval_count": len(interval_codes),
        "symbol_horizon_pairs": len(assets) * len(horizons),
        "workers": workers,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    control = RunControl()
    started_at = time.monotonic()
    try:
        with installed_signal_handlers(control):
            horizons = parse_horizons_arg(args.horizons)
            symbols = parse_symbols_arg(args.symbols)
            needed_intervals = sorted(
                {
                    interval
                    for horizon_name in horizons
                    for interval in (
                        get_horizon_definition(horizon_name).primary_interval,
                        *get_horizon_definition(horizon_name).supporting_intervals,
                    )
                }
            )
            emit(
                "STARTED",
                "run_multi_horizon_fib_backtest_v1",
                mode=args.mode,
                scope="all_enabled_assets" if not symbols else ",".join(symbols),
                workers=max(int(args.workers), 1),
                horizons=",".join(horizons),
            )
            conn = get_db_connection()
            try:
                with phase("resolve_asset_scope"):
                    assets = fetch_assets(conn, symbols=symbols, quote=args.quote)
                    if symbols:
                        existing = {asset.symbol for asset in assets}
                        for missing in sorted(set(symbols) - existing):
                            assets.append(AssetRef(asset_id=-1, symbol=missing))
                        assets = sorted(assets, key=lambda item: item.symbol)
                    emit("INFO", "scope_estimate", **estimate_scope(assets=assets, horizons=horizons, interval_codes=needed_intervals, workers=max(int(args.workers), 1)))
                checkpoint_cache = load_existing_checkpoints(
                    output_dir=Path(args.output_dir),
                    symbols=[asset.symbol for asset in assets],
                    horizons=horizons,
                )
                interval_start_filters = compute_interval_start_filters(
                    assets=assets,
                    horizons=horizons,
                    mode=args.mode,
                    overlap_candles=max(int(args.overlap_candles), 0),
                    checkpoint_cache=checkpoint_cache,
                )
                with phase("fetch_market_candles"):
                    candles_by_symbol = fetch_candles(
                        conn,
                        assets=[asset for asset in assets if asset.asset_id > 0],
                        venue=args.venue,
                        quote=args.quote,
                        interval_codes=needed_intervals,
                        interval_start_filters=interval_start_filters,
                        control=control,
                    )
            finally:
                conn.close()
            if control.interrupted:
                result = {
                    "manifest": {
                        "mode": args.mode,
                        "workers": max(int(args.workers), 1),
                        "fee_bps_per_side": str(args.fee_bps_per_side),
                        "symbols": [asset.symbol for asset in assets],
                        "horizons": horizons,
                        "row_counts": {
                            "swing_events": 0,
                            "active_swing_rows": 0,
                            "fib_level_outcomes": 0,
                            "profile_stats": 0,
                            "context_profile_stats": 0,
                        },
                    }
                }
                status = "INTERRUPTED"
                emit(
                    status,
                    "run_multi_horizon_fib_backtest_v1",
                    elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
                    signal=control.interrupt_signal or "",
                    broker_writes=0,
                    order_submission=0,
                    executor="none",
                )
                return 130
            with phase("load_context_rows", symbol_count=len(assets)):
                context_rows_by_symbol = load_context_rows([asset.symbol for asset in assets])
            symbol_inputs = build_symbol_inputs(
                assets=assets,
                candles_by_symbol=candles_by_symbol,
                context_rows_by_symbol=context_rows_by_symbol,
            )
            with phase("compute_backtest"):
                result = run_multi_horizon_backtest(
                    mode=args.mode,
                    output_dir=Path(args.output_dir),
                    symbol_inputs=symbol_inputs,
                    horizons=horizons,
                    venue=args.venue,
                    quote=args.quote,
                    workers=max(int(args.workers), 1),
                    fee_bps_per_side=Decimal(str(args.fee_bps_per_side)),
                    overlap_candles=max(int(args.overlap_candles), 0),
                    pivot_span=max(int(args.pivot_span), 1),
                    write_files=bool(args.write_files),
                    checkpoint_cache=checkpoint_cache,
                    control=control,
                    progress_callback=emit,
                )
            if args.output == "json":
                print(json.dumps(result["manifest"], indent=2, sort_keys=True), flush=True)
            else:
                for line in build_summary_lines(result):
                    print(line, flush=True)
            status = "INTERRUPTED" if control.interrupted else "FINISHED"
            emit(
                status,
                "run_multi_horizon_fib_backtest_v1",
                elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
                signal=control.interrupt_signal or "",
                broker_writes=0,
                order_submission=0,
                executor="none",
            )
            return 130 if control.interrupted else 0
    except Exception as exc:
        emit(
            "FAILED",
            "run_multi_horizon_fib_backtest_v1",
            elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
            error=str(exc),
            broker_writes=0,
            order_submission=0,
            executor="none",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
