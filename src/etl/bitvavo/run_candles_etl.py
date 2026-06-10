from __future__ import annotations

import argparse
import importlib
import inspect
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.common.utc import utc_now
from src.etl.bitvavo.etl_bitvavo_candles import MarketUnavailableError


DEFAULT_CONFIG_PATH = "configs/etl_bitvavo_candles.yaml"
DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE_ASSET = "EUR"


@dataclass(frozen=True)
class AssetRow:
    asset_id: int
    symbol: str
    market: str


@dataclass(frozen=True)
class EtlConfig:
    venue: str
    quote_asset: str
    intervals: list[str]
    default_lookback: dict[str, str]
    batch_limit: int
    timeout_seconds: int
    sleep_seconds: float
    raw: dict[str, Any]


@dataclass
class RunControl:
    interrupted: bool = False
    signal_name: str | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Bitvavo candles ETL")
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to YAML config (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--start",
        default=None,
        help="Override start timestamp, e.g. 2026-03-01T00:00:00+00:00",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="Override end timestamp, e.g. 2026-03-30T00:00:00+00:00",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run ETL without writing data",
    )
    parser.add_argument(
        "--asset",
        action="append",
        default=None,
        help="Optional symbol filter, e.g. --asset BTC --asset ETH",
    )
    parser.add_argument(
        "--interval",
        action="append",
        default=None,
        help="Optional interval filter, e.g. --interval 1h --interval 4h",
    )
    return parser.parse_args(argv)


def load_config(path: str) -> EtlConfig:
    config_path = Path(path)

    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ValueError("Config root must be a mapping")

    etl_section = data.get("etl", {})
    if not isinstance(etl_section, dict):
        raise ValueError("Config 'etl' section must be a mapping")

    venue = str(etl_section.get("venue", DEFAULT_VENUE))
    quote_asset = str(data.get("quote_asset", DEFAULT_QUOTE_ASSET)).upper()

    intervals = data.get("intervals")
    if not isinstance(intervals, list) or not intervals:
        raise ValueError("Config must contain a non-empty 'intervals' list")

    clean_intervals: list[str] = []
    for interval in intervals:
        if not isinstance(interval, str):
            raise ValueError("All interval entries must be strings")
        clean_intervals.append(interval.strip())

    default_lookback = etl_section.get("default_lookback", {})
    if not isinstance(default_lookback, dict):
        raise ValueError("Config 'etl.default_lookback' must be a mapping")

    clean_lookback: dict[str, str] = {}
    for key, value in default_lookback.items():
        clean_lookback[str(key)] = str(value)

    batch_limit = int(etl_section.get("batch_limit", 1000))
    timeout_seconds = int(etl_section.get("request_timeout_seconds", 20))
    sleep_seconds = float(etl_section.get("sleep_seconds", 0.15))

    return EtlConfig(
        venue=venue,
        quote_asset=quote_asset,
        intervals=clean_intervals,
        default_lookback=clean_lookback,
        batch_limit=batch_limit,
        timeout_seconds=timeout_seconds,
        sleep_seconds=sleep_seconds,
        raw=data,
    )


def parse_iso_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_duration_to_timedelta(value: str) -> timedelta:
    value = value.strip().lower()

    if not value:
        raise ValueError("Duration string is empty")

    unit = value[-1]
    amount_raw = value[:-1]

    if not amount_raw.isdigit():
        raise ValueError(f"Invalid duration: {value}")

    amount = int(amount_raw)

    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    if unit == "w":
        return timedelta(weeks=amount)

    raise ValueError(f"Unsupported duration unit in: {value}")


def resolve_window(
    *,
    interval_code: str,
    start_override: str | None,
    end_override: str | None,
    default_lookback: dict[str, str],
) -> tuple[datetime, datetime]:
    end_dt = parse_iso_utc(end_override) if end_override else utc_now().astimezone(UTC)

    if start_override:
        start_dt = parse_iso_utc(start_override)
        return start_dt, end_dt

    lookback_str = default_lookback.get(interval_code)
    if lookback_str is None:
        raise ValueError(f"No default lookback configured for interval={interval_code}")

    start_dt = end_dt - parse_duration_to_timedelta(lookback_str)
    return start_dt, end_dt


def load_assets(
    conn,
    *,
    quote_asset: str,
    wanted_symbols: set[str] | None = None,
) -> list[AssetRow]:
    sql = """
    SELECT
        asset_id,
        symbol
    FROM asset
    WHERE is_enabled = 1
    ORDER BY asset_id
    """

    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    assets: list[AssetRow] = []

    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from database cursor")

        symbol = str(row["symbol"]).upper()

        if wanted_symbols is not None and symbol not in wanted_symbols:
            continue

        assets.append(
            AssetRow(
                asset_id=int(row["asset_id"]),
                symbol=symbol,
                market=f"{symbol}-{quote_asset}",
            )
        )

    return assets


def emit(message: str) -> None:
    print(message, flush=True)


def iso_now() -> str:
    return utc_now().astimezone(UTC).isoformat()


def install_signal_handlers(control: RunControl) -> tuple[Any, Any]:
    def _handler(signum: int, _frame: Any) -> None:
        if control.interrupted:
            return
        control.interrupted = True
        try:
            control.signal_name = signal.Signals(signum).name
        except ValueError:
            control.signal_name = str(signum)
        emit(
            f"INTERRUPT_SIGNAL run_candles_etl signal={control.signal_name} "
            f"ts={iso_now()}"
        )

    previous_int = signal.getsignal(signal.SIGINT)
    previous_term = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
    return previous_int, previous_term


def restore_signal_handlers(previous_int: Any, previous_term: Any) -> None:
    signal.signal(signal.SIGINT, previous_int)
    signal.signal(signal.SIGTERM, previous_term)


def resolve_etl_module() -> Any:
    return importlib.import_module("src.etl.bitvavo.etl_bitvavo_candles")


def resolve_etl_callable(module: Any) -> Callable[..., Any]:
    candidates = [
        "run_market_interval",
        "run_candles_etl_for_market",
        "run_market_interval_etl",
        "run_etl_for_market",
        "run_candles_for_market",
        "etl_market_interval",
        "run_market_etl",
    ]

    for name in candidates:
        fn = getattr(module, name, None)
        if callable(fn):
            return fn

    callable_names = [
        name
        for name in dir(module)
        if callable(getattr(module, name)) and not name.startswith("_")
    ]

    raise RuntimeError(
        "Could not find ETL callable in src.etl.bitvavo.etl_bitvavo_candles. "
        f"Tried={candidates}. Available={callable_names}"
    )


def build_session(module: Any) -> Any:
    builder = getattr(module, "build_requests_session", None)
    if not callable(builder):
        raise RuntimeError("etl_bitvavo_candles.py is missing build_requests_session()")
    return builder()


def call_etl_function(
    fn: Callable[..., Any],
    *,
    conn,
    session: Any,
    asset: AssetRow,
    interval_code: str,
    start_dt: datetime,
    end_dt: datetime,
    venue: str,
    config: EtlConfig,
    dry_run: bool,
) -> Any:
    signature = inspect.signature(fn)

    candidate_kwargs: dict[str, Any] = {
        "conn": conn,
        "session": session,
        "asset_id": asset.asset_id,
        "symbol": asset.symbol,
        "market": asset.market,
        "market_symbol": asset.market,
        "venue": venue,
        "interval_code": interval_code,
        "interval": interval_code,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "start": start_dt,
        "end": end_dt,
        "start_ts": start_dt,
        "end_ts": end_dt,
        "batch_limit": config.batch_limit,
        "timeout_seconds": config.timeout_seconds,
        "sleep_seconds": config.sleep_seconds,
        "dry_run": dry_run,
        "config": config.raw,
        "etl_config": config.raw.get("etl", {}),
        "quote_asset": config.quote_asset,
    }

    accepted_kwargs: dict[str, Any] = {}

    for name in signature.parameters:
        if name in candidate_kwargs:
            accepted_kwargs[name] = candidate_kwargs[name]

    return fn(**accepted_kwargs)


def extract_written_rows(result: Any) -> int | None:
    if isinstance(result, int):
        return result

    if isinstance(result, dict):
        for key in (
            "rows",
            "rowcount",
            "written_rows",
            "inserted_rows",
            "upserted_rows",
        ):
            value = result.get(key)
            if isinstance(value, int):
                return value

    return None


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    started_at = time.perf_counter()
    control = RunControl()
    previous_int, previous_term = install_signal_handlers(control)
    args = parse_args(argv)

    wanted_symbols = {value.upper() for value in args.asset} if args.asset else None
    scope = ",".join(sorted(wanted_symbols)) if wanted_symbols else "ALL_ENABLED"
    requested_intervals = [value.strip() for value in args.interval] if args.interval else None
    emit(
        "STARTED run_candles_etl "
        f"ts={iso_now()} mode={'dry_run' if args.dry_run else 'write'} "
        f"scope={scope} intervals={','.join(requested_intervals or ['FROM_CONFIG'])} "
        "workers=1 broker_private_calls=0 broker_writes=0 order_submission=0 "
        "live_orders=0 decision_gate=none execution_planner=none executor=none"
    )

    try:
        phase_started = time.perf_counter()
        emit(f"PHASE_STARTED load_config path={args.config}")
        config = load_config(args.config)
        emit(
            f"PHASE_FINISHED load_config elapsed_s={time.perf_counter() - phase_started:.3f} "
            f"interval_count={len(config.intervals)}"
        )

        intervals = requested_intervals or config.intervals
        conn = get_db_connection()
    except Exception as exc:
        elapsed = time.perf_counter() - started_at
        emit(
            f"FAILED run_candles_etl elapsed_s={elapsed:.3f} "
            f"error={exc.__class__.__name__}:{exc}"
        )
        restore_signal_handlers(previous_int, previous_term)
        return 1

    try:
        phase_started = time.perf_counter()
        emit(
            f"PHASE_STARTED load_assets quote_asset={config.quote_asset} "
            f"symbol_filter_count={len(wanted_symbols) if wanted_symbols else 0}"
        )
        assets = load_assets(
            conn,
            quote_asset=config.quote_asset,
            wanted_symbols=wanted_symbols,
        )
        emit(
            f"QUERY_RESULT name=load_assets rows={len(assets)} "
            f"elapsed_s={time.perf_counter() - phase_started:.3f}"
        )

        if not assets:
            emit(
                f"FINISHED run_candles_etl elapsed_s={time.perf_counter() - started_at:.3f} "
                "task_count=0 total_rows=0 skipped=0"
            )
            return 0

        module = resolve_etl_module()
        etl_fn = resolve_etl_callable(module)
        session = build_session(module)

        # Filter assets to active/trading markets before ETL begins.
        # Fail-open: if the market metadata fetch fails, proceed with all assets.
        skipped_market_errors: list[dict[str, str]] = []
        active_market_filter_fn = getattr(module, "fetch_active_bitvavo_markets", None)
        if callable(active_market_filter_fn):
            try:
                phase_started = time.perf_counter()
                emit("PHASE_STARTED filter_active_markets")
                active_markets: set[str] = active_market_filter_fn(
                    session=session, timeout_seconds=config.timeout_seconds
                )
                pre_count = len(assets)
                inactive = [a for a in assets if a.market not in active_markets]
                assets = [a for a in assets if a.market in active_markets]
                for a in inactive:
                    emit(
                        f"SKIPPED_MARKET market={a.market} "
                        f"reason=NOT_IN_ACTIVE_MARKET_LIST"
                    )
                    skipped_market_errors.append(
                        {"market": a.market, "reason": "NOT_IN_ACTIVE_MARKET_LIST"}
                    )
                emit(
                    f"PHASE_FINISHED filter_active_markets "
                    f"elapsed_s={time.perf_counter() - phase_started:.3f} "
                    f"active_count={len(active_markets)} "
                    f"assets_before={pre_count} assets_after={len(assets)} "
                    f"filtered_out={len(inactive)}"
                )
            except Exception as exc:
                emit(
                    f"[WARN] active_market_filter_failed "
                    f"reason={exc.__class__.__name__}:{exc} "
                    "proceeding_without_filter"
                )

        total_written = 0
        total_tasks = len(assets) * len(intervals)
        completed_tasks = 0
        skipped_tasks = 0

        for asset in assets:
            for interval_code in intervals:
                if control.interrupted:
                    raise KeyboardInterrupt(control.signal_name or "SIGINT")

                start_dt, end_dt = resolve_window(
                    interval_code=interval_code,
                    start_override=args.start,
                    end_override=args.end,
                    default_lookback=config.default_lookback,
                )

                phase_started = time.perf_counter()
                emit(
                    f"PHASE_STARTED market_interval venue={config.venue} "
                    f"market={asset.market} "
                    f"interval={interval_code} "
                    f"asset_id={asset.asset_id} "
                    f"start={start_dt.isoformat()} "
                    f"end={end_dt.isoformat()} "
                    f"dry_run={args.dry_run}"
                )

                try:
                    result = call_etl_function(
                        etl_fn,
                        conn=conn,
                        session=session,
                        asset=asset,
                        interval_code=interval_code,
                        start_dt=start_dt,
                        end_dt=end_dt,
                        venue=config.venue,
                        config=config,
                        dry_run=args.dry_run,
                    )
                except MarketUnavailableError as exc:
                    emit(
                        f"SKIPPED_MARKET_ERROR market={asset.market} "
                        f"interval={interval_code} "
                        f"reason=MARKET_UNAVAILABLE "
                        f"http_status={exc.http_status}"
                    )
                    skipped_market_errors.append(
                        {
                            "market": asset.market,
                            "interval": interval_code,
                            "reason": "MARKET_UNAVAILABLE",
                            "http_status": str(exc.http_status),
                        }
                    )
                    skipped_tasks += 1
                    completed_tasks += 1
                    emit(
                        f"PROGRESS run_candles_etl completed={completed_tasks}/{total_tasks} "
                        f"skipped={skipped_tasks} total_rows={total_written} "
                        f"elapsed_s={time.perf_counter() - started_at:.3f}"
                    )
                    continue

                written = extract_written_rows(result)
                if written is not None:
                    total_written += written
                    if written == 0:
                        skipped_tasks += 1
                else:
                    written = -1
                if not args.dry_run:
                    conn.commit()
                    emit(
                        f"CHECKPOINT_WRITTEN market={asset.market} interval={interval_code} "
                        f"rows={written if written >= 0 else 'unknown'}"
                    )

                completed_tasks += 1
                emit(
                    f"PHASE_FINISHED market_interval market={asset.market} interval={interval_code} "
                    f"elapsed_s={time.perf_counter() - phase_started:.3f} "
                    f"rows={written if written >= 0 else 'unknown'}"
                )
                emit(
                    f"PROGRESS run_candles_etl completed={completed_tasks}/{total_tasks} "
                    f"skipped={skipped_tasks} total_rows={total_written} "
                    f"elapsed_s={time.perf_counter() - started_at:.3f}"
                )

        emit(
            f"FINISHED run_candles_etl elapsed_s={time.perf_counter() - started_at:.3f} "
            f"task_count={completed_tasks} total_rows={total_written} skipped={skipped_tasks} "
            f"skipped_market_errors={len(skipped_market_errors)}"
        )
        return 0

    except KeyboardInterrupt:
        conn.rollback()
        emit(
            f"INTERRUPTED run_candles_etl elapsed_s={time.perf_counter() - started_at:.3f} "
            f"signal={control.signal_name or 'SIGINT'}"
        )
        return 130

    except Exception as exc:
        conn.rollback()
        emit(
            f"FAILED run_candles_etl elapsed_s={time.perf_counter() - started_at:.3f} "
            f"error={exc.__class__.__name__}:{exc}"
        )
        return 1

    finally:
        conn.close()
        restore_signal_handlers(previous_int, previous_term)


if __name__ == "__main__":
    raise SystemExit(main())
