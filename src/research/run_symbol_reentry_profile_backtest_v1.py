from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_db_connection
from src.research.htf_fib_reentry_ladder_v1 import RETRACE_LEVELS

UTC = timezone.utc

REPORT_NAME = "run_symbol_reentry_profile_backtest_v1"
REPORT_VERSION = "0.1"

DEFAULT_OUTPUT_DIR = Path("data/research/symbol_reentry_profile_backtest_v1")
DEFAULT_LOOKBACK_CANDLES = 500
DEFAULT_PIVOT_SPAN = 5
DEFAULT_MIN_IMPULSE_PCT = Decimal("15")
DEFAULT_LOOKFORWARD_BARS = 60
DEFAULT_MIN_SAMPLE = 3
DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL = "1d"

RETRACE_LABEL_ORDER: list[str] = [row[0] for row in RETRACE_LEVELS]
RESPECT_LABELS: frozenset[str] = frozenset({"retrace_0_382", "retrace_0_500", "NO_TOUCH"})


@dataclass(frozen=True)
class BacktestCandle:
    ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass(frozen=True)
class ImpulseSwing:
    swing_low_price: Decimal
    swing_high_price: Decimal
    impulse_pct: Decimal
    swing_low_ts: datetime
    swing_high_ts: datetime
    swing_low_idx: int
    swing_high_idx: int


@dataclass(frozen=True)
class RetraceEvent:
    symbol: str
    interval_code: str
    swing_low_price: Decimal
    swing_high_price: Decimal
    impulse_pct: Decimal
    swing_high_ts: str
    deepest_low_price: Decimal
    deepest_retrace_label: str
    retrace_0_382_touched: bool
    retrace_0_500_touched: bool
    retrace_0_618_touched: bool
    retrace_0_786_touched: bool
    bounce_after_touch_pct: Decimal | None


@dataclass(frozen=True)
class SymbolReentryProfile:
    symbol: str
    interval_code: str
    sample_size: int
    touch_count_0_382: int
    touch_count_0_500: int
    touch_count_0_618: int
    touch_count_0_786: int
    preferred_retrace_level: str
    avg_bounce_after_0_382: Decimal | None
    avg_bounce_after_0_500: Decimal | None
    avg_bounce_after_0_618: Decimal | None
    missed_by_pct_main: Decimal | None
    wickiness_score: Decimal
    volatility_score: Decimal
    fib_respect_score: Decimal
    classification: str


def _find_pivot_lows(candles: list[BacktestCandle], span: int) -> list[int]:
    result: list[int] = []
    n = len(candles)
    for i in range(span, n - span):
        low = candles[i].low_price
        start = max(0, i - span)
        end = min(n, i + span + 1)
        if all(low <= candles[j].low_price for j in range(start, end)):
            result.append(i)
    return result


def _find_pivot_highs(candles: list[BacktestCandle], span: int) -> list[int]:
    result: list[int] = []
    n = len(candles)
    for i in range(span, n - span):
        high = candles[i].high_price
        start = max(0, i - span)
        end = min(n, i + span + 1)
        if all(high >= candles[j].high_price for j in range(start, end)):
            result.append(i)
    return result


def detect_impulse_swings(
    candles: list[BacktestCandle],
    *,
    pivot_span: int,
    min_impulse_pct: Decimal,
) -> list[ImpulseSwing]:
    if len(candles) < pivot_span * 2 + 1:
        return []
    lows = _find_pivot_lows(candles, pivot_span)
    highs = _find_pivot_highs(candles, pivot_span)
    swings: list[ImpulseSwing] = []
    used_high_idxs: set[int] = set()
    for high_idx in highs:
        if high_idx in used_high_idxs:
            continue
        prior_lows = [i for i in lows if i < high_idx]
        if not prior_lows:
            continue
        low_idx = prior_lows[-1]
        sl = candles[low_idx].low_price
        sh = candles[high_idx].high_price
        if sl <= Decimal("0") or sh <= sl:
            continue
        impulse_pct = (sh - sl) / sl * Decimal("100")
        if impulse_pct < min_impulse_pct:
            continue
        used_high_idxs.add(high_idx)
        swings.append(
            ImpulseSwing(
                swing_low_price=sl,
                swing_high_price=sh,
                impulse_pct=impulse_pct,
                swing_low_ts=candles[low_idx].ts_utc,
                swing_high_ts=candles[high_idx].ts_utc,
                swing_low_idx=low_idx,
                swing_high_idx=high_idx,
            )
        )
    return swings


def _retrace_price(swing_high: Decimal, leg: Decimal, fib_level: Decimal) -> Decimal:
    return swing_high - leg * fib_level


def classify_retrace_event(
    symbol: str,
    interval_code: str,
    swing: ImpulseSwing,
    candles: list[BacktestCandle],
    *,
    lookforward_bars: int,
) -> RetraceEvent:
    leg = swing.swing_high_price - swing.swing_low_price
    level_prices: dict[str, Decimal] = {
        label: _retrace_price(swing.swing_high_price, leg, fib_level)
        for label, fib_level, _ in RETRACE_LEVELS
    }

    start = swing.swing_high_idx + 1
    end = min(len(candles), start + lookforward_bars)
    window = candles[start:end]

    if not window:
        deepest_low = swing.swing_high_price
        close_at_end = swing.swing_high_price
    else:
        deepest_low = min(c.low_price for c in window)
        close_at_end = window[-1].close_price

    touched: dict[str, bool] = {
        label: deepest_low <= price for label, price in level_prices.items()
    }

    if deepest_low <= swing.swing_low_price:
        deepest_retrace_label = "FULL_RETRACE"
    else:
        deepest_retrace_label = "NO_TOUCH"
        for label in reversed(RETRACE_LABEL_ORDER):
            if touched[label]:
                deepest_retrace_label = label
                break

    bounce_after_touch_pct: Decimal | None = None
    if any(touched.values()) and deepest_low > Decimal("0"):
        bounce_after_touch_pct = (close_at_end - deepest_low) / deepest_low * Decimal("100")

    return RetraceEvent(
        symbol=symbol,
        interval_code=interval_code,
        swing_low_price=swing.swing_low_price,
        swing_high_price=swing.swing_high_price,
        impulse_pct=swing.impulse_pct,
        swing_high_ts=swing.swing_high_ts.isoformat(),
        deepest_low_price=deepest_low,
        deepest_retrace_label=deepest_retrace_label,
        retrace_0_382_touched=touched["retrace_0_382"],
        retrace_0_500_touched=touched["retrace_0_500"],
        retrace_0_618_touched=touched["retrace_0_618"],
        retrace_0_786_touched=touched["retrace_0_786"],
        bounce_after_touch_pct=bounce_after_touch_pct,
    )


def _avg(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def aggregate_profile(
    symbol: str,
    interval_code: str,
    events: list[RetraceEvent],
    *,
    min_sample: int,
    avg_impulse_pct: Decimal,
) -> SymbolReentryProfile:
    n = len(events)

    touch_count_0_382 = sum(1 for e in events if e.retrace_0_382_touched)
    touch_count_0_500 = sum(1 for e in events if e.retrace_0_500_touched)
    touch_count_0_618 = sum(1 for e in events if e.retrace_0_618_touched)
    touch_count_0_786 = sum(1 for e in events if e.retrace_0_786_touched)

    # preferred = the retrace level where price most often reversed (deepest_retrace_label)
    deepest_counts: dict[str, int] = {lbl: 0 for lbl in RETRACE_LABEL_ORDER}
    for e in events:
        if e.deepest_retrace_label in deepest_counts:
            deepest_counts[e.deepest_retrace_label] += 1
    preferred_retrace_level = max(
        RETRACE_LABEL_ORDER,
        key=lambda lbl: (deepest_counts[lbl], -RETRACE_LABEL_ORDER.index(lbl)),
    )

    def _bounce_values(attr: str) -> list[Decimal]:
        return [
            e.bounce_after_touch_pct
            for e in events
            if getattr(e, attr) and e.bounce_after_touch_pct is not None
        ]

    avg_bounce_after_0_382 = _avg(_bounce_values("retrace_0_382_touched"))
    avg_bounce_after_0_500 = _avg(_bounce_values("retrace_0_500_touched"))
    avg_bounce_after_0_618 = _avg(_bounce_values("retrace_0_618_touched"))

    missed_by_values: list[Decimal] = []
    for e in events:
        if not e.retrace_0_500_touched:
            leg = e.swing_high_price - e.swing_low_price
            r500_price = e.swing_high_price - leg * Decimal("0.500")
            if r500_price > Decimal("0") and e.deepest_low_price > r500_price:
                missed_by_values.append(
                    (e.deepest_low_price - r500_price) / r500_price * Decimal("100")
                )
    missed_by_pct_main = _avg(missed_by_values)

    # wick = price only reached r382 zone (shallowest level, didn't continue deeper)
    wick_count = sum(1 for e in events if e.deepest_retrace_label == "retrace_0_382")
    wickiness_score = Decimal(wick_count) / Decimal(n) if n > 0 else Decimal("0")

    respect_count = sum(1 for e in events if e.deepest_retrace_label in RESPECT_LABELS)
    fib_respect_score = Decimal(respect_count) / Decimal(n) if n > 0 else Decimal("0")

    volatility_score = min(avg_impulse_pct / Decimal("100"), Decimal("1"))

    if n < min_sample:
        classification = "INSUFFICIENT_SAMPLE"
    elif preferred_retrace_level in ("retrace_0_618", "retrace_0_786"):
        classification = "DEEP_RETRACE"
    elif wickiness_score >= Decimal("0.5"):
        classification = "WICK_HEAVY"
    elif fib_respect_score >= Decimal("0.6") and preferred_retrace_level in (
        "retrace_0_382",
        "retrace_0_500",
    ):
        classification = "CLEAN_FIB_RESPECT"
    elif preferred_retrace_level == "retrace_0_382":
        classification = "BREAKOUT_RETEST"
    else:
        classification = "INCOHERENT"

    return SymbolReentryProfile(
        symbol=symbol,
        interval_code=interval_code,
        sample_size=n,
        touch_count_0_382=touch_count_0_382,
        touch_count_0_500=touch_count_0_500,
        touch_count_0_618=touch_count_0_618,
        touch_count_0_786=touch_count_0_786,
        preferred_retrace_level=preferred_retrace_level,
        avg_bounce_after_0_382=avg_bounce_after_0_382,
        avg_bounce_after_0_500=avg_bounce_after_0_500,
        avg_bounce_after_0_618=avg_bounce_after_0_618,
        missed_by_pct_main=missed_by_pct_main,
        wickiness_score=wickiness_score,
        volatility_score=volatility_score,
        fib_respect_score=fib_respect_score,
        classification=classification,
    )


def run_symbol_backtest(
    symbol: str,
    candles: list[BacktestCandle],
    *,
    interval_code: str,
    pivot_span: int,
    min_impulse_pct: Decimal,
    lookforward_bars: int,
    min_sample: int,
) -> tuple[SymbolReentryProfile | None, list[RetraceEvent]]:
    swings = detect_impulse_swings(
        candles,
        pivot_span=pivot_span,
        min_impulse_pct=min_impulse_pct,
    )
    if not swings:
        return None, []
    events = [
        classify_retrace_event(
            symbol, interval_code, swing, candles, lookforward_bars=lookforward_bars
        )
        for swing in swings
    ]
    avg_impulse = _avg([e.impulse_pct for e in events]) or Decimal("0")
    profile = aggregate_profile(
        symbol,
        interval_code,
        events,
        min_sample=min_sample,
        avg_impulse_pct=avg_impulse,
    )
    return profile, events


def _table_columns(conn: Any, table_name: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = %s",
            (table_name,),
        )
        return {str(row["column_name"]) for row in cur.fetchall()}


def _to_dec(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def fetch_candles_for_symbols(
    conn: Any,
    *,
    symbols: list[str],
    venue: str,
    interval_code: str,
    lookback_candles: int,
) -> dict[str, list[BacktestCandle]]:
    if not symbols:
        return {}
    asset_cols = _table_columns(conn, "asset")
    where: list[str] = []
    params: list[Any] = []
    if "is_enabled" in asset_cols:
        where.append("is_enabled = 1")
    where.append(
        "UPPER(symbol) IN (" + ",".join(["%s"] * len(symbols)) + ")"
    )
    params.extend(s.upper() for s in symbols)
    sql = "SELECT asset_id, symbol FROM asset"
    if where:
        sql += " WHERE " + " AND ".join(where)
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        asset_rows = list(cur.fetchall())
    if not asset_rows:
        return {}

    asset_ids = [int(row["asset_id"]) for row in asset_rows]
    symbol_by_id = {int(row["asset_id"]): str(row["symbol"]).upper() for row in asset_rows}
    placeholders = ",".join(["%s"] * len(asset_ids))
    candle_sql = f"""
        SELECT c.asset_id, c.open_ts_utc, c.open_price, c.high_price, c.low_price, c.close_price
        FROM obs_market_candle c
        WHERE c.venue = %s
          AND c.interval_code = %s
          AND c.asset_id IN ({placeholders})
        ORDER BY c.asset_id ASC, c.open_ts_utc ASC
    """
    candle_params: list[Any] = [venue, interval_code, *asset_ids]
    with conn.cursor() as cur:
        cur.execute(candle_sql, tuple(candle_params))
        rows = list(cur.fetchall())

    grouped: dict[str, list[BacktestCandle]] = {}
    for row in rows:
        symbol = symbol_by_id.get(int(row["asset_id"]))
        if symbol is None:
            continue
        ts = row["open_ts_utc"]
        if hasattr(ts, "tzinfo"):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            else:
                ts = ts.astimezone(UTC)
        else:
            ts = datetime.fromisoformat(str(ts)).replace(tzinfo=UTC)
        grouped.setdefault(symbol, []).append(
            BacktestCandle(
                ts_utc=ts,
                open_price=_to_dec(row["open_price"]),
                high_price=_to_dec(row["high_price"]),
                low_price=_to_dec(row["low_price"]),
                close_price=_to_dec(row["close_price"]),
            )
        )

    # trim to lookback_candles most recent per symbol
    return {
        sym: candles[-lookback_candles:]
        for sym, candles in grouped.items()
    }


def _fmt_dec(v: Decimal | None, places: int = 6) -> str:
    if v is None:
        return ""
    q = Decimal("1").scaleb(-places)
    return format(v.quantize(q), "f")


def build_profile_row(profile: SymbolReentryProfile) -> dict[str, Any]:
    return {
        "symbol": profile.symbol,
        "interval_code": profile.interval_code,
        "sample_size": profile.sample_size,
        "preferred_retrace_level": profile.preferred_retrace_level,
        "touch_count_0_382": profile.touch_count_0_382,
        "touch_count_0_500": profile.touch_count_0_500,
        "touch_count_0_618": profile.touch_count_0_618,
        "touch_count_0_786": profile.touch_count_0_786,
        "avg_bounce_after_0_382": _fmt_dec(profile.avg_bounce_after_0_382),
        "avg_bounce_after_0_500": _fmt_dec(profile.avg_bounce_after_0_500),
        "avg_bounce_after_0_618": _fmt_dec(profile.avg_bounce_after_0_618),
        "missed_by_pct_main": _fmt_dec(profile.missed_by_pct_main),
        "wickiness_score": _fmt_dec(profile.wickiness_score),
        "volatility_score": _fmt_dec(profile.volatility_score),
        "fib_respect_score": _fmt_dec(profile.fib_respect_score),
        "classification": profile.classification,
    }


def build_event_dict(event: RetraceEvent) -> dict[str, Any]:
    return {
        "symbol": event.symbol,
        "interval_code": event.interval_code,
        "swing_low_price": _fmt_dec(event.swing_low_price, 8),
        "swing_high_price": _fmt_dec(event.swing_high_price, 8),
        "impulse_pct": _fmt_dec(event.impulse_pct, 4),
        "swing_high_ts": event.swing_high_ts,
        "deepest_low_price": _fmt_dec(event.deepest_low_price, 8),
        "deepest_retrace_label": event.deepest_retrace_label,
        "retrace_0_382_touched": event.retrace_0_382_touched,
        "retrace_0_500_touched": event.retrace_0_500_touched,
        "retrace_0_618_touched": event.retrace_0_618_touched,
        "retrace_0_786_touched": event.retrace_0_786_touched,
        "bounce_after_touch_pct": _fmt_dec(event.bounce_after_touch_pct, 4),
    }


def build_manifest(
    profiles: list[SymbolReentryProfile],
    *,
    run_ts: str,
    venue: str,
    interval_code: str,
    lookback_candles: int,
    pivot_span: int,
    min_impulse_pct: str,
    lookforward_bars: int,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "run_ts": run_ts,
        "broker_writes": 0,
        "order_submission": 0,
        "broker_calls": 0,
        "executor": "none",
        "db_writes": 0,
        "db_reads": "candle_read_only",
        "symbols_processed": len(profiles),
        "venue": venue,
        "interval_code": interval_code,
        "lookback_candles": lookback_candles,
        "pivot_span": pivot_span,
        "min_impulse_pct": min_impulse_pct,
        "lookforward_bars": lookforward_bars,
    }


def write_outputs(
    profiles: list[SymbolReentryProfile],
    events_by_symbol: dict[str, list[RetraceEvent]],
    output_dir: Path,
    run_ts: str,
    venue: str,
    interval_code: str,
    lookback_candles: int,
    pivot_span: int,
    min_impulse_pct: Decimal,
    lookforward_bars: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    profile_path = output_dir / "profile_summary_v1.csv"
    rows = [build_profile_row(p) for p in profiles]
    if rows:
        with profile_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    events_path = output_dir / "profile_events_v1.jsonl"
    with events_path.open("w", encoding="utf-8") as f:
        for sym_events in events_by_symbol.values():
            for event in sym_events:
                f.write(json.dumps(build_event_dict(event), ensure_ascii=False) + "\n")

    manifest_path = output_dir / "manifest_v1.json"
    manifest = build_manifest(
        profiles,
        run_ts=run_ts,
        venue=venue,
        interval_code=interval_code,
        lookback_candles=lookback_candles,
        pivot_span=pivot_span,
        min_impulse_pct=str(min_impulse_pct),
        lookforward_bars=lookforward_bars,
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Symbol re-entry profile backtest v1. "
            "Read-only DB candle scan. No broker calls, no order writes."
        )
    )
    parser.add_argument(
        "--symbols",
        default=None,
        metavar="SYM",
        help="Comma-separated symbol list, e.g. WLD,FET,ONDO. Default: all enabled assets.",
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument(
        "--lookback-candles", type=int, default=DEFAULT_LOOKBACK_CANDLES
    )
    parser.add_argument("--pivot-span", type=int, default=DEFAULT_PIVOT_SPAN)
    parser.add_argument(
        "--min-impulse-pct",
        type=float,
        default=float(DEFAULT_MIN_IMPULSE_PCT),
        metavar="PCT",
    )
    parser.add_argument(
        "--lookforward-bars", type=int, default=DEFAULT_LOOKFORWARD_BARS
    )
    parser.add_argument(
        "--min-sample", type=int, default=DEFAULT_MIN_SAMPLE
    )
    parser.add_argument(
        "--output",
        choices=("summary", "none"),
        default="summary",
    )
    parser.add_argument(
        "--write-files",
        action="store_true",
        default=False,
        help=f"Write CSV/JSONL/JSON outputs to --output-dir (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        metavar="DIR",
    )
    return parser.parse_args()


def _parse_symbols(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [s.strip().upper() for s in value.split(",") if s.strip()]
    return sorted(dict.fromkeys(items)) or None


def print_summary(profiles: list[SymbolReentryProfile]) -> None:
    print(f"report={REPORT_NAME}")
    print(f"version={REPORT_VERSION}")
    print(f"broker_writes=0")
    print(f"order_submission=0")
    print(f"broker_calls=0")
    print(f"executor=none")
    print(f"symbols_processed={len(profiles)}")
    for p in sorted(profiles, key=lambda x: x.symbol):
        print(
            f"{p.symbol}: classification={p.classification}"
            f" preferred={p.preferred_retrace_level}"
            f" sample={p.sample_size}"
            f" fib_respect={_fmt_dec(p.fib_respect_score, 3)}"
            f" wickiness={_fmt_dec(p.wickiness_score, 3)}"
        )


def main() -> int:
    args = parse_args()
    symbols = _parse_symbols(args.symbols)
    min_impulse_pct = Decimal(str(args.min_impulse_pct))

    try:
        conn = get_db_connection()
    except Exception as exc:
        print(f"[error] DB connection failed: {exc}", file=sys.stderr)
        return 1

    try:
        candles_by_symbol = fetch_candles_for_symbols(
            conn,
            symbols=symbols or [],
            venue=args.venue,
            interval_code=args.interval,
            lookback_candles=args.lookback_candles,
        )
        if not candles_by_symbol and symbols:
            print(
                f"[warn] No candle data found for symbols: {symbols}",
                file=sys.stderr,
            )
        elif not candles_by_symbol and not symbols:
            print("[warn] No candle data found in DB.", file=sys.stderr)
    except Exception as exc:
        print(f"[error] Candle fetch failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    profiles: list[SymbolReentryProfile] = []
    events_by_symbol: dict[str, list[RetraceEvent]] = {}

    for sym, candles in sorted(candles_by_symbol.items()):
        profile, events = run_symbol_backtest(
            sym,
            candles,
            interval_code=args.interval,
            pivot_span=args.pivot_span,
            min_impulse_pct=min_impulse_pct,
            lookforward_bars=args.lookforward_bars,
            min_sample=args.min_sample,
        )
        if profile is not None:
            profiles.append(profile)
        if events:
            events_by_symbol[sym] = events

    run_ts = datetime.now(UTC).isoformat()

    if args.write_files:
        write_outputs(
            profiles,
            events_by_symbol,
            Path(args.output_dir),
            run_ts=run_ts,
            venue=args.venue,
            interval_code=args.interval,
            lookback_candles=args.lookback_candles,
            pivot_span=args.pivot_span,
            min_impulse_pct=min_impulse_pct,
            lookforward_bars=args.lookforward_bars,
        )

    if args.output == "summary":
        print_summary(profiles)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
