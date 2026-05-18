from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from src.common.db import get_connection


INTERVAL_SECONDS: dict[str, int] = {
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}

DEFAULT_LOOKBACK_DAYS: dict[str, int] = {
    "15m": 7,
    "1h": 30,
    "4h": 90,
    "1d": 365,
}

DEFAULT_MIN_AVG_VOLUME_QUOTE_EUR: dict[str, Decimal] = {
    "15m": Decimal("125"),
    "1h": Decimal("500"),
    "4h": Decimal("2000"),
    "1d": Decimal("10000"),
}


@dataclass(frozen=True)
class CandlePoint:
    asset_id: int
    open_ts_utc: datetime
    close_ts_utc: datetime
    volume_quote_eur: Decimal


@dataclass(frozen=True)
class SparseCandleDiagnostic:
    asset_id: int
    symbol: str
    venue: str
    interval_code: str
    classification: str
    severity_score: Decimal
    window_start_utc: datetime
    window_end_utc: datetime
    first_open_ts_utc: datetime | None
    latest_open_ts_utc: datetime | None
    latest_close_ts_utc: datetime | None
    expected_rows: int
    observed_rows: int
    missing_candles_total: int
    gap_events: int
    small_gap_events: int
    large_gap_events: int
    recent_lag_intervals: int | None
    coverage_ratio: Decimal
    gap_density: Decimal
    avg_volume_quote_eur: Decimal
    median_volume_quote_eur: Decimal
    total_volume_quote_eur: Decimal
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose sparse / missing candle patterns by asset and interval."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="1h", choices=sorted(INTERVAL_SECONDS))
    parser.add_argument("--asset", action="append", default=None)
    parser.add_argument("--from-ts", default=None)
    parser.add_argument("--to-ts", default=None)
    parser.add_argument("--lookback-days", type=int, default=None)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument(
        "--min-avg-volume-quote-eur",
        default=None,
        help="Liquidity threshold used to distinguish DATA_GAP from NO_TRADE_GAP / ILLIQUID_MARKET.",
    )
    parser.add_argument(
        "--classification",
        default=None,
        choices=[
            "HEALTHY",
            "DATA_GAP",
            "NO_TRADE_GAP",
            "ILLIQUID_MARKET",
            "SHORT_HISTORY",
            "NO_DATA",
        ],
    )
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC).replace(tzinfo=None)
    return parsed.astimezone(UTC).replace(tzinfo=None)


def to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quant(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"))


def fetch_default_window_end(
    conn,
    *,
    venue: str,
    interval_code: str,
) -> datetime:
    sql = """
    SELECT MAX(close_ts_utc) AS max_close_ts_utc
    FROM obs_market_candle
    WHERE venue = %s
      AND interval_code = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, [venue, interval_code])
        row = cur.fetchone()

    max_close = row["max_close_ts_utc"] if isinstance(row, dict) else row[0]
    if max_close is None:
        return datetime.now(UTC).replace(tzinfo=None)

    return max_close


def fetch_assets(
    conn,
    *,
    wanted_symbols: set[str] | None,
) -> list[dict[str, Any]]:
    clauses = ["is_enabled = 1"]
    params: list[Any] = []

    if wanted_symbols:
        clauses.append(f"symbol IN ({','.join(['%s'] * len(wanted_symbols))})")
        params.extend(sorted(wanted_symbols))

    sql = f"""
    SELECT asset_id, symbol
    FROM asset
    WHERE {" AND ".join(clauses)}
    ORDER BY asset_id
    """

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from asset query")
        out.append(row)
    return out


def fetch_candles(
    conn,
    *,
    venue: str,
    interval_code: str,
    window_start_utc: datetime,
    window_end_utc: datetime,
    asset_ids: list[int],
) -> dict[int, list[CandlePoint]]:
    if not asset_ids:
        return {}

    sql = f"""
    SELECT
        asset_id,
        open_ts_utc,
        close_ts_utc,
        volume_quote_eur
    FROM obs_market_candle
    WHERE venue = %s
      AND interval_code = %s
      AND close_ts_utc > %s
      AND close_ts_utc <= %s
      AND asset_id IN ({','.join(['%s'] * len(asset_ids))})
    ORDER BY asset_id, open_ts_utc
    """

    params: list[Any] = [
        venue,
        interval_code,
        window_start_utc,
        window_end_utc,
        *asset_ids,
    ]

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    grouped: dict[int, list[CandlePoint]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from candle query")

        grouped[int(row["asset_id"])].append(
            CandlePoint(
                asset_id=int(row["asset_id"]),
                open_ts_utc=row["open_ts_utc"],
                close_ts_utc=row["close_ts_utc"],
                volume_quote_eur=to_decimal(row.get("volume_quote_eur")),
            )
        )

    return grouped


def classify(
    *,
    observed_rows: int,
    expected_rows: int,
    missing_candles_total: int,
    gap_events: int,
    large_gap_events: int,
    recent_lag_intervals: int | None,
    coverage_ratio: Decimal,
    gap_density: Decimal,
    avg_volume_quote_eur: Decimal,
    min_avg_volume_quote_eur: Decimal,
) -> tuple[str, Decimal, str]:
    lag = recent_lag_intervals if recent_lag_intervals is not None else 999999

    severity = Decimal("0")
    severity += (Decimal("1") - coverage_ratio) * Decimal("60")
    severity += min(Decimal(str(gap_density)) * Decimal("100"), Decimal("25"))
    severity += min(Decimal(str(large_gap_events)) * Decimal("4"), Decimal("15"))
    severity += min(Decimal(str(lag)) * Decimal("2"), Decimal("20"))
    severity = max(Decimal("0"), min(Decimal("100"), severity))

    if observed_rows == 0:
        return (
            "NO_DATA",
            quant(Decimal("100")),
            "no observed candles in diagnostic window",
        )

    if (
        missing_candles_total == 0
        and gap_events == 0
        and lag <= 1
        and coverage_ratio >= Decimal("0.98")
    ):
        return (
            "HEALTHY",
            quant(severity),
            "continuous candles in diagnostic window",
        )

    if (
        coverage_ratio < Decimal("0.75")
        and gap_events == 0
        and large_gap_events == 0
        and lag <= 1
    ):
        return (
            "SHORT_HISTORY",
            quant(severity),
            "limited observed history inside diagnostic window without internal gaps",
        )

    if (
        coverage_ratio < Decimal("0.75")
        or gap_density >= Decimal("0.10")
        or (lag >= 6 and avg_volume_quote_eur < min_avg_volume_quote_eur)
    ):
        return (
            "ILLIQUID_MARKET",
            quant(severity),
            "sparse coverage / frequent gaps consistent with weak market activity",
        )

    if (
        avg_volume_quote_eur >= min_avg_volume_quote_eur
        and (large_gap_events > 0 or coverage_ratio < Decimal("0.95") or lag >= 2)
    ):
        return (
            "DATA_GAP",
            quant(severity),
            "missing candles despite meaningful observed quote volume",
        )

    return (
        "NO_TRADE_GAP",
        quant(severity),
        "isolated missing candles likely caused by no trades in those intervals",
    )


def build_diagnostic(
    *,
    asset: dict[str, Any],
    venue: str,
    interval_code: str,
    window_start_utc: datetime,
    window_end_utc: datetime,
    expected_rows: int,
    candles: list[CandlePoint],
    min_avg_volume_quote_eur: Decimal,
) -> SparseCandleDiagnostic:
    interval_seconds = INTERVAL_SECONDS[interval_code]

    if not candles:
        classification, severity, reason = classify(
            observed_rows=0,
            expected_rows=expected_rows,
            missing_candles_total=expected_rows,
            gap_events=0,
            large_gap_events=0,
            recent_lag_intervals=None,
            coverage_ratio=Decimal("0"),
            gap_density=Decimal("1"),
            avg_volume_quote_eur=Decimal("0"),
            min_avg_volume_quote_eur=min_avg_volume_quote_eur,
        )
        return SparseCandleDiagnostic(
            asset_id=int(asset["asset_id"]),
            symbol=str(asset["symbol"]),
            venue=venue,
            interval_code=interval_code,
            classification=classification,
            severity_score=severity,
            window_start_utc=window_start_utc,
            window_end_utc=window_end_utc,
            first_open_ts_utc=None,
            latest_open_ts_utc=None,
            latest_close_ts_utc=None,
            expected_rows=expected_rows,
            observed_rows=0,
            missing_candles_total=expected_rows,
            gap_events=0,
            small_gap_events=0,
            large_gap_events=0,
            recent_lag_intervals=None,
            coverage_ratio=Decimal("0"),
            gap_density=Decimal("1"),
            avg_volume_quote_eur=Decimal("0"),
            median_volume_quote_eur=Decimal("0"),
            total_volume_quote_eur=Decimal("0"),
            reason=reason,
        )

    gap_events = 0
    small_gap_events = 0
    large_gap_events = 0
    missing_candles_total = 0

    for prev, current in zip(candles[:-1], candles[1:]):
        diff_seconds = int((current.open_ts_utc - prev.open_ts_utc).total_seconds())
        diff_intervals = diff_seconds // interval_seconds

        if diff_intervals > 1:
            gap_events += 1
            missing = diff_intervals - 1
            missing_candles_total += missing

            if diff_intervals in (2, 3):
                small_gap_events += 1

            if interval_code == "1h" and diff_intervals >= 6:
                large_gap_events += 1
            elif interval_code == "4h" and diff_intervals >= 6:
                large_gap_events += 1
            elif interval_code == "1d" and diff_intervals >= 7:
                large_gap_events += 1

    observed_rows = len(candles)
    coverage_ratio = (
        Decimal(observed_rows) / Decimal(expected_rows)
        if expected_rows > 0
        else Decimal("0")
    )
    coverage_ratio = min(Decimal("1"), coverage_ratio)

    gap_density = (
        Decimal(missing_candles_total) / Decimal(expected_rows)
        if expected_rows > 0
        else Decimal("0")
    )

    volumes = [c.volume_quote_eur for c in candles]
    total_volume = sum(volumes, Decimal("0"))
    avg_volume = total_volume / Decimal(len(volumes))
    median_volume = Decimal(str(median(volumes)))

    latest_close = candles[-1].close_ts_utc
    lag_seconds = max(0, int((window_end_utc - latest_close).total_seconds()))
    recent_lag_intervals = lag_seconds // interval_seconds

    classification, severity, reason = classify(
        observed_rows=observed_rows,
        expected_rows=expected_rows,
        missing_candles_total=missing_candles_total,
        gap_events=gap_events,
        large_gap_events=large_gap_events,
        recent_lag_intervals=recent_lag_intervals,
        coverage_ratio=coverage_ratio,
        gap_density=gap_density,
        avg_volume_quote_eur=avg_volume,
        min_avg_volume_quote_eur=min_avg_volume_quote_eur,
    )

    return SparseCandleDiagnostic(
        asset_id=int(asset["asset_id"]),
        symbol=str(asset["symbol"]),
        venue=venue,
        interval_code=interval_code,
        classification=classification,
        severity_score=severity,
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
        first_open_ts_utc=candles[0].open_ts_utc,
        latest_open_ts_utc=candles[-1].open_ts_utc,
        latest_close_ts_utc=latest_close,
        expected_rows=expected_rows,
        observed_rows=observed_rows,
        missing_candles_total=missing_candles_total,
        gap_events=gap_events,
        small_gap_events=small_gap_events,
        large_gap_events=large_gap_events,
        recent_lag_intervals=recent_lag_intervals,
        coverage_ratio=quant(coverage_ratio),
        gap_density=quant(gap_density),
        avg_volume_quote_eur=quant(avg_volume),
        median_volume_quote_eur=quant(median_volume),
        total_volume_quote_eur=quant(total_volume),
        reason=reason,
    )


def print_table(rows: list[SparseCandleDiagnostic]) -> None:
    headers = [
        "symbol",
        "class",
        "sev",
        "cov",
        "obs",
        "exp",
        "miss",
        "gaps",
        "lg",
        "lag",
        "avg_vol",
        "med_vol",
        "latest_close",
        "reason",
    ]

    printable: list[list[str]] = []
    for row in rows:
        printable.append(
            [
                row.symbol,
                row.classification,
                str(row.severity_score),
                str(row.coverage_ratio),
                str(row.observed_rows),
                str(row.expected_rows),
                str(row.missing_candles_total),
                str(row.gap_events),
                str(row.large_gap_events),
                "" if row.recent_lag_intervals is None else str(row.recent_lag_intervals),
                str(row.avg_volume_quote_eur),
                str(row.median_volume_quote_eur),
                "" if row.latest_close_ts_utc is None else row.latest_close_ts_utc.isoformat(sep=" "),
                row.reason,
            ]
        )

    widths = [len(header) for header in headers]
    for row in printable:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def fmt(values: list[str]) -> str:
        return " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(values))

    print(fmt(headers))
    print("-+-".join("-" * width for width in widths))
    for row in printable:
        print(fmt(row))


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def main() -> int:
    args = parse_args()

    if args.interval not in INTERVAL_SECONDS:
        raise ValueError(f"Unsupported interval={args.interval}")

    lookback_days = args.lookback_days or DEFAULT_LOOKBACK_DAYS[args.interval]
    min_avg_volume_quote_eur = (
        Decimal(str(args.min_avg_volume_quote_eur))
        if args.min_avg_volume_quote_eur is not None
        else DEFAULT_MIN_AVG_VOLUME_QUOTE_EUR[args.interval]
    )

    wanted_symbols = {s.upper() for s in args.asset} if args.asset else None

    conn = get_connection()
    try:
        window_end_utc = (
            parse_ts(args.to_ts)
            if args.to_ts is not None
            else fetch_default_window_end(
                conn,
                venue=args.venue,
                interval_code=args.interval,
            )
        )

        window_start_utc = (
            parse_ts(args.from_ts)
            if args.from_ts is not None
            else window_end_utc - timedelta(days=lookback_days)
        )

        interval_seconds = INTERVAL_SECONDS[args.interval]
        expected_rows = max(
            1,
            int((window_end_utc - window_start_utc).total_seconds() // interval_seconds),
        )

        assets = fetch_assets(conn, wanted_symbols=wanted_symbols)
        asset_ids = [int(asset["asset_id"]) for asset in assets]

        grouped_candles = fetch_candles(
            conn,
            venue=args.venue,
            interval_code=args.interval,
            window_start_utc=window_start_utc,
            window_end_utc=window_end_utc,
            asset_ids=asset_ids,
        )

        diagnostics = [
            build_diagnostic(
                asset=asset,
                venue=args.venue,
                interval_code=args.interval,
                window_start_utc=window_start_utc,
                window_end_utc=window_end_utc,
                expected_rows=expected_rows,
                candles=grouped_candles.get(int(asset["asset_id"]), []),
                min_avg_volume_quote_eur=min_avg_volume_quote_eur,
            )
            for asset in assets
        ]

        if args.classification:
            diagnostics = [
                row for row in diagnostics
                if row.classification == args.classification
            ]

        diagnostics.sort(
            key=lambda row: (
                row.classification != "HEALTHY",
                row.severity_score,
                row.missing_candles_total,
                row.gap_events,
            ),
            reverse=True,
        )

        diagnostics = diagnostics[: args.limit]

        if args.output == "json":
            print(
                json.dumps(
                    [asdict(row) for row in diagnostics],
                    indent=2,
                    ensure_ascii=False,
                    default=json_default,
                )
            )
        else:
            print_table(diagnostics)

        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
