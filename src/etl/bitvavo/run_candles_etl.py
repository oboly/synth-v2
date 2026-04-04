from __future__ import annotations

import argparse
import importlib
import inspect
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.common.utc import utc_now


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


def parse_args() -> argparse.Namespace:
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
    return parser.parse_args()


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


def main() -> int:
    load_dotenv()
    args = parse_args()

    config = load_config(args.config)

    wanted_symbols = None
    if args.asset:
        wanted_symbols = {value.upper() for value in args.asset}

    intervals = config.intervals
    if args.interval:
        intervals = [value.strip() for value in args.interval]

    conn = get_db_connection()

    try:
        assets = load_assets(
            conn,
            quote_asset=config.quote_asset,
            wanted_symbols=wanted_symbols,
        )

        if not assets:
            print("[WARN] No enabled assets found after filtering.")
            return 0

        module = resolve_etl_module()
        etl_fn = resolve_etl_callable(module)
        session = build_session(module)

        total_written = 0

        for asset in assets:
            for interval_code in intervals:
                start_dt, end_dt = resolve_window(
                    interval_code=interval_code,
                    start_override=args.start,
                    end_override=args.end,
                    default_lookback=config.default_lookback,
                )

                print(
                    f"[RUN] venue={config.venue} "
                    f"market={asset.market} "
                    f"interval={interval_code} "
                    f"asset_id={asset.asset_id} "
                    f"start={start_dt.isoformat()} "
                    f"end={end_dt.isoformat()} "
                    f"dry_run={args.dry_run}"
                )

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

                written = extract_written_rows(result)
                if written is not None:
                    total_written += written
                    print(
                        f"[DONE] market={asset.market} "
                        f"interval={interval_code} "
                        f"rows={written}"
                    )
                else:
                    print(
                        f"[DONE] market={asset.market} "
                        f"interval={interval_code}"
                    )

        print(f"[DONE] total_rows={total_written}")
        return 0

    except Exception as exc:
        conn.rollback()
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
