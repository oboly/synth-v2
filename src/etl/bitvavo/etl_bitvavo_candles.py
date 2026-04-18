from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import requests


BITVAVO_BASE_URL = "https://api.bitvavo.com/v2"
BITVAVO_MAX_LIMIT = 1440


INTERVAL_TO_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}

INTERVAL_TO_DELTA: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
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


def build_requests_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    return session


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def interval_to_ms(interval_code: str) -> int:
    if interval_code not in INTERVAL_TO_MS:
        raise ValueError(f"Unsupported interval_code: {interval_code}")
    return INTERVAL_TO_MS[interval_code]


def interval_to_delta(interval_code: str) -> timedelta:
    if interval_code not in INTERVAL_TO_DELTA:
        raise ValueError(f"Unsupported interval_code: {interval_code}")
    return INTERVAL_TO_DELTA[interval_code]


def floor_to_interval(dt: datetime, interval_code: str) -> datetime:
    dt = ensure_utc(dt)

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
        "interval": interval_code,
        "start": start_ms,
        "end": end_ms,
        "limit": min(limit, BITVAVO_MAX_LIMIT),
    }

    response = session.get(url, params=params, timeout=timeout_seconds)
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected Bitvavo response for {market} {interval_code}: {payload}")

    return list(reversed(payload))


def parse_bitvavo_payload(
    *,
    asset_id: int,
    venue: str,
    interval_code: str,
    payload: list[list[Any]],
) -> list[CandleRow]:
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
    interval_code: str,
    start_dt: datetime,
    end_dt: datetime,
) -> None:
    if not rows:
        return

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

    if len(rows) >= 2:
        for prev_row, row in zip(rows[:-1], rows[1:]):
            diff_ms = int((row.open_ts_utc - prev_row.open_ts_utc).total_seconds() * 1000)
            if diff_ms != interval_ms:
                print(
                    f"[ETL][WARN] intra-chunk gap detected interval={interval_code} "
                    f"prev={prev_row.open_ts_utc.isoformat()} "
                    f"current={row.open_ts_utc.isoformat()} diff_ms={diff_ms}"
                )


def upsert_candles(conn, rows: list[CandleRow]) -> int:
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
    **_: Any,
) -> dict[str, int]:
    del sleep_seconds

    start_dt = floor_to_interval(start_dt, interval_code)
    end_dt = floor_to_interval(end_dt, interval_code)

    if end_dt <= start_dt:
        print(
            f"[ETL] skip market={market} interval={interval_code} "
            f"reason=empty_window start={start_dt.isoformat()} end={end_dt.isoformat()}"
        )
        return {"written_rows": 0}

    interval_ms = interval_to_ms(interval_code)
    limit = min(batch_limit, BITVAVO_MAX_LIMIT)
    chunk_span_ms = interval_ms * limit

    aligned_start_ms = dt_to_ms(start_dt)
    aligned_end_ms = dt_to_ms(end_dt)

    window_start_ms = aligned_start_ms
    total_written = 0
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
            interval_code=interval_code,
            start_dt=ms_to_dt(window_start_ms),
            end_dt=ms_to_dt(window_end_ms),
        )

        first_raw_ts = raw_payload[0][0] if raw_payload else None
        last_raw_ts = raw_payload[-1][0] if raw_payload else None

        print(
            f"[ETL] chunk={chunk_idx} market={market} interval={interval_code} "
            f"window_start={ms_to_dt(window_start_ms).isoformat()} "
            f"window_end={ms_to_dt(window_end_ms).isoformat()} "
            f"raw_count={len(raw_payload)} "
            f"filtered_count={len(filtered_rows)} "
            f"first_raw_ts={first_raw_ts} "
            f"last_raw_ts={last_raw_ts}"
        )

        if not dry_run:
            total_written += upsert_candles(conn, filtered_rows)

        window_start_ms = window_end_ms

    print(
        f"[ETL] done market={market} interval={interval_code} "
        f"start={start_dt.isoformat()} end={end_dt.isoformat()} "
        f"written={total_written} dry_run={dry_run}"
    )

    return {"written_rows": total_written}
