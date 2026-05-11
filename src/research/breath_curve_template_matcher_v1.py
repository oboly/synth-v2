from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

try:
    import pymysql
except Exception:
    pymysql = None


VERSION = "0.1"

MARKERS = [
    (0.236, "FIRST_LIFT_HIGH", "HIGH"),
    (0.382, "FIRST_DIP_LOW", "LOW"),
    (0.500, "SECOND_PEAK_RETEST_HIGH", "HIGH"),
    (0.618, "SECOND_DIP_HIGHER_LOW", "LOW"),
    (0.786, "IGNITION_PRE_SPIKE", "HIGH"),
    (1.000, "MAIN_PULSE_TP_HIGH", "HIGH"),
    (1.272, "OVERSHOOT_EXTENSION_TP", "HIGH"),
]


@dataclass(frozen=True)
class Candle:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class MarkerMatch:
    ratio: float
    code: str
    kind: str
    expected_ts_utc: str
    observed_ts_utc: str | None
    observed_price: float | None
    timing_error_hours: float | None
    timing_score: float
    matched: bool


@dataclass(frozen=True)
class MatchResult:
    symbol: str
    venue: str | None
    interval_code: str | None
    anchor_ts_utc: str
    cycle_days: float
    phase_offset_days: float
    tolerance_hours: float
    template_match_score: float
    shape_score: float
    timing_score: float
    flags: dict[str, bool]
    markers: list[MarkerMatch]


def parse_dt(value: str) -> datetime:
    value = value.strip().replace("Z", "+00:00")
    if len(value) == 10:
        dt = datetime.fromisoformat(value)
    else:
        dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def env_any(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def parse_offsets(value: str) -> list[float]:
    return [float(x.strip()) for x in value.split(",") if x.strip()]


def db_connect() -> Any:
    if pymysql is None:
        raise RuntimeError("pymysql not installed. Use --csv or install pymysql.")

    if load_dotenv:
        load_dotenv()

    return pymysql.connect(
        host=env_any("SYNTH_DB_HOST", "DB_HOST", "MYSQL_HOST", default="127.0.0.1"),
        port=int(env_any("SYNTH_DB_PORT", "DB_PORT", "MYSQL_PORT", default="3306")),
        user=env_any("SYNTH_DB_USER", "DB_USER", "MYSQL_USER", default="root"),
        password=env_any("SYNTH_DB_PASSWORD", "DB_PASSWORD", "MYSQL_PASSWORD", default=""),
        database=env_any("SYNTH_DB_NAME", "DB_NAME", "MYSQL_DATABASE", default="synth"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def table_cols(conn: Any, table_name: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
            """,
            (table_name,),
        )
        return {row["COLUMN_NAME"] for row in cur.fetchall()}


def choose(cols: set[str], options: list[str], required: bool = True) -> str | None:
    for option in options:
        if option in cols:
            return option
    if required:
        raise RuntimeError(f"Missing expected column. Tried: {options}")
    return None


def resolve_asset_id(conn: Any, symbol: str) -> int:
    cols = table_cols(conn, "asset")
    id_col = choose(cols, ["asset_id", "id"])
    symbol_col = choose(cols, ["symbol", "asset_code", "code", "base_symbol", "ticker"])

    candidates = sorted({
        symbol,
        symbol.upper(),
        symbol.replace("-EUR", "").upper(),
        symbol.replace("/EUR", "").upper(),
        symbol.replace("USDT", "").upper(),
    })

    placeholders = ",".join(["%s"] * len(candidates))
    sql = f"SELECT `{id_col}` AS asset_id FROM asset WHERE `{symbol_col}` IN ({placeholders}) LIMIT 1"

    with conn.cursor() as cur:
        cur.execute(sql, tuple(candidates))
        row = cur.fetchone()

    if not row:
        raise RuntimeError(f"Could not resolve asset_id for symbol={symbol}. Try --asset-id.")

    return int(row["asset_id"])


def load_db(symbol: str, asset_id: int | None, venue: str, interval_code: str, start: datetime, end: datetime) -> list[Candle]:
    conn = db_connect()
    try:
        cols = table_cols(conn, "obs_market_candle")

        asset_col = choose(cols, ["asset_id"])
        ts_col = choose(cols, ["open_ts_utc", "ts_utc", "timestamp_utc"])
        open_col = choose(cols, ["open"])
        high_col = choose(cols, ["high"])
        low_col = choose(cols, ["low"])
        close_col = choose(cols, ["close"])
        venue_col = choose(cols, ["venue"], required=False)
        interval_col = choose(cols, ["interval_code", "timeframe"], required=False)
        volume_col = choose(cols, ["volume_quote_eur", "volume_base", "quote_volume", "volume"], required=False)

        aid = asset_id if asset_id is not None else resolve_asset_id(conn, symbol)

        where = [f"`{asset_col}` = %s", f"`{ts_col}` >= %s", f"`{ts_col}` <= %s"]
        params: list[Any] = [aid, iso(start), iso(end)]

        if venue_col:
            where.append(f"`{venue_col}` = %s")
            params.append(venue)

        if interval_col:
            where.append(f"`{interval_col}` = %s")
            params.append(interval_code)

        volume_expr = f"`{volume_col}`" if volume_col else "0"

        sql = f"""
            SELECT
                `{ts_col}` AS ts,
                `{open_col}` AS open_price,
                `{high_col}` AS high_price,
                `{low_col}` AS low_price,
                `{close_col}` AS close_price,
                {volume_expr} AS volume_value
            FROM obs_market_candle
            WHERE {' AND '.join(where)}
            ORDER BY `{ts_col}` ASC
        """

        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()

        out: list[Candle] = []
        for row in rows:
            ts = row["ts"]
            if isinstance(ts, str):
                dt = parse_dt(ts)
            else:
                dt = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)

            out.append(Candle(
                ts=dt,
                open=float(row["open_price"]),
                high=float(row["high_price"]),
                low=float(row["low_price"]),
                close=float(row["close_price"]),
                volume=float(row["volume_value"] or 0.0),
            ))

        return out
    finally:
        conn.close()


def load_csv(path: str) -> list[Candle]:
    out: list[Candle] = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ts = row.get("open_ts_utc") or row.get("timestamp") or row.get("ts") or row.get("time")
            if not ts:
                raise RuntimeError("CSV requires open_ts_utc, timestamp, ts, or time.")
            vol = row.get("volume_quote_eur") or row.get("volume_base") or row.get("volume") or "0"
            out.append(Candle(
                ts=parse_dt(ts),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(vol or 0.0),
            ))
    return sorted(out, key=lambda c: c.ts)


def find_marker(candles: list[Candle], ratio: float, code: str, kind: str, expected: datetime, tolerance_hours: float) -> MarkerMatch:
    start = expected - timedelta(hours=tolerance_hours)
    end = expected + timedelta(hours=tolerance_hours)
    window = [c for c in candles if start <= c.ts <= end]

    if not window:
        return MarkerMatch(ratio, code, kind, iso(expected), None, None, None, 0.0, False)

    if kind == "LOW":
        chosen = min(window, key=lambda c: c.low)
        observed_price = chosen.low
    else:
        chosen = max(window, key=lambda c: c.high)
        observed_price = chosen.high

    err = abs((chosen.ts - expected).total_seconds()) / 3600.0
    score = max(0.0, 1.0 - (err / max(tolerance_hours, 1.0)))

    return MarkerMatch(
        ratio=ratio,
        code=code,
        kind=kind,
        expected_ts_utc=iso(expected),
        observed_ts_utc=iso(chosen.ts),
        observed_price=observed_price,
        timing_error_hours=round(err, 3),
        timing_score=round(score, 4),
        matched=True,
    )


def get_price(markers: list[MarkerMatch], code: str) -> float | None:
    for marker in markers:
        if marker.code == code and marker.matched:
            return marker.observed_price
    return None


def gt(a: float | None, b: float | None, tolerance_pct: float = 0.0) -> bool:
    return a is not None and b is not None and a > b * (1.0 - tolerance_pct)


def lt(a: float | None, b: float | None, tolerance_pct: float = 0.0) -> bool:
    return a is not None and b is not None and a < b * (1.0 + tolerance_pct)


def shape_score(candles: list[Candle], anchor: datetime, markers: list[MarkerMatch]) -> tuple[float, dict[str, bool]]:
    anchor_candles = [c for c in candles if c.ts <= anchor]
    anchor_price = anchor_candles[-1].close if anchor_candles else candles[0].close

    first_high = get_price(markers, "FIRST_LIFT_HIGH")
    first_low = get_price(markers, "FIRST_DIP_LOW")
    second_high = get_price(markers, "SECOND_PEAK_RETEST_HIGH")
    second_low = get_price(markers, "SECOND_DIP_HIGHER_LOW")
    ignition = get_price(markers, "IGNITION_PRE_SPIKE")
    pulse = get_price(markers, "MAIN_PULSE_TP_HIGH")
    overshoot = get_price(markers, "OVERSHOOT_EXTENSION_TP")

    flags = {
        "first_lift_above_anchor": gt(first_high, anchor_price),
        "first_dip_below_first_lift": lt(first_low, first_high),
        "second_peak_above_first_dip": gt(second_high, first_low),
        "second_peak_retests_first_lift": gt(second_high, first_high, 0.025),
        "second_dip_below_second_peak": lt(second_low, second_high),
        "second_dip_higher_than_first_dip": gt(second_low, first_low, 0.010),
        "ignition_above_second_dip": gt(ignition, second_low),
        "pulse_above_ignition": gt(pulse, ignition),
        "pulse_above_second_peak": gt(pulse, second_high),
        "overshoot_above_pulse": gt(overshoot, pulse),
    }

    core = [
        "first_lift_above_anchor",
        "first_dip_below_first_lift",
        "second_peak_above_first_dip",
        "second_dip_below_second_peak",
        "second_dip_higher_than_first_dip",
        "ignition_above_second_dip",
        "pulse_above_ignition",
        "pulse_above_second_peak",
    ]

    return round(sum(1 for k in core if flags[k]) / len(core), 4), flags


def match(candles: list[Candle], symbol: str, venue: str | None, interval_code: str | None, anchor: datetime, cycle_days: float, offset_days: float, tolerance_hours: float) -> MatchResult:
    markers: list[MarkerMatch] = []

    for ratio, code, kind in MARKERS:
        expected = anchor + timedelta(days=(cycle_days * ratio) + offset_days)
        markers.append(find_marker(candles, ratio, code, kind, expected, tolerance_hours))

    s_score, flags = shape_score(candles, anchor, markers)
    t_score = round(sum(m.timing_score for m in markers) / len(markers), 4)
    total = round((0.60 * s_score) + (0.40 * t_score), 4)

    return MatchResult(
        symbol=symbol,
        venue=venue,
        interval_code=interval_code,
        anchor_ts_utc=iso(anchor),
        cycle_days=cycle_days,
        phase_offset_days=offset_days,
        tolerance_hours=tolerance_hours,
        template_match_score=total,
        shape_score=s_score,
        timing_score=t_score,
        flags=flags,
        markers=markers,
    )


def print_result(result: MatchResult) -> None:
    print(f"symbol={result.symbol} venue={result.venue} interval={result.interval_code}")
    print(f"anchor={result.anchor_ts_utc} cycle_days={result.cycle_days} offset_days={result.phase_offset_days}")
    print(f"template_match_score={result.template_match_score:.4f}")
    print(f"shape_score={result.shape_score:.4f} timing_score={result.timing_score:.4f}")
    print("")
    print("flags:")
    for key, value in result.flags.items():
        print(f"  {key}={value}")
    print("")
    print("markers:")
    for marker in result.markers:
        price = "None" if marker.observed_price is None else f"{marker.observed_price:.8f}"
        error = "None" if marker.timing_error_hours is None else f"{marker.timing_error_hours:.2f}h"
        print(
            f"  {marker.ratio:.3f} {marker.code:26s} "
            f"expected={marker.expected_ts_utc} observed={marker.observed_ts_utc} "
            f"price={price} error={error} score={marker.timing_score:.4f}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only 21-day breath curve template matcher.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", dest="interval_code", default="1d")
    parser.add_argument("--anchor-date", required=True)
    parser.add_argument("--cycle-days", type=float, default=21.0)
    parser.add_argument("--offsets", default="-10.5,-7,-5,-3,0,3,5,7,10.5")
    parser.add_argument("--tolerance-hours", type=float, default=36.0)
    parser.add_argument("--csv", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    anchor = parse_dt(args.anchor_date)
    offsets = parse_offsets(args.offsets)

    query_start = anchor + timedelta(days=min(offsets)) - timedelta(hours=args.tolerance_hours + 48)
    query_end = anchor + timedelta(days=args.cycle_days * 1.272 + max(offsets)) + timedelta(hours=args.tolerance_hours + 48)

    if args.csv:
        candles = [c for c in load_csv(args.csv) if query_start <= c.ts <= query_end]
    else:
        candles = load_db(args.symbol, args.asset_id, args.venue, args.interval_code, query_start, query_end)

    if len(candles) < 5:
        raise RuntimeError(f"Not enough candles loaded: {len(candles)}")

    results = [
        match(candles, args.symbol, args.venue, args.interval_code, anchor, args.cycle_days, offset, args.tolerance_hours)
        for offset in offsets
    ]

    best = max(results, key=lambda r: r.template_match_score)

    if args.json:
        print(json.dumps({
            "matcher": "breath_curve_template_matcher_v1",
            "version": VERSION,
            "best": asdict(best),
            "all_offsets": [asdict(r) for r in results],
        }, indent=2, sort_keys=True))
    else:
        print(f"matcher=breath_curve_template_matcher_v1 version={VERSION}")
        print_result(best)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
