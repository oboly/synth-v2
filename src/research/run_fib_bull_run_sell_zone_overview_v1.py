from __future__ import annotations

"""
Synth v2 - Fibo / Elliott bull-run sell zone overview v1.

LAYER:
research-only market structure report

BOUNDARY:
Allowed:
- read market candles
- compute research-only Fibo extension sell zones
- write report artifacts under docs/research and data/research

Forbidden:
- decision_gate writes
- execution_plan writes
- execution_event writes
- capital/account/order/position writes
- broker/executor/runtime actions
"""

import argparse
import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_connection


DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL = "1d"
DEFAULT_FROM_TS = "2022-11-01 00:00:00"
DEFAULT_REPORT_PATH = "docs/research/fib_bull_run_sell_zones_overview_v1.md"
DEFAULT_CSV_PATH = "data/research/fib_bull_run_sell_zones_overview_v1.csv"

FIB_LEVELS = {
    "zone_1_618": Decimal("1.618"),
    "zone_2_000": Decimal("2.000"),
    "zone_2_618": Decimal("2.618"),
    "zone_3_618": Decimal("3.618"),
    "zone_4_236": Decimal("4.236"),
    "zone_5_000": Decimal("5.000"),
    "zone_6_854": Decimal("6.854"),
}


@dataclass(frozen=True)
class CandleRow:
    asset_id: int
    symbol: str
    open_ts_utc: datetime
    close_ts_utc: datetime
    low_price: Decimal
    high_price: Decimal
    close_price: Decimal
    volume_quote_eur: Decimal | None


@dataclass(frozen=True)
class SellZoneRow:
    asset_id: int
    symbol: str
    venue: str
    interval_code: str
    cycle_from_ts_utc: datetime
    latest_ts_utc: datetime | None
    latest_price: Decimal | None
    cycle_low_ts_utc: datetime | None
    cycle_low_price: Decimal | None
    swing_high_ts_utc: datetime | None
    swing_high_price: Decimal | None
    ath_price: Decimal | None
    conservative_zone_low: Decimal | None
    conservative_zone_high: Decimal | None
    primary_zone_low: Decimal | None
    primary_zone_high: Decimal | None
    extension_zone_low: Decimal | None
    extension_zone_high: Decimal | None
    moonbag_zone_low: Decimal | None
    moonbag_zone_high: Decimal | None
    upside_to_primary_low_pct: Decimal | None
    confidence: str
    classification: str
    notes: str


def parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC).replace(tzinfo=None)
    return parsed.astimezone(UTC).replace(tzinfo=None)


def dec(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def q(value: Decimal | None, places: str = "0.0000000001") -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal(places))


def pct(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.01"))


def fmt(value: Decimal | datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def fetch_candles(
    *,
    venue: str,
    interval_code: str,
    from_ts_utc: datetime,
) -> dict[int, list[CandleRow]]:
    sql = """
    SELECT
        a.asset_id,
        a.symbol,
        c.open_ts_utc,
        c.close_ts_utc,
        c.low_price,
        c.high_price,
        c.close_price,
        c.volume_quote_eur
    FROM asset a
    LEFT JOIN obs_market_candle c
      ON c.asset_id = a.asset_id
     AND c.venue = %s
     AND c.interval_code = %s
     AND c.close_ts_utc >= %s
    WHERE a.is_enabled = 1
    ORDER BY a.asset_id, c.close_ts_utc
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [venue, interval_code, from_ts_utc])
            rows = cur.fetchall()
    finally:
        conn.close()

    grouped: dict[int, list[CandleRow]] = {}

    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from database cursor")

        asset_id = int(row["asset_id"])
        grouped.setdefault(asset_id, [])

        if row["close_ts_utc"] is None:
            continue

        grouped[asset_id].append(
            CandleRow(
                asset_id=asset_id,
                symbol=str(row["symbol"]),
                open_ts_utc=row["open_ts_utc"],
                close_ts_utc=row["close_ts_utc"],
                low_price=dec(row["low_price"]),
                high_price=dec(row["high_price"]),
                close_price=dec(row["close_price"]),
                volume_quote_eur=(
                    dec(row["volume_quote_eur"])
                    if row["volume_quote_eur"] is not None
                    else None
                ),
            )
        )

    return grouped


def fetch_enabled_assets() -> list[dict[str, Any]]:
    sql = """
    SELECT asset_id, symbol
    FROM asset
    WHERE is_enabled = 1
    ORDER BY asset_id
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    finally:
        conn.close()

    return [dict(row) for row in rows]


def level(low: Decimal, high: Decimal, fib: Decimal) -> Decimal:
    return low + ((high - low) * fib)


def classify_zone(
    *,
    latest_price: Decimal | None,
    primary_zone_low: Decimal | None,
    extension_zone_low: Decimal | None,
    moonbag_zone_low: Decimal | None,
) -> str:
    if latest_price is None or primary_zone_low is None:
        return "NO_DATA"

    if moonbag_zone_low is not None and latest_price >= moonbag_zone_low:
        return "MOONBAG_EXTENSION_REACHED"

    if extension_zone_low is not None and latest_price >= extension_zone_low:
        return "EXTENSION_SELL_ZONE_ACTIVE"

    if latest_price >= primary_zone_low:
        return "PRIMARY_SELL_ZONE_ACTIVE"

    return "BELOW_PRIMARY_SELL_ZONE"


def confidence_for(candles: list[CandleRow], low_ts: datetime | None, high_ts: datetime | None) -> str:
    if not candles or low_ts is None or high_ts is None:
        return "NONE"

    rows = len(candles)
    if rows >= 900 and high_ts > low_ts:
        return "HIGH"
    if rows >= 365 and high_ts > low_ts:
        return "MEDIUM"
    if rows >= 120 and high_ts > low_ts:
        return "LOW"

    return "VERY_LOW"


def build_row(
    *,
    asset_id: int,
    symbol: str,
    venue: str,
    interval_code: str,
    from_ts_utc: datetime,
    candles: list[CandleRow],
) -> SellZoneRow:
    if not candles:
        return SellZoneRow(
            asset_id=asset_id,
            symbol=symbol,
            venue=venue,
            interval_code=interval_code,
            cycle_from_ts_utc=from_ts_utc,
            latest_ts_utc=None,
            latest_price=None,
            cycle_low_ts_utc=None,
            cycle_low_price=None,
            swing_high_ts_utc=None,
            swing_high_price=None,
            ath_price=None,
            conservative_zone_low=None,
            conservative_zone_high=None,
            primary_zone_low=None,
            primary_zone_high=None,
            extension_zone_low=None,
            extension_zone_high=None,
            moonbag_zone_low=None,
            moonbag_zone_high=None,
            upside_to_primary_low_pct=None,
            confidence="NONE",
            classification="NO_DATA",
            notes="research_only; no candles in selected cycle window",
        )

    latest = candles[-1]
    cycle_low = min(candles, key=lambda c: c.low_price)

    post_low = [c for c in candles if c.close_ts_utc >= cycle_low.close_ts_utc]
    swing_high = max(post_low, key=lambda c: c.high_price) if post_low else None
    ath = max(candles, key=lambda c: c.high_price)

    if swing_high is None or swing_high.high_price <= cycle_low.low_price:
        return SellZoneRow(
            asset_id=asset_id,
            symbol=symbol,
            venue=venue,
            interval_code=interval_code,
            cycle_from_ts_utc=from_ts_utc,
            latest_ts_utc=latest.close_ts_utc,
            latest_price=q(latest.close_price),
            cycle_low_ts_utc=cycle_low.close_ts_utc,
            cycle_low_price=q(cycle_low.low_price),
            swing_high_ts_utc=swing_high.close_ts_utc if swing_high else None,
            swing_high_price=q(swing_high.high_price) if swing_high else None,
            ath_price=q(ath.high_price),
            conservative_zone_low=None,
            conservative_zone_high=None,
            primary_zone_low=None,
            primary_zone_high=None,
            extension_zone_low=None,
            extension_zone_high=None,
            moonbag_zone_low=None,
            moonbag_zone_high=None,
            upside_to_primary_low_pct=None,
            confidence="VERY_LOW",
            classification="NO_VALID_RANGE",
            notes="research_only; no valid low-to-high range after cycle low",
        )

    low = cycle_low.low_price
    high = swing_high.high_price

    conservative_low = level(low, high, FIB_LEVELS["zone_1_618"])
    conservative_high = level(low, high, FIB_LEVELS["zone_2_000"])

    primary_low = level(low, high, FIB_LEVELS["zone_2_618"])
    primary_high = level(low, high, FIB_LEVELS["zone_3_618"])

    extension_low = level(low, high, FIB_LEVELS["zone_4_236"])
    extension_high = level(low, high, FIB_LEVELS["zone_5_000"])

    moonbag_low = level(low, high, FIB_LEVELS["zone_6_854"])
    moonbag_high = moonbag_low * Decimal("1.15")

    upside = None
    if latest.close_price > 0:
        upside = ((primary_low - latest.close_price) / latest.close_price) * Decimal("100")

    confidence = confidence_for(candles, cycle_low.close_ts_utc, swing_high.close_ts_utc)

    classification = classify_zone(
        latest_price=latest.close_price,
        primary_zone_low=primary_low,
        extension_zone_low=extension_low,
        moonbag_zone_low=moonbag_low,
    )

    return SellZoneRow(
        asset_id=asset_id,
        symbol=symbol,
        venue=venue,
        interval_code=interval_code,
        cycle_from_ts_utc=from_ts_utc,
        latest_ts_utc=latest.close_ts_utc,
        latest_price=q(latest.close_price),
        cycle_low_ts_utc=cycle_low.close_ts_utc,
        cycle_low_price=q(low),
        swing_high_ts_utc=swing_high.close_ts_utc,
        swing_high_price=q(high),
        ath_price=q(ath.high_price),
        conservative_zone_low=q(conservative_low),
        conservative_zone_high=q(conservative_high),
        primary_zone_low=q(primary_low),
        primary_zone_high=q(primary_high),
        extension_zone_low=q(extension_low),
        extension_zone_high=q(extension_high),
        moonbag_zone_low=q(moonbag_low),
        moonbag_zone_high=q(moonbag_high),
        upside_to_primary_low_pct=pct(upside),
        confidence=confidence,
        classification=classification,
        notes=(
            "research_only; fib_extensions_from_cycle_low_to_post_low_swing_high; "
            "sell_zone_1=1.618-2.0; primary=2.618-3.618; "
            "extension=4.236-5.0; moonbag=6.854+"
        ),
    )


def write_csv(path: Path, rows: list[SellZoneRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(SellZoneRow.__dataclass_fields__.keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(getattr(row, field)) for field in fieldnames})


def write_markdown(path: Path, rows: list[SellZoneRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    generated_ts = datetime.now(UTC).replace(microsecond=0).isoformat()

    lines: list[str] = []
    lines.append("# Fibo / Elliott Bull-Run Sell Zones Overview V1")
    lines.append("")
    lines.append(f"Generated UTC: `{generated_ts}`")
    lines.append("")
    lines.append("## Boundary")
    lines.append("")
    lines.append("- Research-only harvest map.")
    lines.append("- Not a buy signal.")
    lines.append("- Not an execution plan.")
    lines.append("- Not connected to decision_gate, execution_planner, executor, broker, orders, balances, or positions.")
    lines.append("")
    lines.append("## Method")
    lines.append("")
    lines.append("- Source: `obs_market_candle` daily candles.")
    lines.append("- Anchor low: lowest daily low since selected cycle start.")
    lines.append("- Swing high: highest daily high after that anchor low.")
    lines.append("- Conservative sell zone: 1.618–2.000 extension.")
    lines.append("- Primary bull-run sell zone: 2.618–3.618 extension.")
    lines.append("- Extension sell zone: 4.236–5.000 extension.")
    lines.append("- Moonbag zone: 6.854 extension and above.")
    lines.append("")
    lines.append("## Overview")
    lines.append("")
    lines.append(
        "| Token | Class | Conf | Latest | Cycle Low | Swing High | Conservative Sell | Primary Sell | Extension Sell | Moonbag | Upside to Primary Low |"
    )
    lines.append(
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )

    sorted_rows = sorted(
        rows,
        key=lambda r: (
            r.classification,
            Decimal("999999999") if r.upside_to_primary_low_pct is None else r.upside_to_primary_low_pct,
            r.symbol,
        ),
    )

    for row in sorted_rows:
        conservative = (
            f"{fmt(row.conservative_zone_low)} – {fmt(row.conservative_zone_high)}"
            if row.conservative_zone_low is not None
            else ""
        )
        primary = (
            f"{fmt(row.primary_zone_low)} – {fmt(row.primary_zone_high)}"
            if row.primary_zone_low is not None
            else ""
        )
        extension = (
            f"{fmt(row.extension_zone_low)} – {fmt(row.extension_zone_high)}"
            if row.extension_zone_low is not None
            else ""
        )
        moonbag = (
            f"{fmt(row.moonbag_zone_low)}+"
            if row.moonbag_zone_low is not None
            else ""
        )

        lines.append(
            "| "
            f"{row.symbol} | "
            f"{row.classification} | "
            f"{row.confidence} | "
            f"{fmt(row.latest_price)} | "
            f"{fmt(row.cycle_low_price)} | "
            f"{fmt(row.swing_high_price)} | "
            f"{conservative} | "
            f"{primary} | "
            f"{extension} | "
            f"{moonbag} | "
            f"{fmt(row.upside_to_primary_low_pct)}% |"
        )

    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Tokens with short listing history are lower confidence.")
    lines.append("- For explosive tokens, 6.854+ is treated as moonbag/late-extension territory, not a base-case target.")
    lines.append("- This overview should later be compared with the pro Elliott/Fibo visual lane before promotion into any structured profile hint.")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate research-only Fibo/Elliott bull-run sell-zone overview."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--from-ts", default=DEFAULT_FROM_TS)
    parser.add_argument("--report-path", default=DEFAULT_REPORT_PATH)
    parser.add_argument("--csv-path", default=DEFAULT_CSV_PATH)
    args = parser.parse_args()

    from_ts_utc = parse_ts(str(args.from_ts))

    assets = fetch_enabled_assets()
    candles_by_asset = fetch_candles(
        venue=str(args.venue),
        interval_code=str(args.interval),
        from_ts_utc=from_ts_utc,
    )

    rows = [
        build_row(
            asset_id=int(asset["asset_id"]),
            symbol=str(asset["symbol"]),
            venue=str(args.venue),
            interval_code=str(args.interval),
            from_ts_utc=from_ts_utc,
            candles=candles_by_asset.get(int(asset["asset_id"]), []),
        )
        for asset in assets
    ]

    write_csv(Path(args.csv_path), rows)
    write_markdown(Path(args.report_path), rows)

    print(
        "[DONE] "
        f"rows={len(rows)} "
        f"report={args.report_path} "
        f"csv={args.csv_path} "
        f"venue={args.venue} "
        f"interval={args.interval} "
        f"from_ts={from_ts_utc.isoformat(sep=' ')}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
