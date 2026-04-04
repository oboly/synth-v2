from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import requests


BITVAVO_BASE_URL = "https://api.bitvavo.com/v2"

INTERVAL_MS: dict[str, int] = {
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


@dataclass(frozen=True)
class CandleRow:
    asset_id: int
    venue: str
    interval_code: str
    open_ts_utc: datetime
    close_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume_base: Decimal | None
    volume_quote_eur: Decimal | None
    trade_count: int | None
    source_ts_utc: datetime | None
    ingest_ts_utc: datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def floor_dt(dt: datetime, interval: str) -> datetime:
    if interval not in INTERVAL_MS:
        raise ValueError(f"Unsupported interval: {interval}")

    interval_ms = INTERVAL_MS[interval]
    floored_ms = (to_ms(dt) // interval_ms) * interval_ms
    return from_ms(floored_ms)


def parse_utc_iso8601(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp must be timezone-aware UTC: {value}")

    return dt.astimezone(UTC)


def parse_duration_to_timedelta(value: str) -> timedelta:
    raw = value.strip().lower()

    if raw.endswith("d"):
        return timedelta(days=int(raw[:-1]))
    if raw.endswith("h"):
        return timedelta(hours=int(raw[:-1]))
    if raw.endswith("m"):
        return timedelta(minutes=int(raw[:-1]))

    raise ValueError(f"Unsupported duration format: {value}")


def resolve_range(
    *,
    start: str | None,
    end: str | None,
    default_lookback: str | dict[str, str],
    interval: str,
) -> tuple[datetime, datetime]:
    """
    Resolve start/end range in UTC.

    Accepts:
    - default_lookback as string, e.g. "120d"
    - default_lookback as dict per interval, e.g. {"1h": "120d"}

    The runner currently already resolves per-interval lookback,
    but this helper remains backward-compatible.
    """
    end_dt = parse_utc_iso8601(end) if end else utc_now()
    end_dt = floor_dt(end_dt, interval)

    if start:
        start_dt = parse_utc_iso8601(start)
    else:
        if isinstance(default_lookback, dict):
            if interval not in default_lookback:
                raise KeyError(f"Missing default_lookback for interval: {interval}")
            lookback_value = default_lookback[interval]
        else:
            lookback_value = default_lookback

        start_dt = end_dt - parse_duration_to_timedelta(str(lookback_value))

    start_dt = floor_dt(start_dt, interval)

    if start_dt >= end_dt:
        raise ValueError(
            f"Invalid range for {interval}: start={start_dt.isoformat()} end={end_dt.isoformat()}"
        )

    return start_dt, end_dt


def build_requests_session(api_key: str | None = None) -> requests.Session:
    session = requests.Session()
    if api_key:
        session.headers.update({"Bitvavo-Access-Key": api_key})
    return session


def fetch_bitvavo_candles(
    session: requests.Session,
    market: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    limit: int,
    timeout_seconds: int,
) -> list[list[Any]]:
    url = f"{BITVAVO_BASE_URL}/{market}/candles"
    params = {
        "interval": interval,
        "start": start_ms,
        "end": end_ms,
        "limit": limit,
    }

    response = session.get(url, params=params, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected Bitvavo payload for {market} {interval}: {payload}")

    # Bitvavo returns newest -> oldest. Reverse to chronological order.
    return list(reversed(payload))


def normalize_bitvavo_candle(
    *,
    asset_id: int,
    venue: str,
    interval_code: str,
    raw: list[Any],
    ingest_ts_utc: datetime,
) -> CandleRow:
    open_ms = int(raw[0])
    open_ts_utc = from_ms(open_ms)
    close_ts_utc = open_ts_utc + timedelta(milliseconds=INTERVAL_MS[interval_code])

    close_price = Decimal(str(raw[4]))
    volume_base = Decimal(str(raw[5]))

    return CandleRow(
        asset_id=asset_id,
        venue=venue,
        interval_code=interval_code,
        open_ts_utc=open_ts_utc,
        close_ts_utc=close_ts_utc,
        open_price=Decimal(str(raw[1])),
        high_price=Decimal(str(raw[2])),
        low_price=Decimal(str(raw[3])),
        close_price=close_price,
        volume_base=volume_base,
        volume_quote_eur=close_price * volume_base,
        trade_count=None,
        source_ts_utc=open_ts_utc,
        ingest_ts_utc=ingest_ts_utc,
    )


def upsert_rows(conn, rows: list[CandleRow]) -> int:
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
        volume_quote_eur,
        trade_count,
        source_ts_utc,
        ingest_ts_utc
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    ON DUPLICATE KEY UPDATE
        close_ts_utc = VALUES(close_ts_utc),
        open_price = VALUES(open_price),
        high_price = VALUES(high_price),
        low_price = VALUES(low_price),
        close_price = VALUES(close_price),
        volume_base = VALUES(volume_base),
        volume_quote_eur = VALUES(volume_quote_eur),
        trade_count = VALUES(trade_count),
        source_ts_utc = VALUES(source_ts_utc),
        ingest_ts_utc = VALUES(ingest_ts_utc)
    """

    data = [
        (
            row.asset_id,
            row.venue,
            row.interval_code,
            row.open_ts_utc.replace(tzinfo=None),
            row.close_ts_utc.replace(tzinfo=None),
            str(row.open_price),
            str(row.high_price),
            str(row.low_price),
            str(row.close_price),
            None if row.volume_base is None else str(row.volume_base),
            None if row.volume_quote_eur is None else str(row.volume_quote_eur),
            row.trade_count,
            None if row.source_ts_utc is None else row.source_ts_utc.replace(tzinfo=None),
            row.ingest_ts_utc.replace(tzinfo=None),
        )
        for row in rows
    ]

    with conn.cursor() as cur:
        cur.executemany(sql, data)

    conn.commit()
    return len(rows)


def run_market_interval(
    *,
    conn,
    session: requests.Session,
    venue: str,
    asset_id: int,
    market: str,
    interval: str,
    start_dt: datetime,
    end_dt: datetime,
    batch_limit: int,
    timeout_seconds: int,
    sleep_seconds: float,
    dry_run: bool,
) -> int:
    if interval not in INTERVAL_MS:
        raise ValueError(f"Unsupported interval: {interval}")

    step_ms = INTERVAL_MS[interval]
    total_rows = 0

    # One chunk spans exactly `batch_limit` candles.
    window_span_ms = batch_limit * step_ms

    window_start_ms = to_ms(start_dt)
    end_ms = to_ms(end_dt)

    while window_start_ms < end_ms:
        window_end_ms = min(window_start_ms + window_span_ms, end_ms)

        candles = fetch_bitvavo_candles(
            session=session,
            market=market,
            interval=interval,
            start_ms=window_start_ms,
            end_ms=window_end_ms,
            limit=batch_limit,
            timeout_seconds=timeout_seconds,
        )

        ingest_ts_utc = utc_now()
        rows: list[CandleRow] = []

        for raw in candles:
            row = normalize_bitvavo_candle(
                asset_id=asset_id,
                venue=venue,
                interval_code=interval,
                raw=raw,
                ingest_ts_utc=ingest_ts_utc,
            )

            if row.open_ts_utc < start_dt:
                continue
            if row.open_ts_utc >= end_dt:
                continue

            rows.append(row)

        inserted = len(rows) if dry_run else upsert_rows(conn=conn, rows=rows)
        total_rows += inserted

        chunk_start = from_ms(window_start_ms).isoformat()
        chunk_end = from_ms(window_end_ms).isoformat()

        print(
            f"[CHUNK] market={market} interval={interval} "
            f"window_start={chunk_start} window_end={chunk_end} rows={inserted}"
        )

        if window_end_ms >= end_ms:
            break

        # 1 candle overlap to avoid boundary loss
        next_window_start_ms = window_end_ms - step_ms

        if next_window_start_ms <= window_start_ms:
            print("[WARN] Non-advancing window detected, breaking")
            break

        window_start_ms = next_window_start_ms

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return total_rows
