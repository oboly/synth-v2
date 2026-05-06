"""
Synth v2.5 research runner: PRO_TARGET_BOX_LADDER_V1 preview.

Layer:
    research only.

Boundary:
    - Read-only.
    - No account access.
    - No order creation.
    - No decision/execution writes.
    - Produces theoretical target-box sell ladders from external pro target zones.

Purpose:
    Convert pro target boxes into front-run partial-sell ladder previews.

Example:
    target zone 9.00..10.00
    front_run_pct 0.08
    rungs 5
    distribution front_loaded

    -> first rung starts before zone_low
    -> final rung stays inside/near upper box
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

import pymysql

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


READ_ONLY_FORBIDDEN_SQL_PREFIXES = (
    "insert",
    "update",
    "delete",
    "replace",
    "create",
    "alter",
    "drop",
    "truncate",
    "grant",
    "revoke",
    "call",
    "load",
    "rename",
    "lock",
    "unlock",
)


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass(frozen=True)
class TargetZone:
    source_id: int
    symbol: str
    interval_code: str
    zone_low: Decimal
    zone_high: Decimal
    target_price: Optional[Decimal]
    currency_code: str
    quality_score: Optional[Decimal]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview front-run sell ladders from pro target boxes.")
    parser.add_argument("--source-ids", default="34,53")
    parser.add_argument("--sell-fraction", default="0.20", help="Fraction of position to sell in this target box.")
    parser.add_argument("--rungs", type=int, default=5)
    parser.add_argument("--front-run-pct", default="0.08", help="Start ladder this fraction below target zone low.")
    parser.add_argument("--end-pct-of-zone-high", default="0.98", help="Last rung as fraction of zone high.")
    parser.add_argument(
        "--distribution",
        choices=("front_loaded", "equal"),
        default="front_loaded",
    )
    parser.add_argument("--env-file", default=None)
    return parser.parse_args()


def parse_source_ids(text: str) -> list[int]:
    values: list[int] = []
    for part in text.split(","):
        stripped = part.strip()
        if stripped:
            values.append(int(stripped))
    if not values:
        raise ValueError("At least one source id is required.")
    return values


def d(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(str(value))


def dec_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.quantize(Decimal("0.00000001")), "f")


def pct_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format((value * Decimal("100")).quantize(Decimal("0.0001")), "f")


def load_db_config(env_file: str | None) -> DbConfig:
    if load_dotenv is not None:
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()

    return DbConfig(
        host=os.getenv("SYNTH_DB_HOST") or os.getenv("DB_HOST") or "127.0.0.1",
        port=int(os.getenv("SYNTH_DB_PORT") or os.getenv("DB_PORT") or "3306"),
        user=os.getenv("SYNTH_DB_USER") or os.getenv("DB_USER") or "root",
        password=os.getenv("SYNTH_DB_PASSWORD") or os.getenv("DB_PASSWORD") or "",
        database=os.getenv("SYNTH_DB_NAME") or os.getenv("DB_NAME") or "synth",
    )


def connect(config: DbConfig):
    return pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def assert_read_only_sql(sql: str) -> None:
    stripped = sql.strip().lower()
    first_word = stripped.split(None, 1)[0] if stripped else ""
    if first_word in READ_ONLY_FORBIDDEN_SQL_PREFIXES:
        raise RuntimeError(f"Forbidden non-read SQL: {first_word}")


def fetch_all(conn, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    assert_read_only_sql(sql)
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


def fetch_target_zones(conn, source_ids: list[int]) -> list[TargetZone]:
    placeholders = ",".join(["%s"] * len(source_ids))

    rows = fetch_all(
        conn,
        f"""
        SELECT
            source_id,
            symbol,
            interval_code,
            zone_low,
            zone_high,
            target_price,
            currency_code,
            quality_score
        FROM research_external_chart_observation
        WHERE source_id IN ({placeholders})
          AND method_code = 'PRO_ZONE_CHART'
          AND structure_code = 'TARGET_ZONE'
          AND zone_low IS NOT NULL
          AND zone_high IS NOT NULL
        ORDER BY symbol, source_id, zone_low
        """,
        tuple(source_ids),
    )

    zones: list[TargetZone] = []
    for row in rows:
        zone_low = d(row["zone_low"])
        zone_high = d(row["zone_high"])
        if zone_low is None or zone_high is None:
            continue

        zones.append(
            TargetZone(
                source_id=int(row["source_id"]),
                symbol=str(row["symbol"]),
                interval_code=str(row["interval_code"]),
                zone_low=zone_low,
                zone_high=zone_high,
                target_price=d(row["target_price"]),
                currency_code=str(row.get("currency_code") or "EUR").upper(),
                quality_score=d(row["quality_score"]),
            )
        )

    return zones


def rung_weights(rungs: int, distribution: str) -> list[Decimal]:
    if rungs <= 0:
        raise ValueError("rungs must be > 0")

    if distribution == "equal":
        return [Decimal("1") / Decimal(str(rungs)) for _ in range(rungs)]

    raw = [Decimal(str(rungs - idx)) for idx in range(rungs)]
    total = sum(raw)
    return [value / total for value in raw]


def ladder_prices(
    zone_low: Decimal,
    zone_high: Decimal,
    rungs: int,
    front_run_pct: Decimal,
    end_pct_of_zone_high: Decimal,
) -> list[Decimal]:
    if rungs <= 0:
        raise ValueError("rungs must be > 0")
    if zone_high <= zone_low:
        raise ValueError("zone_high must be > zone_low")

    start_price = zone_low * (Decimal("1") - front_run_pct)
    end_price = zone_high * end_pct_of_zone_high

    if rungs == 1:
        return [start_price]

    step = (end_price - start_price) / Decimal(str(rungs - 1))
    return [start_price + step * Decimal(str(idx)) for idx in range(rungs)]


def print_ladder(
    zones: list[TargetZone],
    sell_fraction: Decimal,
    rungs: int,
    front_run_pct: Decimal,
    end_pct_of_zone_high: Decimal,
    distribution: str,
) -> None:
    columns = [
        "source_id",
        "symbol",
        "interval",
        "currency",
        "zone_low",
        "zone_high",
        "target_price",
        "rung",
        "limit_price",
        "rung_weight_of_target_slice_pct",
        "position_fraction_to_sell_pct",
        "front_run_vs_zone_low_pct",
    ]
    print("\t".join(columns))

    weights = rung_weights(rungs, distribution)

    for zone in zones:
        prices = ladder_prices(
            zone_low=zone.zone_low,
            zone_high=zone.zone_high,
            rungs=rungs,
            front_run_pct=front_run_pct,
            end_pct_of_zone_high=end_pct_of_zone_high,
        )

        for idx, price in enumerate(prices, start=1):
            weight = weights[idx - 1]
            position_fraction = sell_fraction * weight
            front_run_vs_zone_low = (zone.zone_low - price) / zone.zone_low

            values = [
                str(zone.source_id),
                zone.symbol,
                zone.interval_code,
                zone.currency_code,
                dec_text(zone.zone_low),
                dec_text(zone.zone_high),
                dec_text(zone.target_price),
                str(idx),
                dec_text(price),
                pct_text(weight),
                pct_text(position_fraction),
                pct_text(front_run_vs_zone_low),
            ]
            print("\t".join(values))


def main() -> int:
    args = parse_args()

    source_ids = parse_source_ids(args.source_ids)
    sell_fraction = Decimal(str(args.sell_fraction))
    front_run_pct = Decimal(str(args.front_run_pct))
    end_pct_of_zone_high = Decimal(str(args.end_pct_of_zone_high))

    config = load_db_config(args.env_file)
    conn = connect(config)

    try:
        zones = fetch_target_zones(conn, source_ids)
    finally:
        conn.close()

    if not zones:
        print("[NO_TARGET_ZONES] No target zones found.")
        return 0

    print_ladder(
        zones=zones,
        sell_fraction=sell_fraction,
        rungs=args.rungs,
        front_run_pct=front_run_pct,
        end_pct_of_zone_high=end_pct_of_zone_high,
        distribution=args.distribution,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
