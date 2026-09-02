from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import requests


BITVAVO_BASE_URL = "https://api.bitvavo.com/v2"
BITVAVO_MAX_LIMIT = 1440

# Bounded-by-default logging (P0-A). Per-chunk and per-gap diagnostic lines
# are noisy at production asset-universe scale (hundreds of enabled assets
# every 5 minutes) and were a suspected contributor to Odroid root-filesystem
# exhaustion on 2026-07-05. Default production output aggregates these into
# counts returned from run_market_interval(); full per-chunk/per-gap detail
# is only printed when debug logging is explicitly enabled.
DEBUG_ENV_VAR = "SYNTH_CANDLES_ETL_DEBUG"


def debug_logging_enabled() -> bool:
    """Explicit debug mode switch for verbose per-chunk/per-gap ETL logging.

    Read fresh on every call (not cached at import time) so tests and
    callers can toggle it via monkeypatched environment without reload.
    """
    return os.environ.get(DEBUG_ENV_VAR, "").strip().lower() in ("1", "true", "yes")


class MarketUnavailableError(Exception):
    """Raised when a market/interval is rejected by the exchange (HTTP 400/404).

    Callers must catch this per-task and continue — it must not abort the full run.
    """

    def __init__(self, *, market: str, interval_code: str, http_status: int) -> None:
        self.market = market
        self.interval_code = interval_code
        self.http_status = http_status
        super().__init__(
            f"market={market} interval={interval_code} http_status={http_status}"
        )


INTERVAL_TO_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
    "1w": 7 * 24 * 60 * 60_000,
}

INTERVAL_TO_DELTA: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
}


@dataclass(frozen=True)
class CandleRow:
    asset_id: int
    venue: str
    interval_code: str
    open_ts_utc: datetime
    close_ts_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    market: str = ""


def build_requests_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    return session


def fetch_active_bitvavo_markets(
    *,
    session: requests.Session,
    timeout_seconds: int = 20,
) -> set[str]:
    """Return the set of market names whose status is 'trading' from GET /v2/markets.

    Callers should use this to pre-filter the asset list before ETL so that
    delisted/suspended markets (e.g. ALMANAK-EUR) are skipped rather than aborted.
    Raises on HTTP error so the caller can decide whether to fail-open or fail-closed.
    """
    url = f"{BITVAVO_BASE_URL}/markets"
    response = session.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return set()
    return {
        str(item["market"])
        for item in payload
        if isinstance(item, dict)
        and item.get("status") == "trading"
        and item.get("market")
    }


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def normalize_interval_code(interval_code: str) -> str:
    value = str(interval_code).strip()
    lower = value.lower()
    if lower == "1w":
        return "1w"
    return lower


def to_bitvavo_interval_code(interval_code: str) -> str:
    normalized = normalize_interval_code(interval_code)
    if normalized == "1w":
        return "1W"
    return normalized


def interval_to_ms(interval_code: str) -> int:
    interval_code = normalize_interval_code(interval_code)
    if interval_code not in INTERVAL_TO_MS:
        raise ValueError(f"Unsupported interval_code: {interval_code}")
    return INTERVAL_TO_MS[interval_code]


def interval_to_delta(interval_code: str) -> timedelta:
    interval_code = normalize_interval_code(interval_code)
    if interval_code not in INTERVAL_TO_DELTA:
        raise ValueError(f"Unsupported interval_code: {interval_code}")
    return INTERVAL_TO_DELTA[interval_code]


def floor_to_interval(dt: datetime, interval_code: str) -> datetime:
    dt = ensure_utc(dt)
    interval_code = normalize_interval_code(interval_code)

    if interval_code == "1m":
        return dt.replace(second=0, microsecond=0)

    if interval_code == "5m":
        minute = (dt.minute // 5) * 5
        return dt.replace(minute=minute, second=0, microsecond=0)

    if interval_code == "15m":
        minute = (dt.minute // 15) * 15
        return dt.replace(minute=minute, second=0, microsecond=0)

    if interval_code == "30m":
        minute = (dt.minute // 30) * 30
        return dt.replace(minute=minute, second=0, microsecond=0)

    if interval_code == "1h":
        return dt.replace(minute=0, second=0, microsecond=0)

    if interval_code == "4h":
        hour = (dt.hour // 4) * 4
        return dt.replace(hour=hour, minute=0, second=0, microsecond=0)

    if interval_code == "1d":
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)

    if interval_code == "1w":
        day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start - timedelta(days=day_start.weekday())

    raise ValueError(f"Unsupported interval_code: {interval_code}")


def dt_to_ms(dt: datetime) -> int:
    return int(ensure_utc(dt).timestamp() * 1000)


def ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def fetch_bitvavo_candles(
    *,
    session: requests.Session,
    market: str,
    interval_code: str,
    start_ms: int,
    end_ms: int,
    timeout_seconds: int,
    limit: int = BITVAVO_MAX_LIMIT,
) -> list[list[Any]]:
    url = f"{BITVAVO_BASE_URL}/{market}/candles"
    params = {
        "interval": to_bitvavo_interval_code(interval_code),
        "start": start_ms,
        "end": end_ms,
        "limit": min(limit, BITVAVO_MAX_LIMIT),
    }

    response = session.get(url, params=params, timeout=timeout_seconds)
    if response.status_code in (400, 404):
        raise MarketUnavailableError(
            market=market, interval_code=interval_code, http_status=response.status_code
        )
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected Bitvavo response for {market} {interval_code}: {payload}")

    return list(reversed(payload))


def parse_bitvavo_payload(
    *,
    asset_id: int,
    venue: str,
    market: str,
    interval_code: str,
    payload: list[list[Any]],
) -> list[CandleRow]:
    interval_code = normalize_interval_code(interval_code)
    delta = interval_to_delta(interval_code)
    rows: list[CandleRow] = []

    for item in payload:
        if not isinstance(item, list) or len(item) < 6:
            continue

        open_ts = ms_to_dt(int(item[0]))
        close_ts = open_ts + delta

        rows.append(
            CandleRow(
                asset_id=asset_id,
                venue=venue,
                market=market,
                interval_code=interval_code,
                open_ts_utc=open_ts.replace(tzinfo=None),
                close_ts_utc=close_ts.replace(tzinfo=None),
                open=Decimal(str(item[1])),
                high=Decimal(str(item[2])),
                low=Decimal(str(item[3])),
                close=Decimal(str(item[4])),
                volume=Decimal(str(item[5])),
            )
        )

    return rows


def filter_candles_strict(
    *,
    candles: list[CandleRow],
    start_dt: datetime,
    end_dt: datetime,
) -> list[CandleRow]:
    start_naive = ensure_utc(start_dt).replace(tzinfo=None)
    end_naive = ensure_utc(end_dt).replace(tzinfo=None)

    return [
        row
        for row in candles
        if start_naive <= row.open_ts_utc < end_naive
    ]


def validate_chunk_rows(
    *,
    rows: list[CandleRow],
    market: str,
    asset_id: int,
    interval_code: str,
    chunk_index: int,
    start_dt: datetime,
    end_dt: datetime,
) -> int:
    """Validate OHLC/timestamp integrity for one fetched chunk.

    Returns the number of intra-chunk gaps detected (0 if none). Raises
    RuntimeError on hard data-integrity violations (duplicate/non-monotonic
    timestamps, misaligned candles, invalid OHLC geometry, negative volume) —
    those remain fatal and always visible regardless of debug mode.

    Gap-detection lines are diagnostic, not fatal, and are gated behind
    `debug_logging_enabled()` (see module docstring / DEBUG_ENV_VAR) so a
    multi-asset production run does not emit one line per gap by default.
    The caller must still receive the count to include in its own bounded
    aggregate summary.
    """
    if not rows:
        return 0

    interval_delta = interval_to_delta(interval_code)
    interval_ms = interval_to_ms(interval_code)

    start_naive = ensure_utc(start_dt).replace(tzinfo=None)
    end_naive = ensure_utc(end_dt).replace(tzinfo=None)

    seen_open_ts: set[datetime] = set()
    prev_open_ts: datetime | None = None

    for idx, row in enumerate(rows, start=1):
        if row.open_ts_utc in seen_open_ts:
            raise RuntimeError(
                f"Duplicate open_ts_utc in chunk: interval={interval_code} ts={row.open_ts_utc.isoformat()}"
            )
        seen_open_ts.add(row.open_ts_utc)

        if prev_open_ts is not None and row.open_ts_utc <= prev_open_ts:
            raise RuntimeError(
                f"Non-monotonic timestamps in chunk: interval={interval_code} "
                f"prev={prev_open_ts.isoformat()} current={row.open_ts_utc.isoformat()}"
            )
        prev_open_ts = row.open_ts_utc

        aligned_open = floor_to_interval(row.open_ts_utc.replace(tzinfo=UTC), interval_code).replace(tzinfo=None)
        if row.open_ts_utc != aligned_open:
            raise RuntimeError(
                f"Unaligned open_ts_utc: interval={interval_code} ts={row.open_ts_utc.isoformat()}"
            )

        expected_close = row.open_ts_utc + interval_delta
        if row.close_ts_utc != expected_close:
            raise RuntimeError(
                f"Invalid close_ts_utc: interval={interval_code} open={row.open_ts_utc.isoformat()} "
                f"close={row.close_ts_utc.isoformat()} expected={expected_close.isoformat()}"
            )

        if not (start_naive <= row.open_ts_utc < end_naive):
            raise RuntimeError(
                f"Out-of-window candle after filtering: interval={interval_code} "
                f"open_ts={row.open_ts_utc.isoformat()} "
                f"window=[{start_naive.isoformat()}, {end_naive.isoformat()})"
            )

        if row.high < row.low:
            raise RuntimeError(
                f"Invalid OHLC geometry high<low: interval={interval_code} ts={row.open_ts_utc.isoformat()}"
            )

        if row.high < max(row.open, row.close):
            raise RuntimeError(
                f"Invalid OHLC geometry high<max(open,close): interval={interval_code} ts={row.open_ts_utc.isoformat()}"
            )

        if row.low > min(row.open, row.close):
            raise RuntimeError(
                f"Invalid OHLC geometry low>min(open,close): interval={interval_code} ts={row.open_ts_utc.isoformat()}"
            )

        if row.volume < 0:
            raise RuntimeError(
                f"Negative volume: interval={interval_code} ts={row.open_ts_utc.isoformat()}"
            )

    gap_count = 0
    if len(rows) >= 2:
        for prev_row, row in zip(rows[:-1], rows[1:]):
            diff_ms = int((row.open_ts_utc - prev_row.open_ts_utc).total_seconds() * 1000)
            if diff_ms != interval_ms:
                gap_count += 1
                if debug_logging_enabled():
                    print(
                        f"[ETL][WARN] intra-chunk gap detected "
                        f"market={market} asset_id={asset_id} chunk={chunk_index} "
                        f"interval={interval_code} prev={prev_row.open_ts_utc.isoformat()} "
                        f"current={row.open_ts_utc.isoformat()} diff_ms={diff_ms}"
                    )

    return gap_count


def upsert_candles(conn, rows: list[CandleRow], *, authorization: Any = None) -> int:
    from src.operations.writer_capability_authorization_v1 import (
        require_writer_mutation_authorization,
    )

    # Fail closed before any SQL execution.
    require_writer_mutation_authorization(authorization, "public_candle_freshness")
    if not rows:
        return 0
    sql = """
    INSERT INTO obs_market_candle (
        asset_id,
        venue,
        interval_code,
        open_ts_utc,
        close_ts_utc,
        open_price,
        high_price,
        low_price,
        close_price,
        volume_base,
        volume_quote_eur
    ) VALUES (
        %(asset_id)s,
        %(venue)s,
        %(interval_code)s,
        %(open_ts_utc)s,
        %(close_ts_utc)s,
        %(open_price)s,
        %(high_price)s,
        %(low_price)s,
        %(close_price)s,
        %(volume_base)s,
        %(volume_quote_eur)s
    )
    ON DUPLICATE KEY UPDATE
        close_ts_utc = VALUES(close_ts_utc),
        open_price = VALUES(open_price),
        high_price = VALUES(high_price),
        low_price = VALUES(low_price),
        close_price = VALUES(close_price),
        volume_base = VALUES(volume_base),
        volume_quote_eur = VALUES(volume_quote_eur)
    """

    payload = [
        {
            "asset_id": row.asset_id,
            "venue": row.venue,
            "interval_code": row.interval_code,
            "open_ts_utc": row.open_ts_utc,
            "close_ts_utc": row.close_ts_utc,
            "open_price": str(row.open),
            "high_price": str(row.high),
            "low_price": str(row.low),
            "close_price": str(row.close),
            "volume_base": str(row.volume),
            "volume_quote_eur": str(row.volume * row.close),
        }
        for row in rows
    ]

    with conn.cursor() as cur:
        cur.executemany(sql, payload)
        identity_sql = """
        INSERT INTO obs_market_candle_market_identity_v1 (
            asset_id, venue, market, interval_code, open_ts_utc, close_ts_utc,
            open_price, high_price, low_price, close_price, volume_base
        ) VALUES (
            %(asset_id)s, %(venue)s, %(market)s, %(interval_code)s, %(open_ts_utc)s, %(close_ts_utc)s,
            %(open_price)s, %(high_price)s, %(low_price)s, %(close_price)s, %(volume_base)s
        ) ON DUPLICATE KEY UPDATE
            close_ts_utc=VALUES(close_ts_utc), open_price=VALUES(open_price), high_price=VALUES(high_price),
            low_price=VALUES(low_price), close_price=VALUES(close_price), volume_base=VALUES(volume_base)
        """
        identity_payload = [{**item, "market": row.market} for item, row in zip(payload, rows)]
        if any(not item["market"] for item in identity_payload):
            raise ValueError("candle market identity is required")
        cur.executemany(identity_sql, identity_payload)

    return len(rows)


def run_market_interval(
    *,
    conn,
    session,
    asset_id: int,
    market: str,
    venue: str,
    interval_code: str,
    start_dt: datetime,
    end_dt: datetime,
    batch_limit: int = BITVAVO_MAX_LIMIT,
    timeout_seconds: int = 20,
    sleep_seconds: float = 0.0,
    dry_run: bool = False,
    authorization: Any = None,
    **_: Any,
) -> dict[str, int]:
    """Run ETL for one (asset, interval) pair.

    Returns a dict with `written_rows`, `chunks`, `gap_warnings`,
    `raw_payload_rows`, `accepted_rows`, and `dropped_rows` (always present,
    even in the empty-window/no-op case) so the caller
    (run_candles_etl.py) can build a bounded aggregate summary without
    relying on this function's own print statements, which are gated behind
    `debug_logging_enabled()` by default (P0-A).
    """
    del sleep_seconds
    interval_code = normalize_interval_code(interval_code)

    start_dt = floor_to_interval(start_dt, interval_code)
    end_dt = floor_to_interval(end_dt, interval_code)

    if end_dt <= start_dt:
        if debug_logging_enabled():
            print(
                f"[ETL] skip market={market} interval={interval_code} "
                f"reason=empty_window start={start_dt.isoformat()} end={end_dt.isoformat()}"
            )
        return {
            "written_rows": 0,
            "chunks": 0,
            "gap_warnings": 0,
            "raw_payload_rows": 0,
            "accepted_rows": 0,
            "dropped_rows": 0,
        }

    interval_ms = interval_to_ms(interval_code)
    limit = min(batch_limit, BITVAVO_MAX_LIMIT)
    chunk_span_ms = interval_ms * limit

    aligned_start_ms = dt_to_ms(start_dt)
    aligned_end_ms = dt_to_ms(end_dt)

    window_start_ms = aligned_start_ms
    total_written = 0
    total_gap_warnings = 0
    total_raw_payload_rows = 0
    total_accepted_rows = 0
    total_dropped_rows = 0
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
            market=market,
            interval_code=interval_code,
            payload=raw_payload,
        )

        filtered_rows = filter_candles_strict(
            candles=parsed_rows,
            start_dt=ms_to_dt(window_start_ms),
            end_dt=ms_to_dt(window_end_ms),
        )
        raw_count = len(raw_payload)
        accepted_count = len(filtered_rows)
        dropped_count = max(raw_count - accepted_count, 0)
        total_raw_payload_rows += raw_count
        total_accepted_rows += accepted_count
        total_dropped_rows += dropped_count

        total_gap_warnings += validate_chunk_rows(
            rows=filtered_rows,
            market=str(
                locals().get("market")
                or locals().get("market_code")
                or getattr(locals().get("asset"), "market", None)
                or "UNKNOWN"
            ),
            asset_id=int(
                locals().get("asset_id")
                or getattr(locals().get("asset"), "asset_id", -1)
            ),
            interval_code=interval_code,
            chunk_index=int(
                locals().get("chunk_index")
                or locals().get("chunk_idx")
                or locals().get("chunk_no")
                or locals().get("chunk")
                or -1
            ),
            start_dt=ms_to_dt(window_start_ms),
            end_dt=ms_to_dt(window_end_ms),
            )

        if debug_logging_enabled():
            first_raw_ts = raw_payload[0][0] if raw_payload else None
            last_raw_ts = raw_payload[-1][0] if raw_payload else None
            print(
                f"[ETL] chunk={chunk_idx} market={market} interval={interval_code} "
                f"window_start={ms_to_dt(window_start_ms).isoformat()} "
                f"window_end={ms_to_dt(window_end_ms).isoformat()} "
                f"raw_count={raw_count} "
                f"accepted_count={accepted_count} "
                f"dropped_count={dropped_count} "
                f"first_raw_ts={first_raw_ts} "
                f"last_raw_ts={last_raw_ts}"
            )

        if not dry_run:
            total_written += upsert_candles(conn, filtered_rows, authorization=authorization)

        window_start_ms = window_end_ms

    if debug_logging_enabled():
        print(
            f"[ETL] done market={market} interval={interval_code} "
            f"start={start_dt.isoformat()} end={end_dt.isoformat()} "
            f"written={total_written} dry_run={dry_run} "
            f"chunks={chunk_idx} gap_warnings={total_gap_warnings} "
            f"raw_payload_rows={total_raw_payload_rows} "
            f"accepted_rows={total_accepted_rows} "
            f"dropped_rows={total_dropped_rows}"
        )

    return {
        "written_rows": total_written,
        "chunks": chunk_idx,
        "gap_warnings": total_gap_warnings,
        "raw_payload_rows": total_raw_payload_rows,
        "accepted_rows": total_accepted_rows,
        "dropped_rows": total_dropped_rows,
    }
