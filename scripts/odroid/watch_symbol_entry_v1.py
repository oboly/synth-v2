#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REPORT_NAME = "watch_symbol_entry_v1"
REPORT_VERSION = "0.1"
DEFAULT_BASE_URL = "https://api.bitvavo.com/v2"
DEFAULT_NTFY_BASE_URL = "https://ntfy.sh"
NOTIFY_STATES = {"SHALLOW_PULLBACK_STRONG", "NORMAL_RETEST_ZONE", "DEEP_RETEST_ZONE"}


@dataclass(frozen=True)
class Candle:
    open_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass(frozen=True)
class TimeframeContext:
    interval: str
    state: str
    recent_low: Decimal
    recent_high: Decimal
    shallow_level: Decimal
    normal_level: Decimal
    deep_level: Decimal


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Public-market manual entry watcher for one Bitvavo symbol."
    )
    parser.add_argument("--market", default="NEAR-EUR")
    parser.add_argument("--topic", default=None)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--notify-on-wait", action="store_true")
    parser.add_argument("--cooldown-minutes", type=int, default=10)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    return parser.parse_args(argv)


def dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def fmt_ts(value: datetime | None = None) -> str:
    ts = value or datetime.now(UTC)
    return ts.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def fmt_dec(value: Decimal, places: str = "0.000000") -> str:
    try:
        return str(value.quantize(Decimal(places)))
    except Exception:
        return str(value)


def http_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, body: bytes | None = None) -> Any:
    request = Request(url, method=method, headers=headers or {}, data=body)
    with urlopen(request, timeout=20) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def http_post_text(url: str, *, headers: dict[str, str], body: bytes) -> None:
    request = Request(url, method="POST", headers=headers, data=body)
    with urlopen(request, timeout=20):
        return


def fetch_price(*, base_url: str, market: str) -> Decimal:
    query = urlencode({"market": market})
    payload = http_json(f"{base_url}/ticker/price?{query}")
    if isinstance(payload, list):
        if not payload:
            raise RuntimeError(f"No ticker price returned for {market}")
        payload = payload[0]
    return dec(payload["price"])


def fetch_candles(*, base_url: str, market: str, interval: str, limit: int) -> list[Candle]:
    query = urlencode({"interval": interval, "limit": limit})
    payload = http_json(f"{base_url}/{market}/candles?{query}")
    candles: list[Candle] = []
    for row in reversed(payload):
        open_ts_ms, open_px, high_px, low_px, close_px, _volume = row
        candles.append(
            Candle(
                open_ts_utc=datetime.fromtimestamp(int(open_ts_ms) / 1000, tz=UTC),
                open_price=dec(open_px),
                high_price=dec(high_px),
                low_price=dec(low_px),
                close_price=dec(close_px),
            )
        )
    return candles


def classify_timeframe(interval: str, candles: list[Candle], current_price: Decimal) -> TimeframeContext:
    if len(candles) < 8:
        raise RuntimeError(f"Not enough {interval} candles to classify state")

    window = candles[-24:] if interval == "1h" else candles[-16:]
    recent_low = min(candle.low_price for candle in window)
    recent_high = max(candle.high_price for candle in window)
    if recent_high <= recent_low:
        raise RuntimeError(f"Invalid range for {interval}: low={recent_low} high={recent_high}")

    range_size = recent_high - recent_low
    shallow_level = recent_high - (range_size * Decimal("0.382"))
    normal_level = recent_high - (range_size * Decimal("0.500"))
    deep_level = recent_high - (range_size * Decimal("0.618"))

    last_close = window[-1].close_price
    prev_close = window[-2].close_price
    last_high = window[-1].high_price
    last_low = window[-1].low_price

    if current_price >= recent_high * Decimal("0.995") and last_close >= prev_close:
        state = "IMPULSE_CONTINUATION"
    elif last_high >= shallow_level and current_price > shallow_level and current_price < last_high:
        state = "WICK_REJECTION_PULLBACK"
    elif current_price >= shallow_level:
        state = "SHALLOW_PULLBACK_STRONG"
    elif current_price >= normal_level:
        state = "NORMAL_RETEST_ZONE"
    elif current_price >= deep_level and current_price >= recent_low:
        state = "DEEP_RETEST_ZONE"
    else:
        state = "NO_CLEAN_ENTRY"

    if current_price < recent_low or last_low < recent_low:
        state = "NO_CLEAN_ENTRY"

    return TimeframeContext(
        interval=interval,
        state=state,
        recent_low=recent_low,
        recent_high=recent_high,
        shallow_level=shallow_level,
        normal_level=normal_level,
        deep_level=deep_level,
    )


def decision_key(context_15m: TimeframeContext, context_1h: TimeframeContext) -> str:
    for state in ("DEEP_RETEST_ZONE", "NORMAL_RETEST_ZONE", "SHALLOW_PULLBACK_STRONG"):
        if context_15m.state == state or context_1h.state == state:
            return state
    if context_15m.state == "WICK_REJECTION_PULLBACK" or context_1h.state == "WICK_REJECTION_PULLBACK":
        return "WICK_REJECTION_PULLBACK"
    if context_15m.state == "IMPULSE_CONTINUATION" and context_1h.state == "IMPULSE_CONTINUATION":
        return "IMPULSE_CONTINUATION"
    if context_15m.state == context_1h.state:
        return context_15m.state
    return f"{context_15m.state}__{context_1h.state}"


def should_notify(decision: str, *, notify_on_wait: bool) -> bool:
    if decision in NOTIFY_STATES:
        return True
    if notify_on_wait and decision in {"IMPULSE_CONTINUATION", "WICK_REJECTION_PULLBACK", "NO_CLEAN_ENTRY"}:
        return True
    return False


def build_message(market: str, price: Decimal, context_15m: TimeframeContext, context_1h: TimeframeContext, decision: str) -> str:
    return (
        f"{market}\n"
        f"price={fmt_dec(price)}\n"
        f"15m={context_15m.state}\n"
        f"1h={context_1h.state}\n"
        f"15m zones shallow={fmt_dec(context_15m.shallow_level)} normal={fmt_dec(context_15m.normal_level)} deep={fmt_dec(context_15m.deep_level)}\n"
        f"1h zones shallow={fmt_dec(context_1h.shallow_level)} normal={fmt_dec(context_1h.normal_level)} deep={fmt_dec(context_1h.deep_level)}\n"
        f"decision={decision}\n"
        "Manual review only. No order was placed."
    )


def notify_topic(*, topic: str, title: str, message: str) -> None:
    url = f"{DEFAULT_NTFY_BASE_URL.rstrip('/')}/{topic}"
    body = message.encode("utf-8")
    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Title": title,
        "Tags": "warning_chart",
    }
    http_post_text(url, headers=headers, body=body)


def print_poll(market: str, price: Decimal, context_15m: TimeframeContext, context_1h: TimeframeContext, decision: str) -> None:
    print(f"utc={fmt_ts()}")
    print(f"market={market} current_price={fmt_dec(price)}")
    print(f"15m_state={context_15m.state} 1h_state={context_1h.state}")
    print(
        "15m_levels "
        f"shallow={fmt_dec(context_15m.shallow_level)} "
        f"normal={fmt_dec(context_15m.normal_level)} "
        f"deep={fmt_dec(context_15m.deep_level)}"
    )
    print(
        "1h_levels "
        f"shallow={fmt_dec(context_1h.shallow_level)} "
        f"normal={fmt_dec(context_1h.normal_level)} "
        f"deep={fmt_dec(context_1h.deep_level)}"
    )
    print(f"decision_key={decision}")
    print("broker_writes=0 order_submission=0 executor=none")
    print("")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    market = str(args.market).upper()
    cooldown = timedelta(minutes=int(args.cooldown_minutes))
    last_notified_at: datetime | None = None

    while True:
        now = datetime.now(UTC)
        try:
            price = fetch_price(base_url=str(args.base_url).rstrip("/"), market=market)
            candles_15m = fetch_candles(base_url=str(args.base_url).rstrip("/"), market=market, interval="15m", limit=64)
            candles_1h = fetch_candles(base_url=str(args.base_url).rstrip("/"), market=market, interval="1h", limit=64)
            context_15m = classify_timeframe("15m", candles_15m, price)
            context_1h = classify_timeframe("1h", candles_1h, price)
            decision = decision_key(context_15m, context_1h)
            print_poll(market, price, context_15m, context_1h, decision)

            if args.topic and should_notify(decision, notify_on_wait=bool(args.notify_on_wait)):
                if last_notified_at is None or now - last_notified_at >= cooldown:
                    message = build_message(market, price, context_15m, context_1h, decision)
                    notify_topic(
                        topic=str(args.topic),
                        title=f"{market} {decision}",
                        message=message,
                    )
                    last_notified_at = now
                    print(f"notify_sent topic={args.topic} decision={decision}")
                else:
                    remaining = cooldown - (now - last_notified_at)
                    print(f"notify_skipped_cooldown remaining_seconds={int(remaining.total_seconds())}")
        except (HTTPError, URLError, RuntimeError, ValueError) as exc:
            print(f"utc={fmt_ts()} market={market} error={exc}", file=sys.stderr)
            print("broker_writes=0 order_submission=0 executor=none", file=sys.stderr)
            if args.once:
                return 1

        if args.once:
            return 0
        time.sleep(max(5, int(args.seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
