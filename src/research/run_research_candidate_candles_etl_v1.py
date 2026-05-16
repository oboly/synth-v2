from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.etl.bitvavo.etl_bitvavo_candles import (
    BITVAVO_BASE_URL,
    BITVAVO_MAX_LIMIT,
    build_requests_session,
    dt_to_ms,
    fetch_bitvavo_candles,
    filter_candles_strict,
    floor_to_interval,
    interval_to_ms,
    ms_to_dt,
    parse_bitvavo_payload,
    upsert_candles,
    validate_chunk_rows,
)


DEFAULT_VENUE = "bitvavo"
DEFAULT_SYMBOLS = ["APT", "SXT"]
DEFAULT_QUOTE = "EUR"
DEFAULT_INTERVAL = "4h"
DEFAULT_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class AssetCandidate:
    symbol: str
    asset_id: int | None
    is_enabled: int | None
    is_tradeable: int | None
    is_portfolio: int | None


@dataclass(frozen=True)
class CandidateResult:
    symbol: str
    market: str
    asset_id: int | None
    asset_enabled: int | None
    asset_tradeable: int | None
    market_available: bool
    rows_fetched: int
    rows_written: int
    first_close_ts_utc: str | None
    last_close_ts_utc: str | None
    status: str
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only candle ingestion for disabled watch/research candidates."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument(
        "--start",
        default=None,
        help="UTC start timestamp. Defaults to a recent 30 day research window.",
    )
    parser.add_argument("--end", default=None, help="UTC end timestamp. Defaults to now.")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso_utc(value: datetime) -> str:
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def naive_iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def resolve_window(
    *,
    start_arg: str | None,
    end_arg: str | None,
    interval_code: str,
) -> tuple[datetime, datetime]:
    end_dt = parse_ts(end_arg) if end_arg else datetime.now(UTC)
    start_dt = parse_ts(start_arg) if start_arg else end_dt - timedelta(days=30)
    return floor_to_interval(start_dt, interval_code), floor_to_interval(end_dt, interval_code)


def load_assets(conn, symbols: list[str]) -> dict[str, AssetCandidate]:
    clean_symbols = sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()})
    if not clean_symbols:
        return {}

    placeholders = ",".join(["%s"] * len(clean_symbols))
    sql = f"""
    SELECT
        asset_id,
        symbol,
        is_enabled,
        is_tradeable,
        is_portfolio
    FROM asset
    WHERE symbol IN ({placeholders})
    ORDER BY symbol
    """

    with conn.cursor() as cur:
        cur.execute(sql, clean_symbols)
        rows = cur.fetchall()

    found: dict[str, AssetCandidate] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from asset query")
        symbol = str(row["symbol"]).upper()
        found[symbol] = AssetCandidate(
            symbol=symbol,
            asset_id=int(row["asset_id"]),
            is_enabled=int(row["is_enabled"]),
            is_tradeable=int(row["is_tradeable"]),
            is_portfolio=int(row["is_portfolio"]),
        )

    return found


def fetch_market_available(
    *,
    session: requests.Session,
    market: str,
    timeout_seconds: int,
) -> bool:
    response = session.get(
        f"{BITVAVO_BASE_URL}/markets",
        params={"market": market},
        timeout=timeout_seconds,
    )
    if response.status_code == 404:
        return False
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, list):
        return any(str(item.get("market", "")).upper() == market.upper() for item in payload if isinstance(item, dict))
    if isinstance(payload, dict):
        return str(payload.get("market", "")).upper() == market.upper()
    return False


def fetch_candidate_candles(
    *,
    session: requests.Session,
    asset_id: int,
    venue: str,
    market: str,
    interval_code: str,
    start_dt: datetime,
    end_dt: datetime,
    timeout_seconds: int,
) -> list[Any]:
    start_dt = floor_to_interval(start_dt, interval_code)
    end_dt = floor_to_interval(end_dt, interval_code)
    if end_dt <= start_dt:
        return []

    interval_ms = interval_to_ms(interval_code)
    limit = BITVAVO_MAX_LIMIT
    chunk_span_ms = interval_ms * limit

    window_start_ms = dt_to_ms(start_dt)
    aligned_end_ms = dt_to_ms(end_dt)

    all_rows: list[Any] = []
    chunk_idx = 0

    while window_start_ms < aligned_end_ms:
        chunk_idx += 1
        window_end_ms = min(window_start_ms + chunk_span_ms, aligned_end_ms)
        raw_payload = fetch_bitvavo_candles(
            session=session,
            market=market,
            interval_code=interval_code,
            start_ms=window_start_ms,
            end_ms=window_end_ms,
            timeout_seconds=timeout_seconds,
            limit=limit,
        )
        parsed_rows = parse_bitvavo_payload(
            asset_id=asset_id,
            venue=venue,
            interval_code=interval_code,
            payload=raw_payload,
        )
        filtered_rows = filter_candles_strict(
            candles=parsed_rows,
            start_dt=ms_to_dt(window_start_ms),
            end_dt=ms_to_dt(window_end_ms),
        )
        validate_chunk_rows(
            rows=filtered_rows,
            market=market,
            asset_id=asset_id,
            interval_code=interval_code,
            chunk_index=chunk_idx,
            start_dt=ms_to_dt(window_start_ms),
            end_dt=ms_to_dt(window_end_ms),
        )
        all_rows.extend(filtered_rows)
        window_start_ms = window_end_ms

    return all_rows


def run_symbol(
    *,
    conn,
    session: requests.Session,
    candidate: AssetCandidate | None,
    symbol: str,
    venue: str,
    quote: str,
    interval_code: str,
    start_dt: datetime,
    end_dt: datetime,
    write_db: bool,
) -> CandidateResult:
    market = f"{symbol}-{quote}"

    if candidate is None:
        return CandidateResult(
            symbol=symbol,
            market=market,
            asset_id=None,
            asset_enabled=None,
            asset_tradeable=None,
            market_available=False,
            rows_fetched=0,
            rows_written=0,
            first_close_ts_utc=None,
            last_close_ts_utc=None,
            status="ASSET_MISSING",
            reason="Asset row is missing; no candles were fetched or written.",
        )

    warning_parts: list[str] = []
    if candidate.is_enabled:
        warning_parts.append("asset is enabled unexpectedly")
    if candidate.is_tradeable:
        warning_parts.append("asset is tradeable unexpectedly")

    try:
        market_available = fetch_market_available(
            session=session,
            market=market,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        )
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            market_available = False
        else:
            return CandidateResult(
                symbol=symbol,
                market=market,
                asset_id=candidate.asset_id,
                asset_enabled=candidate.is_enabled,
                asset_tradeable=candidate.is_tradeable,
                market_available=False,
                rows_fetched=0,
                rows_written=0,
                first_close_ts_utc=None,
                last_close_ts_utc=None,
                status="FETCH_ERROR",
                reason=f"Market metadata fetch failed: {exc}",
            )

    if not market_available:
        return CandidateResult(
            symbol=symbol,
            market=market,
            asset_id=candidate.asset_id,
            asset_enabled=candidate.is_enabled,
            asset_tradeable=candidate.is_tradeable,
            market_available=False,
            rows_fetched=0,
            rows_written=0,
            first_close_ts_utc=None,
            last_close_ts_utc=None,
            status="MARKET_NOT_AVAILABLE",
            reason="Public venue market metadata did not include this market.",
        )

    try:
        candles = fetch_candidate_candles(
            session=session,
            asset_id=int(candidate.asset_id),
            venue=venue,
            market=market,
            interval_code=interval_code,
            start_dt=start_dt,
            end_dt=end_dt,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        )
    except requests.HTTPError as exc:
        return CandidateResult(
            symbol=symbol,
            market=market,
            asset_id=candidate.asset_id,
            asset_enabled=candidate.is_enabled,
            asset_tradeable=candidate.is_tradeable,
            market_available=True,
            rows_fetched=0,
            rows_written=0,
            first_close_ts_utc=None,
            last_close_ts_utc=None,
            status="FETCH_ERROR",
            reason=f"Candle fetch failed: {exc}",
        )

    rows_written = 0
    if write_db and candles:
        rows_written = upsert_candles(conn, candles)

    status = "WRITTEN" if write_db else "DRY_RUN_OK"
    if not candles:
        status = "NO_CANDLES"

    reason = "Research-only market-data fetch; asset flags were not modified."
    if warning_parts:
        reason = f"{reason} WARNING: {', '.join(warning_parts)}."

    first_close = min((row.close_ts_utc for row in candles), default=None)
    last_close = max((row.close_ts_utc for row in candles), default=None)

    return CandidateResult(
        symbol=symbol,
        market=market,
        asset_id=candidate.asset_id,
        asset_enabled=candidate.is_enabled,
        asset_tradeable=candidate.is_tradeable,
        market_available=True,
        rows_fetched=len(candles),
        rows_written=rows_written,
        first_close_ts_utc=naive_iso_utc(first_close),
        last_close_ts_utc=naive_iso_utc(last_close),
        status=status,
        reason=reason,
    )


def render_table(results: list[CandidateResult]) -> str:
    headers = [
        "symbol",
        "market",
        "asset_id",
        "enabled",
        "tradeable",
        "market",
        "fetched",
        "written",
        "last_close",
        "status",
    ]
    lines = [" | ".join(headers), " | ".join(["---"] * len(headers))]
    for row in results:
        lines.append(
            " | ".join(
                [
                    row.symbol,
                    row.market,
                    "" if row.asset_id is None else str(row.asset_id),
                    "" if row.asset_enabled is None else str(row.asset_enabled),
                    "" if row.asset_tradeable is None else str(row.asset_tradeable),
                    "1" if row.market_available else "0",
                    str(row.rows_fetched),
                    str(row.rows_written),
                    row.last_close_ts_utc or "",
                    row.status,
                ]
            )
        )
    return "\n".join(lines)


def main() -> int:
    load_dotenv()
    args = parse_args()

    symbols = [symbol.strip().upper() for symbol in args.symbols if symbol.strip()]
    quote = args.quote.strip().upper()
    start_dt, end_dt = resolve_window(
        start_arg=args.start,
        end_arg=args.end,
        interval_code=args.interval,
    )

    conn = get_db_connection()
    try:
        asset_map = load_assets(conn, symbols)
        session = build_requests_session()
        results = [
            run_symbol(
                conn=conn,
                session=session,
                candidate=asset_map.get(symbol),
                symbol=symbol,
                venue=args.venue,
                quote=quote,
                interval_code=args.interval,
                start_dt=start_dt,
                end_dt=end_dt,
                write_db=args.write_db,
            )
            for symbol in symbols
        ]

        if args.write_db:
            conn.commit()
        else:
            conn.rollback()

        payload = {
            "report": "research_candidate_candle_ingestion_v1",
            "version": "1.0",
            "scope": "research_only_market_data",
            "venue": args.venue,
            "quote": quote,
            "interval_code": args.interval,
            "start_ts_utc": iso_utc(start_dt),
            "end_ts_utc": iso_utc(end_dt),
            "write_db": bool(args.write_db),
            "results": [asdict(row) for row in results],
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "selection_engine_changes": 0,
            "advice_engine_changes": 0,
            "decision_gate_changes": 0,
            "execution_planner_changes": 0,
            "executor_changes": 0,
        }

        if args.output == "json":
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(render_table(results))
            print(
                f"window={payload['start_ts_utc']}..{payload['end_ts_utc']} "
                f"write_db={payload['write_db']} "
                "broker_calls=0 broker_writes=0 order_submission=0 live_orders=0"
            )

        return 0

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
